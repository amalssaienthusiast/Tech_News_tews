#!/usr/bin/env bash
# ==============================================================================
# Phase 8E: Experiment Execution Wrapper
# Location: experiments/operational_reliability/scripts/run.sh
# Usage:
#   ./run.sh --regime E1
#   ./run.sh --regime E2
#   ./run.sh --config /path/to/config.json [--duration <seconds>]
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CONFIGS_DIR="${SCRIPT_DIR}/../configs"

REGIME="E1"
CONFIG_PATH=""
DURATION_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --regime)
            REGIME="$2"
            shift 2
            ;;
        --config)
            CONFIG_PATH="$2"
            shift 2
            ;;
        --duration)
            DURATION_OVERRIDE="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--regime E1|E2|E3|E4|E5|E6|SMOKE] [--config <path>] [--duration <seconds>]"
            exit 1
            ;;
    esac
done

if [ -z "${CONFIG_PATH}" ]; then
    case "${REGIME}" in
        E1|e1) CONFIG_PATH="${CONFIGS_DIR}/e1_smoke.json" ;;
        E2|e2) CONFIG_PATH="${CONFIGS_DIR}/e2_6h.json" ;;
        E3|e3) CONFIG_PATH="${CONFIGS_DIR}/e3_24h.json" ;;
        E4|e4) CONFIG_PATH="${CONFIGS_DIR}/e4_72h.json" ;;
        E5|e5) CONFIG_PATH="${CONFIGS_DIR}/e5_7d.json" ;;
        E6|e6) CONFIG_PATH="${CONFIGS_DIR}/e6_30d.json" ;;
        SMOKE|smoke) CONFIG_PATH="${CONFIGS_DIR}/smoke_test.json" ;;
        *)
            echo "ERROR: Unsupported regime '${REGIME}'. Valid options: E1, E2, E3, E4, E5, E6, SMOKE"
            exit 1
            ;;
    esac
fi

if [ ! -f "${CONFIG_PATH}" ]; then
    echo "ERROR: Config file '${CONFIG_PATH}' not found."
    exit 1
fi

echo "=============================================================================="
echo "Phase 8E: Launching Operational Reliability Experiment"
echo "Regime: ${REGIME}"
echo "Config: ${CONFIG_PATH}"
if [ -n "${DURATION_OVERRIDE}" ]; then
    echo "Duration Override: ${DURATION_OVERRIDE}s"
fi
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "=============================================================================="

ARGS=(--config "${CONFIG_PATH}")
if [ -n "${DURATION_OVERRIDE}" ]; then
    ARGS+=(--duration "${DURATION_OVERRIDE}")
fi

cd "${REPO_ROOT}"
python3 "${REPO_ROOT}/experiments/operational_reliability/runners/experiment_runner.py" "${ARGS[@]}"
