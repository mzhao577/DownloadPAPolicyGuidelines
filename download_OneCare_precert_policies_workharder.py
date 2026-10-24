#!/usr/bin/env python3
"""
CalOptima Health OneCare - prior-authorization harvest (work-harder edition).

CalOptima (OneCare Medicare D-SNP and Medi-Cal) publishes its prior-auth
required lists, authorization forms and UM policies as Sitecore Content Hub
assets on cop-p-001.sitecorecontenthub.cloud, referenced from caloptima.org
provider pages by bare content id (no file extension).  The engine keeps those
extension-less asset URLs and identifies them by magic bytes after download.

    python3 download_OneCare_precert_policies_workharder.py
    python3 download_OneCare_precert_policies_workharder.py -v
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="OneCare",
    seeds=[
        "https://www.caloptima.org/en/for-providers/claims-and-eligibility/"
        "prior-authorizations",
        "https://www.caloptima.org/en/for-providers/claims-and-eligibility",
        "https://www.caloptima.org/en/for-providers",
        "https://www.caloptima.org/en/for-providers/provider-resources",
        "https://www.caloptima.org/en/for-providers/pharmacy-management",
        "https://www.caloptima.org/en/for-providers/policies-and-procedures",
        "https://www.caloptima.org/en/for-providers/onecare",
    ],
    allow_hosts=["caloptima.org", "sitecorecontenthub.cloud"],
    page_patterns=[r"caloptima\.org/en/for-providers"],
    deny_patterns=[r"/(es|vi|zh|ko|fa|ar)/", r"/(careers|news|about|members)"],
    keywords=["prior authorization", "authorization required",
              "utilization management", "policy", "onecare", "medi-cal",
              "referral", "formulary", "pharmacy", "provider manual"],
    always_keep=[r"sitecorecontenthub\.cloud/api/public/content/"],
    fallback_docs=[
        ("https://cop-p-001.sitecorecontenthub.cloud/api/public/content/"
         "c0dd8bbcaac14feaa087415dac3f3fd9?v=58934819",
         "OneCare Prior Authorization Required List"),
        ("https://cop-p-001.sitecorecontenthub.cloud/api/public/content/"
         "c7d04763723f4c5191e44b8ce3b6c507?v=38cc6a37",
         "CalOptima Medi-Cal Prior Authorization Required List"),
        ("https://cop-p-001.sitecorecontenthub.cloud/api/public/content/"
         "90cdd874e32741bbb5d216c513965979?v=79db4119",
         "OneCare Authorization Request Form"),
    ],
    wayback_prefixes=[
        "www.caloptima.org/*",
        "cop-p-001.sitecorecontenthub.cloud/api/public/content/*",
    ],
    wayback_since=2021,
    max_pages=450,
    depth=3,
    notes="Documents are bare Sitecore Content Hub content ids; file names come "
          "from the link text on the CalOptima provider pages.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
