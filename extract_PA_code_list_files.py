#!/usr/bin/env python3
"""
Pull the prior-authorization CODE LIST documents out of ./downloaded/ into
./downloaded_PAListFiles/, keeping the per-payer subfolder structure.

What counts as a "PA code list"
-------------------------------
Not every document a payer publishes about prior authorization contains the
actual list of procedure codes.  This script keeps a file only when its text
shows all three of:

  1. CODES        - enough distinct procedure codes: CPT (5 digits), CPT
                    Category II/III (4 digits + T/F/U/M) and HCPCS Level II
                    (letter + 4 digits).
  2. DENSITY      - those codes are packed like a table, not sprinkled through
                    prose.  Measured as distinct codes per 1,000 characters of
                    text; a code-list grid scores 5-100, a clinical policy that
                    happens to cite a few codes scores well under 1.
  3. PA CONTEXT   - the words prior authorization / precertification /
                    preauthorization / authorization required / advance
                    notification / prior auth grid appear in the text or the
                    file name.

Documents that are code-dense but are not PA lists (fee schedules, remittance
guides, provider directories, benefit summaries, drug formularies listing NDC
numbers) are rejected by the PA-context test plus an explicit exclusion list.

Text extraction uses PyMuPDF when available and falls back to poppler's
pdftotext; .xlsx/.docx are read straight out of their zip XML, and legacy
.xls/.doc via printable-string extraction.

Usage
-----
    python3 extract_PA_code_list_files.py                 # copy the matches
    python3 extract_PA_code_list_files.py --dry-run       # decide, copy nothing
    python3 extract_PA_code_list_files.py --link          # hard-link (no extra disk)
    python3 extract_PA_code_list_files.py --payer Aetna   # one payer only
    python3 extract_PA_code_list_files.py --report scores.csv --keep-all-scores
    python3 extract_PA_code_list_files.py --min-codes 40 --min-density 3

Every run writes downloaded_PAListFiles/_manifest.csv listing what was copied
and why, and caches per-file text statistics in .pa_scan_cache.json so later
runs only re-read files that changed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "downloaded"
DEST_ROOT = ROOT / "downloaded_PAListFiles"
CACHE_PATH = ROOT / ".pa_scan_cache.json"

DOC_EXTS = {".pdf", ".xlsx", ".xls", ".docx", ".doc"}

# How much of a document to read.  PA lists put their table up front; reading
# the first pages keeps a 22,000-file sweep to a few minutes.
MAX_PAGES = 25
MAX_CHARS = 400_000

# ---------------------------------------------------------------------------
# Code patterns
# ---------------------------------------------------------------------------
CPT_RE = re.compile(r"(?<![\w.-])(\d{5})(?![\w.-])")
CPT_CAT_RE = re.compile(r"(?<![\w.-])(\d{4}[TFUM])(?![\w.-])")
HCPCS_RE = re.compile(r"(?<![\w.-])([A-VX-Z]\d{4})(?![\w.-])")

# 5-digit numbers that are not CPT codes.
NON_CPT = re.compile(r"^(0{4}\d|00000|1[0-2]\d{3}$)")

PA_TERMS = (
    "prior authorization", "prior authorizations", "prior auth",
    "preauthorization", "pre-authorization", "pre authorization",
    "precertification", "pre-certification", "precert", "pre-cert",
    "authorization required", "authorization is required",
    "requires authorization", "requiring authorization",
    "advance notification", "notification required",
    "prior approval", "preauth", "pa required", "pa list", "auth grid",
    "utilization management", "medical necessity review",
    "review required", "authorization list",
    # Phrasings payers use instead of "prior authorization" for the same thing.
    "appropriateness review", "medical necessity determination",
    "medical necessity and appropriateness", "predetermination",
    "prior review", "prior plan approval", "authorization requirement",
    "subject to review", "notification is required", "must be authorized",
    "certification is required", "requires precertification",
)

# File-name patterns that identify a PA list even when the PDF is a scanned or
# otherwise text-poor table.
STRONG_NAME_RE = re.compile(
    r"(prior[\s_-]*auth\w*|pre[\s_-]*auth\w*|precert\w*|pre[\s_-]*cert\w*|"
    r"pa[\s_-]*(list|grid|code|requirement)|auth\w*[\s_-]*(list|grid|"
    r"requirement|code)|advance[\s_-]*notification|notification[\s_-]*list|"
    r"code[\s_-]*list|service[\s_-]*list|requiring[\s_-]*auth\w*|"
    r"j[\s_-]*code[\s_-]*(list|auth))", re.IGNORECASE)

# Document kinds that are never the PA code list, even when the file name also
# says "prior authorization" - the state-mandated PA statistics reports are the
# main offender: they tabulate request volumes by code, not the requirements.
HARD_EXCLUDE_RE = re.compile(
    r"(statistic|metrics[\s_-]*report|\bur[\s_-]*(statistics|report)\b|"
    r"utilization[\s_-]*review[\s_-]*(statistics|report)|transparency|"
    r"annual[\s_-]*report|quarterly[\s_-]*report|newsletter|"
    r"press[\s_-]*release|evidence[\s_-]*of[\s_-]*coverage|\beoc\b|"
    r"annual[\s_-]*notice|\banoc\b|summary[\s_-]*of[\s_-]*benefits|"
    r"member[\s_-]*handbook|provider[\s_-]*directory|"
    r"pharmacy[\s_-]*directory|remittance|claim[\s_-]*form|w-9|1099)",
    re.IGNORECASE)

# Code-dense but off-target unless the file name also marks it as a PA list.
EXCLUDE_NAME_RE = re.compile(
    r"(fee[\s_-]*schedule|provider[\s_-]*manual|reimbursement[\s_-]*policy|"
    r"fee[\s_-]*allowance|rate[\s_-]*sheet|fee[\s_-]*adjustment)",
    re.IGNORECASE)


@dataclass
class Stats:
    path: str
    size: int
    mtime: float
    chars: int = 0
    pages: int = 0
    codes: int = 0
    cpt: int = 0
    hcpcs: int = 0
    density: float = 0.0
    pa_hits: int = 0
    strong_name: bool = False
    excluded_name: bool = False
    hard_excluded: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
def pdf_text(path: Path) -> tuple[str, int]:
    """Return (text, page_count) for the first MAX_PAGES pages."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            pages = doc.page_count
            chunks = []
            for i in range(min(pages, MAX_PAGES)):
                chunks.append(doc.load_page(i).get_text("text"))
                if sum(len(c) for c in chunks) > MAX_CHARS:
                    break
            return "".join(chunks), pages
    except Exception:  # noqa: BLE001
        pass
    try:
        out = subprocess.run(
            ["pdftotext", "-l", str(MAX_PAGES), "-q", str(path), "-"],
            capture_output=True, timeout=120)
        return out.stdout.decode("utf-8", "replace"), 0
    except Exception:  # noqa: BLE001
        return "", 0


