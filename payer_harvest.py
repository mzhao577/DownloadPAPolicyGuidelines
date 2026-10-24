"""
payer_harvest.py - shared "work harder" harvesting engine for the per-payer
prior-authorization / precertification document download scripts.

Each download_<Payer>_precert_policies.py describes WHERE a payer keeps its
documents (a PayerSite config) and calls run(site).  Everything else - the
multi-source discovery, validation, de-duplication, naming and reporting -
lives here.

Why "work harder"
-----------------
A plain <a href> scrape of one landing page recovers a handful of documents at
best: most payer sites are JavaScript-rendered, hide the real list behind a
JSON payload, or spread documents over dozens of state / plan / line-of-
business pages.  This engine therefore attacks every site from six angles and
merges the results:

  1. RAW ASSET REGEX   - every response body (HTML, JS, JSON, XHR payload) is
                         scanned with a regex for document URLs, so links that
                         only exist inside escaped JSON ("\\u002Fdocs\\u002Fx.pdf")
                         or inside a script bundle are still found.
  2. LINK EXTRACTION   - <a href> / <iframe src> / data-* attributes, keeping
                         the human-readable link text for the file name.
  3. BFS CRAWL         - breadth-first crawl of the payer's own site, bounded
                         by URL patterns + depth + page budget, so sibling
                         pages ("...prior-auth/medicare", ".../state/ga") are
                         discovered automatically.
  4. SITEMAPS          - robots.txt Sitemap: lines, /sitemap.xml,
                         /sitemap-index.xml, /wp-sitemap.xml; both the pages
                         (fed into the crawl frontier) and any direct document
                         URLs listed in them.
  5. CMS APIs          - WordPress REST media library, and Sitecore/AEM style
                         JSON endpoints when the site config supplies them.
  6. WAYBACK CDX       - the Internet Archive index for the payer's domain,
                         filtered to document extensions and to relevance
                         keywords.  This recovers documents that are no longer
                         linked, that sit behind a JS wall, or that the live
                         site 403s.  Live URL is always tried first; the
                         archived copy is the fallback.

Supported document types: .pdf, .xlsx/.xlsm/.xls (Excel) and .docx/.doc/.rtf
(Word).

Nothing already collected is downloaded twice.  Before a body is fetched the
candidate is checked against the payer folder two ways: by its SOURCE URL, via
the .download_manifest.json the saver maintains in each folder, and by the FILE
NAME it would be given.  Either hit skips the fetch outright, so a re-run costs
no bandwidth for documents already on disk - even when a document is
rediscovered under a different link label, or when its bytes duplicate a file
already saved under another name.  Delete a file and the next run fetches it
again; --refetch forces the lot.  What is fetched (requests ->
curl fallback) is validated by magic bytes (%PDF for PDF, the OOXML zip
container for xlsx/xlsm/docx, the OLE header for legacy xls/doc, {\\rtf for RTF),
de-duplicated by SHA-256 of the body, and written under ./downloaded/<PayerName>/
with a readable name derived from its link text or a prettified URL stem.

Common CLI flags provided to every payer script:

    --limit N        stop after N successful downloads (0 = no limit)
    --list-only      enumerate candidates, download nothing
    --no-crawl       skip the BFS crawl
    --no-sitemap     skip sitemap discovery
    --no-wayback     skip the Internet Archive sweep
    --wayback-only   use only the Internet Archive sweep
    --since YEAR     earliest Wayback capture year (default 2023)
    --max-pages N    crawl page budget (default from the site config)
    --depth N        crawl depth (default from the site config)
    --workers N      parallel downloads (default 6)
    --pdf-only       PDFs only (ignore Excel and Word documents)
    --excel-only     .xlsx/.xlsm/.xls only
    --word-only      .docx/.doc/.rtf only
    --refetch        re-download documents already present (ignore both the
                     URL manifest and the file-name check)
    --all            widen filters: keep every document found, not just the
                     ones whose URL/label looks prior-auth related
    --verbose        chatty progress
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html as html_mod
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, urlsplit

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT = Path(__file__).resolve().parent
DOWNLOAD_ROOT = ROOT / "downloaded"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CURL = shutil.which("curl")

DOC_EXTS = (".pdf", ".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".rtf")
PDF_EXTS = (".pdf",)
EXCEL_EXTS = (".xlsx", ".xlsm", ".xls")
WORD_EXTS = (".docx", ".doc", ".rtf")

# Words that mark a document (or the page that links it) as prior-auth related.
DEFAULT_KEYWORDS = (
    "precert", "pre-cert", "precertification", "prior-auth", "prior_auth",
    "priorauth", "prior auth", "preauth", "pre-auth", "pre auth", "prea",
    "authorization", "authorisation", "notification", "pa-list", "pa_list",
    "palist", "pa-requirement", "pa requirement", "auth-requirement",
    "auth grid", "auth-grid", "authgrid", "medical policy", "medical-policy",
    "medicalpolicy", "clinical policy", "clinical-policy", "coverage policy",
    "coverage-policy", "clinical guideline", "clinical-guideline",
    "utilization management", "utilization-management", "um-", "-um",
    "step therapy", "step-therapy", "steptherapy", "formulary",
    "provider-administered", "provider administered", "specialty drug",
    "specialty-drug", "medical necessity", "medical-necessity",
    "review requirement", "code list", "code-list", "codelist",
    "hcpcs", "j-code", "jcode", "notification list", "advance notification",
    "summary of changes", "precertification list", "medical drug", "drug list",
    "site of care", "site-of-care", "medical benefit drug",
)

# Short tokens that must match as whole words (a plain substring test would
# fire on unrelated words such as "acceptance" for "cpt").
DEFAULT_WORD_KEYWORDS = (
    "pa", "pal", "um", "cpt", "prec", "auth", "auths", "authorizations",
    "precerts", "grid", "grids",
)

# Documents that are obviously not prior-auth policy material.
NEGATIVE_HINTS = (
    "careers", "newsletter", "press-release", "annual-report", "sitemap",
    "privacy-policy", "nondiscrimination", "non-discrimination", "eeo",
    "brochure-marketing", "wellness-tip", "recipe", "flu-clinic",
)

PRINTABLE_LOG_LOCK = threading.Lock()


def log(msg: str = "") -> None:
    with PRINTABLE_LOG_LOCK:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# Site configuration
# ---------------------------------------------------------------------------
@dataclass
class PayerSite:
    """Everything the engine needs to know about one payer's web presence."""

    payer: str                                  # folder name under downloaded/
    seeds: list[str]                            # start URLs (landing pages)
    allow_hosts: list[str] = field(default_factory=list)
    # A page URL must match one of these to be crawled (empty = any allowed host).
    page_patterns: list[str] = field(default_factory=list)
    # A page URL matching one of these is never crawled.
    deny_patterns: list[str] = field(default_factory=list)
    # Extra relevance keywords, merged with DEFAULT_KEYWORDS.
    keywords: list[str] = field(default_factory=list)
    # Documents whose URL matches one of these are always kept.
    always_keep: list[str] = field(default_factory=list)
    # Hard-coded known documents: (url, label). Used in addition to discovery.
    fallback_docs: list[tuple[str, str]] = field(default_factory=list)
    # Extra sitemap URLs to try beyond the auto-probed ones.
    sitemaps: list[str] = field(default_factory=list)
    # WordPress REST roots, e.g. "https://host" -> /wp-json/wp/v2/media
    wp_roots: list[str] = field(default_factory=list)
    # Arbitrary JSON endpoints to scan for document URLs.
    json_endpoints: list[str] = field(default_factory=list)
    # Wayback CDX url patterns, e.g. "azblue.com/*" or "www.uhcprovider.com/content/*"
    wayback_prefixes: list[str] = field(default_factory=list)
    wayback_since: int = 2023
    # Keep every document found for this payer, not only keyword matches.
    # Used for small payers where the whole provider library is in scope.
    wayback_keep_all: bool = False
    keep_all_docs: bool = False
    max_pages: int = 400
    depth: int = 3
    delay: float = 0.1
    verify_tls: bool = True
    notes: str = ""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def curl_get(url: str, timeout: int = 90, insecure: bool = False) -> bytes | None:
    """Fetch with system curl (different TLS fingerprint than requests)."""
    if not CURL:
        return None
    cmd = [CURL, "-sSL", "--compressed", "-A", USER_AGENT,
           "-H", "Accept: */*", "--max-time", str(timeout), "-o", "-", url]
    if insecure:
        cmd.insert(1, "-k")
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 20)
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode == 0 and proc.stdout:
        return proc.stdout
    return None


