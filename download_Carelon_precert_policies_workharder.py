#!/usr/bin/env python3
"""
Carelon Medical Benefits Management - clinical guideline harvest
(work-harder edition).

This is the generic-engine counterpart to download_Carelon_precert_policies.py
(which stays as the hand-written, WordPress-media-API-only version).  On top of
the media library it adds the sitemap walk, the raw-payload asset regex and an
Internet Archive sweep of the wp-content/uploads tree, which recovers guideline
editions that have since been replaced.

    python3 download_Carelon_precert_policies_workharder.py
    python3 download_Carelon_precert_policies_workharder.py --all-versions
"""

from payer_harvest import PayerSite, run

BASE = "https://guidelines.carelonmedicalbenefitsmanagement.com"

SITE = PayerSite(
    payer="Carelon",
    seeds=[
        BASE + "/",
        BASE + "/current-radiology-guidelines/",
        BASE + "/current-cardiology-guidelines/",
        BASE + "/current-oncology-guidelines/",
        BASE + "/current-musculoskeletal-guidelines/",
        BASE + "/current-sleep-guidelines/",
        BASE + "/current-genetic-testing-guidelines/",
        BASE + "/current-medical-oncology-guidelines/",
        BASE + "/archived-guidelines/",
        "https://www.carelon.com/products/medical-benefits-management",
    ],
    allow_hosts=["carelonmedicalbenefitsmanagement.com", "carelon.com"],
    page_patterns=[r"carelonmedicalbenefitsmanagement\.com",
                   r"carelon\.com/products"],
    deny_patterns=[r"/(wp-admin|wp-login|feed|comment)"],
    keywords=["guideline", "clinical appropriateness", "imaging", "radiology",
              "cardiology", "oncology", "musculoskeletal", "sleep",
              "genetic testing", "rehabilitation", "radiation"],
    always_keep=[r"wp-content/uploads/.*\.pdf"],
    wp_roots=[BASE],
    sitemaps=[BASE + "/wp-sitemap.xml"],
    wayback_prefixes=[
        "guidelines.carelonmedicalbenefitsmanagement.com/wp-content/uploads/*",
        "aimspecialtyhealth.com/wp-content/uploads/*",
    ],
    wayback_since=2021,
    wayback_keep_all=True,
    keep_all_docs=True,
    max_pages=400,
    depth=2,
    notes="Primary source is the WordPress media library (~600 guideline PDFs); "
          "the archive sweep also covers the retired aimspecialtyhealth.com.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
