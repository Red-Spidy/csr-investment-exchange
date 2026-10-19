DB_URL ?= postgresql://csr:csr@localhost:5433/csr_exchange
PSQL   := docker exec -i csr_db psql -U csr -d csr_exchange -v ON_ERROR_STOP=1

.PHONY: up down migrate reset seed test-db test-ml test demo psql datasets

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

test: test-db test-ml

demo: reset seed
	@echo "demo scenario ready"

datasets:
	PYTHONPATH=ml .venv/bin/python -m synth.build

psql:
	docker exec -it csr_db psql -U csr -d csr_exchange
