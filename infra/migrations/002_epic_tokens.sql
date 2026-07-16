CREATE TABLE IF NOT EXISTS epic_tokens (
    clinic_id       TEXT PRIMARY KEY,
    access_token    TEXT NOT NULL,
    refresh_token   TEXT,
    token_type      TEXT DEFAULT 'Bearer',
    expires_at      TIMESTAMPTZ NOT NULL,
    scope           TEXT,
    id_token        TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);