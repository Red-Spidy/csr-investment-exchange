DB_URL ?= postgresql://csr:csr@localhost:5433/csr_exchange
DB_NAME ?= csr_exchange
PSQL    = docker exec -i csr_db psql -U csr -d $(DB_NAME) -v ON_ERROR_STOP=1

.PHONY: up down migrate reset seed test-db test-ml test-api test demo psql datasets api web train train-fraud train-impact train-bert proposals score eval-human proposals-unseen eval-unseen demo-check ui-check test-web test-parity verify rate

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

# Runs on a throwaway database built from db/migrations and db/seed.sql, so it never reads
# or changes the demo data. Every file runs even after a failure, then it fails if any did
# (a bare for loop would report only the last file's result).
DB_TESTS ?= db/tests
TEST_DB  ?= csr_dbtest
TEST_PSQL = docker exec -i csr_db psql -U csr -d $(TEST_DB) -v ON_ERROR_STOP=1
test-db:
	@docker exec csr_db psql -U csr -d csr_exchange -qX -c "DROP DATABASE IF EXISTS $(TEST_DB) WITH (FORCE)" -c "CREATE DATABASE $(TEST_DB)"
	@$(MAKE) --no-print-directory migrate seed DB_NAME=$(TEST_DB) >/dev/null
	@fail=0; \
	for f in $(DB_TESTS)/*.sql; do [ -e "$$f" ] || continue; echo "== $$f"; $(TEST_PSQL) -f - < $$f || fail=1; done; \
	for f in $(DB_TESTS)/*.sh; do [ -e "$$f" ] || continue; echo "== $$f"; DB_NAME=$(TEST_DB) bash $$f || fail=1; done; \
	docker exec csr_db psql -U csr -d csr_exchange -qX -c "DROP DATABASE IF EXISTS $(TEST_DB) WITH (FORCE)"; \
	exit $$fail

test-ml:
	.venv/bin/python -m pytest -q

test-api:
	.venv/bin/python -m pytest -c api/pytest.ini api/tests -q

test-web:
	cd web && npx vitest run && npx tsc -b && npx vite build

test: test-db test-ml test-api test-web

# The browser's offline engine against the real API, reads and writes. Replaces the demo data.
test-parity:
	bash scripts/parity.sh

# Is everything working? Preflight, every layer's tests, then make demo-check. QUICK=1 skips the last.
verify:
	@QUICK=$(QUICK) .venv/bin/python scripts/verify.py

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

# The three BERT readers. Slow -- about two hours on an M4 Pro, including the
# bert-base-cased download -- so it is not part of `make train`.
train-bert:
	PYTHONPATH=ml .venv/bin/python -m nlp.train

# BERT on text it never trained on: the team's hand-written proposals, and another
# LLM's rewrites of the test projects (needs GROQ_API_KEY in .env).
eval-human:
	PYTHONPATH=ml .venv/bin/python -m nlp.external --human

proposals-unseen:
	PYTHONPATH=ml .venv/bin/python -m textgen.generate --split test --providers groq --out ml/datasets/proposals_unseen_writer.jsonl

eval-unseen:
	PYTHONPATH=ml .venv/bin/python -m nlp.external --jsonl ml/datasets/proposals_unseen_writer.jsonl

# Score every project in the database with the trained models, then grade it in SQL.
score:
	PYTHONPATH=ml .venv/bin/python -m pipeline.score

# Rate every NGO update that has words but no rating yet: Gemini when GEMINI_API_KEY is set.
rate:
	PYTHONPATH=ml .venv/bin/python -m progress.rate

# BERT training text via Gemini/Groq (keys in .env). Resumable; LIMIT=300 for a pilot.
proposals:
	PYTHONPATH=ml .venv/bin/python -m textgen.generate $(if $(LIMIT),--limit $(LIMIT),)

# The deck's workflow end to end: fresh scored database, API, built frontend, every page
# rendered in headless Chrome. Leaves a clean, scored demo. Screenshots in demo-check/.
demo-check:
	.venv/bin/python scripts/demo_check.py

# Click through the product on the running stack (make api, make web). Resets the demo data.
ui-check:
	cd web && node e2e/journey.mjs

psql:
	docker exec -it csr_db psql -U csr -d csr_exchange
