# Photo Organizer -- dev/test convenience wrapper around docker compose.
#
# Building release binaries is normally handled by GitHub Actions
# (.github/workflows/build.yml). build-linux/build-windows here just mirror
# the Docker-based build documented in the README for local use.
#
# No local Python needed for any of this -- everything runs in containers.

.PHONY: help dev shell test coverage lint typecheck sec audit check build-linux build-windows clean

help:
	@echo "make dev            interactive shell in the dev container"
	@echo "make shell          alias for 'make dev'"
	@echo "make test           run pytest inside the dev container"
	@echo "make coverage       run pytest with a coverage report (fails under 90%, gui.py excluded)"
	@echo "make lint           run ruff check"
	@echo "make typecheck      run mypy"
	@echo "make sec            run bandit security scan (source code)"
	@echo "make audit          run pip-audit (known CVEs in installed deps)"
	@echo "make check          lint + typecheck + sec + audit + coverage (what CI should run)"
	@echo "make build-linux    build dist_docker/PhotoOrganizer-linux"
	@echo "make build-windows  build dist_docker/PhotoOrganizer.exe via Wine (experimental)"
	@echo "make clean          remove local build/test artifacts"

dev shell:
	docker compose run --rm dev

test:
	docker compose run --rm dev pytest -q

coverage:
	docker compose run --rm dev pytest -q --cov --cov-report=term-missing

lint:
	docker compose run --rm dev ruff check .

typecheck:
	docker compose run --rm dev mypy .

sec:
	docker compose run --rm dev bandit -r photo_organizer run.py

audit:
	docker compose run --rm dev pip-audit

check: lint typecheck sec audit coverage

build-linux:
	docker compose run --rm build-linux

build-windows:
	docker compose run --rm build-windows

clean:
	rm -rf __pycache__ .pytest_cache .coverage build dist dist_docker .buildenv
