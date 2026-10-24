#!/usr/bin/env python3
"""
Horizon BCBS New Jersey - prior-authorization harvest, .xlsx ONLY.

What this is
------------
The same crawl as download_Horizon_precert_policies_workharder.py (same seeds,
same keywords, same Internet-Archive fallback for Horizon's Imperva-protected
HTML pages), narrowed so that the only thing that ever lands on disk is an
Excel **.xlsx** workbook.  PDFs, Word documents and the older Excel formats
(.xls, .xlsm) are discarded.

Two independent gates
---------------------
1. URL gate - the engine's --excel-only filter is reused, but its extension
   set is narrowed from (.xlsx .xlsm .xls) to (.xlsx,), so a link has to end in
   .xlsx to survive discovery.
2. Content gate - after download the body must be a real OOXML workbook: a zip
   container that holds the xl/workbook.xml part.  The engine's own magic-byte
   check cannot tell .xlsx from .docx (both are zips), and Horizon serves
   Imperva interstitials and login pages under .xlsx names, so anything that
   is not a genuine workbook is rejected instead of saved.

Workbooks go to downloaded_NonPDF/Horizon - the same non-PDF tree the full
harvest routes them to - so a run here skips workbooks it already fetched.

    python3 download_Horizon_precert_policies_workharder_EXCELOnly.py
    python3 download_Horizon_precert_policies_workharder_EXCELOnly.py --list-only
    python3 download_Horizon_precert_policies_workharder_EXCELOnly.py -v --all
"""

import io
import sys
import threading
import zipfile

import payer_harvest as ph
from payer_harvest import log
from download_Horizon_precert_policies_workharder import SITE

XLSX_EXTS = (".xlsx",)


def is_xlsx(content: bytes) -> bool:
    """True only for a real OOXML workbook.

    An .xlsx is a zip whose part tree contains xl/workbook.xml.  Checking the
    zip directory (rather than sniffing the first bytes) is what separates a
    workbook from a .docx, a .pptx, a plain zip, and from the HTML error pages
    Horizon's bot protection returns under document URLs.
    """
    if content[:4] != b"PK\x03\x04":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False
    return "xl/workbook.xml" in names


class XlsxOnlySaver(ph.SplitSaver):
    """Splitting saver that drops anything but a genuine .xlsx workbook.

    Inherits the full harvest's PDF / non-PDF routing, so the workbooks land in
    downloaded_NonPDF/<payer> exactly as they would on a full run.
    """

    rejected = 0
    _reject_lock = threading.Lock()

    def save(self, content: bytes, label: str, url: str) -> str | None:
        if not is_xlsx(content):
            with XlsxOnlySaver._reject_lock:
                XlsxOnlySaver.rejected += 1
            log(f"  ! not a real .xlsx workbook, discarded: {url}")
            return None
        return super().save(content, label, url)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Format flags would contradict the point of this script.
    for flag in ("--pdf-only", "--word-only"):
        if flag in argv:
            log(f"error: {flag} makes no sense here - this script is .xlsx only.")
            return 2
    if "--excel-only" not in argv:
        argv.append("--excel-only")

    # Narrow --excel-only from (.xlsx .xlsm .xls) to (.xlsx,).  run() reads
    # EXCEL_EXTS by module-global lookup, so rebinding it here is enough.
    ph.EXCEL_EXTS = XLSX_EXTS

    # run() announces the PDF folder it was going to use; say where the
    # workbooks really go.
    log(f"Workbooks are saved to "
        f"{ph.nonpdf_dir(ph.DOWNLOAD_ROOT / SITE.payer)}")
    rc = ph.run_split(SITE, argv, XlsxOnlySaver)
    if XlsxOnlySaver.rejected:
        log(f"Rejected {XlsxOnlySaver.rejected} download(s) that were not "
            f".xlsx workbooks (wrong format or bot-protection page).")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
