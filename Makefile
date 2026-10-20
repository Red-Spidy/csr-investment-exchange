DB_URL ?= postgresql://csr:csr@localhost:5433/csr_exchange
PSQL   := docker exec -i csr_db psql -U csr -d csr_exchange -v ON_ERROR_STOP=1

.PHONY: up down migrate reset seed test-db test-ml test-api test demo psql datasets api web train train-fraud train-impact

up:
	docker compose up -d
	@until docker exec csr_db pg_isready -U csr -d csr_exchange >/dev/null 2>&1; do sleep 1; done
	@echo "db ready on localhost:5433"

down:
	docker compose down

migrate:
	@for f in db/migrations/*.sql; do echo "-- applying $$f"; $(PSQL) -f - < $$f; done
	@echo "migrations applied"

reset:
	$(PSQL) -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	$(MAKE) migrate

seed:
	$(PSQL) -f - < db/seed.sql
	@echo "seed data loaded"

test-db:
	@for f in db/tests/*.sql; do echo "== $$f"; $(PSQL) -f - < $$f; done
	@echo "== db/tests/06_concurrency.sh"; bash db/tests/06_concurrency.sh

test-ml:
	.venv/bin/python -m pytest -q

test-api:
	.venv/bin/python -m pytest -c api/pytest.ini api/tests -q

test: test-db test-ml test-api

api:
	DATABASE_URL=$(DB_URL) CSR_ALLOW_RESET=1 .venv/bin/python -m uvicorn app.main:app --app-dir api --reload --reload-dir api --port 8000

web:
	cd web && npm run dev

demo: reset seed
	@echo "demo scenario ready"

datasets:
	PYTHONPATH=ml .venv/bin/python -m synth.build

train: train-fraud train-impact

train-fraud:
	PYTHONPATH=ml .venv/bin/python -m fraud.train

train-impact:
	PYTHONPATH=ml .venv/bin/python -m impact.train

psql:
	docker exec -it csr_db psql -U csr -d csr_exchange
