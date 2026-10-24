"""
Download Aetna medical policy documents related to prior authorization /
precertification requirements (procedure codes, drugs, etc.).

What it does
------------
1. Scrapes Aetna's precertification lists page for PDF links that are
   related to precertification / prior authorization / medical drug
   programs and that are 2026 documents.
2. Downloads each matching PDF into the ./downloaded folder.
3. Because Aetna publishes revised versions of a list at the SAME URL
   (e.g. the 2026 precert list was updated Jan 1, then July 1, ...),
   the script also queries the Internet Archive (Wayback Machine) for
   every distinct 2026 snapshot of each matched PDF, so that ALL
   versions published in 2026 are downloaded, not just the latest one.

Usage
-----
    python3 download_aetna_precert_policies.py
"""

import hashlib
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

AETNA_BASE = "https://www.aetna.com"
PRECERT_LISTS_PAGE = (
    "https://www.aetna.com/health-care-professionals/"
    "precertification/precertification-lists.html"
)

DOWNLOAD_DIR = Path(__file__).parent / "downloaded"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
}

# A PDF is considered relevant if its URL or link text mentions any of
# these prior-auth / precert / drug-program keywords ...
RELEVANCE_KEYWORDS = (
    "precert",
    "prior auth",
    "prior-auth",
    "priorauth",
    "medical-drugs",
    "medical drugs",
    "clinical_program",
    "clinical program",
)
# ... and is a 2026 publication.
YEAR = "2026"

WAYBACK_CDX_API = "https://web.archive.org/cdx/search/cdx"


class LinkExtractor(HTMLParser):
    """Collect (href, link_text) pairs from an HTML page."""

    def __init__(self):
        super().__init__()
        self.links = []          # list of (href, text)
        self._current_href = None
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._current_href = href
                self._current_text = []

    def handle_data(self, data):
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._current_href is not None:
            text = " ".join(" ".join(self._current_text).split())
            self.links.append((self._current_href, text))
            self._current_href = None
            self._current_text = []


def find_relevant_pdf_links(session: requests.Session) -> dict[str, str]:
    """Return {absolute_pdf_url: link_text} for relevant 2026 PDFs."""
    print(f"Fetching page: {PRECERT_LISTS_PAGE}")
    resp = session.get(PRECERT_LISTS_PAGE, timeout=60)
    resp.raise_for_status()

    parser = LinkExtractor()
    parser.feed(resp.text)

    relevant = {}
    for href, text in parser.links:
        if ".pdf" not in href.lower():
            continue
        haystack = f"{href} {text}".lower()
        if not any(k in haystack for k in RELEVANCE_KEYWORDS):
            continue
        if YEAR not in haystack:
            continue
        url = urljoin(AETNA_BASE, href)
        relevant[url] = text or Path(urlparse(url).path).name
    return relevant


def save_pdf(content: bytes, dest: Path, seen_hashes: set[str]) -> bool:
    """Write PDF bytes to dest unless identical content was already saved."""
    digest = hashlib.sha256(content).hexdigest()
    if digest in seen_hashes:
        print(f"  Skipped (identical content already saved): {dest.name}")
        return False
    if not content.startswith(b"%PDF"):
        print(f"  Skipped (not a PDF response): {dest.name}")
        return False
    dest.write_bytes(content)
    seen_hashes.add(digest)
    print(f"  Saved: {dest.name} ({len(content):,} bytes)")
    return True


def download_current_version(
    session: requests.Session, url: str, seen_hashes: set[str]
) -> None:
    """Download the currently published version of a PDF from aetna.com."""
    filename = Path(urlparse(url).path).name
    print(f"Downloading current version: {url}")
    resp = session.get(url, timeout=120)
    resp.raise_for_status()
    save_pdf(resp.content, DOWNLOAD_DIR / filename, seen_hashes)


def download_2026_archived_versions(
    session: requests.Session, url: str, seen_hashes: set[str]
) -> None:
    """Download every distinct 2026 snapshot of `url` from the Wayback Machine."""
    params = {
        "url": url,
        "from": f"{YEAR}0101",
        "to": f"{YEAR}1231",
        "output": "json",
        "filter": "statuscode:200",
        "collapse": "digest",
        "fl": "timestamp,original,digest",
    }
    try:
        resp = session.get(WAYBACK_CDX_API, params=params, timeout=60)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:  # noqa: BLE001 - archive lookups are best-effort
        print(f"  Wayback lookup failed for {url}: {exc}")
        return

    snapshots = rows[1:] if rows else []
    if not snapshots:
        print(f"  No 2026 archived versions found for {url}")
        return

    stem = Path(urlparse(url).path).stem
    for timestamp, original, _digest in snapshots:
        snapshot_url = f"https://web.archive.org/web/{timestamp}id_/{original}"
        date = timestamp[:8]
        dest = DOWNLOAD_DIR / f"{stem}_version_{date}.pdf"
        print(f"Downloading archived version ({date}): {snapshot_url}")
        try:
            snap = session.get(snapshot_url, timeout=120)
            snap.raise_for_status()
            save_pdf(snap.content, dest, seen_hashes)
        except Exception as exc:  # noqa: BLE001
            print(f"  Failed to download snapshot {timestamp}: {exc}")
        time.sleep(1)  # be polite to the archive


def main() -> None:
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    pdf_links = find_relevant_pdf_links(session)
    if not pdf_links:
        raise SystemExit(
            "No relevant 2026 precertification PDFs found - "
            "the page layout may have changed."
        )

    print(f"\nFound {len(pdf_links)} relevant 2026 document(s):")
    for url, text in pdf_links.items():
        print(f"  - {text}\n    {url}")
    print()

    seen_hashes: set[str] = set()
    for url in pdf_links:
        download_current_version(session, url, seen_hashes)
        download_2026_archived_versions(session, url, seen_hashes)
        print()

    saved = sorted(p.name for p in DOWNLOAD_DIR.glob("*.pdf"))
    print(f"Done. {len(saved)} file(s) in {DOWNLOAD_DIR}:")
    for name in saved:
        print(f"  {name}")


if __name__ == "__main__":
    main()