class Fetcher:
    """requests.Session with a curl fallback and a tiny in-memory cache."""

    def __init__(self, verify: bool = True):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.verify = verify
        self._cache: dict[str, tuple[bytes | None, str]] = {}
        self._lock = threading.Lock()

    def get(self, url: str, timeout: int = 60, cache: bool = True,
            referer: str | None = None) -> tuple[bytes | None, str]:
        """Return (body_bytes | None, content_type_lower)."""
        if cache:
            with self._lock:
                if url in self._cache:
                    return self._cache[url]
        result: tuple[bytes | None, str] = (None, "")
        headers = {"Referer": referer} if referer else None
        for attempt in range(2):
            try:
                resp = self.session.get(url, timeout=timeout, verify=self.verify,
                                        allow_redirects=True, headers=headers)
                if resp.ok and resp.content:
                    result = (resp.content,
                              resp.headers.get("Content-Type", "").lower())
                    break
            except Exception:  # noqa: BLE001
                pass
            if attempt == 0:
                time.sleep(0.4)
        if result[0] is None:
            data = curl_get(url, timeout=timeout, insecure=not self.verify)
            if data:
                result = (data, "")
        if cache:
            with self._lock:
                self._cache[url] = result
        return result


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
BLOCK_MARKERS = (
    b"just a moment", b"cf-browser-verification", b"challenge-platform",
    b"access denied", b"request blocked", b"enable javascript and cookies",
    b"incapsula incident", b"forbidden</", b"error 403", b"bot detection",
    b"_incapsula_resource", b"noindex, nofollow\"><meta name=\"format-detection",
)


def looks_blocked(body: bytes | None) -> bool:
    """True when a page body is an anti-bot interstitial rather than content."""
    if not body:
        return True
    head = body[:4000].lower()
    return any(m in head for m in BLOCK_MARKERS)


def fetch_page(fetcher: "Fetcher", url: str, timeout: int = 45
               ) -> tuple[bytes | None, str]:
    """Fetch an HTML page, falling back to its newest Internet Archive copy.

    Several payer sites (Medica, Dean Health, Avera) sit behind Cloudflare or
    edge bot rules that answer scripted clients with a challenge page.  The
    archived copy still contains the real document links, which is all this
    tool needs.
    """
    body, ctype = fetcher.get(url, timeout=timeout)
    if body is not None and not looks_blocked(body):
        return body, ctype
    arch, actype = fetcher.get(f"https://web.archive.org/web/2id_/{url}",
                               timeout=timeout + 60)
    if arch is not None and not looks_blocked(arch):
        return arch, actype
    return body, ctype


class LinkExtractor(HTMLParser):
    """Collect (href, text) for <a>, plus src/data-href style attributes."""

    ATTRS = ("href", "src", "data-href", "data-url", "data-file",
             "data-document", "data-link", "data-pdf")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._title: str = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a":
            href = d.get("href")
            if href:
                self._href = href
                self._title = d.get("title") or d.get("aria-label") or ""
                self._text = []
                return
        for key in self.ATTRS:
            val = d.get(key)
            if val and re.search(r"\.(pdf|xls[xm]?|docx?|rtf)(\?|#|$)", val, re.I):
                self.links.append((val, d.get("title") or d.get("aria-label") or ""))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = " ".join(" ".join(self._text).split())
            self.links.append((self._href, text or self._title))
            self._href = None
            self._text = []
            self._title = ""


def unescape_payload(raw: str) -> str:
    """Undo the escaping used by embedded JSON / JS string payloads."""
    out = raw
    out = out.replace("\\u002F", "/").replace("\\u002f", "/")
    out = out.replace("\\u0026", "&").replace("\\u003c", "<").replace("\\u003e", ">")
    out = out.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")
    try:
        out = html_mod.unescape(out)
    except Exception:  # noqa: BLE001
        pass
    return out


