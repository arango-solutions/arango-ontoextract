#!/usr/bin/env bash
# Fetch public ontology-extraction benchmark corpora into samples/corpora/external/.
#
# Minimal mode (default) downloads a small, benchmark-usable subset:
#   - Re-DocRED (dev subset, ~5 MB)
#   - WebNLG 2020 (test split, ~10 MB)
#   - CUAD (sample contracts, ~3 MB)
#   - CRAFT (two annotated articles, ~2 MB)
#   - SEC EDGAR 10-K (3 recent public filings, ~20 MB)
#
# Full mode (--full) downloads complete corpora where available (several GB total).
#
# Idempotent: re-running only fetches what's missing unless --force is passed.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTERNAL="${ROOT}/samples/corpora/external"

FULL=0
FORCE=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--full] [--force] [--help]

Options:
  --full    Download complete corpora (several GB). Default: minimal subsets.
  --force   Re-download even if target directory already exists.
  --help    Show this help and exit.

Target directory: ${EXTERNAL}
EOF
}

for arg in "$@"; do
  case "$arg" in
    --full)  FULL=1 ;;
    --force) FORCE=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; usage; exit 2 ;;
  esac
done

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: missing required tool '$1'. Install it and retry." >&2
    exit 1
  }
}

require curl
require unzip
require tar

mkdir -p "$EXTERNAL"

need_fetch() {
  # need_fetch <target_dir>
  local dir="$1"
  if [[ "$FORCE" == "1" ]]; then return 0; fi
  if [[ ! -d "$dir" ]]; then return 0; fi
  if [[ -z "$(ls -A "$dir" 2>/dev/null)" ]]; then return 0; fi
  echo "==> $(basename "$dir") already present — skipping (use --force to re-download)"
  return 1
}

download() {
  # download <url> <output_path>
  echo "    fetching: $1"
  if ! curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 -o "$2" "$1"; then
    echo "    warning: download failed for $1 — leaving target incomplete" >&2
    return 1
  fi
}

# ────────────────────────────────────────────────────────────────
# Re-DocRED — document-level relation extraction
# https://github.com/tonytan48/Re-DocRED (MIT)
# ────────────────────────────────────────────────────────────────
fetch_redocred() {
  local dir="${EXTERNAL}/redocred"
  need_fetch "$dir" || return 0
  mkdir -p "$dir"
  echo "==> Re-DocRED"
  local base="https://raw.githubusercontent.com/tonytan48/Re-DocRED/main/data"
  download "${base}/dev_revised.json" "${dir}/dev_revised.json" || true
  if [[ "$FULL" == "1" ]]; then
    download "${base}/train_revised.json" "${dir}/train_revised.json" || true
    download "${base}/test_revised.json"  "${dir}/test_revised.json"  || true
  fi
  download "https://raw.githubusercontent.com/tonytan48/Re-DocRED/main/LICENSE" "${dir}/LICENSE" || true
}

# ────────────────────────────────────────────────────────────────
# WebNLG 2020 — RDF triples ↔ natural language
# https://gitlab.com/shimorina/webnlg-dataset (CC BY-NC-SA 4.0)
# ────────────────────────────────────────────────────────────────
fetch_webnlg() {
  local dir="${EXTERNAL}/webnlg"
  need_fetch "$dir" || return 0
  mkdir -p "$dir"
  echo "==> WebNLG 2020"
  local base="https://gitlab.com/shimorina/webnlg-dataset/-/raw/master/release_v3.0/en"
  download "${base}/test/rdf-to-text-generation-test-data-with-refs-en.xml" \
           "${dir}/rdf-to-text-test.xml" || true
  if [[ "$FULL" == "1" ]]; then
    download "${base}/train/webnlg_release_v3.0_en_train.xml" "${dir}/train.xml" || true
    download "${base}/dev/webnlg_release_v3.0_en_dev.xml"     "${dir}/dev.xml"   || true
  fi
  cat > "${dir}/LICENSE.txt" <<'LIC'
WebNLG is licensed under CC BY-NC-SA 4.0.
https://creativecommons.org/licenses/by-nc-sa/4.0/
Source: https://gitlab.com/shimorina/webnlg-dataset
LIC
}

