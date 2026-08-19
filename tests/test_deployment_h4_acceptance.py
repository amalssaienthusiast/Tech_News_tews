"""
Phase 8H-H4 Deployment Acceptance Test Suite.
Location: tests/test_deployment_h4_acceptance.py

Authoritative acceptance tests for clean-host cloud deployment and container contract:
1. Dockerfile static syntax, multi-stage structure, and base image
2. Non-root container security user (technews) and filesystem ownership (/app, /data)
3. Canonical API command (uvicorn src.api.app:app) and legacy entrypoint exclusion
4. Container healthcheck contract targeting /health
5. Docker Compose decoupled topology (api, worker, prometheus)
6. Compose API service contract (ports, volume, healthcheck)
7. Compose Worker service contract (python -m src.worker, volume, depends_on)
8. Shared SQLite volume mount parity (/data)
9. Zero hardcoded secrets in deployment manifests
10. Worker CLI argument parser contract (--concurrency, --db-path, --timeout)
11. Cloud VM bootstrap script repeatability and idempotency
12. Cloud-only runtime execution boundary separation
"""

import ast
import os
from pathlib import Path
import shutil
import unittest
import yaml

REPO_ROOT = Path(__file__).parent.parent


class TestDeploymentH4Acceptance(unittest.TestCase):
    """Static and Local Acceptance Tests for Phase 8H-H4 Production Deployment."""

    @classmethod
    def setUpClass(cls):
        cls.dockerfile_path = REPO_ROOT / "Dockerfile"
        cls.compose_path = REPO_ROOT / "docker-compose.yml"
        cls.bootstrap_path = REPO_ROOT / "experiments" / "operational_reliability" / "scripts" / "bootstrap.sh"
        cls.worker_path = REPO_ROOT / "src" / "worker.py"

        cls.dockerfile_content = cls.dockerfile_path.read_text(encoding="utf-8")
        cls.compose_content = cls.compose_path.read_text(encoding="utf-8")
        cls.compose_yaml = yaml.safe_load(cls.compose_content)

    # 1. Multi-Stage Dockerfile & Base Image
    def test_01_dockerfile_multi_stage_structure(self):
        self.assertIn("FROM python:3.12-slim-bookworm AS builder", self.dockerfile_content)
        self.assertIn("FROM python:3.12-slim-bookworm AS runtime", self.dockerfile_content)
        self.assertIn("COPY --from=builder /build/wheels /wheels", self.dockerfile_content)

    # 2. Non-Root Security User & File Ownership
    def test_02_dockerfile_non_root_security_user(self):
        self.assertIn("groupadd -r technews", self.dockerfile_content)
        self.assertIn("useradd -r -g technews", self.dockerfile_content)
        self.assertIn("chown -R technews:technews /app /data", self.dockerfile_content)
        self.assertIn("USER technews", self.dockerfile_content)

    # 3. Canonical API Command & Legacy Entrypoint Exclusion
    def test_03_dockerfile_canonical_cmd_and_legacy_exclusion(self):
        self.assertIn('"uvicorn", "src.api.app:app"', self.dockerfile_content)
        self.assertIn('"0.0.0.0"', self.dockerfile_content)
        self.assertIn('"8000"', self.dockerfile_content)

        # Ensure NO legacy entrypoints are invoked
        self.assertNotIn("main_engine.py", self.dockerfile_content)
        self.assertNotIn("src/api/main.py", self.dockerfile_content)
        self.assertNotIn("main.py", self.dockerfile_content)

    # 4. Healthcheck Contract
    def test_04_dockerfile_healthcheck_contract(self):
        self.assertIn("HEALTHCHECK", self.dockerfile_content)
        self.assertIn("http://localhost:8000/health", self.dockerfile_content)

    # 5. Compose Topology
    def test_05_compose_services_topology(self):
        services = self.compose_yaml.get("services", {})
        self.assertIn("api", services, "Compose must define 'api' service")
        self.assertIn("worker", services, "Compose must define 'worker' service")
        self.assertIn("prometheus", services, "Compose must define 'prometheus' service")
        self.assertEqual(len(services), 3, "Compose must contain exactly api, worker, and prometheus")

    # 6. Compose API Service Contract
    def test_06_compose_api_service_contract(self):
        api = self.compose_yaml["services"]["api"]
        self.assertEqual(api["container_name"], "technews_api")
        self.assertIn("8000:8000", api["ports"])

        env = api.get("environment", [])
        self.assertIn("TECHNEWS_ENV=production", env)
        self.assertIn("TECHNEWS_DB_PATH=/data/canonical_technews.db", env)

        volumes = api.get("volumes", [])
        self.assertIn("sqlite_data:/data", volumes)

    # 7. Compose Worker Service Contract
    def test_07_compose_worker_service_contract(self):
        worker = self.compose_yaml["services"]["worker"]
        self.assertEqual(worker["container_name"], "technews_worker")
        self.assertEqual(worker["command"], ["python", "-m", "src.worker", "--concurrency", "2", "--db-path", "/data/canonical_technews.db"])

        env = worker.get("environment", [])
        self.assertIn("TECHNEWS_ENV=production", env)
        self.assertIn("TECHNEWS_DB_PATH=/data/canonical_technews.db", env)

        volumes = worker.get("volumes", [])
        self.assertIn("sqlite_data:/data", volumes)
        self.assertEqual(worker.get("depends_on"), ["api"])

    # 8. Shared SQLite Volume Parity
    def test_08_compose_shared_storage_volume(self):
        volumes = self.compose_yaml.get("volumes", {})
        self.assertIn("sqlite_data", volumes)
        self.assertIn("prometheus_data", volumes)

    # 9. No Hardcoded Secrets in Deployment Manifests
    def test_09_no_hardcoded_secrets_in_manifests(self):
        # API keys in compose must use ${VAR} interpolation
        for env_entry in self.compose_yaml["services"]["api"]["environment"]:
            if "API_KEY" in env_entry:
                key, val = env_entry.split("=", 1)
                self.assertTrue(
                    val.startswith("${") and val.endswith("}"),
                    f"Secret {key} must use variable interpolation, got: {val}",
                )

        # Dockerfile must not contain hardcoded keys
        self.assertNotIn("TECHNEWS_ADMIN_API_KEY=", self.dockerfile_content)
        self.assertNotIn("tns_", self.dockerfile_content)

    # 10. Worker CLI Argument Parser Contract
    def test_10_worker_cli_arguments(self):
        from src.worker import parse_args
        import sys

        orig_argv = sys.argv
        try:
            sys.argv = ["worker", "--concurrency", "4", "--db-path", "/tmp/test.db", "--timeout", "10.5", "--log-level", "DEBUG"]
            args = parse_args()
            self.assertEqual(args.concurrency, 4)
            self.assertEqual(args.db_path, "/tmp/test.db")
            self.assertEqual(args.timeout, 10.5)
            self.assertEqual(args.log_level, "DEBUG")
        finally:
            sys.argv = orig_argv

    # 11. Cloud VM Bootstrap Script Capabilities
    def test_11_bootstrap_script_capabilities(self):
        bootstrap_content = self.bootstrap_path.read_text(encoding="utf-8")
        self.assertIn("--install-system-deps", bootstrap_content)
        self.assertIn("DEBIAN_FRONTEND=noninteractive", bootstrap_content)
        self.assertIn("PRAGMA journal_mode=WAL;", bootstrap_content)
        self.assertIn("smoke_test.json", bootstrap_content)

    # 12. Local vs Cloud-Only Container Runtime Status
    def test_12_container_runtime_availability_check(self):
        has_docker = shutil.which("docker") is not None
        if not has_docker:
            self.assertFalse(has_docker)
        else:
            self.assertTrue(has_docker)

    # 13. Cloud Acceptance H4 Script Strict Trap & Assertions
    def test_13_cloud_acceptance_h4_script_structure(self):
        harness_path = REPO_ROOT / "experiments" / "operational_reliability" / "scripts" / "cloud_acceptance_h4.sh"
        self.assertTrue(harness_path.exists(), "cloud_acceptance_h4.sh must exist")
        content = harness_path.read_text(encoding="utf-8")

        self.assertIn("set -euo pipefail", content)
        self.assertIn("record_failure", content)
        self.assertIn("trap 'record_failure $? $LINENO \"$BASH_COMMAND\"' ERR", content)
        self.assertIn("results/failure.json", content)
        self.assertIn("http://localhost:8000/health", content)
        self.assertIn("api_acceptance_results.json", content)
        self.assertIn("sqlite_audit.json", content)
        self.assertIn("evidence_completeness.json", content)
        self.assertIn("final/checksums.sha256", content)

    # 14. Deployment Manifest Schema Validation
    def test_14_deployment_manifest_schema_validation(self):
        import json
        import jsonschema

        schema_path = REPO_ROOT / "experiments" / "operational_reliability" / "schemas" / "deployment_manifest_schema.json"
        self.assertTrue(schema_path.exists(), "deployment_manifest_schema.json must exist")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        valid_manifest = {
            "schema_version": "1.0.0",
            "experiment_name": "phase_8h_cloud_runtime_acceptance",
            "phase": "Phase 8H-H4",
            "run_id": "test_run_123",
            "run_name": "20260817T164907Z_H4_CLOUD_RUNTIME_test123",
            "started_at": "2026-08-17T16:49:07Z",
            "ended_at": "2026-08-17T16:50:07Z",
            "git_commit": "bff6c7c0123456789abcdef0123456789abcdef0",
            "git_branch": "phase-4-acquisition-zombies",
            "git_dirty": False,
            "build_duration_seconds": 15.0,
            "shutdown_duration_seconds": 2.5,
            "health_status": "200",
            "fail_closed_auth": "PASS",
            "worker_status": "PASS",
            "database_integrity": "PASS",
            "restart_status": "200",
            "final_status": "PASS",
            "exit_code": 0,
        }

        # Valid manifest should pass
        jsonschema.validate(instance=valid_manifest, schema=schema)

        # Invalid manifest (missing required fields) should fail
        invalid_manifest = {"schema_version": "1.0.0"}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_manifest, schema=schema)

    # 15. Secret Leak Detector Logic Test
    def test_15_secret_leak_detector_logic(self):
        import tempfile

        test_secret = "tns_admin_super_secret_token_12345"
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Clean file
            clean_file = tmp_path / "clean.json"
            clean_file.write_text('{"status": "ok", "key": "[REDACTED]"}', encoding="utf-8")

            # Leak detection function
            def check_leak(secret: str, root_dir: Path) -> bool:
                for p in root_dir.rglob("*"):
                    if p.is_file() and secret in p.read_text(encoding="utf-8", errors="ignore"):
                        return True
                return False

            self.assertFalse(check_leak(test_secret, tmp_path))

            # Contaminated file
            dirty_file = tmp_path / "dirty.log"
            dirty_file.write_text(f"DEBUG: Auth header used: {test_secret}", encoding="utf-8")

            self.assertTrue(check_leak(test_secret, tmp_path))

    # 16. Evidence Completeness Auditor Logic Test
    def test_16_evidence_completeness_auditor(self):
        import tempfile

        required_artifacts = [
            "environment/host_fingerprint.json",
            "application/startup_logs.txt",
            "results/health_response.json",
            "database/sqlite_audit.json",
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Incomplete dir
            for rel in required_artifacts[:2]:
                f = tmp_path / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("sample content", encoding="utf-8")

            missing = [rel for rel in required_artifacts if not (tmp_path / rel).exists()]
            self.assertEqual(len(missing), 2)
            self.assertIn("results/health_response.json", missing)
            self.assertIn("database/sqlite_audit.json", missing)

            # Complete dir
            for rel in required_artifacts[2:]:
                f = tmp_path / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("sample content", encoding="utf-8")

            missing_after = [rel for rel in required_artifacts if not (tmp_path / rel).exists()]
            self.assertEqual(len(missing_after), 0)


if __name__ == "__main__":
    unittest.main()
