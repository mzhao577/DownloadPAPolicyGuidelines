#!/usr/bin/env python3
"""
Humana - prior-authorization / notification list harvest (work-harder edition).

Sources
-------
* provider.humana.com prior-authorization pages (Medicare, commercial,
  Medicaid/Healthy Horizons by state, preauthorization-and-notification lists,
  medical and pharmacy coverage policies).
* Humana serves its documents from the Scene7 asset host
  assets.humana.com/is/content/humana/... - those URLs appear only inside the
  page payloads, so the raw-asset regex picks them up.
* Internet Archive sweep of both hosts for the superseded editions.

    python3 download_Humana_precert_policies_workharder.py
    python3 download_Humana_precert_policies_workharder.py --all-versions
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="Humana",
    seeds=[
        "https://provider.humana.com/coverage-claims/prior-authorizations/"
        "prior-authorization-lists",
        "https://provider.humana.com/coverage-claims/prior-authorizations",
        "https://provider.humana.com/coverage-claims/medical-resources",
        "https://provider.humana.com/coverage-claims/medical-resources/"
        "medical-pharmacy-coverage-policies",
        "https://provider.humana.com/pharmacy-resources",
        "https://provider.humana.com/coverage-claims",
        "https://www.humana.com/provider/medical-resources/clinical/"
        "preauthorization-and-notification",
    ],
    allow_hosts=["humana.com"],
    page_patterns=[r"provider\.humana\.com/(coverage-claims|pharmacy-resources|"
                   r"medical-resources)",
                   r"humana\.com/provider/"],
    deny_patterns=[r"/(careers|news|about|espanol)", r"/member"],
    keywords=["preauthorization", "notification list", "healthy horizons",
              "medical coverage policy", "pharmacy coverage policy",
              "dsnp", "medicare advantage", "medicaid"],
    always_keep=[r"assets\.humana\.com/is/content/humana/.*(auth|precert|"
                 r"notification|policy|list)"],
    fallback_docs=[
        ("https://assets.humana.com/is/content/humana/FINAL_Medicare%20and%20"
         "DSNP%20Prior%20Authorization%20and%20Notification%20List%20-%20"
         "1-1-2026pdf",
         "Medicare and DSNP Prior Authorization and Notification List 1-1-2026"),
        ("https://assets.humana.com/is/content/humana/2026%20Medicare%20Prior%20"
         "Authorization%20Listpdf",
         "2026 Medicare Prior Authorization List"),
    ],
    wayback_prefixes=[
        "provider.humana.com/*",
        "assets.humana.com/is/content/humana/*",
        "docushare-web.apps.external.pioneer.humana.com/*",
    ],
    wayback_since=2022,
    max_pages=450,
    depth=3,
    notes="Humana's Scene7 asset URLs end in 'pdf' without a dot, so the "
          "fallback list carries them explicitly.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