DOC_URL_RE = re.compile(
    r"""(?P<url>(?:https?://|/)[^\s"'<>()\[\]{}\\|^`]+?\.(?:pdf|xlsx|xlsm|xls|docx|doc|rtf))"""
    r"""(?P<qs>\?[^\s"'<>()\[\]{}\\|^`]*)?""",
    re.IGNORECASE,
)

PAGE_URL_RE = re.compile(r"""href\s*=\s*["']([^"'#>]+)["']""", re.IGNORECASE)

# Asset hosts that serve documents without a file extension.
EXTLESS_DOC_RE = re.compile(
    r"""https?://assets\.humana\.com/is/content/humana/[^\s"'<>()\[\]{}\\|^`]*pdf"""
    r"""|https?://[a-z0-9-]+\.sitecorecontenthub\.cloud/api/public/content/"""
    r"""[^\s"'<>()\[\]{}\\|^`]+""",
    re.IGNORECASE,
)


def extract_doc_urls(body: bytes, base_url: str) -> dict[str, str]:
    """Every document URL mentioned anywhere in the body -> label (may be '')."""
    found: dict[str, str] = {}
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return found
    text = unescape_payload(text)

    # 1. Structured links (best labels).
    parser = LinkExtractor()
    try:
        parser.feed(text)
    except Exception:  # noqa: BLE001
        pass
    for href, label in parser.links:
        if not re.search(r"\.(pdf|xls[xm]?|docx?|rtf)(\?|#|$)", href, re.I):
            continue
        url = absolutize(href, base_url)
        if url:
            if label or url not in found:
                found[url] = label or found.get(url, "")

    # 2. Raw regex over the whole payload (catches JSON/JS-only references).
    for m in DOC_URL_RE.finditer(text):
        raw = m.group("url")
        url = absolutize(raw, base_url)
        if url:
            found.setdefault(url, "")

    # 3. Extension-less document hosts (Humana's Scene7 assets end in "pdf"
    #    with no dot; Sitecore Content Hub serves bare content ids).
    for m in EXTLESS_DOC_RE.finditer(text):
        url = absolutize(m.group(0), base_url)
        if url:
            found.setdefault(url, "")
    return found


