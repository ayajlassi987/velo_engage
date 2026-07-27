# 9. Clinical Note Intelligence (MedGemma + NemoGuard)

## Purpose

Extract structured medical information — diagnoses, medications,
procedures, follow-up recommendations, clinical risks — from unstructured
Epic clinical notes, so the console can surface a real, machine-readable
summary of a patient's clinical history instead of a wall of free text.
This is the master spec's "Task 2." Shown in the console at
`/clinical-summaries`.

## Where it runs, and why

`ve_clinical_intel` runs **on the DGX Spark** (a GPU box, separate physical
machine from the rest of this stack) — not in `docker-compose.dev.yml`,
because GPU-bound MedGemma/NemoGuard inference calls need to be local to
the GPU. The patient data isn't local to the GPU, though — so this service
calls back over the network to `ve_connect`'s HTTP API on the main machine
for both reads (fetching notes) and writes (storing extractions), rather
than opening a direct Postgres connection (the DGX has no root access to
set up a real VPN network interface, only a rootless Tailscale userspace
HTTP proxy).

## The pipeline, per note

1. **Pull the note** — `ve_connect` gained a new capability for this:
   `_pull_clinical_notes()` in `adapter.py` searches Epic for
   `DocumentReference` resources, fetches each attachment's `Binary` (only
   `text/plain`/`text/xml` — scanned/PDF notes are out of scope for v1,
   would need OCR), and returns decoded note text over
   `GET /patients/{id}/clinical-notes`. Notes are never written to
   `ve_connect`'s own database — only returned in the HTTP response, so raw
   note text never touches disk on the main machine.
2. **Safety gate first** (`nemoguard_client.py`) — every note is checked
   against NVIDIA's NemoGuard content-safety NIM *before* it's ever sent to
   MedGemma. A note that fails this check is logged and skipped entirely,
   never reaching the extraction model. Honest scope note: NemoGuard
   detects unsafe/toxic *content*, not factual hallucination in a
   structured extraction — it's the safety gate the roadmap specifies, but
   it isn't what actually keeps the extraction honest (see step 4).
3. **Extraction** (`medgemma_client.py`) — calls the team's `model_server`
   (MedGemma 27B, text-only variant) via its real SSE-based
   `/v1/chat/completions` API (not OpenAI-compatible JSON — `data:`-prefixed
   token events accumulated into a full string, then parsed as JSON),
   prompted for strict JSON output covering diagnoses/medications/
   procedures/follow-up/risks.
4. **Validation** (`validation.py`) — non-LLM sanity checks: extracted
   ICD-10-shaped codes matched against a regex, medication names checked
   non-empty, any response that fails to parse as valid JSON is flagged
   rather than silently dropped. **This, not NemoGuard, is the actual
   hallucination-reduction mechanism for this task** — a cheap, deterministic
   check that a model's structured output at least has the right shape,
   run every time regardless of how confident the model sounded.
5. **Store** — a FHIR-shaped-but-not-fully-validated dict (the same
   convention every other Epic resource in this system uses) upserted into
   `clinical_extractions` via `ve_connect`'s `POST /clinical-extractions`.
   Raw note text and raw MedGemma output are discarded after this step —
   never written to disk — a deliberate retention decision: this system has
   no encryption-at-rest or audit-logging anywhere, and raw clinical note
   text would be the most sensitive data it ever handled.

## Why this design

- **Safety and validation are two different concerns, done by two
  different mechanisms.** NemoGuard answers "is this text unsafe to
  process at all"; the regex/shape validation answers "did the model
  actually produce something structurally sane." Neither one substitutes
  for the other, and conflating them (e.g. trusting NemoGuard alone to mean
  "the extraction is trustworthy") would be a real accuracy risk for a
  clinical-facing feature.
- **Discard raw text, keep structured output only** — the minimum data
  retention this feature could get away with, given no other privacy
  infrastructure exists in this codebase yet.
- **Fault-tolerant resource fetching, same pattern as the rest of Epic
  integration** (file 8) — PDF/scanned notes are explicitly out of scope
  rather than silently mishandled; a note in an unsupported format is
  skipped, not force-fed to an extraction model expecting text.