def zip_xml_text(path: Path, members: tuple[str, ...]) -> str:
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            for name in names:
                if not name.startswith(members):
                    continue
                try:
                    raw = zf.read(name).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
                chunks.append(re.sub(r"<[^>]+>", " ", raw))
                if sum(len(c) for c in chunks) > MAX_CHARS:
                    break
    except Exception:  # noqa: BLE001
        return ""
    return " ".join(chunks)


def legacy_text(path: Path) -> str:
    """Printable runs out of a legacy OLE (.doc/.xls) file."""
    try:
        data = path.read_bytes()[:8_000_000]
    except Exception:  # noqa: BLE001
        return ""
    runs = re.findall(rb"[\x20-\x7e]{4,}", data)
    text = b" ".join(runs).decode("ascii", "replace")
    # Legacy xls stores numbers in binary; the text pass still catches the
    # code columns that were entered as text plus all headings.
    return text[:MAX_CHARS]


def extract_text(path: Path) -> tuple[str, int]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return pdf_text(path)
    if ext == ".xlsx":
        return zip_xml_text(path, ("xl/",)), 0
    if ext == ".docx":
        return zip_xml_text(path, ("word/",)), 0
    if ext in (".xls", ".doc"):
        return legacy_text(path), 0
    return "", 0


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_file(path_str: str) -> Stats:
    path = Path(path_str)
    st = path.stat()
    stats = Stats(path=path_str, size=st.st_size, mtime=st.st_mtime)
    name = path.name
    stats.strong_name = bool(STRONG_NAME_RE.search(name))
    stats.excluded_name = bool(EXCLUDE_NAME_RE.search(name))
    stats.hard_excluded = bool(HARD_EXCLUDE_RE.search(name))
    try:
        text, pages = extract_text(path)
    except Exception as exc:  # noqa: BLE001
        stats.error = str(exc)[:120]
        return stats
    stats.pages = pages
    stats.chars = len(text)
    if not text:
        return stats

    low = text.lower()
    cpt = {c for c in CPT_RE.findall(text) if not NON_CPT.match(c)}
    cpt |= set(CPT_CAT_RE.findall(text))
    hcpcs = set(HCPCS_RE.findall(text))
    stats.cpt = len(cpt)
    stats.hcpcs = len(hcpcs)
    stats.codes = len(cpt) + len(hcpcs)
    stats.density = round(stats.codes / max(stats.chars, 1) * 1000, 3)
    blob = low + " " + name.lower().replace("_", " ").replace("-", " ")
    stats.pa_hits = sum(blob.count(t) for t in PA_TERMS)
    return stats