def extract_page_urls(body: bytes, base_url: str) -> list[str]:
    try:
        text = unescape_payload(body.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return []
    urls = []
    for href in PAGE_URL_RE.findall(text):
        href = href.strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        if re.search(r"\.(pdf|xls[xm]?|docx?|rtf|jpe?g|png|gif|svg|css|js|zip|mp4)(\?|$)",
                     href, re.I):
            continue
        u = absolutize(href, base_url)
        if u:
            urls.append(u)
    # Same-site absolute paths mentioned in JSON payloads.
    for m in re.finditer(r'"(?:url|href|link|path)"\s*:\s*"(/[^"]{3,200})"', text):
        u = absolutize(m.group(1), base_url)
        if u and not re.search(r"\.(pdf|xls[xm]?|docx?|rtf)$", u, re.I):
            urls.append(u)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def absolutize(href: str, base_url: str) -> str | None:
    href = href.strip().strip('"\'')
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    try:
        url = urljoin(base_url, href)
    except Exception:  # noqa: BLE001
        return None
    url = url.split("#")[0]
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return url


def doc_ext(url: str) -> str:
    path = unquote(urlsplit(url).path).lower()
    for ext in DOC_EXTS:
        if path.endswith(ext):
            return ext
    # Humana's Scene7 asset host drops the dot: ".../2026 Medicare ... Listpdf"
    if path.endswith("pdf"):
        return ".pdf"
    return ""


# ---------------------------------------------------------------------------
# Relevance
# ---------------------------------------------------------------------------
def build_matcher(site: PayerSite, keep_all: bool):
    keep_all = keep_all or site.keep_all_docs
    keywords = tuple(k.lower() for k in (list(DEFAULT_KEYWORDS) + list(site.keywords)))
    word_re = re.compile(
        r"(?:^|[^a-z0-9])(?:" + "|".join(DEFAULT_WORD_KEYWORDS) + r")(?:[^a-z0-9]|$)",
        re.I)
    always = [re.compile(p, re.I) for p in site.always_keep]

    def relevant(url: str, label: str = "") -> bool:
        blob = f"{unquote(url)} {label}".lower()
        if any(p.search(url) or p.search(label or "") for p in always):
            return True
        if keep_all:
            return not any(n in blob for n in NEGATIVE_HINTS)
        if any(n in blob for n in NEGATIVE_HINTS):
            return False
        if any(k in blob for k in keywords):
            return True
        return bool(word_re.search(blob))

    return relevant


def host_allowed(url: str, hosts: list[str]) -> bool:
    netloc = urlsplit(url).netloc.lower().split(":")[0]
    for h in hosts:
        h = h.lower()
        if netloc == h or netloc.endswith("." + h):
            return True
    return False


# ---------------------------------------------------------------------------
# Discovery sources
# ---------------------------------------------------------------------------
def discover_sitemaps(fetcher: Fetcher, site: PayerSite, verbose: bool
                      ) -> tuple[list[str], dict[str, str]]:
    """Return (page_urls, {doc_url: label}) harvested from XML sitemaps."""
    candidates: list[str] = list(site.sitemaps)
    roots = {f"{urlsplit(s).scheme}://{urlsplit(s).netloc}" for s in site.seeds}
    for root in roots:
        body, _ = fetcher.get(f"{root}/robots.txt", timeout=25)
        if body:
            for line in body.decode("utf-8", "replace").splitlines():
                if line.lower().startswith("sitemap:"):
                    candidates.append(line.split(":", 1)[1].strip())
        candidates += [f"{root}/sitemap.xml", f"{root}/sitemap-index.xml",
                       f"{root}/sitemap_index.xml", f"{root}/wp-sitemap.xml"]

    pages: list[str] = []
    docs: dict[str, str] = {}
    seen_maps: set[str] = set()
    queue = list(dict.fromkeys(candidates))
    processed = 0
    while queue and processed < 60:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        body, _ = fetcher.get(sm, timeout=45)
        if not body or b"<" not in body[:400]:
            continue
        processed += 1
        text = body.decode("utf-8", "replace")
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
        if verbose and locs:
            log(f"      sitemap {sm}: {len(locs)} entries")
        for loc in locs:
            loc = html_mod.unescape(loc)
            if loc.lower().endswith(".xml") or ".xml?" in loc.lower():
                if len(seen_maps) + len(queue) < 60:
                    queue.append(loc)
            elif doc_ext(loc):
                docs.setdefault(loc, "")
            else:
                pages.append(loc)
    return pages, docs


def discover_wordpress(fetcher: Fetcher, site: PayerSite, verbose: bool
                       ) -> dict[str, str]:
    """Enumerate the WordPress media library of any configured WP root."""
    docs: dict[str, str] = {}
    for root in site.wp_roots:
        page = 1
        while page <= 40:
            url = (f"{root.rstrip('/')}/wp-json/wp/v2/media?media_type=application"
                   f"&per_page=100&page={page}&_fields=source_url,title,mime_type")
            body, _ = fetcher.get(url, timeout=60)
            if not body:
                break
            try:
                items = json.loads(body.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                break
            if not isinstance(items, list) or not items:
                break
            for item in items:
                src = item.get("source_url", "")
                if doc_ext(src):
                    title = html_mod.unescape(
                        (item.get("title") or {}).get("rendered", ""))
                    docs.setdefault(src, title)
            if verbose:
                log(f"      wp media page {page}: {len(items)} items "
                    f"({len(docs)} docs)")
            if len(items) < 100:
                break
            page += 1
            time.sleep(0.2)
    return docs


def discover_json_endpoints(fetcher: Fetcher, site: PayerSite, verbose: bool
                            ) -> dict[str, str]:
    docs: dict[str, str] = {}
    for endpoint in site.json_endpoints:
        body, _ = fetcher.get(endpoint, timeout=60)
        if not body:
            if verbose:
                log(f"      json endpoint unreachable: {endpoint}")
            continue
        found = extract_doc_urls(body, endpoint)
        # Try to pair titles with URLs inside JSON objects.
        try:
            text = unescape_payload(body.decode("utf-8", "replace"))
            for m in re.finditer(
                    r'"(?:title|name|label|linkText|displayName)"\s*:\s*"([^"]{3,200})"'
                    r'[^{}]{0,400}?"(?:url|href|link|path|file|documentUrl)"\s*:\s*'
                    r'"([^"]+\.(?:pdf|xls[xm]?|docx?|rtf)[^"]*)"', text, re.I | re.S):
                url = absolutize(m.group(2), endpoint)
                if url:
                    found[url] = m.group(1)
        except Exception:  # noqa: BLE001
            pass
        if verbose:
            log(f"      json endpoint {endpoint}: {len(found)} docs")
        for url, label in found.items():
            if label or url not in docs:
                docs[url] = label or docs.get(url, "")
    return docs


def crawl(fetcher: Fetcher, site: PayerSite, extra_pages: list[str],
          max_pages: int, depth: int, relevant, verbose: bool
          ) -> dict[str, str]:
    """Bounded BFS over the payer's own pages, harvesting document links."""
    page_pats = [re.compile(p, re.I) for p in site.page_patterns]
    deny_pats = [re.compile(p, re.I) for p in site.deny_patterns]
    hosts = site.allow_hosts or [urlsplit(s).netloc for s in site.seeds]

    def crawlable(url: str) -> bool:
        if not host_allowed(url, hosts):
            return False
        if any(p.search(url) for p in deny_pats):
            return False
        if page_pats and not any(p.search(url) for p in page_pats):
            return False
        return True

    frontier: list[tuple[str, int]] = [(u, 0) for u in site.seeds]
    frontier += [(u, depth - 1) for u in extra_pages if crawlable(u)]
    seen: set[str] = set()
    docs: dict[str, str] = {}
    visited = 0

    while frontier and visited < max_pages:
        url, d = frontier.pop(0)
        norm = url.rstrip("/")
        if norm in seen:
            continue
        seen.add(norm)
        body, ctype = fetch_page(fetcher, url, timeout=45)
        visited += 1
        if not body:
            continue
        if "pdf" in ctype or body.startswith(b"%PDF"):
            docs.setdefault(url, "")
            continue
        for durl, label in extract_doc_urls(body, url).items():
            if label or durl not in docs:
                docs[durl] = label or docs.get(durl, "")
        if verbose and visited % 25 == 0:
            log(f"      crawled {visited} pages, {len(docs)} document links")
        if d >= depth:
            continue
        for nxt in extract_page_urls(body, url):
            if nxt.rstrip("/") in seen or not crawlable(nxt):
                continue
            # Prefer pages whose URL looks prior-auth related: push them first.
            if relevant(nxt):
                frontier.insert(0, (nxt, d + 1))
            elif d + 1 < depth:
                frontier.append((nxt, d + 1))
        time.sleep(site.delay)
    if verbose:
        log(f"      crawl visited {visited} page(s)")
    return docs


CDX = "http://web.archive.org/cdx/search/cdx"


def discover_wayback(fetcher: Fetcher, site: PayerSite, since: int,
                     relevant, keep_all: bool, verbose: bool,
                     all_versions: bool = False
                     ) -> dict[str, list[str]]:
    """Return {live_url: [wayback_timestamp, ...]} from the Internet Archive.

    With all_versions=False only the newest capture of each URL is kept.  With
    all_versions=True the index is collapsed by content digest instead, so
    every distinct revision published at that URL is returned - this is how the
    superseded monthly/quarterly editions of a payer's PA list are recovered.
    """
    out: dict[str, list[str]] = {}
    collapse = "digest" if all_versions else "urlkey"
    for prefix in site.wayback_prefixes:
        params = (f"?url={requests.utils.quote(prefix, safe='*/:')}"
                  f"&output=text&fl=original,timestamp&collapse={collapse}"
                  f"&filter=statuscode:200&from={since}0101&limit=40000")
        body, _ = fetcher.get(CDX + params, timeout=180, cache=False)
        if not body:
            if verbose:
                log(f"      wayback: no response for {prefix}")
            continue
        rows = 0
        for line in body.decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            original, ts = parts[0], parts[1]
            if not doc_ext(original.split("?")[0]):
                continue
            if "404.aspx" in original.lower() or "error" in original.lower()[:60]:
                continue
            rows += 1
            if not (keep_all or site.wayback_keep_all or relevant(original)):
                continue
            live = original
            if live.startswith("http://"):
                live = "https://" + live[len("http://"):]
            live = live.replace(":80/", "/")
            stamps = out.setdefault(live, [])
            if all_versions:
                stamps.append(ts)
            elif not stamps or ts > stamps[0]:
                out[live] = [ts]
        if verbose:
            log(f"      wayback {prefix}: {rows} archived documents, "
                f"{len(out)} kept so far")
        time.sleep(0.5)
    return out


# ---------------------------------------------------------------------------
# Naming / saving
# ---------------------------------------------------------------------------
GENERIC_LABELS = {
    "", "click here", "here", "pdf", "download", "link", "view", "more",
    "learn more", "read more", "open", "document", "form", "list", "opens in a new window",
}


def prettify_stem(url: str) -> str:
    stem = unquote(Path(urlsplit(url).path).stem)
    stem = re.sub(r"[-_+]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = re.sub(r"^\d{6,}\s*", "", stem)          # leading asset ids
    stem = re.sub(r"\b([a-f0-9]{16,})\b", "", stem, flags=re.I)
    return stem.strip() or "document"


def safe_filename(label: str, url: str, ext: str) -> str:
    base = html_mod.unescape((label or "").strip())
    # Accordion toggles and bullets often lead the link text ("+ FAQ").
    base = re.sub(r"^[\s+\-•‣▪●>|]+", "", base)
    base = re.sub(r"\s*\(?\bopens? in (a )?new (window|tab)\b\)?\.?", "", base, flags=re.I)
    # "... PDF , 201 KB Last Updated : 03/25/2025" -> "..."
    base = re.sub(r"\s*(pdf|xls[xm]?|docx?|rtf)\s*,?\s*\d+(\.\d+)?\s*[kmg]?b\b.*$", "",
                  base, flags=re.I)
    base = re.sub(r"\s*last\s+updated\s*:?.*$", "", base, flags=re.I)
    base = re.sub(r"\s*\(?\b(pdf|xls[xm]?|docx?|rtf)\b\)?\s*$", "", base, flags=re.I)
    base = re.sub(r"\s*\(\s*\d+(\.\d+)?\s*[kmg]?b\s*\)\s*$", "", base, flags=re.I)
    base = re.sub(r"\s+", " ", base).strip(" .-_ ")
    if base.lower() in GENERIC_LABELS or len(base) < 4:
        base = prettify_stem(url)
    # Keep a URL hint when the label is very generic but reusable.
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" ._")
    if not base:
        base = "document"
    if len(base) > 150:
        base = base[:150].rstrip(" ._")
    return base + ext


def sniff_ext(content: bytes) -> str:
    """Extension implied by the magic bytes ('' when unrecognised).

    Recognises PDF, the OOXML zip container (xlsx / xlsm / docx / pptx), the
    legacy OLE container (xls / doc) and RTF.
    """
    if content[:4] == b"%PDF" or b"%PDF-" in content[:1024]:
        return ".pdf"
    if content[:5] == b"{\\rtf":
        return ".rtf"
    if content[:4] == b"PK\x03\x04":
        # The zip's first entries name the part tree: word/ for Word documents,
        # xl/ for workbooks.  Scan a generous window - the central directory of
        # a large workbook can push those names past the first few hundred bytes.
        head = content[:16000]
        if b"word/" in head:
            return ".docx"
        if b"xl/" in head or b"workbook.xml" in head:
            return ".xlsx"
        return ".xlsx"
    if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        # OLE compound file: Word and Excel share it; the URL extension decides.
        return ".xls"
    return ""


# Formats that share a container and therefore cannot be told apart from the
# magic bytes alone - any member of the group satisfies any other.
_ZIP_OFFICE = (".xlsx", ".xlsm", ".docx")
_OLE_OFFICE = (".xls", ".doc")


def magic_ok(content: bytes, ext: str) -> bool:
    sniffed = sniff_ext(content)
    if not sniffed:
        return False
    if not ext:                       # extension-less asset URL: any doc is fine
        return True
    if ext == ".pdf":
        return sniffed == ".pdf"
    if ext == ".rtf":
        return sniffed == ".rtf"
    if ext in _ZIP_OFFICE:
        return sniffed in _ZIP_OFFICE
    if ext in _OLE_OFFICE:
        # A .doc/.xls URL may serve a modern OOXML file after a CMS migration.
        return sniffed in _OLE_OFFICE + _ZIP_OFFICE
    return False


MANIFEST_NAME = ".download_manifest.json"


def count_files(folder: Path) -> int:
    """Documents in a payer folder, ignoring the saver's own bookkeeping."""
    return sum(1 for p in folder.iterdir()
               if p.is_file() and not p.name.startswith("."))


def url_key(url: str) -> str:
    """Normalised identity of a document URL (scheme, www and query ignored)."""
    return re.sub(r"^https?://(www\.)?", "", url.split("?")[0]).lower()


# --all-versions asks for every archived revision of one URL, so the manifest
# has to tell those revisions apart - the dated suffix run() puts on the label
# becomes part of the key.  Without this, revision 2 would look like revision 1
# and be skipped as "already downloaded".
_VERSION_LABEL_RE = re.compile(r"\(version (\d{4}-\d{2}-\d{2})\)\s*$")


def manifest_key(label: str, url: str) -> str:
    m = _VERSION_LABEL_RE.search(label or "")
    return f"{url_key(url)}#{m.group(1)}" if m else url_key(url)


class Saver:
    def __init__(self, dest_dir: Path):
        self.dest_dir = dest_dir
        self.seen_hashes: set[str] = set()
        self.hash_names: dict[str, str] = {}
        self.lock = threading.Lock()
        self.saved: list[str] = []
        self.existing_names: dict[str, str] = {}
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Index the folder three ways over, so a re-run skips work at three
        # levels: by SOURCE URL and by NAME before a document is fetched, and
        # by CONTENT after.
        self.manifest_path = dest_dir / MANIFEST_NAME
        self.manifest = self._load_manifest()
        self._dirty = False
        self._index_existing()
        for existing in dest_dir.iterdir():
            if existing.is_file() and existing.name != MANIFEST_NAME:
                try:
                    digest = hashlib.sha256(existing.read_bytes()).hexdigest()
                except Exception:  # noqa: BLE001
                    continue
                self.seen_hashes.add(digest)
                self.hash_names.setdefault(digest, existing.name)

    def _load_manifest(self) -> dict[str, str]:
        """url_key -> file name, from the last run.  Entries whose file has
        since been deleted are dropped, so removing a file really does mean
        'fetch it again'."""
        try:
            raw = json.loads(self.manifest_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items()
                if isinstance(v, str) and (self.dest_dir / v).exists()}

    def flush(self) -> None:
        """Persist manifest entries learned from skips (saves write as they go)."""
        with self.lock:
            if self._dirty:
                self._write_manifest()
                self._dirty = False

    def _write_manifest(self) -> None:
        """Persist the URL index.  Written via a temp file so an interrupted
        run cannot leave a half-written manifest behind."""
        tmp = self.manifest_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.manifest, indent=1, sort_keys=True),
                           "utf-8")
            tmp.replace(self.manifest_path)
        except OSError:
            pass

    def already_have(self, label: str, url: str) -> tuple[bool, str]:
        """Is this document already in the payer folder?

        Checked BEFORE the body is fetched, so a re-run costs no bandwidth for
        documents that are already on disk.  Returns (found, existing_name).

        Two things are tried, in order:

          1. the SOURCE URL, looked up in the manifest this saver wrote on an
             earlier run.  This is the reliable one - it holds even when the
             document is rediscovered under a different link label, or when its
             content turned out to duplicate a file already saved under another
             name.
          2. the FILE NAME, for folders filled before the manifest existed (and
             for files put there by hand).  Two names are tried, because the
             same document can be discovered under different labels on
             different runs: the name built from this run's link label, and the
             name built from the URL's own file stem.  Matching is
             case-insensitive and ignores the " (2)" suffix the saver adds on
             collisions, so re-runs recognise their own earlier output.
        """
        key = manifest_key(label, url)
        with self.lock:
            name = self.manifest.get(key)
            if name and (self.dest_dir / name).exists():
                return True, name
        ext = doc_ext(url)
        exts = [ext] if ext else list(DOC_EXTS)
        wanted = set()
        for e in exts:
            wanted.add(safe_filename(label, url, e))
            wanted.add(safe_filename("", url, e))       # URL-stem form
        with self.lock:
            for name in wanted:
                hit = self.existing_names.get(self._norm(name))
                if hit:
                    # Remember the URL behind this name, so folders filled
                    # before the manifest existed gain a URL index too.
                    self.manifest[key] = hit
                    self._dirty = True
                    return True, hit
        return False, ""

    @staticmethod
    def _norm(name: str) -> str:
        """Fold case and the collision suffix so re-runs match their own files."""
        stem, ext = Path(name).stem, Path(name).suffix
        stem = re.sub(r"\s*\(\d+\)$", "", stem)
        return f"{stem.strip().lower()}{ext.lower()}"

    def _index_existing(self) -> None:
        """Map normalised file name -> actual file name, for the pre-fetch check."""
        self.existing_names = {}
        for existing in self.dest_dir.iterdir():
            if existing.is_file() and not existing.name.startswith("."):
                self.existing_names.setdefault(self._norm(existing.name),
                                               existing.name)

    def save(self, content: bytes, label: str, url: str) -> str | None:
        digest = hashlib.sha256(content).hexdigest()
        ext = doc_ext(url) or sniff_ext(content) or ".bin"
        key = manifest_key(label, url)
        with self.lock:
            if digest in self.seen_hashes:
                # Same bytes under a second URL.  Point that URL at the file we
                # already hold, so the next run skips it before fetching rather
                # than downloading it again to rediscover it is a duplicate.
                twin = self.hash_names.get(digest)
                if twin:
                    self.manifest[key] = twin
                    self._write_manifest()
                    self._dirty = False
                return None
            self.seen_hashes.add(digest)
            name = safe_filename(label, url, ext)
            dest = self.dest_dir / name
            n = 2
            while dest.exists():
                dest = self.dest_dir / f"{Path(name).stem} ({n}){ext}"
                n += 1
            dest.write_bytes(content)
            self.saved.append(dest.name)
            # Keep the name index live so two workers racing on the same
            # document within one run don't both write it.
            self.existing_names.setdefault(self._norm(dest.name), dest.name)
            self.hash_names.setdefault(digest, dest.name)
            self.manifest[key] = dest.name
            self._write_manifest()
            self._dirty = False
        return dest.name


