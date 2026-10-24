#!/usr/bin/env python3
"""
Medica - prior-authorization / UM policy harvest (work-harder edition).

Medica keeps its provider documents on partner.medica.com under
/-/media/documents/provider/... (Sitecore media library).  The UM policy page
lists well over a hundred individual policy PDFs, so the crawl walks the whole
policies-and-guidelines section and the media library paths found in the raw
payloads, then sweeps the Internet Archive for superseded editions.

    python3 download_Medica_precert_policies_workharder.py
    python3 download_Medica_precert_policies_workharder.py --all-versions
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="Medica",
    seeds=[
        "https://partner.medica.com/providers/policies-and-guidelines/"
        "um-policies-and-prior-authorization",
        "https://partner.medica.com/providers/policies-and-guidelines",
        "https://partner.medica.com/providers/policies-and-guidelines/"
        "medical-policies",
        "https://partner.medica.com/providers/policies-and-guidelines/"
        "pharmacy-policies",
        "https://partner.medica.com/providers/policies-and-guidelines/"
        "coverage-policies",
        "https://partner.medica.com/providers",
        "https://partner.medica.com/providers/forms",
    ],
    allow_hosts=["medica.com"],
    page_patterns=[r"partner\.medica\.com/providers", r"medica\.com/-/media"],
    deny_patterns=[r"/(members|shop|careers|news|events)"],
    keywords=["um policy", "utilization management policy", "coverage policy",
              "medical policy", "prior authorization list", "ihcp",
              "medicare prior authorization", "pharmacy policy"],
    always_keep=[r"medica\.com/-/media/documents/provider/"],
    fallback_docs=[
        ("https://partner.medica.com/-/media/documents/provider/"
         "prior-authorization-list.pdf?la=en", "Prior Authorization List"),
        ("https://partner.medica.com/-/media/documents/provider/"
         "2026-medicare-prior-authorization-list.pdf?la=en",
         "2026 Medicare Prior Authorization List"),
    ],
    wayback_prefixes=[
        "partner.medica.com/-/media/*",
        "partner.medica.com/providers/*",
        "www.medica.com/-/media/*",
    ],
    wayback_since=2022,
    max_pages=600,
    depth=4,
    notes="Medica's UM policies are individual PDFs in the Sitecore media "
          "library at /-/media/documents/provider/.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
