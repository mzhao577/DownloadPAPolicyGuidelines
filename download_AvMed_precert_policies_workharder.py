#!/usr/bin/env python3
"""
AvMed - prior-authorization document harvest (work-harder edition).

Sources
-------
* avmed.org provider prior-authorization pages (crawled, plus the whole
  provider / medical-policy section discovered from the sitemap).
* AvMed serves its documents from a Sitecore Content Hub CDN
  (shc-p-001.sitecorecontenthub.cloud/api/public/content/...), so document
  URLs are collected from raw page/JSON payloads, not just <a href>.
* Internet Archive sweep of avmed.org for archived PA lists and older
  effective-dated versions.

    python3 download_AvMed_precert_policies_workharder.py
    python3 download_AvMed_precert_policies_workharder.py --list-only -v
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="AvMed",
    seeds=[
        "https://www.avmed.org/en/provider/provider-tools/prior-authorization",
        "https://www.avmed.org/en/provider/provider-tools",
        "https://www.avmed.org/en/provider",
        "https://www.avmed.org/en/provider/provider-resources",
        "https://www.avmed.org/en/provider/provider-tools/medical-policies",
        "https://www.avmed.org/en/provider/pharmacy",
    ],
    allow_hosts=["avmed.org", "sitecorecontenthub.cloud"],
    page_patterns=[r"avmed\.org/en/(provider|pharmacy|forms|medical)"],
    deny_patterns=[r"/(careers|news|blog|events|espanol|es/)"],
    keywords=["authorization requirement", "no authorization",
              "referral guideline", "coverage guideline", "provider manual"],
    always_keep=[r"sitecorecontenthub\.cloud/api/public/content/"],
    fallback_docs=[
        ("https://shc-p-001.sitecorecontenthub.cloud/api/public/content/"
         "prior-authorization-requirements.pdf?v=3ae9e903",
         "Prior Authorization Requirements"),
        ("https://shc-p-001.sitecorecontenthub.cloud/api/public/content/"
         "1b58fcdc148c41fe931b8008096fc5a9?v=4b97d353",
         "No Authorization Required List of Procedure Codes"),
        ("https://shc-p-001.sitecorecontenthub.cloud/api/public/content/"
         "Medical-Prior-Authorization-Request-Form-2026.pdf?v=aee4d138",
         "Medical Prior Authorization Request Form 2026"),
    ],
    wayback_prefixes=["avmed.org/*"],
    wayback_since=2022,
    max_pages=350,
    depth=3,
    notes="Documents live on AvMed's Sitecore Content Hub CDN; the old "
          "avmed.org/media/... paths now 404 and are recovered from the "
          "Internet Archive.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