# ---------------------------------------------------------------------------
# PDF / non-PDF split
# ---------------------------------------------------------------------------
# Payers that publish workbooks and Word documents alongside their PDFs can
# keep the two apart: PDFs stay in downloaded/<payer>/, everything else goes to
# a parallel tree of the same shape.  Opt in with run_split() instead of run().
NONPDF_ROOT = ROOT / "downloaded_NonPDF"


def nonpdf_dir(pdf_dir: Path) -> Path:
    """downloaded/<payer> -> downloaded_NonPDF/<payer> (same structure)."""
    return NONPDF_ROOT / pdf_dir.name


class SplitSaver:
    """Saver front-end that files PDFs and non-PDFs into separate trees.

    Wraps two ordinary Savers - one per tree - so each keeps its own name index
    and content hashes, and duplicate detection stays correct within a folder.
    The non-PDF saver is built on first use, so a payer that publishes nothing
    but PDFs never grows an empty downloaded_NonPDF folder.
    """

    instances: list["SplitSaver"] = []

    def __init__(self, dest_dir: Path):
        self.pdf = Saver(dest_dir)
        self.nonpdf_dir = nonpdf_dir(dest_dir)
        self._other: Saver | None = None
        self._lock = threading.Lock()
        SplitSaver.instances.append(self)

    @property
    def other(self) -> Saver:
        with self._lock:
            if self._other is None:
                self._other = Saver(self.nonpdf_dir)
            return self._other

    @property
    def seen_hashes(self) -> set[str]:
        # run() reports this against the PDF folder it just announced, and
        # reading it must not bring the non-PDF folder into existence.
        return self.pdf.seen_hashes

    def already_have(self, label: str, url: str) -> tuple[bool, str]:
        ext = doc_ext(url)
        if ext == ".pdf":
            return self.pdf.already_have(label, url)
        # Non-PDF, and extension-less URLs whose tree is unknown until the bytes
        # arrive: a hit in EITHER tree counts as already held.  The PDF tree is
        # consulted because folders harvested before the split hold workbooks
        # and Word files too - already collected is already collected, and
        # re-downloading them into the new tree would only make a second copy.
        #
        # A non-PDF folder that does not exist holds nothing, so it is not
        # opened just to be asked: merely considering a workbook must not
        # conjure an empty folder for a payer that never publishes one.
        savers = [self.pdf]
        if self._other is not None or self.nonpdf_dir.exists():
            savers.insert(0, self.other)
        for saver in savers:
            have, existing = saver.already_have(label, url)
            if have:
                return True, existing
        return False, ""

    def flush(self) -> None:
        self.pdf.flush()
        if self._other is not None:
            self._other.flush()

    def save(self, content: bytes, label: str, url: str) -> str | None:
        # The bytes decide, not the link: sniff first, fall back to the URL
        # extension only when the magic bytes are unrecognised.
        ext = sniff_ext(content) or doc_ext(url)
        return (self.pdf if ext == ".pdf" else self.other).save(content, label, url)


