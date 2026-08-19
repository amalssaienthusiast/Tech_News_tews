#!/usr/bin/env bash
# ==============================================================================
# Phase 8H-H4: Clean Cloud VM Bootstrap Script for Operational Reliability Testing
# Location: experiments/operational_reliability/scripts/bootstrap.sh
# Supported Hosts: Ubuntu 22.04 / 24.04 LTS, Debian 11 / 12, macOS
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

INSTALL_SYSTEM_DEPS=false
for arg in "$@"; do
    case "${arg}" in
        --install-system-deps|--provision)
            INSTALL_SYSTEM_DEPS=true
            ;;
    esac
done

echo "=============================================================================="
echo "Phase 8H-H4: Provisioning Clean Cloud VM Host for Operational Reliability"
echo "Repository Root: ${REPO_ROOT}"
echo "Timestamp (UTC): $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "=============================================================================="

# 1. System Package Provisioning (if apt-get available and root/sudo or requested)
if [ "${INSTALL_SYSTEM_DEPS}" = true ] || ([ "$(id -u)" -eq 0 ] && command -v apt-get &> /dev/null); then
    echo "[1/8] Provisioning OS-level system dependencies via apt-get..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends \
        git \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        sqlite3 \
        libsqlite3-dev \
        curl \
        ca-certificates \
        procps
    
    # Optional Docker installation if missing
    if ! command -v docker &> /dev/null; then
        echo "  - Installing Docker engine and compose plugin..."
        apt-get install -y --no-install-recommends docker.io docker-compose-v2 || true
    fi
else
    echo "[1/8] Checking core system utilities..."
    for cmd in git python3 sqlite3; do
        if ! command -v "${cmd}" &> /dev/null; then
            echo "ERROR: Required command '${cmd}' is not installed."
            echo "Hint: Re-run with root/sudo or pass --install-system-deps to install system packages."
            exit 1
        fi
        echo "  - ${cmd}: $(command -v "${cmd}")"
    done
fi

# 2. Check Python Version (>= 3.11 required)
echo "[2/8] Checking Python version..."
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
echo "  - Detected Python: ${PY_VER}"

# 3. Check Container Toolchain Status
echo "[3/8] Inspecting container toolchain (Docker / Compose)..."
if command -v docker &> /dev/null; then
    echo "  - Docker: $(docker --version 2>/dev/null || echo 'installed')"
    if docker compose version &> /dev/null; then
        echo "  - Docker Compose: $(docker compose version 2>/dev/null)"
    elif command -v docker-compose &> /dev/null; then
        echo "  - Docker Compose (standalone): $(docker-compose --version 2>/dev/null)"
    fi
else
    echo "  - Docker: NOT INSTALLED (Static validation will be enforced; runtime container testing requires cloud host)"
fi

# 4. Check Disk Space (>= 10 GB recommended for soak logs)
echo "[4/8] Checking available disk space..."
if command -v df &> /dev/null; then
    df -h "${REPO_ROOT}"
fi

# 5. Virtual Environment & Python Dependencies
echo "[5/8] Installing and verifying Python dependencies..."
cd "${REPO_ROOT}"
if [ -f "pyproject.toml" ]; then
    python3 -m pip install --upgrade pip setuptools wheel
    python3 -m pip install -e ".[dev]" || python3 -m pip install -e .
fi

# Optional Playwright headless browser check
if python3 -c "import playwright" &> /dev/null; then
    echo "  - Installing Playwright Chromium browser binaries..."
    python3 -m playwright install chromium || true
fi

# 6. Verify SQLite Version & WAL Capability
echo "[6/8] Verifying SQLite WAL capabilities..."
python3 -c "
import sqlite3, tempfile, os
with tempfile.NamedTemporaryFile(suffix='.db') as f:
    conn = sqlite3.connect(f.name)
    cur = conn.cursor()
    cur.execute('PRAGMA journal_mode=WAL;')
    mode = cur.fetchone()[0]
    print(f'  - SQLite Version: {sqlite3.sqlite_version}, Journal Mode: {mode}')
    assert mode.upper() == 'WAL', 'WAL mode initialization failed'
"

# 7. Verify Git State
echo "[7/8] Verifying Git repository state..."
GIT_COMMIT=$(git rev-parse HEAD || echo "unknown")
GIT_DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
echo "  - HEAD Commit: ${GIT_COMMIT}"
echo "  - Uncommitted Changes: ${GIT_DIRTY}"

# 8. Run Framework Self-Test
echo "[8/8] Executing framework self-test..."
python3 "${REPO_ROOT}/experiments/operational_reliability/runners/experiment_runner.py" \
    --config "${REPO_ROOT}/experiments/operational_reliability/configs/smoke_test.json" \
    --duration 5.0 \
    --smoke-test

echo "=============================================================================="
echo "🟢 Cloud Host Successfully Bootstrapped and Verified!"
echo "To launch an experiment, run:"
echo "  ./experiments/operational_reliability/scripts/run.sh --regime E1"
echo "=============================================================================="