# ────────────────────────────────────────────────────────────────
# CUAD — Contract Understanding Atticus Dataset
# https://www.atticusprojectai.org/cuad (CC BY 4.0)
# ────────────────────────────────────────────────────────────────
fetch_cuad() {
  local dir="${EXTERNAL}/cuad"
  need_fetch "$dir" || return 0
  mkdir -p "$dir"
  echo "==> CUAD (sample)"
  download "https://raw.githubusercontent.com/TheAtticusProject/cuad/main/data/master_clauses.csv" \
           "${dir}/master_clauses.csv" || true
  if [[ "$FULL" == "1" ]]; then
    echo "    note: full CUAD contracts require manual download from"
    echo "          https://zenodo.org/records/4595826 (≈ 460 MB zip)"
  fi
  cat > "${dir}/LICENSE.txt" <<'LIC'
CUAD is released under Creative Commons Attribution 4.0 (CC BY 4.0).
https://creativecommons.org/licenses/by/4.0/
Source: https://github.com/TheAtticusProject/cuad
LIC
}

# ────────────────────────────────────────────────────────────────
# CRAFT — Colorado Richly Annotated Full-Text corpus
# https://github.com/UCDenver-ccp/CRAFT (CC BY 3.0 + CC BY-SA 3.0 per article)
# ────────────────────────────────────────────────────────────────
fetch_craft() {
  local dir="${EXTERNAL}/craft"
  need_fetch "$dir" || return 0
  mkdir -p "$dir"
  echo "==> CRAFT (2 sample articles)"
  # CRAFT article 11532192 (PLoS Biology) and 12585968 (PLoS Genetics).
  local ids=("11532192" "12585968")
  for id in "${ids[@]}"; do
    download "https://raw.githubusercontent.com/UCDenver-ccp/CRAFT/master/articles/txt/${id}.txt" \
             "${dir}/${id}.txt" || true
  done
  if [[ "$FULL" == "1" ]]; then
    echo "    note: full CRAFT corpus (97 articles + annotations) is ~200 MB;"
    echo "          clone https://github.com/UCDenver-ccp/CRAFT directly."
  fi
  cat > "${dir}/LICENSE.txt" <<'LIC'
CRAFT articles are licensed under CC BY 3.0 or CC BY-SA 3.0 depending on the journal.
See each article header for details.
Source: https://github.com/UCDenver-ccp/CRAFT
LIC
}

# ────────────────────────────────────────────────────────────────
# SEC EDGAR 10-K samples — public domain filings
# https://www.sec.gov/edgar (public records; respect rate limits & User-Agent)
# ────────────────────────────────────────────────────────────────
fetch_sec_edgar() {
  local dir="${EXTERNAL}/sec-edgar"
  need_fetch "$dir" || return 0
  mkdir -p "$dir"
  echo "==> SEC EDGAR 10-K samples"
  local ua="AOE-Benchmark-Fetch (arango-ontoextract) contact@example.com"
  # Three recent, stable public 10-K filings (Apple FY23, Microsoft FY24, Costco FY24).
  local filings=(
    "apple-fy23|https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
    "microsoft-fy24|https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm"
    "costco-fy24|https://www.sec.gov/Archives/edgar/data/909832/000090983224000011/cost-20240901.htm"
  )
  for entry in "${filings[@]}"; do
    local name="${entry%%|*}"
    local url="${entry#*|}"
    echo "    fetching: ${name}"
    curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 \
      -H "User-Agent: ${ua}" \
      -o "${dir}/${name}.html" "$url" || echo "    warning: ${name} failed" >&2
    sleep 1  # SEC fair-access rate limit
  done
  cat > "${dir}/LICENSE.txt" <<'LIC'
SEC filings are U.S. federal public records (public domain).
Source: https://www.sec.gov/edgar
If you redistribute, include SEC's required attribution to the original filer.
LIC
}

echo "AOE corpora fetch"
echo "  target: ${EXTERNAL}"
echo "  mode:   $([[ "$FULL" == "1" ]] && echo "full" || echo "minimal")"
echo ""

fetch_redocred
fetch_webnlg
fetch_cuad
fetch_craft
fetch_sec_edgar

echo ""
echo "Done. Inventory:"
find "$EXTERNAL" -maxdepth 2 -mindepth 1 -type d | sort | while read -r d; do
  count=$(find "$d" -maxdepth 1 -type f | wc -l | tr -d ' ')
  echo "  $(basename "$(dirname "$d")")/$(basename "$d"): ${count} files"
done
