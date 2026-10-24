#!/usr/bin/env python3
"""
Regenerate listofpayer_withWebsites.csv from the per-payer work-harder scripts.

Every seed URL, hard-coded document host and Internet Archive prefix that the
scripts actually use is listed, one row per website, with the plan label from
the original payer list.

    python3 write_websites_csv.py
"""

import csv
import importlib
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "listofpayer_withWebsites.csv"

# Plan labels from the original payer list, keyed by payer folder name.
PLANS = {
    "Aetna": "Commercial & Medicare",
    "UnitedHealthcare": "Commercial / Individual Exchange / Medicare",
    "Cigna": "Commercial & Medicare Advantage",
    "Humana": "Medicare & Commercial",
    "Anthem": "Individual & Commercial (multi-state)",
    "Horizon": "New Jersey (all)",
    "Medica": "Commercial & Medicare",
    "AveraCare": "Avera Health Plans",
    "BCBS_AZ": "Commercial & Medicare",
    "EviCore": "Clinical Guidelines (all plans)",
    "Carelon": "Clinical Guidelines (all)",
    "AvMed": "All plans",
    "BannerHealth": "Commercial & Medicare Advantage",
    "EverNorth": "Prior Authorization Resources",
    "DeanHealth": "Commercial & Medicare",
    "USFamilyHealth": "Martin's Point & Johns Hopkins USFHP",
    "Highmark": "Commercial, Wholecare & Health Options",
    "OneCare": "CalOptima OneCare (Medicare D-SNP) & Medi-Cal",
}

ORDER = list(PLANS)


def main() -> None:
    rows: list[tuple[str, str, str]] = []
    for payer in ORDER:
        module_name = f"download_{payer}_precert_policies_workharder"
        try:
            site = importlib.import_module(module_name).SITE
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {module_name}: {exc}")
            continue
        plan = PLANS.get(payer, "")
        seen: set[str] = set()

        def add(url: str, note: str = "") -> None:
            key = url.rstrip("/")
            if key in seen:
                return
            seen.add(key)
            rows.append((payer, f"{plan} - {note}" if note else plan, url))

        for seed in site.seeds:
            add(seed)
        for url, _label in site.fallback_docs:
            root = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
            add(root, "document host")
        for prefix in site.wayback_prefixes:
            host = prefix.split("/")[0]
            add(f"https://{host}", "Internet Archive sweep")

    with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["PayerName", "PayerPlan", "Website"])
        writer.writerows(rows)
    print(f"Wrote {len(rows)} website row(s) for {len(ORDER)} payers "
          f"to {CSV_PATH}")


if __name__ == "__main__":
    main()
