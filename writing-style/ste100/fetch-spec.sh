#!/bin/bash
# Download the official ASD-STE100 Issue 9 PDF and extract its text for bin/ste-check.
# The spec is free of charge but ASD does not permit redistribution, so spec/ is gitignored.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p spec
URL="https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/126 Safari/537.36"
curl -fL -A "$UA" -o spec/ASD-STE100_ISSUE9.pdf "$URL"
pdftotext -layout spec/ASD-STE100_ISSUE9.pdf spec/ste100.txt
pages=$(pdfinfo spec/ASD-STE100_ISSUE9.pdf | awk '/^Pages:/ {print $2}')
echo "spec/ASD-STE100_ISSUE9.pdf: $pages pages (Issue 9 has 434)"
