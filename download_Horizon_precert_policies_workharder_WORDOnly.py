#!/usr/bin/env python3
"""
Horizon BCBS New Jersey - prior-authorization harvest, Word documents ONLY.

What this is
------------
The same crawl as download_Horizon_precert_policies_workharder.py (same seeds,
same keywords, same Internet-Archive fallback for Horizon's Imperva-protected
HTML pages), narrowed so that the only thing that ever lands on disk is a Word
document.  PDFs and Excel workbooks are discarded.

    .docx   Word 2007+ (OOXML)
    .doc    legacy Word (OLE compound file)
    .rtf    only with --include-rtf (RTF is Word-adjacent, not Word itself)

Two independent gates
---------------------
1. URL gate - the engine's --word-only filter is reused, but its extension set
   is narrowed from (.docx .doc .rtf) to (.docx .doc), so a link has to end in
   a Word extension to survive discovery.
2. Content gate - after download the body must really be a Word document: an
   OOXML zip holding word/document.xml, or an OLE compound file carrying a
   WordDocument stream.  The engine's own magic-byte check cannot tell .docx
   from .xlsx (both are zips) nor .doc from .xls (both are OLE), and Horizon
   serves Imperva interstitials and login pages under document names, so
   anything that is not a genuine Word file is rejected instead of saved.

A .doc URL that serves a modern .docx after a CMS migration is accepted - it is
still a Word document.  A .doc URL that serves a workbook is not.

Documents go to downloaded_NonPDF/Horizon - the same non-PDF tree the full
harvest routes them to - so a run here skips documents it already fetched.

    python3 download_Horizon_precert_policies_workharder_WORDOnly.py
    python3 download_Horizon_precert_policies_workharder_WORDOnly.py --list-only
    python3 download_Horizon_precert_policies_workharder_WORDOnly.py --include-rtf -v
"""

import io
import sys
import threading
import zipfile

import payer_harvest as ph
from payer_harvest import log
from download_Horizon_precert_policies_workharder import SITE

WORD_EXTS = (".docx", ".doc")
WORD_EXTS_WITH_RTF = (".docx", ".doc", ".rtf")

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# OLE directory entry names are stored UTF-16LE, so the stream that identifies
# a legacy Word file appears in the raw bytes in this encoding.
OLE_WORD_STREAM = "WordDocument".encode("utf-16-le")


def word_format(content: bytes) -> str:
    """The Word format this body really is ('' when it is not a Word file).

    Returns '.docx', '.doc' or '.rtf'.  Looking inside the container is what
    separates a Word file from a workbook: .docx and .xlsx are both zips and
    .doc and .xls are both OLE compound files, so the leading magic bytes alone
    cannot tell them apart.
    """
    if content[:5] == b"{\\rtf":
        return ".rtf"
    if content[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = zf.namelist()
        except (zipfile.BadZipFile, OSError, ValueError):
            return ""
        return ".docx" if "word/document.xml" in names else ""
    if content[:8] == OLE_MAGIC:
        return ".doc" if OLE_WORD_STREAM in content else ""
    return ""


class WordOnlySaver(ph.SplitSaver):
    """Splitting saver that drops anything but a genuine Word document.

    Inherits the full harvest's PDF / non-PDF routing, so the documents land in
    downloaded_NonPDF/<payer> exactly as they would on a full run.
    """

    allowed: tuple[str, ...] = (".docx", ".doc")
    rejected = 0
    _reject_lock = threading.Lock()

    def save(self, content: bytes, label: str, url: str) -> str | None:
        fmt = word_format(content)
        if fmt not in WordOnlySaver.allowed:
            with WordOnlySaver._reject_lock:
                WordOnlySaver.rejected += 1
            log(f"  ! not a Word document ({fmt or 'unrecognised'}), "
                f"discarded: {url}")
            return None
        return super().save(content, label, url)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Format flags would contradict the point of this script.
    for flag in ("--pdf-only", "--excel-only"):
        if flag in argv:
            log(f"error: {flag} makes no sense here - this script is Word only.")
            return 2

    # --include-rtf is ours, not the engine's; take it out before parsing.
    include_rtf = "--include-rtf" in argv
    argv = [a for a in argv if a != "--include-rtf"]
    if "--word-only" not in argv:
        argv.append("--word-only")

    exts = WORD_EXTS_WITH_RTF if include_rtf else WORD_EXTS

    # Narrow --word-only to the chosen set.  run() reads WORD_EXTS by
    # module-global lookup, so rebinding it here is enough.
    ph.WORD_EXTS = exts
    WordOnlySaver.allowed = exts

    log(f"Keeping only: {' '.join(exts)}")
    # run() announces the PDF folder it was going to use; say where the Word
    # documents really go.
    log(f"Documents are saved to "
        f"{ph.nonpdf_dir(ph.DOWNLOAD_ROOT / SITE.payer)}")
    rc = ph.run_split(SITE, argv, WordOnlySaver)
    if WordOnlySaver.rejected:
        log(f"Rejected {WordOnlySaver.rejected} download(s) that were not Word "
            f"documents (wrong format or bot-protection page).")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
