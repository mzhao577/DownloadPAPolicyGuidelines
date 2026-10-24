#!/usr/bin/env python3
"""
Avera Health Plans (AveraCare) - preauthorization harvest (work-harder edition).

averahealthplans.com answers automated clients with "Access Denied" from its
edge, so the live crawl usually returns nothing.  This script therefore leans
on two extra routes:

  * the Internet Archive index for averahealthplans.com (including the
    /app/files/public/... asset tree where the preauthorization list and the
    medical policies live),
  * a curl-based retry with browser headers, which sometimes gets through when
    python-requests does not.

File types
----------
Downloads PDF **and** Excel **and** Word documents:

    .pdf                      Adobe PDF
    .xlsx  .xlsm  .xls        Excel workbooks (OOXML and legacy)
    .docx  .doc   .rtf        Word documents (OOXML, legacy and RTF)

Every candidate is validated by magic bytes after download, so an "Access
Denied" page served with a document name is rejected rather than saved.
Restrict the run with --pdf-only, --excel-only or --word-only.

Nothing here filters by keyword: keep_all_docs is on for this payer, so every
document the crawl and the archive turn up is kept whatever its name or format.

Where the files land
--------------------
PDFs go to the usual tree; everything else goes to a parallel tree of the same
shape, so the PDF library stays a PDF library:

    downloaded/AveraCare/...            .pdf
    downloaded_NonPDF/AveraCare/...     .xlsx .xlsm .xls .docx .doc .rtf

Routing is decided by the downloaded bytes, not by the URL, so a workbook
served from a .pdf-looking link still lands in downloaded_NonPDF.  The non-PDF
folder is created only when there is something to put in it.  Word and Excel
files collected into downloaded/AveraCare before the split stay where they are
and are not fetched again.

    python3 download_AveraCare_precert_policies_workharder.py
    python3 download_AveraCare_precert_policies_workharder.py --wayback-only
    python3 download_AveraCare_precert_policies_workharder.py --excel-only -v
"""

from payer_harvest import PayerSite, run_split

SITE = PayerSite(
    payer="AveraCare",
    seeds=[
        "https://www.averahealthplans.com/insurance/for-providers/"
        "preauthorizations/",
        "https://www.averahealthplans.com/insurance/for-providers/",
        "https://www.averahealthplans.com/insurance/for-providers/"
        "medical-policies/",
        "https://www.averahealthplans.com/insurance/for-providers/"
        "provider-resources/",
        "https://www.averahealthplans.com/insurance/for-providers/pharmacy/",
    ],
    allow_hosts=["averahealthplans.com", "avera.org"],
    page_patterns=[r"averahealthplans\.com/(insurance|app/files)"],
    deny_patterns=[r"/(careers|news|espanol)"],
    keywords=["preauthorization", "medical policy", "provider manual",
              "pharmacy policy", "avera"],
    always_keep=[r"averahealthplans\.com/app/files/public/"],
    fallback_docs=[
        ("https://www.averahealthplans.com/app/files/public/"
         "5eca6f2d-6a6c-4762-88ce-57cbf356401a/preauthorization-list.pdf",
         "Avera Health Plans Preauthorization List"),
    ],
    wayback_prefixes=[
        "averahealthplans.com/*",
        "www.averahealthplans.com/app/files/*",
    ],
    wayback_since=2019,
    wayback_keep_all=True,
    keep_all_docs=True,
    max_pages=250,
    depth=3,
    notes="Live site edge-blocks scripted clients; the Internet Archive is the "
          "primary source here (keyword filter relaxed for this payer).  PDFs "
          "go to downloaded/, Excel and Word to downloaded_NonPDF/.",
)

if __name__ == "__main__":
    raise SystemExit(run_split(SITE))
