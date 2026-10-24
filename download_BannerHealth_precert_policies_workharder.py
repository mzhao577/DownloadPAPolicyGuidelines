#!/usr/bin/env python3
"""
Banner Health Plans - prior-authorization grid harvest (work-harder edition).

Covers both Banner sites in the payer list:
  * bannerhealth.com/bhpprovider/... (Banner Health Plans commercial PA grids),
  * bannerhealth.com/medicare/providers/... (Banner Medicare Advantage grids).

Banner's grids are Sitecore media assets under /-/media/files/project/...
whose URLs only appear inside the page payloads, and each grid is republished
with a new "eff<date>" file name every few weeks - so the Internet Archive
sweep of the media tree adds a large number of dated editions.

    python3 download_BannerHealth_precert_policies_workharder.py
    python3 download_BannerHealth_precert_policies_workharder.py --all-versions
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="BannerHealth",
    seeds=[
        "https://www.bannerhealth.com/bhpprovider/prior-authorizations/"
        "prior-auth-grids",
        "https://www.bannerhealth.com/bhpprovider/prior-authorizations",
        "https://www.bannerhealth.com/bhpprovider",
        "https://www.bannerhealth.com/bhpprovider/resources",
        "https://www.bannerhealth.com/medicare/providers/pa-grids",
        "https://www.bannerhealth.com/medicare/providers",
        "https://www.bannerhealth.com/medicare/providers/provider-resources",
        "https://www.bannerhealth.com/bhpprovider/pharmacy",
    ],
    allow_hosts=["bannerhealth.com"],
    page_patterns=[r"bannerhealth\.com/(bhpprovider|medicare|-/media)"],
    deny_patterns=[r"/(careers|locations|services|patients|about-us|news)"],
    keywords=["pa grid", "prior auth grid", "medical pa", "pharmacy pa",
              "medicare advantage", "banner university", "bufc", "aetna",
              "formulary", "provider manual"],
    always_keep=[r"bannerhealth\.com/-/media/.*(pa|auth|grid)",
                 r"prior-authorization-grids"],
    fallback_docs=[
        ("https://www.bannerhealth.com/medicare/-/media/files/project/medicare/"
         "for-providers/prior-authorization-grids/medical/"
         "prov-bma_medical-pa-grid_eff01232025.pdf",
         "Banner Medicare Advantage Medical PA Grid eff 01-23-2025"),
        ("https://www.bannerhealth.com/medicare/-/media/files/project/medicare/"
         "for-providers/prior-authorization-grids/pharmacy/"
         "prov_bma_pharm-pa-grid_eff06152026_v2_en.pdf",
         "Banner Medicare Advantage Pharmacy PA Grid eff 06-15-2026"),
    ],
    wayback_prefixes=[
        "www.bannerhealth.com/-/media/*",
        "www.bannerhealth.com/bhpprovider/*",
        "www.bannerhealth.com/medicare/*",
    ],
    wayback_since=2021,
    max_pages=500,
    depth=3,
    notes="Banner republishes each grid under a new eff<date> file name, so "
          "the archive sweep yields the full version history.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
