# "Work harder" payer document harvesters

One script per payer in `listofpayer_withWebsites.csv`, built on the shared
engine in `payer_harvest.py`. Each script downloads that payer's prior
authorization / precertification material into `downloaded/<PayerName>/`.

```
payer_harvest.py                                   shared harvesting engine
download_<Payer>_precert_policies_workharder.py    one per payer (18 scripts)
run_all_workharder.sh                              run some or all of them
prune_bad_downloads.py                             delete truncated/invalid files
write_websites_csv.py                              regenerate the websites CSV
extract_PA_code_list_files.py                      pull the PA code lists into
                                                   downloaded_PAListFiles/
```

## Pulling out just the PA code lists

`extract_PA_code_list_files.py` reads every downloaded document and copies only
the ones that carry a **list of procedure codes requiring prior authorization /
precertification** into `downloaded_PAListFiles/<Payer>/`, keeping the same
subfolder structure and writing `_manifest.csv` alongside.

A file is kept only when all three hold:

1. **Codes** — enough distinct CPT (5-digit), CPT Category II/III
   (4-digit + T/F/U/M) and HCPCS Level II (letter + 4-digit) codes
   (`--min-codes`, default 30).
2. **Density** — the codes are packed like a table rather than cited in prose:
   distinct codes per 1,000 characters (`--min-density`, default 2.0). A PA
   grid scores 5–100; a clinical policy that cites a few codes scores well
   under 1.
3. **PA context** — prior authorization / precertification / preauthorization /
   authorization required / advance notification / appropriateness review
   wording in the text or the file name.

Statistics and metrics reports, EOC/ANOC, benefit summaries, directories,
newsletters and remittance guides are hard-excluded even when they are
code-dense and mention prior authorization; fee schedules, rate sheets and
provider manuals are excluded unless the file name marks them as a PA list.

```bash
python3 extract_PA_code_list_files.py --dry-run          # decide, copy nothing
python3 extract_PA_code_list_files.py                    # copy the matches
python3 extract_PA_code_list_files.py --link             # hard-link instead
python3 extract_PA_code_list_files.py --payer Cigna -v
python3 extract_PA_code_list_files.py --report scores.csv --keep-all-scores
python3 extract_PA_code_list_files.py --min-codes 50 --min-density 4
```

Text comes from PyMuPDF (falling back to poppler `pdftotext`), from the zip XML
for .xlsx/.docx and from printable-string extraction for legacy .xls/.doc.
Per-file statistics are cached in `.pa_scan_cache.json`, so re-runs with
different thresholds are instant.

## Why "work harder"

A plain `<a href>` scrape of one landing page finds a handful of documents.
Every script here attacks its payer's site from six directions and merges the
results:

1. **Raw asset regex** — every response body (HTML, JS, JSON, XHR payload) is
   scanned for document URLs, so links that exist only inside escaped JSON
   (`/docs/x.pdf`) or inside a script bundle are still found.
2. **Link extraction** — `<a href>`, `<iframe src>` and `data-*` attributes,
   keeping the human-readable link text for the file name.
3. **Bounded BFS crawl** of the payer's own site (URL-pattern, depth and page
   budget limited), which discovers the per-state / per-plan sibling pages.
4. **Sitemaps** — `robots.txt` `Sitemap:` lines, `/sitemap.xml`,
   `/sitemap-index.xml`, `/wp-sitemap.xml`; both the pages and any documents
   listed directly.
5. **CMS APIs** — the WordPress REST media library (Carelon, Johns Hopkins
   USFHP) and site-specific JSON endpoints (EviCore's Drupal JSON:API).
6. **Internet Archive (CDX)** — the index of archived documents for the
   payer's asset trees, filtered to document extensions and prior-auth
   keywords. This recovers documents that are no longer linked, that sit
   behind a JavaScript wall, or whose live URL now 403s.

Pages that answer scripted clients with a Cloudflare / edge challenge (Medica,
Dean Health, Avera) are re-fetched from their newest archived copy, which still
contains the real document links.

## Validation and naming

* Every body must match the magic bytes for its type (`%PDF`, `PK\x03\x04` for
  xlsx/docx, the OLE header for legacy xls/doc). Asset URLs with no extension
  (Sitecore Content Hub content ids, Humana's Scene7 assets) are identified
  after download from those bytes.
* Truncated captures are rejected: the Internet Archive cuts some snapshots at
  exactly 1 MiB, which yields an unreadable PDF. A PDF must carry `%%EOF` in
  its last 8 KB, a zip-based file its end-of-central-directory record. If only
  a cut-short copy exists the document is skipped and counted separately.
* De-duplication is by SHA-256 of the body, and files already in the payer
  folder are hashed at start-up, so re-running a script is idempotent.
* File names come from the link text (cleaned of "PDF, 201 KB Last Updated…"
  noise), falling back to a prettified URL stem.

## Usage

```bash
python3 download_Aetna_precert_policies_workharder.py              # everything
python3 download_Aetna_precert_policies_workharder.py --list-only -v
python3 download_Cigna_precert_policies_workharder.py --all-versions
./run_all_workharder.sh                                            # all payers
PARALLEL=4 ./run_all_workharder.sh Aetna Cigna Humana Medica
python3 prune_bad_downloads.py --delete
```

Common flags (every script accepts them):

| flag | effect |
|---|---|
| `--limit N` | stop after N documents |
| `--list-only` | enumerate candidates, download nothing |
| `--no-crawl` / `--no-sitemap` / `--no-wayback` | turn one source off |
| `--wayback-only` | Internet Archive only (useful when a site edge-blocks) |
| `--all-versions` | download every distinct archived revision of each document, dated in the file name |
| `--since YEAR` | earliest archive capture year (default per payer, 2019–2023) |
| `--max-pages N`, `--depth N` | crawl budget |
| `--workers N` | parallel downloads (default 6) |
| `--pdf-only` | ignore xlsx/docx/xls/doc |
| `--all` | keep every document found, not just prior-auth keyword matches |
| `--verbose` | chatty progress |

## Known limits

* **Anthem, Horizon, AZ Blue** publish their authoritative code-level PA
  requirements through interactive lookup tools; what is downloadable is the
  published list/policy PDFs around those tools.
* **EviCore** gates its full guideline browser behind a health-plan selector;
  the Drupal file tree and the archive sweep are the productive routes.
* **Evernorth** keeps its medical PA lists behind the authenticated provider
  portal — the public material is largely behavioral health.
* **Avera Health Plans** edge-blocks scripted clients entirely; that payer runs
  archive-first.