def decide(s: Stats, min_codes: int, min_density: float) -> tuple[bool, str]:
    """(keep, reason) for one scored file."""
    if s.error:
        return False, f"unreadable: {s.error}"
    if s.codes == 0 and s.chars < 200:
        return False, "no extractable text (scanned image?)"
    if s.hard_excluded:
        return False, "not a requirements list (statistics/report/EOC/directory)"
    if s.excluded_name and not s.strong_name:
        return False, "excluded document kind (fee schedule/manual/rate sheet)"
    if s.pa_hits == 0:
        return False, "no prior-authorization wording"

    # A code table: many distinct codes AND packed densely.
    if s.codes >= min_codes and s.density >= min_density:
        return True, (f"code table: {s.codes} distinct codes, "
                      f"density {s.density}/1k chars")
    # A short but unmistakable list (e.g. a one-page PA grid).
    if s.strong_name and s.codes >= max(8, min_codes // 3) and s.density >= 1.0:
        return True, (f"PA-list file name + {s.codes} codes, "
                      f"density {s.density}/1k chars")
    if s.codes < min_codes:
        return False, f"only {s.codes} distinct codes"
    return False, (f"codes too sparse: density {s.density}/1k chars "
                   f"({s.codes} codes in {s.chars:,} chars)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def load_cache() -> dict[str, dict]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Copy prior-authorization procedure-code lists out of "
                    "./downloaded/ into ./downloaded_PAListFiles/.")
    ap.add_argument("--src", default=str(SRC_ROOT))
    ap.add_argument("--dest", default=str(DEST_ROOT))
    ap.add_argument("--payer", default="", help="limit to one payer subfolder")
    ap.add_argument("--min-codes", type=int, default=30,
                    help="distinct procedure codes required (default 30)")
    ap.add_argument("--min-density", type=float, default=2.0,
                    help="distinct codes per 1,000 characters (default 2.0)")
    ap.add_argument("--dry-run", action="store_true",
                    help="score and report, copy nothing")
    ap.add_argument("--link", action="store_true",
                    help="hard-link instead of copying (saves disk space)")
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 1))
    ap.add_argument("--report", default="",
                    help="also write the full score table to this CSV")
    ap.add_argument("--keep-all-scores", action="store_true",
                    help="report rejected files too (with the reason)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    src_root = Path(args.src)
    dest_root = Path(args.dest)
    scan_root = src_root / args.payer if args.payer else src_root
    if not scan_root.is_dir():
        raise SystemExit(f"no such folder: {scan_root}")

    files = [p for p in sorted(scan_root.rglob("*"))
             if p.is_file() and p.suffix.lower() in DOC_EXTS
             and not p.name.startswith(".")]
    print(f"Scanning {len(files):,} document(s) under {scan_root} "
          f"with {args.workers} workers ...")

    cache = {} if args.no_cache else load_cache()
    todo, scored = [], {}
    for p in files:
        st = p.stat()
        hit = cache.get(str(p))
        if hit and hit.get("size") == st.st_size and hit.get("mtime") == st.st_mtime:
            scored[str(p)] = Stats(**hit)
        else:
            todo.append(str(p))
    print(f"  {len(scored):,} cached, {len(todo):,} to read")

    if todo:
        done = 0
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
            for stats in pool.map(score_file, todo, chunksize=8):
                scored[stats.path] = stats
                done += 1
                if done % 500 == 0:
                    print(f"    read {done:,}/{len(todo):,}")
        cache.update({k: asdict(v) for k, v in scored.items()})
        if not args.no_cache:
            CACHE_PATH.write_text(json.dumps(cache))

    rows, kept = [], []
    for path_str in sorted(scored):
        s = scored[path_str]
        keep, reason = decide(s, args.min_codes, args.min_density)
        rel = Path(path_str).relative_to(src_root)
        rows.append((rel, s, keep, reason))
        if keep:
            kept.append((rel, s, reason))

    # ---- copy -----------------------------------------------------------
    copied = 0
    if not args.dry_run:
        for rel, s, reason in kept:
            target = dest_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            source = src_root / rel
            if target.exists() and target.stat().st_size == s.size:
                continue
            if args.link:
                if target.exists():
                    target.unlink()
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copy2(source, target)
            else:
                shutil.copy2(source, target)
            copied += 1

        dest_root.mkdir(parents=True, exist_ok=True)
        with (dest_root / "_manifest.csv").open("w", newline="",
                                                encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Payer", "File", "DistinctCodes", "CPT", "HCPCS",
                        "CodesPer1kChars", "PATermHits", "Pages", "Bytes",
                        "Reason"])
            for rel, s, reason in kept:
                w.writerow([rel.parts[0], str(rel), s.codes, s.cpt, s.hcpcs,
                            s.density, s.pa_hits, s.pages, s.size, reason])

    if args.report:
        with Path(args.report).open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Payer", "File", "Keep", "DistinctCodes", "CPT",
                        "HCPCS", "CodesPer1kChars", "PATermHits", "Chars",
                        "Pages", "Reason"])
            for rel, s, keep, reason in rows:
                if keep or args.keep_all_scores:
                    w.writerow([rel.parts[0], str(rel), "yes" if keep else "no",
                                s.codes, s.cpt, s.hcpcs, s.density, s.pa_hits,
                                s.chars, s.pages, reason])
        print(f"Score report written to {args.report}")

    # ---- summary --------------------------------------------------------
    by_payer: dict[str, list[int]] = {}
    for rel, s, keep, _ in rows:
        payer = rel.parts[0]
        bucket = by_payer.setdefault(payer, [0, 0])
        bucket[0] += 1
        bucket[1] += 1 if keep else 0

    print()
    print(f"{'Payer':<20}{'scanned':>10}{'PA code lists':>16}")
    print("-" * 46)
    for payer in sorted(by_payer):
        total, hits = by_payer[payer]
        print(f"{payer:<20}{total:>10,}{hits:>16,}")
    print("-" * 46)
    print(f"{'TOTAL':<20}{len(rows):>10,}{len(kept):>16,}")
    if args.dry_run:
        print("\n(dry run - nothing copied)")
    else:
        print(f"\n{copied:,} file(s) written to {dest_root} "
              f"({'hard links' if args.link else 'copies'}); "
              f"manifest at {dest_root / '_manifest.csv'}")

    if args.verbose:
        print("\nSample of kept files:")
        for rel, s, reason in kept[:40]:
            print(f"  {rel}\n      {reason}")


if __name__ == "__main__":
    main()
