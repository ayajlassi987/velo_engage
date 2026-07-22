-- Per-stage timestamps for outcomes — previously only a single recorded_at
-- column existed, shared by delivered/read/replied/booked/attended, so every
-- update clobbered the previous stage's timing and no duration between
-- stages (e.g. "days from contact to booking") could ever be recovered.
-- Prerequisite for any timing/survival-style model (see PROJECT_STATUS.md).
ALTER TABLE outcomes
    ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS read_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS replied_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS booked_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS attended_at  TIMESTAMPTZ;
