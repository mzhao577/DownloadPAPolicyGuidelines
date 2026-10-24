#!/usr/bin/env python3
"""
Cigna - precertification / prior-authorization harvest (work-harder edition).

Covers both Cigna sites from the payer list:
  * cigna.com commercial precertification + coverage-policy pages
    (documents live under /static/www-cigna-com/docs/...),
  * medicareproviders.cigna.com (Cigna Medicare Advantage), whose PA
    requirement lists live under /static/medicareproviders-cigna-com/docs/...

Also sweeps the Internet Archive for both static document trees, which
recovers the quarterly editions of the master precertification list.

    python3 download_Cigna_precert_policies_workharder.py
    python3 download_Cigna_precert_policies_workharder.py --all-versions -v
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="Cigna",
    seeds=[
        "https://www.cigna.com/health-care-providers/coverage-and-claims/"
        "precertification",
        "https://www.cigna.com/health-care-providers/coverage-and-claims",
        "https://www.cigna.com/health-care-providers/coverage-and-claims/policies",
        "https://www.cigna.com/health-care-providers/coverage-and-claims/"
        "policies/coverage-policies",
        "https://www.cigna.com/health-care-providers/coverage-and-claims/"
        "policies/medical-coverage-policies",
        "https://www.cigna.com/health-care-providers/coverage-and-claims/"
        "prior-authorization",
        "https://medicareproviders.cigna.com/",
        "https://medicareproviders.cigna.com/provider-resources",
        "https://medicareproviders.cigna.com/prior-authorization",
    ],
    allow_hosts=["cigna.com"],
    page_patterns=[r"cigna\.com/(health-care-providers|static)",
                   r"medicareproviders\.cigna\.com"],
    deny_patterns=[r"/(individuals-families|employers|about-us|newsroom)",
                   r"/es/"],
    keywords=["precertification", "coverage policy", "master precert",
              "codes removed", "medical necessity review",
              "medicare advantage prior authorization", "modifier",
              "reimbursement policy"],
    always_keep=[r"/docs/.*precert", r"prior-authorization-requirements",
                 r"master-precertification"],
    fallback_docs=[
        ("https://www.cigna.com/static/www-cigna-com/docs/"
         "master-precertification-list-for-providers.pdf",
         "Master Precertification List for Providers"),
        ("https://www.cigna.com/static/www-cigna-com/docs/"
         "master-precertification-list-codes-removed-for-providers.pdf",
         "Master Precertification List - Codes Removed"),
        ("https://medicareproviders.cigna.com/static/medicareproviders-cigna-com/"
         "docs/prior-authorization-requirements.pdf",
         "Cigna Medicare Prior Authorization Requirements"),
    ],
    wayback_prefixes=[
        "www.cigna.com/static/www-cigna-com/docs/*",
        "medicareproviders.cigna.com/static/*",
        "static.cigna.com/assets/chcp/*",
    ],
    wayback_since=2022,
    max_pages=450,
    depth=3,
    notes="Cigna's provider pages are JS-rendered; the document URLs are read "
          "out of the embedded payloads and from the /static/ document trees.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
