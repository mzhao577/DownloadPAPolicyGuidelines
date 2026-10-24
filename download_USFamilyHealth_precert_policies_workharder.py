#!/usr/bin/env python3
"""
US Family Health Plan - utilization-management harvest (work-harder edition).

USFHP is a TRICARE Prime option run by regional sponsors; the payer list names
two of them:

  * Martin's Point Health Care (martinspoint.org) - UM section of the provider
    manual, prior-authorization lists and ProAuth material,
  * Johns Hopkins USFHP (hopkinsusfhp.org) - a WordPress site whose
    outpatient/inpatient authorization guidelines live in wp-content/uploads,
    so the WordPress media library is enumerated directly.

Both sites are crawled, both media trees are swept in the Internet Archive.

    python3 download_USFamilyHealth_precert_policies_workharder.py
    python3 download_USFamilyHealth_precert_policies_workharder.py -v
"""

from payer_harvest import PayerSite, run

SITE = PayerSite(
    payer="USFamilyHealth",
    seeds=[
        "https://martinspoint.org/for-providers/provider-manual/"
        "utilization-management",
        "https://martinspoint.org/for-providers/provider-manual",
        "https://martinspoint.org/for-providers",
        "https://martinspoint.org/for-providers/resources-forms",
        "https://martinspoint.org/for-providers/prior-authorization",
        "https://www.hopkinsusfhp.org/for-providers/",
        "https://www.hopkinsusfhp.org/for-providers/prior-authorization/",
        "https://www.hopkinsusfhp.org/for-providers/provider-resources/",
        "https://www.hopkinsusfhp.org/",
    ],
    allow_hosts=["martinspoint.org", "hopkinsusfhp.org"],
    page_patterns=[r"martinspoint\.org/(for-providers|sites|media)",
                   r"hopkinsusfhp\.org"],
    deny_patterns=[r"/(careers|news|events|find-a-doctor|wp-admin)"],
    keywords=["utilization management", "prior authorization",
              "referral", "provider manual", "authorization guideline",
              "outpatient guideline", "inpatient", "proauth", "usfhp",
              "tricare", "medical policy", "clinical criteria"],
    always_keep=[r"hopkinsusfhp\.org/wp-content/uploads/",
                 r"martinspoint\.org/.*(auth|um|policy|manual)"],
    wp_roots=["https://www.hopkinsusfhp.org"],
    fallback_docs=[
        ("https://www.hopkinsusfhp.org/wp-content/uploads/2020/08/"
         "outpatient-guidelines.pdf",
         "Johns Hopkins USFHP Outpatient Prior Authorization Guidelines"),
    ],
    wayback_prefixes=[
        "www.hopkinsusfhp.org/wp-content/uploads/*",
        "martinspoint.org/*",
        "www.martinspoint.org/*",
    ],
    wayback_since=2019,
    wayback_keep_all=True,
    keep_all_docs=True,
    max_pages=400,
    depth=3,
    notes="Two regional USFHP sponsors; Johns Hopkins runs WordPress, so its "
          "media library is enumerated through the REST API.",
)

if __name__ == "__main__":
    raise SystemExit(run(SITE))
