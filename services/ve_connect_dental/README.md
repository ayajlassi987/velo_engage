# ve_connect_dental

**Status: prototype.** This service exists to prove the dental-treatment-
pathway design (see the architecture discussion recorded around this
service's creation) end to end against real-shaped data before any real
clinic or clinical advisor is involved. Nothing it produces should be
treated as a clinically-reviewed suggestion — see
`policies/dental_pathways/*.yml`'s `status` field.

`ve_connect_dental` pulls dental procedure/appointment/patient data from
**OpenDental** (a practice management system, not Epic) and maps it into
this platform's own schema (`dental_procedure_history`). It is a **sibling
service to `ve_connect`, not a modification of it** — Epic's integration is
completely untouched by this work. The two exist because they talk to two
unrelated external systems with unrelated auth, schemas, and failure modes,
same reasoning that already justifies `ve_connect` being separate from
`ve_orchestrator`.

## Why OpenDental, and why a two-phase integration plan

Epic is primarily a medical EHR; most standalone dental practices run a
dedicated practice-management system instead (OpenDental, Dentrix,
Eaglesoft, Curve Dental, Denticon). OpenDental was chosen first because it's
free, open-source, and self-hostable — real development and testing can
start immediately, without waiting on a vendor relationship the way
Dentrix/Eaglesoft typically require.

The client (`client.py`) is built behind one interface
(`get_patient`/`get_procedures`/`get_appointments`) specifically so the
transport underneath — direct MySQL today, OpenDental's REST API later — can
be swapped without touching `mapper.py` or anything downstream. Today's
implementation (`OpenDentalMySQLClient`) talks directly to a MySQL database,
which is the only thing needed for Phase A below.

## Phase A — local development, no contact with OpenDental required

OpenDental itself is free to download and self-host; you don't need
anyone's permission to do this phase.

1. Install OpenDental (client + MySQL backend) following OpenDental's own
   current installation docs. The desktop client is traditionally
   Windows-only, so a Windows VM may be needed even though this repo runs
   in Linux/WSL — the MySQL backend is what this service actually talks to.
2. Through OpenDental's own UI, hand-enter a handful of realistic test
   patients and procedure sequences matching the pilot pathway in
   `policies/dental_pathways/restorative_endodontic.yml` — e.g. an exam +
   X-ray, a shallow-caries filling, and a deep-caries root-canal-then-crown
   case. This gives controlled, correctly-shaped ground truth, arguably
   better than generic sample data since it's designed to exercise the
   exact pathway the state machine needs to walk.
3. Confirm the real column names/types for the tables this service reads
   (`procedurelog`, `appointment`, `patient` in OpenDental's own schema —
   OpenDental publishes a schema reference on their own wiki) against your
   actual local instance before trusting anything hardcoded here; OpenDental
   schema details can shift between versions.
4. Point `.env` (`OPENDENTAL_DB_HOST`/`PORT`/`NAME`/`USER`/`PASSWORD`) at
   your local instance and run this service against it.
5. Separately, empirically check whether OpenDental's REST API can be
   enabled for purely local/internal use without a Developer Key, or
   whether that gate applies even to a self-hosted single instance — this
   determines how much of Phase B below is actually needed later.

## Phase B — going live with a real clinic (only after Phase A is verified)

6. Register as an OpenDental developer to obtain a **Developer Key**.
7. Each pilot clinic generates its own **Customer Key** from inside their
   own OpenDental installation and shares it with you — this is a
   per-clinic manual exchange, not a single OAuth app the way Epic's
   registration works. Store each clinic's key in Vault, same convention as
   every other per-clinic credential in this project (Epic, Meta, Twilio).
8. Confirm the API's current documented rate limits and add backoff to the
   client before depending on it.
9. Implement `OpenDentalAPIClient` behind the same interface as
   `OpenDentalMySQLClient` and switch the configured transport per clinic —
   `mapper.py` and everything downstream needs no changes.
10. Live smoke test against the real clinic's data, verified directly
    against Postgres, same discipline used for every other integration in
    this project.

## A problem this integration introduces that Epic-only pipelines don't have

**Patient identity resolution across systems.** A clinic may have both an
Epic medical record and an OpenDental dental record for the same real
person. Without an explicit matching step (deterministic match on
name+DOB+phone, or a manual linking action in the console), these are
silently treated as two different patients — fragmenting history and
undermining the existing consent/de-dup logic, which assumes one identity
per real patient. This service does not yet implement that matching step;
build it before real dual-source data is flowing for any single clinic.
