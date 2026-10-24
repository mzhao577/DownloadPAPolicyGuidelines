#!/bin/bash
#
# Count the number of files in each subfolder of an input folder.
#
# Usage:
#   ./count_files_per_subfolder.sh <folder>
#
# Example:
#   ./count_files_per_subfolder.sh \
#     /Users/max-imac/MaxWork/AgentWork/DownloadPAPolicyGuidelines/downloaded
#
# For every immediate subfolder it prints the count of regular files found
# anywhere inside that subfolder (recursively), then a grand total.

set -euo pipefail

folder="${1:-}"

if [[ -z "$folder" ]]; then
    echo "Usage: $0 <folder>" >&2
    exit 1
fi

if [[ ! -d "$folder" ]]; then
    echo "Error: '$folder' is not a directory." >&2
    exit 1
fi

printf '%8s  %s\n' "FILES" "SUBFOLDER"
printf '%8s  %s\n' "-----" "---------"

total=0
found_subfolder=0

# Iterate the immediate subdirectories. A trailing-slash glob matches only
# directories and handles names with spaces; nullglob makes it expand to
# nothing (instead of the literal pattern) when there are no subfolders.
shopt -s nullglob
for sub in "$folder"/*/; do
    sub="${sub%/}"          # strip the trailing slash
    found_subfolder=1
    # Count regular files anywhere under this subfolder (null-safe).
    count=$(find "$sub" -type f -print0 | tr -dc '\0' | wc -c | tr -d ' ')
    printf '%8s  %s\n' "$count" "$(basename "$sub")"
    total=$((total + count))
done

if [[ "$found_subfolder" -eq 0 ]]; then
    echo "(no subfolders found in '$folder')"
    exit 0
fi

printf '%8s  %s\n' "-----" "---------"
printf '%8s  %s\n' "$total" "TOTAL"