def run_split(site: PayerSite, argv: list[str] | None = None,
              saver_factory: type = SplitSaver) -> int:
    """run(), with PDFs and non-PDFs written to their own trees."""
    before = len(SplitSaver.instances)
    rc = run(site, argv, saver_factory=saver_factory)
    for saver in SplitSaver.instances[before:]:
        if saver._other is not None:
            log(f"Non-PDF folder now holds "
                f"{count_files(saver.nonpdf_dir)} file(s): "
                f"{saver.nonpdf_dir}")
    return rc


def wayback_url(original: str, ts: str) -> str:
    return f"https://web.archive.org/web/{ts}id_/{original}"


def looks_complete(content: bytes, ext: str) -> bool:
    """Reject bodies that were cut short (the Internet Archive truncates some
    captures at exactly 1 MiB, which yields an unreadable PDF)."""
    ext = ext or sniff_ext(content)
    if ext in (".rtf", ".doc", ".xls"):
        return len(content) != 1048576   # no cheap end marker; flag the 1 MiB cut
    if ext == ".pdf":
        return b"%%EOF" in content[-8192:]
    if ext in _ZIP_OFFICE:
        # End-of-central-directory record must be present for a valid zip.
        return b"PK\x05\x06" in content[-66000:]
    return len(content) != 1048576


