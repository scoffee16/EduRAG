-- Infrastructure extensions required by the EduRAG MVP.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Application schema and migration placeholder. Business tables are owned by
-- later application migrations.
CREATE SCHEMA IF NOT EXISTS edurage;

CREATE TABLE IF NOT EXISTS edurage.schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER DATABASE edurage SET search_path TO edurage, public;