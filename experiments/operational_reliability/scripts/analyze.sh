#!/usr/bin/env bash
# ==============================================================================
# Phase 8E: Offline Experiment Analysis Wrapper
# Location: experiments/operational_reliability/scripts/analyze.sh
# Usage:
#   ./analyze.sh --run-dir /path/to/runs/<RUN_ID>
#   ./analyze.sh --latest
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RUNS_DIR="${SCRIPT_DIR}/../runs"

RUN_DIR=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --run-dir)
            RUN_DIR="$2"
            shift 2
            ;;
        --latest)
            RUN_DIR=$(find "${RUNS_DIR}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)
            shift 1
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--run-dir <path>] [--latest]"
            exit 1
            ;;
    esac
done

if [ -z "${RUN_DIR}" ]; then
    RUN_DIR=$(find "${RUNS_DIR}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)
fi

if [ -z "${RUN_DIR}" ] || [ ! -d "${RUN_DIR}" ]; then
    echo "ERROR: No experiment run directory found in ${RUNS_DIR}."
    exit 1
fi

echo "=============================================================================="
echo "Phase 8E: Analyzing Experiment Run Directory"
echo "Target Run: ${RUN_DIR}"
echo "=============================================================================="

cd "${REPO_ROOT}"
python3 "${REPO_ROOT}/experiments/operational_reliability/analysis/run_analyzer.py" \
    --run-dir "${RUN_DIR}" \
    --verify-checksums