def fetch_document(fetcher: Fetcher, url: str, ts: str | list[str] | None,
                   referer: str | None = None,
                   archive_first: bool = False) -> tuple[bytes | None, str]:
    """Try live URL, then curl, then the archived snapshot.

    archive_first is used when a specific archived revision is wanted (the
    --all-versions mode), where the live URL would return today's edition.

    Returns (content, status) where status is 'ok', 'truncated' (only a
    cut-short copy exists) or 'fail'.
    """
    ext = doc_ext(url)
    partial: bytes | None = None
    stamps = [ts] if isinstance(ts, str) else list(ts or [])
    ts = stamps[0] if stamps else None

    def consider(data: bytes | None) -> bytes | None:
        nonlocal partial
        if not data or not magic_ok(data, ext):
            return None
        if looks_complete(data, ext):
            return data
        if partial is None or len(data) > len(partial):
            partial = data
        return None

    if archive_first and ts:
        arch, _ = fetcher.get(wayback_url(url, ts), timeout=180, cache=False)
        good = consider(arch)
        if good:
            return good, "ok"

    body, ctype = fetcher.get(url, timeout=120, cache=False, referer=referer)
    if body is not None and "text/html" in ctype and not body[:4] == b"%PDF":
        body = None
    good = consider(body)
    if good:
        return good, "ok"
    good = consider(curl_get(url, timeout=120))
    if good:
        return good, "ok"
    if ts:
        arch, _ = fetcher.get(wayback_url(url, ts), timeout=180, cache=False)
        good = consider(arch)
        if good:
            return good, "ok"
        # Some captures are only complete under a different timestamp.
        arch2, _ = fetcher.get(wayback_url(url, "2"), timeout=180, cache=False)
        good = consider(arch2)
        if good:
            return good, "ok"
    if partial is not None:
        return None, "truncated"
    return None, "fail"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def build_parser(site: PayerSite) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=f"Download {site.payer} prior-authorization / precertification "
                    f"documents (work-harder edition).")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--no-crawl", action="store_true")
    ap.add_argument("--no-sitemap", action="store_true")
    ap.add_argument("--no-wayback", action="store_true")
    ap.add_argument("--wayback-only", action="store_true")
    ap.add_argument("--since", type=int, default=site.wayback_since)
    ap.add_argument("--max-pages", type=int, default=site.max_pages)
    ap.add_argument("--depth", type=int, default=site.depth)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pdf-only", action="store_true",
                    help="ignore Excel and Word documents (PDF only)")
    ap.add_argument("--excel-only", action="store_true",
                    help="keep only .xlsx/.xlsm/.xls documents")
    ap.add_argument("--word-only", action="store_true",
                    help="keep only .docx/.doc/.rtf documents")
    ap.add_argument("--refetch", action="store_true",
                    help="re-download documents whose file name is already in "
                         "the payer folder (default: skip them)")
    ap.add_argument("--all-versions", action="store_true",
                    help="download every distinct archived revision of each "
                         "document, not just the newest (file names get the "
                         "capture date)")
    ap.add_argument("--all", action="store_true",
                    help="keep every document found, not just prior-auth matches")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap


