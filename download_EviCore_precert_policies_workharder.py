#!/usr/bin/env python3
"""
EviCore by Evernorth - clinical guideline harvest (work-harder edition).

EviCore's public clinical guidelines are Drupal-hosted files under
evicore.com/sites/default/files/<yyyy-mm>/<name>.pdf.  The guideline browser
itself is a JavaScript app behind a health-plan selector, so a plain scrape of
/provider/clinical-guidelines returns almost nothing.

This script therefore:
  * crawls every provider / resources / clinical-guidelines page it can reach,
  * pulls file URLs out of the raw payloads (the app's JSON lists the files),
  * queries the Drupal JSON:API (/jsonapi/node/... and /jsonapi/media/file)
    when it is reachable,
  * sweeps the Internet Archive for the whole /sites/default/files/ tree,
    which is where the retired guideline editions still live.

File types
----------
Downloads PDF **and** Excel **and** Word documents:

    .pdf                      Adobe PDF
    .xlsx  .xlsm  .xls        Excel workbooks (OOXML and legacy)
    .docx  .doc   .rtf        Word documents (OOXML, legacy and RTF)

Every candidate is validated by magic bytes after download, so an error page
served with a document name is rejected rather than saved.  Restrict the run
with --pdf-only, --excel-only or --word-only.

Nothing here filters by keyword: keep_all_docs is on for this payer, so every
document the crawl, the JSON:API and the archive turn up is kept whatever its
name or format.

Where the files land
--------------------
PDFs go to the usual tree; everything else goes to a parallel tree of the same
shape, so the PDF library stays a PDF library:

    downloaded/EviCore/...              .pdf
    downloaded_NonPDF/EviCore/...       .xlsx .xlsm .xls .docx .doc .rtf

Routing is decided by the downloaded bytes, not by the URL, so a workbook
served from a .pdf-looking link still lands in downloaded_NonPDF.  The non-PDF
folder is created only when there is something to put in it.  Word and Excel
files collected into downloaded/EviCore before the split stay where they are
and are not fetched again.

    python3 download_EviCore_precert_policies_workharder.py
    python3 download_EviCore_precert_policies_workharder.py --since 2020 -v
    python3 download_EviCore_precert_policies_workharder.py --excel-only
"""

from payer_harvest import PayerSite, run_split

SITE = PayerSite(
    payer="EviCore",
    seeds=[
        "https://www.evicore.com/provider/clinical-guidelines",
        "https://www.evicore.com/provider",
        "https://www.evicore.com/provider/clinical-guidelines-details",
        "https://www.evicore.com/resources",
        "https://www.evicore.com/provider/online-resources",
        "https://www.evicore.com/healthplan",
        "https://www.evicore.com/provider/general-resources",
    ],
    allow_hosts=["evicore.com"],
    page_patterns=[r"evicore\.com/(provider|resources|healthplan|sites|jsonapi)"],
    deny_patterns=[r"/(careers|about|contact|news|login)"],
    keywords=["clinical guideline", "criteria", "tip sheet", "code list",
              "solution", "imaging", "cardiology", "oncology", "msk",
              "musculoskeletal", "sleep", "radiation", "post acute",
              "specialty drug", "lab management", "gastroenterology",
              "required medical information", "checklist"],
    always_keep=[r"evicore\.com/sites/default/files/"],
    json_endpoints=[
        "https://www.evicore.com/jsonapi/media/document?page[limit]=200",
        "https://www.evicore.com/jsonapi/node/clinical_guideline?page[limit]=200",
        "https://www.evicore.com/api/clinicalguidelines",
    ],
    fallback_docs=[
        ("https://www.evicore.com/sites/default/files/2025-09/EviCore%20Medical%20"
         "Records%20Required%20Document_updated%209-9-2025.pdf",
         "Required Medical Information Checklist"),
        ("https://www.evicore.com/sites/default/files/2026-05/"
         "gastroenterology-tip-sheet.pdf", "Gastroenterology Tip Sheet"),
    ],
    wayback_prefixes=[
        "www.evicore.com/sites/default/files/*",
        "www.evicore.com/provider/*",
        "evicore.com/sites/default/files/*",
    ],
    wayback_since=2020,
    wayback_keep_all=True,
    keep_all_docs=True,
    max_pages=500,
    depth=3,
    notes="Guideline browser is JS-gated behind a health-plan selector; the "
          "Drupal file tree and the Internet Archive are the productive routes."
          "  PDFs go to downloaded/, Excel and Word to downloaded_NonPDF/.",
)

if __name__ == "__main__":
    raise SystemExit(run_split(SITE))
