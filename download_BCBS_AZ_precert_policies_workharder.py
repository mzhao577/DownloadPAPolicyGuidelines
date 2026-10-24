#!/usr/bin/env python3
"""
Blue Cross Blue Shield of Arizona (AZ Blue) - prior-authorization harvest
(work-harder edition).

Sources
-------
* azblue.com and provider.azblue.com prior-authorization / medical-policy
  pages; the PDFs live under provider.azblue.com/~/media/azblue/files/... and
  www.azblue.com/-/media/... .
* priorauth.azblue.com (the code lookup tool) is checked for any static
  document it exposes.
* Internet Archive sweep of both media trees, which recovers the quarterly
  prior-auth code lists and the older quick guides.

    python3 download_BCBS_AZ_precert_policies_workharder.py
    python3 download_BCBS_AZ_precert_policies_workharder.py --all-versions
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="BCBS_AZ",
    seeds=[
        "https://www.azblue.com/provider/resources/"
        "prior-authorization-and-medical-policies",
        "https://www.azblue.com/provider/resources",
        "https://www.azblue.com/provider",
        "https://provider.azblue.com/",
        "https://provider.azblue.com/providers/precertification",
        "https://provider.azblue.com/providers/forms",
        "https://www.azblue.com/provider/pharmacy",
        "https://www.azblue.com/medicare/provider",
    ],
    allow_hosts=["azblue.com"],
    page_patterns=[r"azblue\.com/(provider|providers|medicare|-/media|~/media)"],
    deny_patterns=[r"/(careers|news|shop|members|individuals)"],
    keywords=["quick guide", "medical policy", "pharmacy policy",
              "precertification", "prior auth", "metrics report",
              "step therapy", "inpatient admission", "snf", "tpa"],
    always_keep=[r"azblue\.com/(-|~)/media/"],
    fallback_docs=[
        ("https://provider.azblue.com/~/media/azblue/files/healthcare/"
         "precertification-requests-quick-guide.pdf",
         "Precertification Requests Quick Guide"),
    ],
    wayback_prefixes=[
        "www.azblue.com/-/media/*",
        "provider.azblue.com/*",
        "www.azblue.com/provider/*",
        "azblue.com/pdfs/*",
    ],
    wayback_since=2021,
    max_pages=500,
    depth=3,
    notes="AZ Blue's full PA code list is only in the priorauth.azblue.com "
          "lookup tool; the published quick guides, policy lists and metrics "
          "reports are collected here.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
