-- 001_extensions.sql -- required extensions
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector: semantic CSR<->project matching
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid() for idempotency keys
