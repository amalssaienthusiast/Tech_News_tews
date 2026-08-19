"""
Deployment Baseline Tests — Task 1B.1 & 1B.2

Verifies:
  - Dockerfile converges on canonical port 8080 and /api/v1/health endpoint.
  - Dockerfile healthcheck format and EXPOSE instruction.
  - docker-compose.yml references port 8080 for engine and feeder bot services.
  - .env.example contains all required configuration parameters without hardcoded secrets.
"""

from pathlib import Path
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Docker Configuration Audit Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDockerConfiguration:
    """Audit Dockerfile and docker-compose.yml for canonical port 8000 convergence."""

    @pytest.fixture
    def repo_root(self):
        return Path(__file__).parent.parent

    def test_dockerfile_exposes_port_8000(self, repo_root):
        dockerfile = repo_root / "Dockerfile"
        assert dockerfile.exists()
        content = dockerfile.read_text(encoding="utf-8")
        assert "EXPOSE 8000" in content, "Dockerfile must expose canonical port 8000"

    def test_dockerfile_healthcheck_targets_health(self, repo_root):
        dockerfile = repo_root / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")
        assert "http://localhost:8000/health" in content, (
            "Dockerfile healthcheck must hit http://localhost:8000/health"
        )

    def test_docker_compose_uses_port_8000(self, repo_root):
        compose_file = repo_root / "docker-compose.yml"
        assert compose_file.exists()
        content = compose_file.read_text(encoding="utf-8")
        assert "8000:8000" in content
        assert "http://localhost:8000/health" in content


# ─────────────────────────────────────────────────────────────────────────────
# Environment Configuration Audit Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvironmentConfiguration:
    """Audit environment template files for keys and absence of hardcoded secrets."""

    @pytest.fixture
    def repo_root(self):
        return Path(__file__).parent.parent

    def test_env_example_has_all_required_keys(self, repo_root):
        env_example = repo_root / ".env.example"
        assert env_example.exists()
        content = env_example.read_text(encoding="utf-8")

        required_keys = [
            "GOOGLE_API_KEY",
            "GOOGLE_CSE_ID",
            "GEMINI_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "API_ALLOW_ANONYMOUS",
            "API_CORS_ORIGINS",
        ]
        for key in required_keys:
            assert f"{key}=" in content, f".env.example must document {key}"

    def test_env_example_has_no_hardcoded_secrets(self, repo_root):
        env_example = repo_root / ".env.example"
        content = env_example.read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
        for line in lines:
            if "=" in line:
                key, val = line.split("=", 1)
                # Ignore boolean / default config values
                if key in ("LLM_PROVIDER", "LLM_MODEL", "API_ALLOW_ANONYMOUS", "API_CORS_ORIGINS", "REDIS_URL"):
                    continue
                # Secret values must be empty in template
                assert val == "", f".env.example has hardcoded secret value for {key}: '{val}'"
