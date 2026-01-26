# Makefile for the AMT Cycle Workbench
# Backend: Litestar + granian via uv (Python 3.14) | Frontend: React+TS+Vite via pnpm (Node 22)
# DuckDB is an embedded file (make seed); backend/frontend can run locally OR fully in Docker.

# Backend port (5000 is taken by macOS AirPlay Receiver; the Vite dev server proxies here).
PORT ?= 5001

.DEFAULT_GOAL := help

.PHONY: help install install-backend install-frontend env backend frontend run dev clean \
        test seed gwm-sample up down build logs

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend ## Install backend (uv) + frontend (pnpm) deps

install-backend: env ## Install backend deps with uv
	cd backend && uv sync

install-frontend: ## Install frontend deps with pnpm
	cd frontend && pnpm install

env: ## Create backend/.env from the example if missing
	@test -f backend/.env || (cp backend/.env.example backend/.env && \
		echo "Created backend/.env from example.")

backend: seed ## Run the Litestar backend (granian) locally (override with PORT=...)
	cd backend && PORT=$(PORT) uv run python app.py

frontend: ## Run the Vite dev server (http://localhost:3000)
	cd frontend && pnpm dev

run: seed ## Run backend + frontend locally together (Ctrl-C stops both)
	@echo "Backend  -> http://localhost:$(PORT)"
	@echo "Frontend -> http://localhost:3000"
	@trap 'kill 0' INT TERM EXIT; \
	( cd backend && PORT=$(PORT) uv run python app.py ) & \
	( cd frontend && pnpm dev ) & \
	wait

dev: run ## Alias for 'run'

test: ## Run the backend test suite (pytest)
	cd backend && uv run pytest

seed: ## (Re)build the embedded DuckDB database (db/haulsim.duckdb)
	uv run --script db/generate_seed.py

gwm-sample: ## (Re)generate uploadable .gwm import samples (pass ARGS="--cycles 20 --site ESC")
	chmod +x executables/GWMReader.exe
	uv run --script tools/generate_gwm.py $(ARGS)
	@echo "Upload sample_data/import_sample_ESC.zip via the WebUI Import card (site: BhpEscondida)."

# --- Docker: full stack (backend + frontend; DuckDB is baked into the backend image) ---
build: ## Build the backend + frontend images
	docker compose build

up: ## Build + run the full stack in Docker (http://localhost:3000)
	@test -f .env || cp .env.docker.example .env
	docker compose up -d --build
	@echo "Frontend -> http://localhost:3000   |   Backend -> http://localhost:5001"

down: ## Stop the full stack
	docker compose down

logs: ## Tail all container logs
	docker compose logs -f

clean: ## Remove installed dependencies (venv + node_modules)
	rm -rf backend/.venv frontend/node_modules
