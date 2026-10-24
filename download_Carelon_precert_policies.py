"""
Download Carelon Medical Benefits Management clinical guideline documents
(the criteria Carelon, formerly AIM Specialty Health, uses for prior
authorization) and save them as PDFs under ./downloaded/Carelon/.

Why a dedicated script
----------------------
Carelon publishes its guidelines at
https://guidelines.carelonmedicalbenefitsmanagement.com/ as a
JavaScript-rendered list, so a plain <a href> scrape finds almost nothing
(the generic multi-payer script only recovered a single hard-coded PDF).
The site is WordPress, though, which gives two much richer sources:

  1. The WordPress REST media API
       /wp-json/wp/v2/media?media_type=application&per_page=100&page=N
     enumerates EVERY uploaded document (~600 guideline PDFs), each with a
     clean human-readable title. This is the primary source.

  2. The XML sitemap + category / solution landing pages, crawled for
     wp-content/uploads/*.pdf links. Used to supplement the media library
     and as a fallback if the REST API is ever unavailable.

Every candidate is validated (body must start with b"%PDF"), de-duplicated
by SHA-256 content hash, and saved with a readable name derived from the
document title / link text.

Usage
-----
    python3 download_Carelon_precert_policies.py            # download all
    python3 download_Carelon_precert_policies.py --limit 20 # first 20 (test)
    python3 download_Carelon_precert_policies.py --list-only # enumerate only
    python3 download_Carelon_precert_policies.py --no-crawl  # media API only
"""

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

BASE = "https://guidelines.carelonmedicalbenefitsmanagement.com"
MEDIA_API = f"{BASE}/wp-json/wp/v2/media"
SITEMAP_INDEX = f"{BASE}/wp-sitemap.xml"
DOWNLOAD_DIR = Path(__file__).parent / "downloaded" / "Carelon"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# curl gets past TLS-fingerprint bot protection that can 403 python-requests.
CURL = shutil.which("curl")


