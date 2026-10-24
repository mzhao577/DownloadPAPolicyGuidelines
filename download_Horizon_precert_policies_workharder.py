#!/usr/bin/env python3
"""
Horizon BCBS New Jersey - prior-authorization harvest (work-harder edition).

File types
----------
Downloads PDF **and** Excel **and** Word documents:

    .pdf                      Adobe PDF
    .xlsx  .xlsm  .xls        Excel workbooks (OOXML and legacy)
    .docx  .doc   .rtf        Word documents (OOXML, legacy and RTF)

Every candidate is validated by magic bytes after download - an OOXML workbook
must be a real zip container with an end-of-central-directory record, a legacy
workbook a real OLE compound file, a PDF must carry %%EOF - so a login page or
an error page served with a .xlsx name is rejected rather than saved.  Restrict
the run with --pdf-only, --excel-only or --word-only when you want one format.

Where the files land
--------------------
PDFs go to the usual tree; everything else goes to a parallel tree of the same
shape, so the PDF library stays a PDF library:

    downloaded/Horizon/...              .pdf
    downloaded_NonPDF/Horizon/...       .xlsx .xlsm .xls .docx .doc .rtf

Routing is decided by the downloaded bytes, not by the URL, so a workbook
served from a .pdf-looking link still lands in downloaded_NonPDF.  The non-PDF
folder is created only when there is something to put in it.  The split itself
lives in payer_harvest.run_split(), so other payers can opt into it too.

Where the documents are
-----------------------
Horizon exposes PA requirements mainly through a CPT/HCPCS search tool, but a
large set of supporting documents (procedures requiring authorization, medical
policy lists, utilization-management program material, Braven Health Medicare
lists, and the authorization request forms) sit under
horizonblue.com/sites/default/files/... and in the provider resource sections.

www.horizonblue.com is behind Imperva/Incapsula bot protection: scripted
requests to its HTML pages come back as a ~1 KB JavaScript interstitial rather
than the page.  The engine detects that shell and re-fetches the page from its
newest Internet Archive copy, which still carries the real document links, so
the crawl keeps working; the documents themselves download from the live host.

    python3 download_Horizon_precert_policies_workharder.py
    python3 download_Horizon_precert_policies_workharder.py --excel-only -v
    python3 download_Horizon_precert_policies_workharder.py --list-only
"""

from payer_harvest import PayerSite, run_split

# Any Horizon-hosted asset with a document extension is kept, whatever the file
# name says - Horizon names spreadsheets things like "2026-cpt-code-changes.xlsx"
# that carry no prior-auth keyword of their own.
HORIZON_DOC_ASSET = (
    r"(horizonblue|braven-health)\.com/.*\."
    r"(pdf|xlsx|xlsm|xls|docx|doc|rtf)(\?|#|$)"
)

SITE = PayerSite(
    payer="Horizon",
    seeds=[
        "https://www.horizonblue.com/providers/resources/"
        "provider-self-service-tools/prior-authorization-search",
        "https://www.horizonblue.com/providers/prior-authorizations",
        "https://www.horizonblue.com/providers/policies-procedures",
        "https://www.horizonblue.com/providers/policies-procedures/"
        "policies/medical-policies",
        "https://www.horizonblue.com/providers/products/"
        "utilization-management-programs",
        "https://www.horizonblue.com/providers/resources",
        "https://www.horizonblue.com/providers/forms",
        # Forms and reference material are where Horizon posts its workbooks
        # and Word templates.
        "https://www.horizonblue.com/providers/forms/authorization-forms",
        "https://www.horizonblue.com/providers/resources/manuals-guides",
        "https://www.horizonblue.com/providers/claims-payments",
        "https://www.horizonblue.com/providers",
        "https://www.braven-health.com/providers",
        "https://www.braven-health.com/providers/resources",
    ],
    allow_hosts=["horizonblue.com", "braven-health.com"],
    page_patterns=[r"horizonblue\.com/(providers|sites/default/files)",
                   r"braven-health\.com/(providers|sites)"],
    deny_patterns=[r"/(members|shop|employers|careers|news)"],
    keywords=["procedures requiring", "utilization management",
              "medical policy", "braven", "medicare advantage",
              "specialty pharmacy", "provider manual", "code list",
              # Spreadsheet / template wording used on Horizon's forms pages.
              "workbook", "worksheet", "spreadsheet", "template", "matrix",
              "code changes", "fee schedule change", "roster"],
    always_keep=[
        HORIZON_DOC_ASSET,
        r"horizonblue\.com/sites/default/files/.*(auth|policy|precert|prior)",
    ],
    wayback_prefixes=[
        "www.horizonblue.com/sites/default/files/*",
        "www.horizonblue.com/providers/*",
        "www.braven-health.com/*",
        # Horizon's older asset trees, which held .xls/.doc downloads.
        "www.horizonblue.com/sites/default/files/documents/*",
        "services.horizonblue.com/*",
    ],
    wayback_since=2019,
    max_pages=600,
    depth=3,
    notes="Horizon's authoritative PA source is a code-search tool; collected "
          "here are the published supporting lists, policies and forms in PDF, "
          "Excel and Word format. HTML pages are Imperva-protected, so the "
          "crawl reads them from the Internet Archive.",
)

if __name__ == "__main__":
    raise SystemExit(run_split(SITE))
