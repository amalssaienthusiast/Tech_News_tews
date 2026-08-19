"""
Architecture Boundary Tests for Tech News Scrapper.
Location: tests/test_architecture_boundaries.py

Enforces strict Layer Boundary Rules via static AST inspection:
  1. src/domain/ must have ZERO imports from outer layers (engine, api, zombies, bypass, db_storage, gui_qt, etc.)
  2. src/domain/ must have ZERO third-party network or database imports (e.g., aiohttp, requests, fastapi, aiosqlite)
  3. src/engine/ must have ZERO imports from gui_qt
  4. src/core/ must have ZERO imports from delivery surfaces (api, gui_qt, telegram_feeder_bot)
"""

import ast
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent


class TestDomainLayerIsolation:
    """Verifies that src/domain/ is pure and has zero external or outer-layer dependencies."""

    @pytest.fixture
    def domain_files(self):
        domain_dir = REPO_ROOT / "src" / "domain"
        assert domain_dir.exists(), "src/domain directory must exist"
        return list(domain_dir.glob("*.py"))

    def test_domain_has_no_outer_layer_imports(self, domain_files):
        forbidden_prefixes = (
            "src.engine",
            "src.api",
            "src.zombies",
            "src.bypass",
            "src.db_storage",
            "src.crawler",
            "src.realtime",
            "src.intelligence",
            "src.resilience",
            "gui_qt",
            "telegram_feeder_bot",
            "main_engine",
        )

        for py_file in domain_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in forbidden_prefixes:
                            assert not alias.name.startswith(forbidden), (
                                f"{py_file.name} violates domain purity by importing '{alias.name}'"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for forbidden in forbidden_prefixes:
                            assert not node.module.startswith(forbidden), (
                                f"{py_file.name} violates domain purity by importing from '{node.module}'"
                            )

    def test_domain_has_no_network_or_storage_third_party_imports(self, domain_files):
        forbidden_third_party = (
            "aiohttp",
            "requests",
            "httpx",
            "fastapi",
            "starlette",
            "uvicorn",
            "aiosqlite",
            "asyncpg",
            "sqlite3",
            "playwright",
            "primp",
            "redis",
            "celery",
            "bs4",
            "lxml",
        )

        for py_file in domain_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in forbidden_third_party, (
                            f"{py_file.name} imports forbidden third-party library '{alias.name}'"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        root_mod = node.module.split(".")[0]
                        assert root_mod not in forbidden_third_party, (
                            f"{py_file.name} imports from forbidden third-party library '{node.module}'"
                        )


class TestEngineAndCoreBoundaries:
    """Verifies that engine and core modules do not import UI or delivery surfaces."""

    def test_engine_has_zero_api_imports(self):
        """Verify that src/engine/ has ZERO imports from src.api (absolute or relative)."""
        engine_dir = REPO_ROOT / "src" / "engine"
        if not engine_dir.exists():
            return
        for py_file in engine_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("src.api"), (
                            f"{py_file.name} violates Layer 4 boundary by importing '{alias.name}'"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        assert not node.module.startswith("src.api"), (
                            f"{py_file.name} violates Layer 4 boundary by importing from '{node.module}'"
                        )
                        # Check relative imports like from ..api.routes import ...
                        if node.level > 0 and "api" in node.module.split("."):
                            assert False, (
                                f"{py_file.name} violates Layer 4 boundary by relative import from '{node.module}'"
                            )

    def test_engine_has_no_gui_qt_imports(self):
        engine_dir = REPO_ROOT / "src" / "engine"
        if not engine_dir.exists():
            return
        for py_file in engine_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("gui_qt"), f"{py_file.name} imports '{alias.name}'"
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        assert not node.module.startswith("gui_qt"), f"{py_file.name} imports from '{node.module}'"

    def test_core_has_no_gui_or_api_imports(self):
        core_dir = REPO_ROOT / "src" / "core"
        if not core_dir.exists():
            return
        forbidden = ("gui_qt", "src.api", "telegram_feeder_bot")
        for py_file in core_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for f in forbidden:
                            assert not alias.name.startswith(f), f"{py_file.name} imports '{alias.name}'"
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for f in forbidden:
                            assert not node.module.startswith(f), f"{py_file.name} imports from '{node.module}'"


class TestZombieLayerIsolation:
    """Verifies that src/zombies/ layer respects strict architecture boundaries (Phase 4E)."""

    @pytest.fixture
    def zombie_files(self):
        zombie_dir = REPO_ROOT / "src" / "zombies"
        assert zombie_dir.exists(), "src/zombies directory must exist"
        return list(zombie_dir.glob("*.py"))

    def test_zombies_have_no_forbidden_outer_layer_imports(self, zombie_files):
        """Zombies must not import delivery surfaces, DB storage, or pipeline internals."""
        forbidden_prefixes = (
            "src.api",
            "gui_qt",
            "telegram_feeder_bot",
            "src.db_storage",
            "src.pipeline.stages",
            "src.pipeline.runner",
            "src.pipeline.adapters",
        )

        for py_file in zombie_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in forbidden_prefixes:
                            assert not alias.name.startswith(forbidden), (
                                f"{py_file.name} violates zombie boundary by importing '{alias.name}'"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for forbidden in forbidden_prefixes:
                            assert not node.module.startswith(forbidden), (
                                f"{py_file.name} violates zombie boundary by importing from '{node.module}'"
                            )

    def test_zombies_have_zero_eventsource_imports(self, zombie_files):
        """Active zombie acquisition layer must not import legacy EventSource or event_types."""
        forbidden_modules = ("src.events", "src.events.event_types")
        forbidden_symbols = ("EventSource",)

        for py_file in zombie_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for mod in forbidden_modules:
                            assert not alias.name.startswith(mod), (
                                f"{py_file.name} imports forbidden legacy event module '{alias.name}'"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for mod in forbidden_modules:
                            assert not node.module.startswith(mod), (
                                f"{py_file.name} imports from forbidden legacy event module '{node.module}'"
                            )
                    for alias in node.names:
                        assert alias.name not in forbidden_symbols, (
                            f"{py_file.name} imports forbidden legacy symbol '{alias.name}'"
                        )

    def test_zombies_public_exports_coherence(self):
        """Verify that src/zombies/__init__.py exports all canonical classes with zero legacy symbols."""
        init_file = REPO_ROOT / "src" / "zombies" / "__init__.py"
        tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))

        exported_symbols = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, ast.List):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant):
                                    exported_symbols.add(elt.value)

        expected_symbols = {
            "ZombieBase",
            "ObservationIngestionCallback",
            "ZRss",
            "ZWeb",
            "ZCorp",
            "ZHacker",
            "ZGitHub",
            "ZSecurity",
            "ZombieSwarm",
            "SourceObservationIngestionCallback",
        }
        assert expected_symbols.issubset(exported_symbols), (
            f"Missing required exports in src/zombies/__init__.py: {expected_symbols - exported_symbols}"
        )
        assert "EventSource" not in exported_symbols, "EventSource must not be exported by src/zombies"


class TestStorageArchitectureBoundaries:
    """Enforces permanent retirement of legacy db_storage and single canonical SQLite storage model."""

    def test_db_storage_package_does_not_exist(self):
        """Permanent invariant: src/db_storage directory must never exist in the repository."""
        db_storage_dir = REPO_ROOT / "src" / "db_storage"
        assert not db_storage_dir.exists(), (
            "src/db_storage has been permanently retired and must not exist on the filesystem"
        )

    def test_production_codebase_has_zero_db_storage_imports(self):
        """No module in src/, gui_qt/, or root entrypoints may import src.db_storage."""
        search_dirs = [REPO_ROOT / "src", REPO_ROOT / "gui_qt"]
        py_files = []
        for d in search_dirs:
            if d.exists():
                py_files.extend(d.rglob("*.py"))
        py_files.extend(REPO_ROOT.glob("*.py"))

        forbidden_prefixes = ("src.db_storage", "db_storage")
        for py_file in py_files:
            if ".git" in str(py_file) or "__pycache__" in str(py_file):
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in forbidden_prefixes:
                            assert not alias.name.startswith(forbidden), (
                                f"{py_file.relative_to(REPO_ROOT)} illegally imports retired package '{alias.name}'"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for forbidden in forbidden_prefixes:
                            assert not node.module.startswith(forbidden), (
                                f"{py_file.relative_to(REPO_ROOT)} illegally imports from retired package '{node.module}'"
                            )


class TestEventsArchitectureBoundaries:
    """Enforces permanent retirement of legacy src/events package and EventStore class."""

    def test_events_package_does_not_exist(self):
        """Permanent invariant: src/events directory must never exist in the repository."""
        events_dir = REPO_ROOT / "src" / "events"
        assert not events_dir.exists(), (
            "src/events has been permanently retired and must not exist on the filesystem"
        )

    def test_production_codebase_has_zero_events_imports(self):
        """No module in src/, gui_qt/, or root entrypoints may import src.events."""
        search_dirs = [REPO_ROOT / "src", REPO_ROOT / "gui_qt"]
        py_files = []
        for d in search_dirs:
            if d.exists():
                py_files.extend(d.rglob("*.py"))
        py_files.extend(REPO_ROOT.glob("*.py"))

        forbidden_prefixes = ("src.events", "events.event_store", "events.event_types")
        for py_file in py_files:
            if ".git" in str(py_file) or "__pycache__" in str(py_file):
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in forbidden_prefixes:
                            assert not alias.name.startswith(forbidden), (
                                f"{py_file.relative_to(REPO_ROOT)} illegally imports retired package '{alias.name}'"
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for forbidden in forbidden_prefixes:
                            assert not node.module.startswith(forbidden), (
                                f"{py_file.relative_to(REPO_ROOT)} illegally imports from retired package '{node.module}'"
                            )

    def test_production_codebase_has_zero_event_store_symbol_references(self):
        """No module in src/ may reference or instantiate the legacy EventStore symbol."""
        src_dir = REPO_ROOT / "src"
        py_files = [f for f in src_dir.rglob("*.py") if "__pycache__" not in str(f)]

        for py_file in py_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "EventStore":
                    assert False, (
                        f"{py_file.relative_to(REPO_ROOT)} references forbidden legacy symbol 'EventStore'"
                    )


class TestLegacyModulesArchitectureBoundaries:
    """Enforces permanent retirement of legacy src/database.py and src/scraper.py modules."""

    def test_legacy_database_module_does_not_exist(self):
        """Permanent invariant: src/database.py must never exist in the repository."""
        database_file = REPO_ROOT / "src" / "database.py"
        assert not database_file.exists(), (
            "src/database.py has been permanently retired and must not exist on the filesystem"
        )

    def test_legacy_scraper_module_does_not_exist(self):
        """Permanent invariant: src/scraper.py must never exist in the repository."""
        scraper_file = REPO_ROOT / "src" / "scraper.py"
        assert not scraper_file.exists(), (
            "src/scraper.py has been permanently retired and must not exist on the filesystem"
        )

    def test_obsolete_tests_do_not_exist(self):
        """Permanent invariant: tests/test_database.py and test_scraper.py must not exist."""
        assert not (REPO_ROOT / "tests" / "test_database.py").exists(), (
            "tests/test_database.py is obsolete and must not exist"
        )
        assert not (REPO_ROOT / "tests" / "test_scraper.py").exists(), (
            "tests/test_scraper.py is obsolete and must not exist"
        )

    def test_production_codebase_has_zero_legacy_module_imports(self):
        """No module in src/, gui_qt/, scripts/, or root entrypoints may import src.database or src.scraper."""
        search_dirs = [REPO_ROOT / "src", REPO_ROOT / "gui_qt", REPO_ROOT / "scripts"]
        py_files = []
        for d in search_dirs:
            if d.exists():
                py_files.extend(d.rglob("*.py"))
        py_files.extend(REPO_ROOT.glob("*.py"))

        forbidden_prefixes = ("src.database", "src.scraper", "database", "scraper")
        for py_file in py_files:
            if ".git" in str(py_file) or "__pycache__" in str(py_file):
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in forbidden_prefixes:
                            if alias.name == forbidden or alias.name.startswith(forbidden + "."):
                                assert False, (
                                    f"{py_file.relative_to(REPO_ROOT)} illegally imports retired module '{alias.name}'"
                                )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for forbidden in forbidden_prefixes:
                            if node.module == forbidden or node.module.startswith(forbidden + "."):
                                assert False, (
                                    f"{py_file.relative_to(REPO_ROOT)} illegally imports from retired module '{node.module}'"
                                )

    def test_production_codebase_has_zero_legacy_symbol_references(self):
        """No module in src/ may reference or instantiate LegacyDatabaseShim or TechNewsScraper."""
        src_dir = REPO_ROOT / "src"
        py_files = [f for f in src_dir.rglob("*.py") if "__pycache__" not in str(f)]

        forbidden_symbols = ("LegacyDatabaseShim", "TechNewsScraper", "get_database")
        for py_file in py_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in forbidden_symbols:
                    assert False, (
                        f"{py_file.relative_to(REPO_ROOT)} references forbidden legacy symbol '{node.id}'"
                    )


class TestZombieArchitectureBoundaries:
    """Enforces that acquisition, zombies, and crawler modules never import persistence/storage directly."""

    def test_zombies_have_zero_storage_imports(self):
        """Zombies and crawlers must produce SourceObservation, never importing src.storage or sqlite3 directly."""
        acquisition_dirs = [REPO_ROOT / "src" / "zombies", REPO_ROOT / "src" / "scrapers"]
        py_files = []
        for d in acquisition_dirs:
            if d.exists():
                py_files.extend(d.rglob("*.py"))

        forbidden_prefixes = (
            "src.storage.sqlite_engine",
            "src.storage.sqlite_article_repository",
            "src.storage.sqlite_event_repository",
            "src.storage.sqlite_source_health_repository",
            "src.storage.sqlite_auxiliary_repositories",
            "sqlite3",
        )
        for py_file in py_files:
            if ".git" in str(py_file) or "__pycache__" in str(py_file) or py_file.name == "coordinator.py":
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in forbidden_prefixes:
                            if alias.name == forbidden or alias.name.startswith(forbidden + "."):
                                assert False, (
                                    f"Acquisition module {py_file.relative_to(REPO_ROOT)} illegally imports storage module '{alias.name}'"
                                )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for forbidden in forbidden_prefixes:
                            if node.module == forbidden or node.module.startswith(forbidden + "."):
                                assert False, (
                                    f"Acquisition module {py_file.relative_to(REPO_ROOT)} illegally imports from storage module '{node.module}'"
                                )