def run(site: PayerSite, argv: list[str] | None = None,
        saver_factory: type | None = None) -> int:
    """Harvest one payer.  saver_factory swaps in a different Saver (see
    run_split, which files non-PDFs into their own tree)."""
    args = build_parser(site).parse_args(argv)
    verbose = args.verbose
    fetcher = Fetcher(verify=site.verify_tls)
    relevant = build_matcher(site, keep_all=args.all)

    log("=" * 78)
    log(f"{site.payer} - prior-authorization document harvest")
    if site.notes:
        log(f"  {site.notes}")
    log("=" * 78)

    docs: dict[str, str] = {}          # url -> label
    ts_map: dict[str, list[str]] = {}  # url -> wayback timestamps (fallback)
    referer_map: dict[str, str] = {}

    def merge(new: dict[str, str], source: str) -> None:
        before = len(docs)
        for url, label in new.items():
            if label or url not in docs:
                docs[url] = label or docs.get(url, "")
        log(f"  [{source}] {len(new)} document link(s) "
            f"(+{len(docs) - before} new, {len(docs)} total)")

    if not args.wayback_only:
        # 1. Seed pages (always fetched, even if crawling is off).
        seed_docs: dict[str, str] = {}
        for seed in site.seeds:
            body, ctype = fetch_page(fetcher, seed, timeout=60)
            if not body or looks_blocked(body):
                log(f"  ! seed unreachable or bot-blocked (live and archived): "
                    f"{seed}")
                continue
            if body.startswith(b"%PDF"):
                seed_docs[seed] = ""
                continue
            for u, lbl in extract_doc_urls(body, seed).items():
                if lbl or u not in seed_docs:
                    seed_docs[u] = lbl or seed_docs.get(u, "")
                referer_map.setdefault(u, seed)
        merge(seed_docs, "seed pages")

        # 2. Sitemaps.
        sitemap_pages: list[str] = []
        if not args.no_sitemap:
            sitemap_pages, sm_docs = discover_sitemaps(fetcher, site, verbose)
            merge(sm_docs, "sitemap documents")
            keep = [p for p in sitemap_pages
                    if host_allowed(p, site.allow_hosts or
                                    [urlsplit(s).netloc for s in site.seeds])
                    and relevant(p)]
            log(f"  [sitemap pages] {len(sitemap_pages)} page(s), "
                f"{len(keep)} look prior-auth related")
            sitemap_pages = keep

        # 3. CMS APIs.
        if site.wp_roots:
            merge(discover_wordpress(fetcher, site, verbose), "wordpress media")
        if site.json_endpoints:
            merge(discover_json_endpoints(fetcher, site, verbose), "json endpoints")

        # 4. BFS crawl.
        if not args.no_crawl:
            crawled = crawl(fetcher, site, sitemap_pages, args.max_pages,
                            args.depth, relevant, verbose)
            merge(crawled, "site crawl")

        # 5. Hard-coded fallbacks.
        if site.fallback_docs:
            merge({u: l for u, l in site.fallback_docs}, "known documents")

    # 6. Internet Archive.
    if not args.no_wayback and site.wayback_prefixes:
        wb = discover_wayback(fetcher, site, args.since, relevant, args.all,
                              verbose, all_versions=args.all_versions)
        wb_docs = {}
        for url, stamps in wb.items():
            ts_map.setdefault(url, sorted(set(stamps), reverse=True))
            wb_docs[url] = ""
        merge(wb_docs, "internet archive")

    # ---- filter ----------------------------------------------------------
    keep: list[tuple[str, str]] = []
    for url, label in docs.items():
        ext = doc_ext(url)
        if not ext:
            # Extension-less asset URLs (Sitecore Content Hub content ids) are
            # kept: the magic-byte check after download decides what they are.
            if not EXTLESS_DOC_RE.match(url):
                continue
        if ext:
            if args.pdf_only and ext not in PDF_EXTS:
                continue
            if args.excel_only and ext not in EXCEL_EXTS:
                continue
            if args.word_only and ext not in WORD_EXTS:
                continue
        if not relevant(url, label):
            continue
        keep.append((url, label))

    # De-duplicate URLs that differ only by query string / http-https / case.
    dedup: dict[str, tuple[str, str]] = {}
    for url, label in keep:
        key = re.sub(r"^https?://(www\.)?", "", url.split("?")[0]).lower()
        prev = dedup.get(key)
        if prev is None or (not prev[1] and label):
            dedup[key] = (url, label)
    pairs = sorted(dedup.values(), key=lambda kv: (kv[1] or kv[0]).lower())

    # Expand each URL into its archived revisions when --all-versions is on.
    ordered: list[tuple[str, str, str | None]] = []
    for url, label in pairs:
        stamps = ts_map.get(url) or []
        if args.all_versions and len(stamps) > 1:
            for ts in stamps:
                dated = f"{label or prettify_stem(url)} (version {ts[:4]}-{ts[4:6]}-{ts[6:8]})"
                ordered.append((url, dated, ts))
        else:
            ordered.append((url, label, stamps[0] if stamps else None))

    log("")
    log(f"Candidate documents after filtering: {len(ordered)} "
        f"(from {len(docs)} discovered link(s))")

    if args.list_only:
        for url, label, ts in ordered:
            log(f"  {label or '(no label)'}\n      {url}"
                + (f"   [archive {ts}]" if ts else ""))
        return 0

    if args.limit:
        ordered = ordered[:args.limit]

    dest_dir = DOWNLOAD_ROOT / site.payer
    saver = (saver_factory or Saver)(dest_dir)
    log(f"Downloading into {dest_dir} ({len(saver.seen_hashes)} file(s) already there)")

    stats = {"saved": 0, "present": 0, "dup": 0, "fail": 0, "truncated": 0}
    stats_lock = threading.Lock()

    def worker(item):
        idx, (url, label, ts) = item
        if not args.refetch:
            have, existing = saver.already_have(label, url)
            if have:
                with stats_lock:
                    stats["present"] += 1
                if verbose:
                    log(f"  [{idx}] already in folder, not downloaded: {existing}")
                return
        content, status = fetch_document(fetcher, url, ts,
                                         referer_map.get(url),
                                         archive_first=bool(ts) and args.all_versions)
        if content is None:
            with stats_lock:
                stats["truncated" if status == "truncated" else "fail"] += 1
            if verbose:
                log(f"  [{idx}] {status.upper()} {url}")
            return
        name = saver.save(content, label, url)
        with stats_lock:
            if name:
                stats["saved"] += 1
                log(f"  [{idx}/{len(ordered)}] saved {name} ({len(content):,} B)")
            else:
                stats["dup"] += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        list(pool.map(worker, enumerate(ordered, 1)))
    saver.flush()

    log("")
    log("-" * 78)
    log(f"{site.payer}: {stats['saved']} new file(s) saved, "
        f"{stats['present']} already in the folder by name (not downloaded), "
        f"{stats['dup']} duplicate content, "
        f"{stats['truncated']} only available truncated (skipped), "
        f"{stats['fail']} unavailable.")
    log(f"Folder now holds {count_files(dest_dir)} file(s): {dest_dir}")
    return 0
