-- 003_vector_index.sql -- HNSW indexes for cosine similarity matching.
-- Built after the tables exist; cosine ops because embeddings are L2-normalised.
CREATE INDEX idx_extractions_embedding
    ON project_extractions USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_rulebooks_embedding
    ON csr_rulebooks USING hnsw (embedding vector_cosine_ops);
