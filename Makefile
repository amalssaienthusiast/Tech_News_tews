# Makefile — common dev tasks for Tech News Scraper
#
# Usage:
#   make help          # show all targets
#   make install       # install deps in dev mode
#   make test          # run tests
#   make lint          # run ruff
#   make lock          # regenerate requirements.lock
#   make docker        # build + run docker-compose stack
#   make clean         # remove caches

.DEFAULT_GOAL := help

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: help install install-dev test lint lock docker docker-up docker-down clean

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
	      /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install:  ## Install production dependencies
	$(PIP) install -r requirements.txt

install-dev:  ## Install dev dependencies (lint, test, type-check)
	$(PIP) install -r requirements-dev.txt
	pre-commit install

test:  ## Run pytest (skipping live-network and torch-dependent tests)
	$(PYTHON) -m pytest tests/ \
		--ignore=tests/test_live_bypass.py \
		--ignore=tests/test_google_search_diagnostic.py \
		--ignore=tests/test_scraper.py \
		--ignore=tests/test_gui_qt.py \
		--tb=short -q

test-all:  ## Run ALL tests (including live-network and torch-dependent)
	$(PYTHON) -m pytest tests/ --tb=short -q

lint:  ## Run ruff
	ruff check src/ tests/
	ruff format --check src/ tests/

lint-fix:  ## Auto-fix lint issues
	ruff check --fix src/ tests/
	ruff format src/ tests/

lock:  ## Regenerate requirements.lock from requirements.txt
	pip-compile requirements.txt -o requirements.lock
	pip-compile requirements-dev.txt -o requirements-dev.lock

docker:  ## Build the Docker image
	docker build -t tech-news-scraper:latest .

docker-up:  ## Start the docker-compose stack (app + redis)
	docker compose up -d

docker-up-full:  ## Start the full stack (app + redis + postgres + elasticsearch)
	docker compose --profile full up -d

docker-down:  ## Stop the docker-compose stack
	docker compose down

clean:  ## Remove Python caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ *.egg-info .coverage htmlcov
