# DocMind Agent

DocMind Agent is an enterprise-oriented document management and question answering platform built around a Vue 3 frontend, a FastAPI backend, and a Docker-based local stack. The project focuses on keeping the core ingestion, retrieval, chat streaming, security, and admin workflows runnable first, while leaving room to connect real LLM and embedding providers without breaking the base system.

## Repository layout

```text
.
├─ backend/                  FastAPI service, Celery workers, tests
├─ frontend/                 Vue 3 + Vite web client
├─ docs/                     Architecture, API, deployment, and runbooks
├─ infra/                    Sidecar services and container helpers
├─ scripts/                  Smoke tests, CI gate, release preflight scripts
├─ docker-compose.yml        Core infrastructure services
└─ docker-compose.dev.yml    App services for local development
```

## Current capabilities

- JWT-based authentication and multi-tenant access control
- Document upload, ingestion task orchestration, and status tracking
- Hybrid retrieval stack with PostgreSQL, Redis, MinIO, Elasticsearch, Milvus, and Neo4j
- Streaming chat and runtime task management
- Admin dashboards for system monitoring, ingestion, security audit, runtime evaluation, and user management
- Delivery scripts for smoke tests, CI gates, and preflight checks

## Tech stack

- Frontend: Vue 3, Vite, Pinia, Vue Router, Vitest
- Backend: FastAPI, SQLAlchemy, Celery, Redis, PostgreSQL, pytest, Ruff
- Infrastructure: Docker Compose, MinIO, Milvus, Elasticsearch, Neo4j, ClamAV, Ollama

## Quick start

### 1. Prepare environment

Copy the sample configuration and adjust values as needed:

```powershell
Copy-Item .env.example .env
```

The checked-in sample is configured for local Docker development by default.

### 2. Start the stack

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Default local endpoints:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Backend docs: `http://localhost:8000/api/docs`
- Flower: `http://localhost:5555`
- MinIO console: `http://localhost:9001`

### 3. Optional Ollama bootstrap

The default local model wiring targets Ollama. Pull the baseline models after the container is up:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d ollama
docker exec docmind-ollama ollama pull qwen2.5:1.5b
docker exec docmind-ollama ollama pull nomic-embed-text
```

### 4. Stop the stack

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

## Local development

### Backend

```powershell
Set-Location backend
py -3 -m pip install -r requirements.txt
pytest -q
```

### Frontend

```powershell
Set-Location frontend
npm ci
npm run build
```

## Validation and delivery

Smoke and release tooling lives under `scripts/`:

- `scripts/smoke_e2e.py` for end-to-end smoke validation
- `scripts/ci_gate.py` for delivery gate checks
- `scripts/release-preflight.ps1` for local release preflight reports

Run the documented preflight flow from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-preflight.ps1
```

Generated delivery reports are intentionally ignored by Git.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API reference](docs/API.md)
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Deployment guide](docs/DEPLOYMENT.md)
- [Delivery runbook](docs/DELIVERY_RUNBOOK.md)
- [AI placeholder boundaries](docs/AI_API_PLACEHOLDERS.md)

## Notes

- `.env` is excluded from version control. Use `.env.example` as the template.
- Runtime caches, generated reports, upload samples, and local planning notes are excluded through `.gitignore`.
- The project is designed to run cleanly through Docker Compose; keep local code and containerized runtime in sync when changing app code.
