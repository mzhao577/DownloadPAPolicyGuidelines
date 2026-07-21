"""
Download prior authorization / precertification documents for a list of
payers, one payer at a time.

Payer names are taken from the terminal, either as arguments or from a
text file (one payer per line):

    python3 download_ManyPayer_precert_policies.py Aetna Cigna humana
    python3 download_ManyPayer_precert_policies.py --file listofpayer.txt

Name matching is forgiving: "UHC", "unitedhealthcare", "BCBS_AZ",
"Avera care", etc. all resolve to the right payer.

For each payer the script:
  1. Scrapes the payer's prior-authorization / precertification web
     page(s) for PDF links whose URL or link text looks like a prior
     auth / precert document.
  2. Adds known direct PDF URLs for that payer (some payer sites render
     their links with JavaScript, so scraping alone can miss them).
  3. Downloads every unique document into ./downloaded/<PayerName>/.

Some payers (e.g. Anthem, Horizon BCBSNJ) publish requirements through
interactive code-lookup tools instead of PDFs; for those the script
downloads whatever PDFs it can find and prints the lookup-tool URL.
"""

import argparse
import hashlib
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

DOWNLOAD_DIR = Path(__file__).parent / "downloaded"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# Keywords that mark a PDF link as a prior-auth / precert document.
DEFAULT_KEYWORDS = (
    "precert",
    "pre-cert",
    "prior auth",
    "prior-auth",
    "priorauth",
    "prior_auth",
    "preauthorization",
    "pre-authorization",
    "preauth",
    "advance notification",
    "advance-notification",
    "advnotice",
    "notification list",
    "pa-requirements",
    "pa requirements",
)

