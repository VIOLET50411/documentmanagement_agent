.PHONY: dev up down build test lint migrate

# --- Development ---
dev:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

up:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d

down:
	docker-compose down -v

build:
	docker-compose build

# --- Backend ---
backend-install:
	cd backend && pip install -r requirements.txt

backend-dev:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

celery-worker:
	cd backend && celery -A celery_app worker --loglevel=info --autoscale=8,2

celery-flower:
	cd backend && celery -A celery_app flower --port=5555

# --- Frontend ---
frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

# --- Database ---
migrate:
	cd backend && alembic upgrade head

migrate-create:
	cd backend && alembic revision --autogenerate -m "$(msg)"

# --- Testing ---
test:
	cd backend && pytest tests/ -v --cov=app

lint:
	cd backend && ruff check app/
	cd backend && mypy app/

# --- Evaluation ---
eval:
	cd backend && python -m app.evaluation.ragas_runner

loadtest:
	py -3 scripts/loadtest_baseline.py --base-url http://localhost:18000

smoke:
	py -3 scripts/smoke_e2e.py --base-url http://localhost:18000

gate:
	py -3 scripts/ci_gate.py --base-url http://localhost:18000

ollama-pull:
	docker exec docmind-ollama ollama pull qwen2.5:1.5b

preflight:
	powershell -ExecutionPolicy Bypass -File .\scripts\release-preflight.ps1
