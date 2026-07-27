-- Multi-clinic productization: every table already had a clinic_id column
-- (confirmed via investigation before this migration — see PROJECT_STATUS.md),
-- but nothing anywhere recorded which clinics actually exist, or which
-- clinic a logged-in console user belongs to. This is the first real
-- multi-tenancy scaffolding in the project.

CREATE TABLE IF NOT EXISTS clinics (
    clinic_id   TEXT PRIMARY KEY,
    clinic_name TEXT NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per console user, one clinic each — deliberately not a many-to-many
-- membership table. A real multi-location group (one person overseeing
-- several clinics) is a real future need, but nothing in this codebase's
-- auth model (Keycloak roles, unrelated to clinic identity — see
-- PROJECT_STATUS.md) has ever supported switching between clinics, and nothing
-- asked for it here. One clinic per user is the simplest thing that actually
-- proves data isolation works end-to-end.
CREATE TABLE IF NOT EXISTS clinic_users (
    username   TEXT PRIMARY KEY,
    clinic_id  TEXT NOT NULL REFERENCES clinics(clinic_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO clinics (clinic_id, clinic_name) VALUES
    ('clinic_alnoor_001', 'Al Noor Clinic')
ON CONFLICT (clinic_id) DO NOTHING;

-- Existing seed Keycloak users (admin, owner, staff — see
-- infra/keycloak/velo-engage-realm.json) all map to the original clinic, so
-- today's behavior is unchanged until a second clinic/user is added.
INSERT INTO clinic_users (username, clinic_id) VALUES
    ('admin', 'clinic_alnoor_001'),
    ('owner', 'clinic_alnoor_001'),
    ('staff', 'clinic_alnoor_001')
ON CONFLICT (username) DO NOTHING;
