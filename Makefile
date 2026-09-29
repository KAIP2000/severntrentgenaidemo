.PHONY: dev backend frontend test eval-test eval-seed eval-live

dev:
	docker compose up --build

backend:
	cd backend && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && ../.venv/bin/python -m pytest
	cd frontend && npm run lint

eval-test:
	cd backend && ../.venv/bin/python -m pytest -q tests/test_evaluation.py

eval-seed:
	cd backend && ../.venv/bin/python -m app.evaluation.cli seed

eval-live:
	cd backend && ../.venv/bin/python -m app.evaluation.cli live
