#!/usr/bin/env python3
"""
Delete files under ./downloaded/ that are not usable documents:

  * PDFs with no %%EOF marker in the last 8 KB (truncated captures - the
    Internet Archive cuts some snapshots at exactly 1 MiB),
  * zip-based office files with no end-of-central-directory record,
  * zero-byte files and HTML error pages saved with a document extension.

    python3 prune_bad_downloads.py            # report only
    python3 prune_bad_downloads.py --delete   # actually remove them
"""

import argparse
from pathlib import Path

from payer_harvest import DOWNLOAD_ROOT, looks_complete, magic_ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--payer", default="", help="limit to one payer folder")
    args = ap.parse_args()

    root = DOWNLOAD_ROOT / args.payer if args.payer else DOWNLOAD_ROOT
    bad: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        ext = path.suffix.lower()
        if ext not in (".pdf", ".xlsx", ".xls", ".docx", ".doc"):
            continue
        data = path.read_bytes()
        if not data:
            bad.append((path, "empty"))
        elif not magic_ok(data, ext):
            bad.append((path, "not a real document"))
        elif not looks_complete(data, ext):
            bad.append((path, f"truncated ({len(data):,} bytes)"))

    for path, why in bad:
        print(f"{'DELETE' if args.delete else 'BAD   '} {why:<28} "
              f"{path.relative_to(DOWNLOAD_ROOT)}")
        if args.delete:
            path.unlink()
    print(f"\n{len(bad)} problem file(s) "
          f"{'deleted' if args.delete else 'found (run with --delete)'}.")


if __name__ == "__main__":
    main()
