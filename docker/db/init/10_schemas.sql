CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TABLE IF NOT EXISTS meta.ingestions (
    ingest_id text PRIMARY KEY,
    input_path text NOT NULL,
    input_hash text NOT NULL,
    detected_crs text,
    chosen_crs text,
    status text NOT NULL,
    report_path text,
    log_dir text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION meta.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_ingestions_updated_at ON meta.ingestions;
CREATE TRIGGER tr_ingestions_updated_at
BEFORE UPDATE ON meta.ingestions
FOR EACH ROW
EXECUTE FUNCTION meta.set_updated_at();
