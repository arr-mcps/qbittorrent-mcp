.PHONY: help sync test test-integration build bump-patch bump-minor bump-major clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

sync: ## Install/update dependencies
	uv sync

test: ## Run the offline test suite
	uv run pytest

test-integration: ## Run tests against the live qBittorrent instance (needs QBITTORRENT_URL + auth env)
	uv run pytest -m integration

build: ## Build wheel + sdist into dist/
	uv build

bump-patch: ## Bump patch version, e.g. 0.1.0 -> 0.1.1
	uv version --bump patch

bump-minor: ## Bump minor version, e.g. 0.1.0 -> 0.2.0
	uv version --bump minor

bump-major: ## Bump major version, e.g. 0.1.0 -> 1.0.0
	uv version --bump major

clean: ## Remove build artifacts
	rm -rf dist .pytest_cache
