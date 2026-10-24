"""
Download prior authorization / precertification / notification documents for a
list of payers, one payer at a time, and record the source websites used.

Usage
-----
    # Download for specific payers:
    python3 download_ManyPayer_precert_policies.py Aetna Cigna humana

    # Download for every payer listed in a file (one name per line):
    python3 download_ManyPayer_precert_policies.py --file listofpayer.txt

    # Download EVERY payer in the registry:
    python3 download_ManyPayer_precert_policies.py --all

    # Only (re)write listofpayer_withWebsites.csv, download nothing:
    python3 download_ManyPayer_precert_policies.py --csv-only

    # Also fetch every distinct version published in a year via the
    # Internet Archive (Wayback Machine) for each document that was found:
    python3 download_ManyPayer_precert_policies.py Aetna --year 2026

Name matching is forgiving: "UHC", "unitedhealthcare", "BCBS_AZ",
"Avera care", "us family health", etc. all resolve to the right payer.

For each payer the script:
  1. Scrapes the payer's prior-authorization / precertification web page(s)
     for PDF links whose URL or link text looks like a prior-auth / precert /
     notification document (embedded JSON "content fragments" are unescaped
     and scanned too, because many payer pages are JavaScript-rendered).
  2. Adds a small hard-coded fallback list of known direct PDF URLs for that
     payer, used only if scraping turns up nothing (so a page-layout change
     degrades gracefully instead of failing).
  3. Downloads every unique document into ./downloaded/<PayerName>/, using a
     human-friendly file name derived from the link label, validating that
     each body is a real PDF and de-duplicating by SHA-256 content hash.

Whenever the script runs it also (re)writes listofpayer_withWebsites.csv with
one row per (PayerName, PayerPlan, Website) so the source pages are recorded.

Some payers (e.g. Anthem, Horizon BCBSNJ) publish requirements through
interactive code-lookup tools instead of PDFs; for those the script downloads
whatever PDFs it can find and prints the lookup-tool URL.
"""

import argparse
import csv
import hashlib
import html
import re
import shutil
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

# Some payer CDNs (Imperva/Akamai bot protection) fingerprint the TLS/HTTP
# client and return 403 to python-requests while allowing a normal browser
# or curl. When available, curl is used as a fallback for those responses.
CURL = shutil.which("curl")

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloaded"
WEBSITES_CSV = BASE_DIR / "listofpayer_withWebsites.csv"
WAYBACK_CDX_API = "https://web.archive.org/cdx/search/cdx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# Keywords that mark a PDF link as a prior-auth / precert / notification doc.
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
    "pre-auth",
    "advance notification",
    "advance-notification",
    "advnotice",
    "notification list",
    "notification-list",
    "pa-requirements",
    "pa requirements",
    "pa-list",
    "pa list",
    "prior authorization",
    "authorization list",
    "summary of change",
    "summary-of-change",
    "clinical program",
    "clinical_program",
    "medical-drug",
    "medical drug",
)

