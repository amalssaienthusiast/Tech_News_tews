"""
Test License Consistency and Metadata Integrity.
Ensures that LICENSE, pyproject.toml, and README.md do not diverge.
"""

from pathlib import Path
import tomllib
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_license_file_exists():
    license_file = REPO_ROOT / "LICENSE"
    assert license_file.is_file(), "LICENSE file must exist at repository root"
    content = license_file.read_text(encoding="utf-8")
    assert "Copyright (c) 2026 amalssaienthusiast" in content
    assert "proprietary and confidential" in content.lower()


def test_pyproject_license_metadata():
    pyproject_file = REPO_ROOT / "pyproject.toml"
    assert pyproject_file.is_file(), "pyproject.toml must exist"
    data = tomllib.loads(pyproject_file.read_text(encoding="utf-8"))
    
    project = data.get("project", {})
    license_info = project.get("license", {})
    license_text = license_info.get("text", "")
    
    assert license_text == "Proprietary", f"pyproject.toml license must be Proprietary, got: {license_text}"


def test_readme_license_consistency():
    readme_file = REPO_ROOT / "README.md"
    assert readme_file.is_file(), "README.md must exist"
    content = readme_file.read_text(encoding="utf-8")
    
    assert "MIT License" not in content, "README.md must not reference MIT License"
    assert "proprietary and confidential" in content.lower(), "README.md must reflect proprietary license"
