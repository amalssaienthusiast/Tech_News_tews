"""
Environment Fingerprinting Module for Operational Reliability Benchmarks.
Location: experiments/operational_reliability/runners/environment_fingerprint.py

Collects comprehensive OS, hardware, Python runtime, SQLite, and Git metadata
to guarantee full scientific reproducibility of long-running soak experiments.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, UTC
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional

import psutil


@dataclass(frozen=True)
class EnvironmentFingerprint:
    hostname: str
    platform: str
    os_release: str
    kernel: str
    python_version: str
    python_executable: str
    sqlite_version: str
    sqlite_compile_options: List[str]
    cpu_model: str
    cpu_cores_physical: int
    cpu_cores_logical: int
    ram_total_mb: float
    swap_total_mb: float
    disk_total_gb: float
    disk_free_gb: float
    filesystem_type: str
    docker_version: Optional[str]
    git_commit: str
    git_dirty: bool
    collected_at_utc: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_git_info(repo_root: Path) -> Dict[str, Any]:
    """Extract exact Git commit and clean/dirty status."""
    try:
        commit_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        commit = commit_res.stdout.strip()
    except Exception:
        commit = "unknown"

    try:
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        dirty_lines = [l for l in status_res.stdout.strip().splitlines() if l and not l.endswith(".gitkeep")]
        git_dirty = len(dirty_lines) > 0
    except Exception:
        git_dirty = False

    return {"commit": commit, "dirty": git_dirty}


def get_cpu_model() -> str:
    """Retrieve detailed CPU brand/model name cross-platform."""
    if platform.system() == "Darwin":
        try:
            res = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
    elif platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return platform.processor() or "Unknown CPU"


def get_sqlite_compile_options() -> List[str]:
    """Retrieve SQLite compile-time options."""
    try:
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("PRAGMA compile_options;")
        options = [row[0] for row in cursor.fetchall()]
        conn.close()
        return options
    except Exception:
        return []


def get_docker_version() -> Optional[str]:
    """Retrieve Docker CLI version if installed."""
    if not shutil.which("docker"):
        return None
    try:
        res = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=3)
        return res.stdout.strip() if res.returncode == 0 else None
    except Exception:
        return None


def collect_environment_fingerprint(repo_root: Path) -> EnvironmentFingerprint:
    """Collect full hardware, OS, runtime, and Git metadata."""
    git_info = get_git_info(repo_root)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(str(repo_root))

    fs_type = "unknown"
    try:
        for part in psutil.disk_partitions():
            if str(repo_root).startswith(part.mountpoint):
                fs_type = part.fstype
                break
    except Exception:
        pass

    return EnvironmentFingerprint(
        hostname=platform.node(),
        platform=platform.platform(),
        os_release=f"{platform.system()} {platform.release()}",
        kernel=platform.version(),
        python_version=platform.python_version(),
        python_executable=sys.executable,
        sqlite_version=sqlite3.sqlite_version,
        sqlite_compile_options=get_sqlite_compile_options(),
        cpu_model=get_cpu_model(),
        cpu_cores_physical=psutil.cpu_count(logical=False) or 1,
        cpu_cores_logical=psutil.cpu_count(logical=True) or 1,
        ram_total_mb=round(mem.total / (1024 * 1024), 2),
        swap_total_mb=round(swap.total / (1024 * 1024), 2),
        disk_total_gb=round(disk.total / (1024 * 1024 * 1024), 2),
        disk_free_gb=round(disk.free / (1024 * 1024 * 1024), 2),
        filesystem_type=fs_type,
        docker_version=get_docker_version(),
        git_commit=git_info["commit"],
        git_dirty=git_info["dirty"],
        collected_at_utc=datetime.now(UTC).isoformat(),
    )


def dump_environment_artifacts(fingerprint: EnvironmentFingerprint, env_dir: Path, repo_root: Path) -> None:
    """Write human-readable raw environment dump files to the environment/ subfolder."""
    env_dir.mkdir(parents=True, exist_ok=True)

    # 1. git.txt
    try:
        git_log = subprocess.run(["git", "log", "-n", "1"], cwd=str(repo_root), capture_output=True, text=True).stdout
        git_status = subprocess.run(["git", "status"], cwd=str(repo_root), capture_output=True, text=True).stdout
        git_content = f"Commit: {fingerprint.git_commit}\nDirty: {fingerprint.git_dirty}\n\n=== Git Log ===\n{git_log}\n=== Git Status ===\n{git_status}\n"
    except Exception as e:
        git_content = f"Error capturing Git details: {e}\n"
    (env_dir / "git.txt").write_text(git_content, encoding="utf-8")

    # 2. python.txt
    py_content = (
        f"Python Version: {fingerprint.python_version}\n"
        f"Executable: {fingerprint.python_executable}\n"
        f"Compiler: {platform.python_compiler()}\n"
        f"Build: {platform.python_build()}\n"
        f"Implementation: {platform.python_implementation()}\n"
    )
    (env_dir / "python.txt").write_text(py_content, encoding="utf-8")

    # 3. pip-freeze.txt
    try:
        pip_res = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True)
        pip_content = pip_res.stdout if pip_res.returncode == 0 else f"pip freeze failed: {pip_res.stderr}"
    except Exception as e:
        pip_content = f"pip freeze error: {e}\n"
    (env_dir / "pip-freeze.txt").write_text(pip_content, encoding="utf-8")

    # 4. os-release.txt
    os_content = f"Platform: {fingerprint.platform}\nOS Release: {fingerprint.os_release}\n"
    if os.path.exists("/etc/os-release"):
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as f:
                os_content += f"\n=== /etc/os-release ===\n{f.read()}"
        except Exception:
            pass
    (env_dir / "os-release.txt").write_text(os_content, encoding="utf-8")

    # 5. kernel.txt
    (env_dir / "kernel.txt").write_text(f"Kernel Version: {fingerprint.kernel}\nSystem: {platform.uname()}\n", encoding="utf-8")

    # 6. cpu.txt
    cpu_content = (
        f"Model: {fingerprint.cpu_model}\n"
        f"Physical Cores: {fingerprint.cpu_cores_physical}\n"
        f"Logical Cores: {fingerprint.cpu_cores_logical}\n"
        f"Architecture: {platform.machine()}\n"
    )
    (env_dir / "cpu.txt").write_text(cpu_content, encoding="utf-8")

    # 7. memory.txt
    mem_content = (
        f"Total RAM: {fingerprint.ram_total_mb} MB\n"
        f"Total Swap: {fingerprint.swap_total_mb} MB\n"
    )
    (env_dir / "memory.txt").write_text(mem_content, encoding="utf-8")

    # 8. disk.txt
    disk_content = (
        f"Total Space: {fingerprint.disk_total_gb} GB\n"
        f"Free Space: {fingerprint.disk_free_gb} GB\n"
        f"Filesystem: {fingerprint.filesystem_type}\n"
    )
    (env_dir / "disk.txt").write_text(disk_content, encoding="utf-8")

    # 9. sqlite.txt
    sqlite_content = (
        f"SQLite Version: {fingerprint.sqlite_version}\n"
        f"Compile Options:\n" + "\n".join(f"- {opt}" for opt in fingerprint.sqlite_compile_options) + "\n"
    )
    (env_dir / "sqlite.txt").write_text(sqlite_content, encoding="utf-8")

    # 10. docker.txt
    docker_content = f"Docker Version: {fingerprint.docker_version or 'Not Installed/Not Available'}\n"
    (env_dir / "docker.txt").write_text(docker_content, encoding="utf-8")