# ---------------------------------------------------------------------------
# Payer registry.
#
# Each payer maps to:
#   aliases : alternate names accepted from the terminal
#   sites   : list of {plan, page, direct_pdfs} where
#               plan        : market / plan label (used in the CSV and to
#                             disambiguate file names)
#               page        : provider PA / precert web page scraped for links
#                             (also recorded in listofpayer_withWebsites.csv)
#               direct_pdfs : list of {label, url} known documents, used as a
#                             fallback when scraping the page finds nothing
#   note    : printed when the payer relies on an interactive lookup tool
# ---------------------------------------------------------------------------
PAYERS = {
    "Aetna": {
        "aliases": ["aetna"],
        "sites": [
            {
                "plan": "Commercial & Medicare",
                "page": (
                    "https://www.aetna.com/health-care-professionals/"
                    "precertification/precertification-lists.html"
                ),
                "direct_pdfs": [
                    {
                        "label": "2026 Precertification List",
                        "url": (
                            "https://www.aetna.com/content/dam/aetna/pdfs/"
                            "aetnacom/healthcare-professionals/"
                            "2026_Precert_List.pdf"
                        ),
                    },
                ],
            },
        ],
    },
    "UnitedHealthcare": {
        "aliases": [
            "uhc", "united", "unitedhealthcare", "united healthcare",
            "united health care",
        ],
        "sites": [
            {
                "plan": "Commercial",
                "page": (
                    "https://www.uhcprovider.com/en/prior-auth-advance-"
                    "notification/adv-notification-plan-reqs.html"
                ),
                "direct_pdfs": [
                    {
                        "label": "UHC Commercial Advance Notification "
                                 "and PA Requirements (2026)",
                        "url": (
                            "https://www.uhcprovider.com/content/dam/provider/"
                            "docs/public/prior-auth/pa-requirements/commercial/"
                            "UHC-Commercial-Advance-Notification-PA-"
                            "Requirements-1-2026.pdf"
                        ),
                    },
                    {
                        "label": "2026 Summary of Changes - Advance "
                                 "Notification and Prior Authorization",
                        "url": (
                            "https://www.uhcprovider.com/content/dam/provider/"
                            "docs/public/prior-auth/pa-requirements/multi/"
                            "2026-Summary-of-Changes-AdvNotice-and-"
                            "PriorAuth.pdf"
                        ),
                    },
                ],
            },
            {
                "plan": "Individual Exchange",
                "page": (
                    "https://www.uhcprovider.com/en/prior-auth-advance-"
                    "notification/adv-notification-plan-reqs.html"
                ),
                "direct_pdfs": [
                    {
                        "label": "UHC Exchange Plans Advance Notification "
                                 "and PA (Eff 1-1-26)",
                        "url": (
                            "https://www.uhcprovider.com/content/dam/provider/"
                            "docs/public/prior-auth/exchanges/"
                            "UHC-Exchange-Plans-Advance-Notification-PA-"
                            "Eff-1-1-26.pdf"
                        ),
                    },
                ],
            },
        ],
    },
    "Cigna": {
        "aliases": ["cigna"],
        "sites": [
            {
                "plan": "Commercial",
                "page": (
                    "https://www.cigna.com/health-care-providers/"
                    "coverage-and-claims/precertification"
                ),
                "direct_pdfs": [
                    {
                        "label": "Master Precertification List for Providers",
                        "url": (
                            "https://www.cigna.com/static/www-cigna-com/docs/"
                            "master-precertification-list-for-providers.pdf"
                        ),
                    },
                    {
                        "label": "Master Precertification List - Codes "
                                 "Removed",
                        "url": (
                            "https://www.cigna.com/static/www-cigna-com/docs/"
                            "master-precertification-list-codes-removed-for-"
                            "providers.pdf"
                        ),
                    },
                ],
            },
            {
                "plan": "Medicare Advantage",
                "page": (
                    "https://medicareproviders.cigna.com/"
                ),
                "direct_pdfs": [
                    {
                        "label": "Cigna Medicare Prior Authorization "
                                 "Requirements",
                        "url": (
                            "https://medicareproviders.cigna.com/static/"
                            "medicareproviders-cigna-com/docs/"
                            "prior-authorization-requirements.pdf"
                        ),
                    },
                ],
            },
        ],
    },
    "Humana": {
        "aliases": ["humana"],
        "sites": [
            {
                "plan": "Medicare & Commercial",
                "page": (
                    "https://provider.humana.com/coverage-claims/"
                    "prior-authorizations/prior-authorization-lists"
                ),
                "direct_pdfs": [
                    {
                        "label": "Medicare and DSNP Prior Authorization "
                                 "and Notification List (1-1-2026)",
                        "url": (
                            "https://assets.humana.com/is/content/humana/"
                            "FINAL_Medicare%20and%20DSNP%20Prior%20"
                            "Authorization%20and%20Notification%20List%20-%20"
                            "1-1-2026pdf"
                        ),
                    },
                    {
                        "label": "2026 Medicare Prior Authorization List",
                        "url": (
                            "https://assets.humana.com/is/content/humana/"
                            "2026%20Medicare%20Prior%20Authorization%20Listpdf"
                        ),
                    },
                ],
            },
        ],
    },
    "Anthem": {
        "aliases": ["anthem", "anthem bcbs", "elevance"],
        "sites": [
            {
                "plan": "Individual & Commercial",
                "page": (
                    "https://www.anthem.com/provider/individual-commercial/"
                    "prior-authorization"
                ),
                "direct_pdfs": [],
            },
        ],
        "note": (
            "Anthem publishes most prior-auth requirements through its "
            "interactive lookup tool (state-specific lists at "
            "providers.anthem.com)."
        ),
    },
    "Horizon": {
        "aliases": [
            "horizon", "horizon bcbs", "horizon bcbsnj",
            "horizon blue cross",
        ],
        "sites": [
            {
                "plan": "New Jersey (all)",
                "page": (
                    "https://www.horizonblue.com/providers/resources/"
                    "provider-self-service-tools/prior-authorization-search"
                ),
                "direct_pdfs": [],
            },
        ],
        "note": (
            "Horizon BCBSNJ publishes prior-auth requirements through a "
            "CPT/HCPCS code search tool."
        ),
    },
    "Medica": {
        "aliases": ["medica"],
        "sites": [
            {
                "plan": "Commercial & Medicare",
                "page": (
                    "https://partner.medica.com/providers/policies-and-"
                    "guidelines/um-policies-and-prior-authorization"
                ),
                "direct_pdfs": [
                    {
                        "label": "Prior Authorization List",
                        "url": (
                            "https://partner.medica.com/-/media/documents/"
                            "provider/prior-authorization-list.pdf?la=en"
                        ),
                    },
                    {
                        "label": "2026 Medicare Prior Authorization List",
                        "url": (
                            "https://partner.medica.com/-/media/documents/"
                            "provider/2026-medicare-prior-authorization-"
                            "list.pdf?la=en"
                        ),
                    },
                ],
            },
        ],
    },
    "AveraCare": {
        "aliases": [
            "avera", "avera care", "averacare", "avera health plans",
        ],
        "sites": [
            {
                "plan": "Avera Health Plans",
                "page": (
                    "https://www.averahealthplans.com/insurance/for-providers/"
                    "preauthorizations/"
                ),
                "direct_pdfs": [
                    {
                        "label": "Preauthorization List",
                        "url": (
                            "https://www.averahealthplans.com/app/files/"
                            "public/5eca6f2d-6a6c-4762-88ce-57cbf356401a/"
                            "preauthorization-list.pdf"
                        ),
                    },
                ],
            },
        ],
        "note": (
            "averahealthplans.com currently returns 'Access Denied' (edge/IP "
            "block) to automated clients; run from an allowed network to "
            "retrieve the preauthorization list."
        ),
    },
    "BCBS_AZ": {
        "aliases": [
            "bcbs az", "bcbsaz", "azblue", "az blue",
            "blue cross blue shield arizona",
            "blue cross blue shield of arizona",
        ],
        "sites": [
            {
                "plan": "Commercial & Medicare",
                "page": (
                    "https://www.azblue.com/provider/resources/"
                    "prior-authorization-and-medical-policies"
                ),
                "direct_pdfs": [
                    {
                        "label": "Precertification Requests Quick Guide",
                        "url": (
                            "https://provider.azblue.com/~/media/azblue/files/"
                            "healthcare/precertification-requests-quick-"
                            "guide.pdf"
                        ),
                    },
                ],
            },
        ],
        "note": (
            "AZ Blue's full prior-auth code lists are behind its lookup tool "
            "at https://priorauth.azblue.com/"
        ),
    },
    "EviCore": {
        "aliases": [
            "evicore", "evicore by evernorth", "evicore healthcare",
            "carecore", "medsolutions",
        ],
        "sites": [
            {
                "plan": "Clinical Guidelines (all plans)",
                "page": "https://www.evicore.com/provider/clinical-guidelines",
                "direct_pdfs": [
                    {
                        "label": "Required Medical Information Checklist",
                        "url": (
                            "https://www.evicore.com/sites/default/files/"
                            "2025-09/EviCore%20Medical%20Records%20Required%20"
                            "Document_updated%209-9-2025.pdf"
                        ),
                    },
                    {
                        "label": "Gastroenterology Tip Sheet",
                        "url": (
                            "https://www.evicore.com/sites/default/files/"
                            "2026-05/gastroenterology-tip-sheet.pdf"
                        ),
                    },
                ],
            },
        ],
        "note": (
            "EviCore's full specialty clinical guidelines are gated behind a "
            "health-plan selector at evicore.com/provider/clinical-guidelines "
            "(choose plan, then download)."
        ),
    },
    "Carelon": {
        "aliases": [
            "carelon", "carelon medical benefits management", "carelon mbm",
            "aim specialty health", "aim",
        ],
        "sites": [
            {
                "plan": "Clinical Guidelines (all)",
                "page": (
                    "https://guidelines."
                    "carelonmedicalbenefitsmanagement.com/"
                ),
                "direct_pdfs": [
                    {
                        "label": "Clinical Appropriateness Guideline - "
                                 "Imaging of the Brain (UC0126)",
                        "url": (
                            "https://guidelines."
                            "carelonmedicalbenefitsmanagement.com/wp-content/"
                            "uploads/2025/11/Imaging-of-the-Brain-2025-11-15-"
                            "UC0126.pdf"
                        ),
                    },
                ],
            },
            {
                "plan": "Radiology Guidelines",
                "page": (
                    "https://guidelines."
                    "carelonmedicalbenefitsmanagement.com/"
                    "current-radiology-guidelines/"
                ),
                "direct_pdfs": [],
            },
        ],
        "note": (
            "Carelon (formerly AIM Specialty Health) publishes guideline PDFs "
            "as a JavaScript-rendered list; prior-auth submission is via "
            "providerportal.com (login)."
        ),
    },
    "AvMed": {
        "aliases": ["avmed", "avmed health plans", "av-med"],
        "sites": [
            {
                "plan": "All plans",
                "page": (
                    "https://www.avmed.org/en/provider/provider-tools/"
                    "prior-authorization"
                ),
                "direct_pdfs": [
                    {
                        "label": "Prior Authorization Requirements",
                        "url": (
                            "https://shc-p-001.sitecorecontenthub.cloud/api/"
                            "public/content/prior-authorization-"
                            "requirements.pdf?v=3ae9e903"
                        ),
                    },
                    {
                        "label": "No Authorization Required List of "
                                 "Procedure Codes",
                        "url": (
                            "https://shc-p-001.sitecorecontenthub.cloud/api/"
                            "public/content/"
                            "1b58fcdc148c41fe931b8008096fc5a9?v=4b97d353"
                        ),
                    },
                    {
                        "label": "Medical Prior Authorization Request "
                                 "Form 2026",
                        "url": (
                            "https://shc-p-001.sitecorecontenthub.cloud/api/"
                            "public/content/Medical-Prior-Authorization-"
                            "Request-Form-2026.pdf?v=aee4d138"
                        ),
                    },
                ],
            },
        ],
        "note": (
            "AvMed's prior-auth PDFs are hosted on its Sitecore Content Hub "
            "CDN; the older avmed.org/media/... paths now 404."
        ),
    },
    "BannerHealth": {
        "aliases": [
            "banner", "banner health", "banner health plans",
            "banner health network", "banner aetna",
            "banner university health plans", "banner medicare",
        ],
        "sites": [
            {
                "plan": "Commercial (Banner Health Plans)",
                "page": (
                    "https://www.bannerhealth.com/bhpprovider/"
                    "prior-authorizations/prior-auth-grids"
                ),
                "direct_pdfs": [],
            },
            {
                "plan": "Medicare Advantage",
                "page": (
                    "https://www.bannerhealth.com/medicare/providers/pa-grids"
                ),
                "direct_pdfs": [
                    {
                        "label": "Banner Medicare Advantage Medical PA Grid "
                                 "(eff 01-23-2025)",
                        "url": (
                            "https://www.bannerhealth.com/medicare/-/media/"
                            "files/project/medicare/for-providers/"
                            "prior-authorization-grids/medical/"
                            "prov-bma_medical-pa-grid_eff01232025.pdf"
                        ),
                    },
                    {
                        "label": "Banner Medicare Advantage Pharmacy PA Grid "
                                 "(eff 06-15-2026)",
                        "url": (
                            "https://www.bannerhealth.com/medicare/-/media/"
                            "files/project/medicare/for-providers/"
                            "prior-authorization-grids/pharmacy/"
                            "prov_bma_pharm-pa-grid_eff06152026_v2_en.pdf"
                        ),
                    },
                ],
            },
        ],
        "note": (
            "Banner|Aetna precertification is administered via Aetna's "
            "national precert list."
        ),
    },
    "EverNorth": {
        "aliases": [
            "evernorth", "evernorth health services",
            "evernorth behavioral health", "express scripts",
        ],
        "sites": [
            {
                "plan": "Prior Authorization Resources",
                "page": (
                    "https://www.evernorth.com/prior-authorization-resources"
                ),
                "direct_pdfs": [
                    {
                        "label": "Evernorth Behavioral Health - "
                                 "Authorization and Billing Resource Guide",
                        "url": (
                            "https://static.evernorth.com/assets/evernorth/"
                            "provider/pdf/resourceLibrary/behavioral/"
                            "authorization-and-billing-resource.pdf"
                        ),
                    },
                    {
                        "label": "Evernorth Behavioral Health - "
                                 "Inpatient Prior Authorization Form",
                        "url": (
                            "https://static.evernorth.com/assets/evernorth/"
                            "provider/pdf/resourceLibrary/behavioral/"
                            "inpatient-prior-authorization-form.pdf"
                        ),
                    },
                ],
            },
        ],
        "note": (
            "Evernorth's full service-level PA list sits behind the "
            "authenticated provider.evernorth.com portal; the public docs are "
            "behavioral-health PA resources."
        ),
    },
    "DeanHealth": {
        "aliases": [
            "dean", "dean health", "dean health plan", "deancare", "dhp",
            "prevea360",
        ],
        "sites": [
            {
                "plan": "Commercial & Medicare",
                "page": (
                    "https://www.deancare.com/providers/medical-management"
                ),
                "direct_pdfs": [
                    {
                        "label": "Dean Health Plan Master Service List "
                                 "(commercial PA list)",
                        "url": (
                            "https://www.deancare.com/getmedia/"
                            "d4696fb0-6037-40d0-ad41-0028bba682ac/"
                            "Dean-Health-Plan-Master-Service-List.pdf"
                        ),
                    },
                    {
                        "label": "Dean 2026 Medicare Advantage Prior "
                                 "Authorization and Notification Service List",
                        "url": (
                            "https://www.deancare.com/getmedia/"
                            "c9f53b3a-488a-4001-aedc-1aaeb5fa81e6/"
                            "Dean-2026-medicare-advantage-prior-authorization-"
                            "service-list.pdf"
                        ),
                    },
                ],
            },
        ],
        "note": (
            "deancare.com HTML pages are bot-protected (403 to scripts); the "
            "PDFs under /getmedia/ are fetched directly. Prevea360 is the "
            "sister brand."
        ),
    },
    "USFamilyHealth": {
        "aliases": [
            "us family health", "us family health plan", "usfhp",
            "martins point usfhp", "johns hopkins usfhp",
        ],
        "sites": [
            {
                "plan": "Martin's Point USFHP",
                "page": (
                    "https://martinspoint.org/for-providers/provider-manual/"
                    "utilization-management"
                ),
                "direct_pdfs": [],
            },
            {
                "plan": "Johns Hopkins USFHP",
                "page": "https://www.hopkinsusfhp.org/for-providers/",
                "direct_pdfs": [
                    {
                        "label": "Johns Hopkins USFHP Outpatient Prior "
                                 "Authorization Guidelines",
                        "url": (
                            "https://www.hopkinsusfhp.org/wp-content/uploads/"
                            "2020/08/outpatient-guidelines.pdf"
                        ),
                    },
                ],
            },
        ],
        "note": (
            "US Family Health Plan is a TRICARE Prime plan run by regional "
            "sponsors; Martin's Point posts auth requirements via its ProAuth "
            "portal rather than a single list PDF."
        ),
    },
    "Highmark": {
        "aliases": [
            "highmark", "highmark bcbs", "highmark blue cross blue shield",
            "highmark inc",
        ],
        "sites": [
            {
                "plan": "Commercial (multi-region)",
                "page": (
                    "https://providers.highmark.com/authorization/"
                    "obtaining-authorizations.html"
                ),
                "direct_pdfs": [
                    {
                        "label": "List of Procedures/DME Requiring "
                                 "Authorization (Commercial)",
                        "url": (
                            "https://providers.highmark.com/content/dam/"
                            "highmark/en/providerresourcecenter/pdfs/"
                            "multi-region/documents/pdfs/authorization/"
                            "obtaining-authorizations/Proc-Requiring-Auth-"
                            "list.pdf"
                        ),
                    },
                    {
                        "label": "FEP List of Procedures/DME Requiring "
                                 "Authorization",
                        "url": (
                            "https://providers.highmark.com/content/dam/"
                            "highmark/en/providerresourcecenter/pdfs/all/"
                            "documents/pdfs/authorization/"
                            "obtaining-authorizations/"
                            "fep-authorization-list.pdf"
                        ),
                    },
                ],
            },
            {
                "plan": "Wholecare (Medicaid/Medicare)",
                "page": (
                    "https://providers.highmark.com/wholecare/"
                    "provider-resources/prior-authorization-code-lookup.html"
                ),
                "direct_pdfs": [
                    {
                        "label": "Highmark Wholecare PA Medicaid List (PA)",
                        "url": (
                            "https://providers.highmark.com/content/dam/"
                            "highmark/en/providerresourcecenter/wholecare/"
                            "documents/pdfs/provider-resources/"
                            "prior-authorization-list/"
                            "pa-medicaid-prior-authorization-list-wholecare-"
                            "060126.pdf"
                        ),
                    },
                    {
                        "label": "Highmark Health Options DE Prior "
                                 "Authorization Code List (Jun 2026)",
                        "url": (
                            "https://providers.highmark.com/content/dam/"
                            "highmark/en/providerresourcecenter/"
                            "highmark-health-options/hho-de/documents/pdfs/"
                            "prior-authorization-code-lookup/"
                            "hho-de-pal-notification-06012026.pdf"
                        ),
                    },
                ],
            },
        ],
    },
    "OneCare": {
        "aliases": [
            "onecare", "caloptima onecare", "caloptima",
            "caloptima health onecare",
        ],
        "sites": [
            {
                "plan": "CalOptima OneCare (Medicare D-SNP)",
                "page": (
                    "https://www.caloptima.org/en/for-providers/"
                    "claims-and-eligibility/prior-authorizations"
                ),
                "direct_pdfs": [
                    {
                        "label": "OneCare Prior Authorization Required List",
                        "url": (
                            "https://cop-p-001.sitecorecontenthub.cloud/api/"
                            "public/content/"
                            "c0dd8bbcaac14feaa087415dac3f3fd9?v=58934819"
                        ),
                    },
                    {
                        "label": "CalOptima Medi-Cal Prior Authorization "
                                 "Required List",
                        "url": (
                            "https://cop-p-001.sitecorecontenthub.cloud/api/"
                            "public/content/"
                            "c7d04763723f4c5191e44b8ce3b6c507?v=38cc6a37"
                        ),
                    },
                    {
                        "label": "OneCare Authorization Request Form",
                        "url": (
                            "https://cop-p-001.sitecorecontenthub.cloud/api/"
                            "public/content/"
                            "90cdd874e32741bbb5d216c513965979?v=79db4119"
                        ),
                    },
                ],
            },
        ],
        "note": (
            "OneCare here is CalOptima OneCare (Medicare D-SNP, Orange County "
            "CA); PDFs are on CalOptima's Sitecore Content Hub CDN."
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


def curl_get(url: str, timeout: int = 120) -> bytes | None:
    """Fetch a URL with the system curl (follows redirects). None on failure."""
    if not CURL:
        return None
    try:
        proc = subprocess.run(
            [CURL, "-sSL", "-A", HEADERS["User-Agent"], "-H", "Accept: */*",
             "--max-time", str(timeout), "-o", "-", url],
            capture_output=True, timeout=timeout + 20,
        )
    except Exception:  # noqa: BLE001 - curl missing/timed out; caller handles
        return None
    if proc.returncode == 0 and proc.stdout:
        return proc.stdout
    return None


def fetch(session, url, timeout=120):
    """Return (content_bytes, content_type) for a URL.

    Tries requests first; on any failure or non-2xx response, falls back to
    curl (which gets past TLS-fingerprint bot protection some payer CDNs use).
    Returns (None, "") if both fail.
    """
    try:
        resp = session.get(url, timeout=timeout)
        if resp.ok and resp.content:
            return resp.content, resp.headers.get("Content-Type", "").lower()
    except Exception:  # noqa: BLE001 - fall through to curl
        pass
    data = curl_get(url, timeout)
    return (data, "") if data else (None, "")


def normalize(name: str) -> str:
    """Lowercase and strip everything but letters/digits, for matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_payer(name: str):
    """Map a user-supplied payer name to (canonical, config), or None."""
    wanted = normalize(name)
    if not wanted:
        return None
    for canonical, cfg in PAYERS.items():
        for candidate in [canonical, *cfg["aliases"]]:
            if normalize(candidate) == wanted:
                return canonical, cfg
    return None


def unescape_embedded_markup(raw: str) -> str:
    """Unescape JSON/JS-escaped HTML embedded in a page.

    Payer pages often embed the real document list as data (e.g. JSON
    "content fragments") where '<' appears as \\u003c, '>' as \\u003e,
    '&nbsp;' as \\u0026nbsp;, and quotes are backslash-escaped. Decode the
    common escapes so the same link scanner can see the <a href> markup.
    """
    text = raw
    # \uXXXX -> character
    text = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        text,
    )
    # \/ -> /  and  \" -> "  and  \' -> '
    text = text.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")
    # &nbsp; &amp; etc.
    text = html.unescape(text)
    return text


def scrape_pdf_links(session, page_url, keywords):
    """Return {pdf_url: link_text} for matching links found on a page.

    Scans both the plain HTML and an unescaped copy of any embedded
    JSON/JS markup, so JavaScript-rendered document lists are covered.
    """
    content, _ctype = fetch(session, page_url, timeout=60)
    if content is None:
        print("    Could not fetch page (blocked or unreachable)")
        return {}
    page_text = content.decode("utf-8", errors="replace")

    found = {}
    for source in (page_text, unescape_embedded_markup(page_text)):
        parser = LinkExtractor()
        try:
            parser.feed(source)
        except Exception:  # noqa: BLE001 - malformed markup, keep going
            continue
        for href, text in parser.links:
            if ".pdf" not in href.lower():
                continue
            haystack = f"{href} {text}".lower()
            if not any(k in haystack for k in keywords):
                continue
            abs_url = urljoin(page_url, href.strip())
            # Prefer a non-empty link text if we see the same URL twice.
            if abs_url not in found or (text and not found[abs_url]):
                found[abs_url] = text
    return found


EFFECTIVE_DATE_RE = re.compile(
    r"(\d{1,2}[-_]\d{1,2}[-_]\d{2,4}|\d{4}[-_]\d{1,2}[-_]\d{1,2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-_ ]?\d{4})",
    re.IGNORECASE,
)


def url_stem_hint(url: str) -> str:
    """A readable market/document hint from a URL path stem.

    e.g. ".../UHC-River-Valley-Prior-Authorization-Effective-4-1-2025.pdf"
    -> "UHC River Valley Prior Authorization". Used to disambiguate links
    whose visible text is generic (just a date), where the market lives in
    the URL rather than the label.
    """
    stem = unquote(Path(urlparse(url).path).stem)
    # Drop trailing effective-date / version tails, keep the descriptive part.
    stem = re.sub(
        r"[-_]?(eff(?:ective)?[-_ ]?\d.*|\d{1,2}[-_]\d{1,2}[-_]\d{2,4}.*|"
        r"\d{4}[-_]\d{1,2}[-_]\d{1,2}.*)$",
        "", stem, flags=re.IGNORECASE,
    )
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem


def _is_generic_label(base: str) -> bool:
    """True if a label carries no distinguishing words (just a date/effective)."""
    if re.search(r"\beffective\b|\bupdated\b", base, re.IGNORECASE):
        return True
    # Only digits, punctuation, and short month tokens -> generic.
    return re.fullmatch(
        r"[\s\W\d]*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
        r"[a-z]*[\s\W\d]*)*",
        base, flags=re.IGNORECASE,
    ) is not None


def safe_filename(label: str, url: str, category: str = "") -> str:
    """Build a readable, filesystem-safe .pdf name from the link label.

    Falls back to the URL basename when there is no usable label. A
    category (plan/section) prefix is added when supplied so a "Medical"
    and a "Medication" list with the same label don't collide. When the
    label is generic (e.g. just an effective date) a market hint derived
    from the URL is added so per-market documents stay distinct and named.
    """
    base = (label or "").strip()
    # Link labels often end in a redundant "(PDF)" / "PDF" marker.
    base = re.sub(r"[\s\-]*\(?\bpdf\b\)?\s*$", "", base, flags=re.IGNORECASE).strip()
    if not base:
        base = unquote(Path(urlparse(url).path).name)
        base = re.sub(r"\.pdf$", "", base, flags=re.IGNORECASE)

    # A generic label (just a date) gains a market hint from the URL.
    if base and _is_generic_label(base):
        hint = url_stem_hint(url)
        if hint and normalize(hint) not in normalize(base):
            base = f"{hint} - {base}"

    if category:
        cat = category.strip()
        if normalize(cat) and normalize(cat) not in normalize(base):
            base = f"{cat} - {base}"

    # Collapse whitespace and strip characters invalid in file names.
    base = re.sub(r"\s+", " ", base).strip()
    base = re.sub(r'[<>:"/\\|?*]', "_", base)
    base = base.strip(" ._")
    if not base:
        base = "document"
    # Keep names to a sane length.
    if len(base) > 150:
        base = base[:150].rstrip(" ._")
    return f"{base}.pdf"


def download_pdf(session, url, dest_dir, seen_hashes, label="",
                 category="") -> bool:
    """Download one PDF; validate, de-duplicate by content, then save."""
    print(f"  Downloading: {url}")
    content, content_type = fetch(session, url, timeout=120)
    if content is None:
        print("    Failed: request blocked or unreachable")
        return False

    # If requests came back with a non-PDF body (e.g. a 200 bot-challenge
    # HTML page), try curl once more before giving up.
    if not content.startswith(b"%PDF") and "application/pdf" not in content_type:
        alt = curl_get(url, timeout=120)
        if alt and alt.startswith(b"%PDF"):
            content = alt

    if not content.startswith(b"%PDF"):
        print("    Skipped (response is not a PDF)")
        return False

    digest = hashlib.sha256(content).hexdigest()
    if digest in seen_hashes:
        print("    Skipped (duplicate content already saved)")
        return False

    dest = dest_dir / safe_filename(label, url, category)
    # Avoid clobbering a different document that produced the same name.
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
        stem, suffix = dest.stem, dest.suffix
        n = 2
        while dest.exists():
            dest = dest_dir / f"{stem} ({n}){suffix}"
            n += 1

    dest.write_bytes(content)
    seen_hashes.add(digest)
    print(f"    Saved: {dest.name} ({len(content):,} bytes)")
    return True


def download_year_versions(session, url, dest_dir, seen_hashes, year,
                           label="", category="") -> int:
    """Download every distinct snapshot of `url` published in `year`.

    Uses the Internet Archive (Wayback Machine) CDX API, collapsing by
    digest, and fetches each snapshot in raw (id_) form.
    """
    params = {
        "url": url,
        "from": f"{year}0101",
        "to": f"{year}1231",
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
        print(f"    Wayback lookup failed for {url}: {exc}")
        return 0

    snapshots = rows[1:] if rows else []
    if not snapshots:
        print(f"    No {year} archived versions found for {url}")
        return 0

    saved = 0
    for timestamp, original, _digest in snapshots:
        snapshot_url = f"https://web.archive.org/web/{timestamp}id_/{original}"
        date = timestamp[:8]
        version_label = f"{label or Path(urlparse(url).path).stem} " \
                        f"(version {date})"
        if download_pdf(session, snapshot_url, dest_dir, seen_hashes,
                        label=version_label, category=category):
            saved += 1
        time.sleep(1)  # be polite to the archive
    return saved


def process_payer(session, canonical, cfg, year=None) -> int:
    """Download all prior-auth documents for one payer. Returns file count."""
    print(f"\n{'=' * 70}\nPayer: {canonical}\n{'=' * 70}")
    keywords = cfg.get("keywords", DEFAULT_KEYWORDS)
    dest_dir = DOWNLOAD_DIR / canonical
    seen_hashes: set[str] = set()
    saved = 0

    for site in cfg["sites"]:
        plan = site.get("plan", "")
        page = site.get("page", "")
        print(f"\n  Plan: {plan or '(default)'}")
        if page:
            print(f"  Scanning page: {page}")

        # 1. Scrape the live page.
        scraped = scrape_pdf_links(session, page, keywords) if page else {}

        # 2. Fall back to known direct PDFs only if scraping found nothing.
        documents = dict(scraped)  # {url: label}
        if not documents:
            for doc in site.get("direct_pdfs", []):
                documents.setdefault(doc["url"], doc.get("label", ""))
            if documents:
                print(f"  Scraping found nothing; using "
                      f"{len(documents)} known fallback URL(s).")
        else:
            print(f"  Found {len(documents)} document link(s) on the page.")
            # Merge in any known direct PDFs that scraping missed.
            for doc in site.get("direct_pdfs", []):
                documents.setdefault(doc["url"], doc.get("label", ""))

        if not documents:
            print("  No downloadable prior-auth PDFs for this plan.")
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)
        for url, label in documents.items():
            if download_pdf(session, url, dest_dir, seen_hashes,
                            label=label, category=plan):
                saved += 1
            if year:
                saved += download_year_versions(
                    session, url, dest_dir, seen_hashes, year,
                    label=label, category=plan,
                )

    if cfg.get("note"):
        print(f"\n  Note: {cfg['note']}")
    print(f"\n  {saved} file(s) saved for {canonical}"
          + (f" -> {dest_dir}" if saved else ""))
    return saved


def write_websites_csv(path: Path = WEBSITES_CSV) -> int:
    """Write PayerName, PayerPlan, Website (one row per distinct website).

    When several plans of a payer share one website, they are combined into
    a single row so there is exactly one row per website.
    """
    rows = []
    for canonical, cfg in PAYERS.items():
        # Preserve first-seen order of websites; merge plan labels per site.
        by_site: dict[str, list[str]] = {}
        for site in cfg["sites"]:
            page = site.get("page", "")
            if not page:
                continue
            plan = site.get("plan", "")
            plans = by_site.setdefault(page, [])
            if plan and plan not in plans:
                plans.append(plan)
        for page, plans in by_site.items():
            rows.append((canonical, " / ".join(plans), page))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["PayerName", "PayerPlan", "Website"])
        writer.writerows(rows)
    print(f"Wrote {len(rows)} row(s) to {path}")
    return len(rows)


def read_payer_names(args) -> list[str]:
    names = list(args.payers)
    if args.file:
        content = Path(args.file).read_text()
        names.extend(line.strip() for line in content.splitlines())
    if args.all:
        names.extend(PAYERS.keys())
    return [n for n in names if n.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Download prior authorization / precertification documents for "
            "one or more payers and record the source websites."
        )
    )
    ap.add_argument("payers", nargs="*",
                    help="payer names, e.g. Aetna UHC Cigna")
    ap.add_argument("-f", "--file",
                    help="text file with one payer name per line")
    ap.add_argument("--all", action="store_true",
                    help="process every payer in the registry")
    ap.add_argument("--year", type=int,
                    help="also download every distinct version published in "
                         "this year via the Internet Archive")
    ap.add_argument("--csv-only", action="store_true",
                    help="only (re)write listofpayer_withWebsites.csv")
    args = ap.parse_args()

    # Always keep the websites CSV in sync with the registry.
    write_websites_csv()
    if args.csv_only:
        return

    names = read_payer_names(args)
    if not names:
        ap.print_usage()
        print(f"\nSupported payers: {', '.join(sorted(PAYERS))}")
        print("(Use --csv-only to just write listofpayer_withWebsites.csv, "
              "or --all to download everything.)")
        sys.exit(1)

    session = requests.Session()
    session.headers.update(HEADERS)
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    total = 0
    unresolved = []
    processed = set()
    for name in names:
        resolved = resolve_payer(name)
        if resolved is None:
            unresolved.append(name)
            print(f"\nUnknown payer '{name}' - skipping.")
            continue
        canonical, cfg = resolved
        if canonical in processed:
            continue
        processed.add(canonical)
        total += process_payer(session, canonical, cfg, year=args.year)

    print(f"\n{'=' * 70}")
    print(f"Finished. {total} file(s) downloaded to {DOWNLOAD_DIR}")
    if unresolved:
        print(f"Unrecognized payer name(s): {', '.join(sorted(set(unresolved)))}")
        print(f"Supported payers: {', '.join(sorted(PAYERS))}")


if __name__ == "__main__":
    main()
