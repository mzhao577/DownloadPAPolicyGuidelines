#!/usr/bin/env python3
"""
UnitedHealthcare - prior-authorization / advance-notification harvest
(work-harder edition).

Sources
-------
* uhcprovider.com prior-auth landing pages for every line of business
  (commercial, exchange, Medicare Advantage, community plan by state, dual
  special needs, UHC West), crawled to depth 3.
* The DAM asset tree www.uhcprovider.com/content/dam/provider/docs/public/
  prior-auth/... where the plan-requirement PDFs actually live; URLs are
  pulled straight out of the raw page/JSON payloads.
* Internet Archive sweep of that DAM subtree, which recovers the monthly
  editions of each state's PA list and the superseded summaries of change.

    python3 download_UnitedHealthcare_precert_policies_workharder.py
    python3 download_UnitedHealthcare_precert_policies_workharder.py --all-versions
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="UnitedHealthcare",
    seeds=[
        "https://www.uhcprovider.com/en/prior-auth-advance-notification/"
        "adv-notification-plan-reqs.html",
        "https://www.uhcprovider.com/en/prior-auth-advance-notification.html",
        "https://www.uhcprovider.com/en/prior-auth-advance-notification/"
        "adv-notification-plan-reqs/paan-comm-plan-req.html",
        "https://www.uhcprovider.com/en/prior-auth-advance-notification/"
        "adv-notification-plan-reqs/paan-exchange-plan-reqs.html",
        "https://www.uhcprovider.com/en/prior-auth-advance-notification/"
        "adv-notification-plan-reqs/paan-medicare-advantage.html",
        "https://www.uhcprovider.com/en/prior-auth-advance-notification/"
        "adv-notification-plan-reqs/paan-comm-plan-req/paan-comm-plan-req-state.html",
        "https://www.uhcprovider.com/en/prior-auth-advance-notification/"
        "specialty-medical-injectable-drugs.html",
        "https://www.uhcprovider.com/en/policies-protocols.html",
        "https://www.uhcprovider.com/en/policies-protocols/commercial-policies.html",
        "https://www.uhcprovider.com/en/policies-protocols/"
        "medicare-advantage-policy-guidelines.html",
    ],
    allow_hosts=["uhcprovider.com"],
    page_patterns=[r"uhcprovider\.com/en/(prior-auth|policies-protocols|"
                   r"health-plans-by-state|resource-library)"],
    deny_patterns=[r"/(news|events|training|contact-us)"],
    keywords=["advance notification", "plan requirement", "paan",
              "specialty medical injectable", "policy guideline",
              "community plan", "dual complete", "prior auth requirement"],
    always_keep=[r"/docs/public/prior-auth/", r"/docs/public/policies/",
                 r"adv-?notice", r"summary-of-changes"],
    fallback_docs=[
        ("https://www.uhcprovider.com/content/dam/provider/docs/public/"
         "prior-auth/pa-requirements/commercial/"
         "UHC-Commercial-Advance-Notification-PA-Requirements-1-2026.pdf",
         "UHC Commercial Advance Notification and PA Requirements 2026"),
        ("https://www.uhcprovider.com/content/dam/provider/docs/public/"
         "prior-auth/pa-requirements/multi/"
         "2026-Summary-of-Changes-AdvNotice-and-PriorAuth.pdf",
         "2026 Summary of Changes - Advance Notification and Prior Authorization"),
        ("https://www.uhcprovider.com/content/dam/provider/docs/public/"
         "prior-auth/exchanges/UHC-Exchange-Plans-Advance-Notification-PA-"
         "Eff-1-1-26.pdf",
         "UHC Exchange Plans Advance Notification and PA Eff 1-1-2026"),
    ],
    wayback_prefixes=[
        "www.uhcprovider.com/content/dam/provider/docs/public/prior-auth/*",
        "www.uhcprovider.com/content/dam/provider/docs/public/policies/*",
    ],
    wayback_since=2023,
    max_pages=600,
    depth=3,
    notes="UHC publishes a separate PA/advance-notification list per state and "
          "line of business; all of them live under /docs/public/prior-auth/.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