# ---------------------------------------------------------------------------
# Payer registry.
#
# aliases     : alternate names accepted from the terminal
# pages       : payer web pages scraped for matching PDF links
# direct_pdfs : known document URLs (used when pages are JS-rendered)
# note        : printed when the payer relies on an interactive lookup tool
# ---------------------------------------------------------------------------
PAYERS = {
    "Aetna": {
        "aliases": ["aetna"],
        "pages": [
            "https://www.aetna.com/health-care-professionals/"
            "precertification/precertification-lists.html",
        ],
        "direct_pdfs": [
            "https://www.aetna.com/content/dam/aetna/pdfs/aetnacom/"
            "healthcare-professionals/2026_Precert_List.pdf",
        ],
    },
    "UnitedHealthcare": {
        "aliases": ["uhc", "united", "unitedhealthcare", "united healthcare",
                    "united health care"],
        "pages": [
            "https://www.uhcprovider.com/en/prior-auth-advance-notification/"
            "adv-notification-plan-reqs.html",
        ],
        "direct_pdfs": [
            "https://www.uhcprovider.com/content/dam/provider/docs/public/"
            "prior-auth/pa-requirements/commercial/"
            "UHC-Commercial-Advance-Notification-PA-Requirements-1-2026.pdf",
            "https://www.uhcprovider.com/content/dam/provider/docs/public/"
            "prior-auth/pa-requirements/multi/"
            "2026-Summary-of-Changes-AdvNotice-and-PriorAuth.pdf",
            "https://www.uhcprovider.com/content/dam/provider/docs/public/"
            "prior-auth/exchanges/"
            "UHC-Exchange-Plans-Advance-Notification-PA-Eff-1-1-26.pdf",
        ],
    },
    "Cigna": {
        "aliases": ["cigna"],
        "pages": [
            "https://www.cigna.com/health-care-providers/"
            "coverage-and-claims/precertification",
        ],
        "direct_pdfs": [
            "https://www.cigna.com/static/www-cigna-com/docs/"
            "master-precertification-list-for-providers.pdf",
            "https://www.cigna.com/static/www-cigna-com/docs/"
            "master-precertification-list-codes-removed-for-providers.pdf",
            "https://medicareproviders.cigna.com/static/"
            "medicareproviders-cigna-com/docs/"
            "prior-authorization-requirements.pdf",
        ],
    },
    "Humana": {
        "aliases": ["humana"],
        "pages": [
            "https://provider.humana.com/coverage-claims/"
            "prior-authorizations/prior-authorization-lists",
        ],
        "direct_pdfs": [
            "https://assets.humana.com/is/content/humana/"
            "FINAL_Medicare%20and%20DSNP%20Prior%20Authorization"
            "%20and%20Notification%20List%20-%201-1-2026pdf",
            "https://assets.humana.com/is/content/humana/"
            "2026%20Medicare%20Prior%20Authorization%20Listpdf",
        ],
    },
    "Anthem": {
        "aliases": ["anthem", "anthem bcbs", "elevance"],
        "pages": [
            "https://www.anthem.com/provider/individual-commercial/"
            "prior-authorization",
        ],
        "direct_pdfs": [],
        "note": (
            "Anthem publishes most prior-auth requirements through its "
            "interactive lookup tool at https://www.anthem.com/provider/"
            "individual-commercial/prior-authorization (state-specific "
            "lists at providers.anthem.com)."
        ),
    },
    "Horizon": {
        "aliases": ["horizon", "horizon bcbs", "horizon bcbsnj",
                    "horizon blue cross"],
        "pages": [
            "https://www.horizonblue.com/providers/resources/"
            "provider-self-service-tools/prior-authorization-search",
        ],
        "direct_pdfs": [],
        "note": (
            "Horizon BCBSNJ publishes prior-auth requirements through a "
            "CPT/HCPCS code search tool: https://www.horizonblue.com/"
            "providers/resources/provider-self-service-tools/"
            "prior-authorization-search"
        ),
    },
    "Medica": {
        "aliases": ["medica"],
        "pages": [
            "https://partner.medica.com/providers/policies-and-guidelines/"
            "um-policies-and-prior-authorization",
        ],
        "direct_pdfs": [
            "https://partner.medica.com/-/media/documents/provider/"
            "prior-authorization-list.pdf?la=en",
            "https://partner.medica.com/-/media/documents/provider/"
            "2026-medicare-prior-authorization-list.pdf?la=en",
        ],
    },
    "AveraCare": {
        "aliases": ["avera", "avera care", "averacare",
                    "avera health plans"],
        "pages": [
            "https://www.averahealthplans.com/insurance/for-providers/"
            "preauthorizations/",
        ],
        "direct_pdfs": [
            "https://www.averahealthplans.com/app/files/public/"
            "5eca6f2d-6a6c-4762-88ce-57cbf356401a/preauthorization-list.pdf",
        ],
    },
    "BCBS_AZ": {
        "aliases": ["bcbs az", "bcbsaz", "azblue", "az blue",
                    "blue cross blue shield arizona",
                    "blue cross blue shield of arizona"],
        "pages": [
            "https://www.azblue.com/provider/resources/"
            "prior-authorization-and-medical-policies",
        ],
        "direct_pdfs": [
            "https://provider.azblue.com/~/media/azblue/files/healthcare/"
            "precertification-requests-quick-guide.pdf",
        ],
        "note": (
            "AZ Blue's full prior-auth code lists are behind its lookup "
            "tool: https://priorauth.azblue.com/"
        ),
    },
}


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


