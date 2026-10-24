#!/usr/bin/env python3
"""
Aetna - precertification / prior-authorization document harvest
(work-harder edition).

Sources
-------
* aetna.com precertification landing pages (lists, code lists, participating
  provider precert, behavioral health, Medicare) crawled to depth 3.
* Every document reference found in raw page/JSON payloads under
  aetna.com/content/dam/... (Aetna's AEM asset tree), including the ones the
  page only reveals through JavaScript.
* Internet Archive sweep of the aetna.com DAM prior-auth folders, which
  recovers the superseded monthly/quarterly versions of the precert list.

    python3 download_Aetna_precert_policies_workharder.py
    python3 download_Aetna_precert_policies_workharder.py --since 2020 -v
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="Aetna",
    seeds=[
        "https://www.aetna.com/health-care-professionals/precertification/"
        "precertification-lists.html",
        "https://www.aetna.com/health-care-professionals/precertification.html",
        "https://www.aetna.com/health-care-professionals/precertification/"
        "precertification-participating-provider.html",
        "https://www.aetna.com/health-care-professionals/precertification/"
        "behavioral-health-precertification.html",
        "https://www.aetna.com/health-care-professionals/clinical-policy-bulletins.html",
        "https://www.aetna.com/health-care-professionals/"
        "clinical-policy-bulletins/medical-clinical-policy-bulletins.html",
        "https://www.aetna.com/health-care-professionals/utilization-management.html",
        "https://www.aetna.com/health-care-professionals/"
        "medicare-precertification-lists.html",
        "https://www.aetna.com/health-care-professionals/newsletters-news/"
        "office-link-updates.html",
    ],
    allow_hosts=["aetna.com"],
    page_patterns=[r"aetna\.com/health-care-professionals",
                   r"aetna\.com/content/dam/aetna/pdfs"],
    deny_patterns=[r"/(es|espanol)/", r"/individuals-families", r"/employers"],
    keywords=["precertification list", "clinical policy bulletin",
              "national precertification", "participating provider precert",
              "behavioral health precert", "clinical program summary",
              "specialty drug", "part b step therapy"],
    always_keep=[r"aetna\.com/content/dam/aetna/pdfs/.*(precert|prior|auth)",
                 r"precert", r"clinical_program_summary"],
    fallback_docs=[
        ("https://www.aetna.com/content/dam/aetna/pdfs/aetnacom/"
         "healthcare-professionals/2026_Precert_List.pdf",
         "2026 Aetna Precertification List"),
        ("https://www.aetna.com/content/dam/aetna/pdfs/aetnacom/"
         "healthcare-professionals/bh_precert_list.pdf",
         "Aetna Behavioral Health Precertification List"),
        ("https://www.aetna.com/content/dam/aetna/pdfs/aetnacom/"
         "healthcare-professionals/2026_Aetna_Commercial_Clinical_Program_Summary.pdf",
         "2026 Aetna Commercial Clinical Program Summary"),
    ],
    wayback_prefixes=[
        "www.aetna.com/content/dam/aetna/pdfs/aetnacom/healthcare-professionals/*",
        "www.aetna.com/health-care-professionals/*",
    ],
    wayback_since=2021,
    max_pages=500,
    depth=3,
    notes="Aetna's national precert list is revised several times a year at the "
          "same DAM URL; the Internet Archive sweep recovers the superseded "
          "versions.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
