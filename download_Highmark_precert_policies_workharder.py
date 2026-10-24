#!/usr/bin/env python3
"""
Highmark - authorization requirement harvest (work-harder edition).

Highmark's provider resource centre publishes a separate authorization list
per region (PA/WV/DE/NY multi-region, FEP) and per Medicaid/Medicare brand
(Highmark Wholecare, Highmark Health Options DE), all as AEM assets under
providers.highmark.com/content/dam/highmark/en/providerresourcecenter/... .

This script crawls the authorization and provider-resource sections of every
brand, extracts the DAM asset URLs from the raw payloads, and sweeps the
Internet Archive for the dated editions (the Medicaid lists are republished
monthly with the effective date in the file name).

File types
----------
Downloads PDF **and** Excel **and** Word documents:

    .pdf                      Adobe PDF
    .xlsx  .xlsm  .xls        Excel workbooks (OOXML and legacy)
    .docx  .doc   .rtf        Word documents (OOXML, legacy and RTF)

Every candidate is validated by magic bytes after download, so a login page or
an error page served with a .xlsx name is rejected rather than saved.  Restrict
the run with --pdf-only, --excel-only or --word-only when you want one format.

Where the files land
--------------------
PDFs go to the usual tree; everything else goes to a parallel tree of the same
shape, so the PDF library stays a PDF library:

    downloaded/Highmark/...             .pdf
    downloaded_NonPDF/Highmark/...      .xlsx .xlsm .xls .docx .doc .rtf

Routing is decided by the downloaded bytes, not by the URL, so a workbook
served from a .pdf-looking link still lands in downloaded_NonPDF.  The non-PDF
folder is created only when there is something to put in it.

    python3 download_Highmark_precert_policies_workharder.py
    python3 download_Highmark_precert_policies_workharder.py --all-versions
    python3 download_Highmark_precert_policies_workharder.py --excel-only -v
"""

from payer_harvest import PayerSite, run_split

# Any Highmark-hosted workbook or Word document is kept, whatever the file name
# says - the DAM serves them under names like "auth-code-list.xlsx" and
# reimbursement grids that carry no prior-auth keyword of their own.
#
# Deliberately NOT extended to .pdf: Highmark's PDF selection already works off
# the keyword list, and a pdf catch-all here would quietly pull in the whole
# provider-resource library.  Add "pdf|" below for full Horizon-style parity.
HIGHMARK_NONPDF_ASSET = (
    r"highmark(prc)?\.com/.*\."
    r"(xlsx|xlsm|xls|docx|doc|rtf)(\?|#|$)"
)

SITE = PayerSite(
    payer="Highmark",
    seeds=[
        "https://providers.highmark.com/authorization/obtaining-authorizations.html",
        "https://providers.highmark.com/authorization.html",
        "https://providers.highmark.com/resources/provider-resource-center.html",
        "https://providers.highmark.com/wholecare/provider-resources/"
        "prior-authorization-code-lookup.html",
        "https://providers.highmark.com/wholecare/provider-resources.html",
        "https://providers.highmark.com/highmark-health-options/"
        "provider-resources.html",
        "https://providers.highmark.com/policies-guidelines/"
        "medical-policy-and-provider-reimbursement.html",
        "https://providers.highmark.com/pharmacy.html",
        "https://providers.highmark.com/claims-payment-policies.html",
    ],
    allow_hosts=["highmark.com"],
    page_patterns=[r"providers\.highmark\.com/(authorization|resources|"
                   r"wholecare|highmark-health-options|policies-guidelines|"
                   r"pharmacy|claims|content/dam)"],
    deny_patterns=[r"/(login|careers|news|contact)"],
    keywords=["requiring authorization", "authorization list",
              "prior authorization list", "code lookup", "medical policy",
              "reimbursement policy", "pharmacy policy", "wholecare",
              "health options", "fep", "notification",
              # Spreadsheet / template wording used on Highmark's resource and
              # reimbursement pages, where the workbooks live.
              "workbook", "worksheet", "spreadsheet", "template", "matrix",
              "code changes", "fee schedule", "roster", "grid"],
    always_keep=[
        HIGHMARK_NONPDF_ASSET,
        r"providers\.highmark\.com/content/dam/.*(auth|prior|pal)",
    ],
    fallback_docs=[
        ("https://providers.highmark.com/content/dam/highmark/en/"
         "providerresourcecenter/pdfs/multi-region/documents/pdfs/authorization/"
         "obtaining-authorizations/Proc-Requiring-Auth-list.pdf",
         "List of Procedures DME Requiring Authorization (Commercial)"),
        ("https://providers.highmark.com/content/dam/highmark/en/"
         "providerresourcecenter/pdfs/all/documents/pdfs/authorization/"
         "obtaining-authorizations/fep-authorization-list.pdf",
         "FEP List of Procedures DME Requiring Authorization"),
    ],
    wayback_prefixes=[
        "providers.highmark.com/content/dam/*",
        "providers.highmark.com/*",
        "hbcbs.highmarkprc.com/*",
        # Highmark's older PRC hosts, which held the .xls/.doc downloads.
        "*.highmarkprc.com/*",
    ],
    wayback_since=2022,
    max_pages=700,
    depth=3,
    notes="One authorization list per region and per Medicaid/Medicare brand; "
          "Medicaid lists are reissued monthly with the effective date in the "
          "file name.  PDFs go to downloaded/, Excel and Word to "
          "downloaded_NonPDF/.",
)

if __name__ == "__main__":
    raise SystemExit(run_split(SITE))