# ---------------------------------------------------------------------------
# HTTP helpers (requests first, curl fallback)
# ---------------------------------------------------------------------------
def curl_get(url: str, timeout: int = 120) -> bytes | None:
    """Fetch a URL with system curl (follows redirects). None on failure."""
    if not CURL:
        return None
    try:
        proc = subprocess.run(
            [CURL, "-sSL", "-A", HEADERS["User-Agent"], "-H", "Accept: */*",
             "--max-time", str(timeout), "-o", "-", url],
            capture_output=True, timeout=timeout + 20,
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode == 0 and proc.stdout:
        return proc.stdout
    return None


def fetch(session, url, timeout=90):
    """Return (content_bytes, content_type). Tries requests, then curl."""
    try:
        resp = session.get(url, timeout=timeout)
        if resp.ok and resp.content:
            return resp.content, resp.headers.get("Content-Type", "").lower()
    except Exception:  # noqa: BLE001
        pass
    data = curl_get(url, timeout)
    return (data, "") if data else (None, "")


class LinkExtractor(HTMLParser):
    """Collect (href, link_text) pairs from an HTML page."""

    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._href = href
                self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = " ".join(" ".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None
            self._text = []


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def discover_via_media_api(session, verbose=True) -> dict[str, str]:
    """Enumerate every PDF in the WordPress media library.

    Returns {pdf_url: title}. Pages through
    /wp-json/wp/v2/media?media_type=application&per_page=100.
    """
    found: dict[str, str] = {}
    page = 1
    per_page = 100
    while True:
        url = (f"{MEDIA_API}?media_type=application&per_page={per_page}"
               f"&page={page}&_fields=source_url,title,mime_type")
        content, _ = fetch(session, url, timeout=60)
        if content is None:
            if verbose:
                print(f"    Media API page {page} unreachable.")
            break
        try:
            items = json.loads(content.decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            # A 400 (page overrun) or HTML error page ends pagination.
            if verbose and page == 1:
                print(f"    Media API returned no JSON: {exc}")
            break
        if not isinstance(items, list) or not items:
            break
        for item in items:
            src = item.get("source_url", "")
            if not src.lower().endswith(".pdf"):
                continue
            title = html.unescape((item.get("title") or {}).get("rendered", ""))
            found.setdefault(src, title)
        if verbose:
            print(f"    Media API page {page}: {len(items)} items "
                  f"({len(found)} PDFs so far)")
        if len(items) < per_page:
            break
        page += 1
        time.sleep(0.3)  # be polite
    return found


def sitemap_landing_pages(session, sitemap_url, verbose=True) -> list[str]:
    """Return category / solution landing-page URLs from the sitemap index.

    Skips the 'posts-post' child sitemap (hundreds of individual guideline
    pages already covered by the media API) to keep the crawl bounded.
    """
    content, _ = fetch(session, sitemap_url, timeout=45)
    if content is None:
        return []
    text = content.decode("utf-8", errors="replace")
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
    child_maps = [u for u in locs if u.lower().endswith(".xml")]
    pages = [u for u in locs if not u.lower().endswith(".xml")]
    for child in child_maps:
        if not re.search(r"(page|solutions|category)", child, re.IGNORECASE):
            continue
        sub, _ = fetch(session, child, timeout=45)
        if sub is None:
            continue
        pages.extend(re.findall(r"<loc>\s*([^<\s]+)\s*</loc>",
                                sub.decode("utf-8", errors="replace")))
        time.sleep(0.2)
    host = urlparse(BASE).netloc
    uniq, seen = [], set()
    for u in pages:
        if urlparse(u).netloc == host and u not in seen:
            seen.add(u)
            uniq.append(u)
    if verbose:
        print(f"    Sitemap yielded {len(uniq)} landing page(s) to crawl.")
    return uniq


def discover_via_crawl(session, verbose=True) -> dict[str, str]:
    """Crawl the home page + sitemap landing pages for uploaded PDF links."""
    found: dict[str, str] = {}
    pages = [BASE, f"{BASE}/", f"{BASE}/current-radiology-guidelines/"]
    pages.extend(sitemap_landing_pages(session, SITEMAP_INDEX, verbose=verbose))

    seen_pages, ordered = set(), []
    for p in pages:
        if p not in seen_pages:
            seen_pages.add(p)
            ordered.append(p)

    for i, page in enumerate(ordered, 1):
        content, _ = fetch(session, page, timeout=45)
        if content is None:
            continue
        parser = LinkExtractor()
        try:
            parser.feed(content.decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            pass
        for href, text in parser.links:
            low = href.lower()
            if "wp-content/uploads" not in low or ".pdf" not in low:
                continue
            abs_url = urljoin(page, href.split("#")[0].strip())
            found.setdefault(abs_url, text)
        if verbose and i % 20 == 0:
            print(f"    Crawled {i}/{len(ordered)} pages "
                  f"({len(found)} PDF links)")
        time.sleep(0.15)
    if verbose:
        print(f"    Crawl found {len(found)} uploaded PDF link(s).")
    return found


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------
def safe_filename(title: str, url: str) -> str:
    """Readable, filesystem-safe .pdf name from the document title."""
    base = html.unescape((title or "").strip())
    base = re.sub(r"[\s\-]*\(?\bpdf\b\)?\s*$", "", base, flags=re.IGNORECASE)
    if not base:
        base = unquote(Path(urlparse(url).path).stem)
        base = re.sub(r"[-_]+", " ", base).strip()
    base = re.sub(r"\s+", " ", base).strip()
    base = re.sub(r'[<>:"/\\|?*]', "_", base).strip(" ._")
    if not base:
        base = "guideline"
    if len(base) > 160:
        base = base[:160].rstrip(" ._")
    return f"{base}.pdf"


def download_pdf(session, url, title, seen_hashes) -> bool:
    """Download one PDF; validate, de-duplicate by content, then save."""
    content, ctype = fetch(session, url, timeout=90)
    if content is None:
        print(f"    Failed (blocked/unreachable): {url}")
        return False
    if not content.startswith(b"%PDF") and "application/pdf" not in ctype:
        alt = curl_get(url, timeout=90)
        if alt and alt.startswith(b"%PDF"):
            content = alt
    if not content.startswith(b"%PDF"):
        print(f"    Skipped (not a PDF): {url}")
        return False

    digest = hashlib.sha256(content).hexdigest()
    if digest in seen_hashes:
        return False

    dest = DOWNLOAD_DIR / safe_filename(title, url)
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
        stem, suffix, n = dest.stem, dest.suffix, 2
        while dest.exists():
            dest = DOWNLOAD_DIR / f"{stem} ({n}){suffix}"
            n += 1

    dest.write_bytes(content)
    seen_hashes.add(digest)
    print(f"    Saved: {dest.name} ({len(content):,} bytes)")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Download Carelon Medical Benefits Management clinical "
                    "guideline PDFs (prior-authorization criteria).")
    ap.add_argument("--limit", type=int, default=0,
                    help="only download the first N documents (0 = all)")
    ap.add_argument("--no-crawl", action="store_true",
                    help="use only the WordPress media API (skip the "
                         "sitemap/landing-page supplement)")
    ap.add_argument("--list-only", action="store_true",
                    help="enumerate documents but do not download them")
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update(HEADERS)

    print(f"Discovering Carelon guideline documents at {BASE}")
    print("  [1] WordPress media API ...")
    documents = discover_via_media_api(session)
    print(f"      -> {len(documents)} PDF(s) from the media library.")

    if not args.no_crawl:
        print("  [2] Sitemap + landing-page crawl (supplement) ...")
        before = len(documents)
        for url, text in discover_via_crawl(session).items():
            documents.setdefault(url, text)
        print(f"      -> {len(documents) - before} additional PDF(s) from "
              f"crawling (total {len(documents)}).")

    if not documents:
        raise SystemExit(
            "No Carelon guideline PDFs found - the site layout or API may "
            "have changed.")

    ordered = sorted(documents.items(), key=lambda kv: (kv[1] or kv[0]).lower())
    if args.limit > 0:
        ordered = ordered[:args.limit]

    print(f"\nTotal distinct PDF URLs to process: {len(ordered)}")
    if args.list_only:
        for url, title in ordered:
            print(f"  {title or '(no title)'}\n    {url}")
        print(f"\n{len(ordered)} document(s) listed (nothing downloaded).")
        return

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    seen_hashes: set[str] = set()
    saved = 0
    for i, (url, title) in enumerate(ordered, 1):
        print(f"  [{i}/{len(ordered)}] {title or Path(urlparse(url).path).name}")
        if download_pdf(session, url, title, seen_hashes):
            saved += 1
        time.sleep(0.15)  # be polite

    print(f"\n{'=' * 70}")
    print(f"Done. {saved} unique PDF(s) saved to {DOWNLOAD_DIR}")
    print(f"({len(ordered) - saved} skipped as duplicates or non-PDFs.)")


if __name__ == "__main__":
    main()