def normalize(name: str) -> str:
    """Lowercase and strip everything but letters/digits, for matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_payer(name: str):
    """Map a user-supplied payer name to (canonical, config), or None."""
    wanted = normalize(name)
    if not wanted:
        return None
    for canonical, cfg in PAYERS.items():
        candidates = [canonical] + cfg["aliases"]
        if any(normalize(c) == wanted for c in candidates):
            return canonical, cfg
    return None


def filename_from_url(url: str) -> str:
    """Derive a safe local filename from a document URL."""
    name = unquote(Path(urlparse(url).path).name)
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    # Humana asset URLs end in "...Listpdf" with no dot.
    if not name.lower().endswith(".pdf"):
        name = re.sub(r"pdf$", "", name, flags=re.IGNORECASE).strip() + ".pdf"
    return name


def scrape_pdf_links(session, page_url, keywords):
    """Return {pdf_url: link_text} for matching links found on a page."""
    try:
        resp = session.get(page_url, timeout=60)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"    Could not fetch page ({exc})")
        return {}

    parser = LinkExtractor()
    parser.feed(resp.text)

    found = {}
    for href, text in parser.links:
        if ".pdf" not in href.lower():
            continue
        haystack = f"{href} {text}".lower()
        if not any(k in haystack for k in keywords):
            continue
        found[urljoin(page_url, href)] = text
    return found


def download_pdf(session, url, dest_dir, seen_hashes) -> bool:
    """Download one PDF; skip duplicates and non-PDF responses."""
    dest = dest_dir / filename_from_url(url)
    print(f"  Downloading: {url}")
    try:
        resp = session.get(url, timeout=120)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"    Failed: {exc}")
        return False

    if not resp.content.startswith(b"%PDF"):
        print(f"    Skipped (response is not a PDF): {dest.name}")
        return False

    digest = hashlib.sha256(resp.content).hexdigest()
    if digest in seen_hashes:
        print(f"    Skipped (duplicate content): {dest.name}")
        return False

    dest.write_bytes(resp.content)
    seen_hashes.add(digest)
    print(f"    Saved: {dest.name} ({len(resp.content):,} bytes)")
    return True


def process_payer(session, canonical: str, cfg: dict) -> int:
    """Download all prior-auth documents for one payer. Returns file count."""
    print(f"\n{'=' * 70}\nPayer: {canonical}\n{'=' * 70}")
    keywords = cfg.get("keywords", DEFAULT_KEYWORDS)

    documents = {}
    for page in cfg["pages"]:
        print(f"  Scanning page: {page}")
        documents.update(scrape_pdf_links(session, page, keywords))
    for url in cfg["direct_pdfs"]:
        documents.setdefault(url, "")

    if not documents:
        print("  No downloadable prior-auth PDFs found for this payer.")
        if cfg.get("note"):
            print(f"  Note: {cfg['note']}")
        return 0

    dest_dir = DOWNLOAD_DIR / canonical
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Found {len(documents)} document link(s).")

    seen_hashes: set[str] = set()
    saved = sum(
        download_pdf(session, url, dest_dir, seen_hashes) for url in documents
    )
    if cfg.get("note"):
        print(f"  Note: {cfg['note']}")
    print(f"  {saved} file(s) saved to {dest_dir}")
    return saved


def read_payer_names(args) -> list[str]:
    names = list(args.payers)
    if args.file:
        content = Path(args.file).read_text()
        names.extend(line.strip() for line in content.splitlines())
    return [n for n in names if n.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Download prior authorization / precertification documents "
            "for one or more payers."
        )
    )
    ap.add_argument("payers", nargs="*", help="payer names, e.g. Aetna UHC Cigna")
    ap.add_argument(
        "-f", "--file",
        help="text file with one payer name per line (e.g. listofpayer.txt)",
    )
    args = ap.parse_args()

    names = read_payer_names(args)
    if not names:
        ap.print_usage()
        print(f"\nSupported payers: {', '.join(sorted(PAYERS))}")
        sys.exit(1)

    session = requests.Session()
    session.headers.update(HEADERS)
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    total = 0
    unresolved = []
    for name in names:
        resolved = resolve_payer(name)
        if resolved is None:
            unresolved.append(name)
            print(f"\nUnknown payer '{name}' - skipping.")
            continue
        total += process_payer(session, *resolved)

    print(f"\n{'=' * 70}")
    print(f"Finished. {total} file(s) downloaded to {DOWNLOAD_DIR}")
    if unresolved:
        print(f"Unrecognized payer name(s): {', '.join(unresolved)}")
        print(f"Supported payers: {', '.join(sorted(PAYERS))}")


if __name__ == "__main__":
    main()
