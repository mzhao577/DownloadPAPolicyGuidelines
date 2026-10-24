#!/usr/bin/env python3
"""
Dean Health Plan / Prevea360 - prior-authorization harvest
(work-harder edition).

deancare.com returns 403 to scripted clients on its HTML pages but serves the
documents under /getmedia/<guid>/<name>.pdf without complaint.  The same
document set is published on the sister brand prevea360.com and on
ssmhealth.com, so this script works all three, and sweeps the Internet Archive
for the /getmedia/ trees to recover the effective-dated service lists.

    python3 download_DeanHealth_precert_policies_workharder.py
    python3 download_DeanHealth_precert_policies_workharder.py --all-versions
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="DeanHealth",
    seeds=[
        "https://www.deancare.com/providers/medical-management",
        "https://www.deancare.com/providers",
        "https://www.deancare.com/providers/resources",
        "https://www.deancare.com/providers/pharmacy",
        "https://www.prevea360.com/providers/medical-management",
        "https://www.prevea360.com/providers",
        "https://www.ssmhealth.com/insurance-plans/provider-resources",
    ],
    allow_hosts=["deancare.com", "prevea360.com", "ssmhealth.com"],
    page_patterns=[r"(deancare|prevea360)\.com/(providers|getmedia)",
                   r"ssmhealth\.com/insurance-plans"],
    deny_patterns=[r"/(careers|news|find-a-doctor|members|espanol)"],
    keywords=["master service list", "service list", "medical management",
              "prior authorization", "medicare advantage", "referral",
              "medical policy", "pharmacy policy", "formulary"],
    always_keep=[r"/getmedia/"],
    fallback_docs=[
        ("https://www.deancare.com/getmedia/d4696fb0-6037-40d0-ad41-0028bba682ac/"
         "Dean-Health-Plan-Master-Service-List.pdf",
         "Dean Health Plan Master Service List (commercial PA list)"),
        ("https://www.deancare.com/getmedia/c9f53b3a-488a-4001-aedc-1aaeb5fa81e6/"
         "Dean-2026-medicare-advantage-prior-authorization-service-list.pdf",
         "Dean 2026 Medicare Advantage Prior Authorization Service List"),
    ],
    wayback_prefixes=[
        "www.deancare.com/getmedia/*",
        "www.deancare.com/providers/*",
        "www.prevea360.com/getmedia/*",
    ],
    wayback_since=2020,
    max_pages=400,
    depth=3,
    notes="HTML pages are bot-protected; documents under /getmedia/ download "
          "fine, and Prevea360 publishes the same lists.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
