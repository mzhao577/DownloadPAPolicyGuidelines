#!/usr/bin/env python3
"""
Anthem (Elevance) - prior-authorization requirement harvest
(work-harder edition).

Anthem publishes a separate PA requirement list per state, plan and line of
business, spread over several hosts:

  * www.anthem.com/provider/... (individual & commercial landing pages),
  * providers.anthem.com / provider.anthem.com (provider resource centres,
    docs/gpp/... asset tree),
  * mediproviders.anthem.com (Medicaid state sites),
  * www11.anthem.com legacy document tree.

This script crawls all of them, pulls document URLs out of the raw payloads
(Anthem's lists are rendered from embedded JSON), and sweeps the Internet
Archive for the state PA lists that are no longer linked.

    python3 download_Anthem_precert_policies_workharder.py
    python3 download_Anthem_precert_policies_workharder.py --max-pages 900 -v
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="Anthem",
    seeds=[
        "https://www.anthem.com/provider/individual-commercial/prior-authorization",
        "https://www.anthem.com/provider/prior-authorization/",
        "https://www.anthem.com/provider/policies/",
        "https://www.anthem.com/provider/medical-policies-clinical-utilization-management-guidelines/",
        "https://providers.anthem.com/",
        "https://providers.anthem.com/california-provider/home",
        "https://providers.anthem.com/georgia-provider/home",
        "https://providers.anthem.com/new-york-provider/home",
        "https://providers.anthem.com/ohio-provider/home",
        "https://providers.anthem.com/virginia-provider/home",
        "https://providers.anthem.com/colorado-provider/home",
        "https://providers.anthem.com/connecticut-provider/home",
        "https://providers.anthem.com/indiana-provider/home",
        "https://providers.anthem.com/kentucky-provider/home",
        "https://providers.anthem.com/maine-provider/home",
        "https://providers.anthem.com/missouri-provider/home",
        "https://providers.anthem.com/nevada-provider/home",
        "https://providers.anthem.com/new-hampshire-provider/home",
        "https://providers.anthem.com/wisconsin-provider/home",
    ],
    allow_hosts=["anthem.com"],
    page_patterns=[r"anthem\.com/(provider|docs|dam|ms|.*provider)",
                   r"providers\.anthem\.com",
                   r"mediproviders\.anthem\.com"],
    deny_patterns=[r"/(login|logon|careers|newsroom|find-care)",
                   r"/(member|individual-family)/"],
    keywords=["prior authorization requirement", "pa requirement",
              "precertification", "clinical utilization management",
              "medical policy", "specialty pharmacy", "medical injectable",
              "ana_spl", "spl", "requirements list", "code list",
              "provider manual", "reimbursement policy"],
    always_keep=[r"anthem\.com/(dam|docs)/.*(auth|precert|pa[-_])",
                 r"_PA_List", r"PreCert", r"prior[-_]?auth"],
    wayback_prefixes=[
        "www.anthem.com/dam/*",
        "providers.anthem.com/*",
        "www.anthem.com/docs/*",
        "www11.anthem.com/provider/*",
        "mediproviders.anthem.com/*",
    ],
    wayback_since=2022,
    max_pages=700,
    depth=3,
    notes="Anthem's per-state PA lists are rendered from embedded JSON; the "
          "archive sweep also recovers the retired www11.anthem.com documents.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
