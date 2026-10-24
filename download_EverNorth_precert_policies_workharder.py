#!/usr/bin/env python3
"""
Evernorth - prior-authorization resource harvest (work-harder edition).

Evernorth's service-level PA lists sit behind the authenticated
provider.evernorth.com portal, but a substantial public library exists:

  * evernorth.com/prior-authorization-resources and the behavioral-health
    provider pages,
  * static.evernorth.com/assets/evernorth/provider/pdf/resourceLibrary/...
    (the CDN tree that holds the PA forms, authorization/billing guides and
    medical-necessity criteria),
  * Express Scripts / Accredo PA forms referenced from those pages.

The Internet Archive sweep of the static CDN tree adds the older editions.

    python3 download_EverNorth_precert_policies_workharder.py
    python3 download_EverNorth_precert_policies_workharder.py -v
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="EverNorth",
    seeds=[
        "https://www.evernorth.com/prior-authorization-resources",
        "https://www.evernorth.com/provider-resources",
        "https://www.evernorth.com/behavioral-health/providers",
        "https://www.evernorth.com/behavioral-health/providers/resources",
        "https://www.evernorth.com/health-care-providers",
        "https://www.evernorth.com/care-solutions",
        "https://www.evernorth.com/behavioral-health/providers/"
        "clinical-resources",
    ],
    allow_hosts=["evernorth.com"],
    page_patterns=[r"evernorth\.com/(prior|provider|behavioral|health-care|"
                   r"care-solutions|assets|static)"],
    deny_patterns=[r"/(careers|newsroom|about|insights|events)"],
    keywords=["prior authorization", "authorization and billing",
              "medical necessity criteria", "behavioral health",
              "precertification", "resource guide", "clinical criteria",
              "accredo", "express scripts", "specialty"],
    always_keep=[r"static\.evernorth\.com/assets/.*\.(pdf|xlsx?|docx?)"],
    fallback_docs=[
        ("https://static.evernorth.com/assets/evernorth/provider/pdf/"
         "resourceLibrary/behavioral/authorization-and-billing-resource.pdf",
         "Evernorth Behavioral Health Authorization and Billing Resource Guide"),
        ("https://static.evernorth.com/assets/evernorth/provider/pdf/"
         "resourceLibrary/behavioral/inpatient-prior-authorization-form.pdf",
         "Evernorth Behavioral Health Inpatient Prior Authorization Form"),
    ],
    wayback_prefixes=[
        "static.evernorth.com/assets/evernorth/provider/*",
        "www.evernorth.com/*",
    ],
    wayback_since=2021,
    max_pages=450,
    depth=3,
    notes="Public library is mostly behavioral-health PA material; the "
          "medical PA lists require the authenticated provider portal.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
