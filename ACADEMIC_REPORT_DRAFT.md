> **Note to the author before submission**: This draft mirrors the structure, section numbering, and academic register of a teammate's PFE report from the same host company (Velodoc), applied to the *Velo Engage* (VeloDoc) system actually built and verified across this project's development sessions — every architectural, implementation, and design-decision claim below reflects the real, working codebase (services, migrations, tests, and documented sessions), not invented content. Three things still need your own hand before submission: (1) your name, university, submission date, and jury/supervisor names — left as placeholders below; (2) the exact final numeric metrics for the propensity, expected-value, uplift, and survival models — Chapter IV cites real, repository-verified numbers for the no-show model (pulled directly from `ml/data/reports/`) and flags the remaining models' cells for you to fill from your own current MLflow registry, so the report never states a number that wasn't actually produced; (3) a Figures/Diagrams pass — this draft describes each figure in text where the source repository has an equivalent (the system architecture, the daily pipeline, the risk/priority bands, the console screens) so you can produce the actual graphics from the running application and the `ARCHITECTURE.md`/`docs/project_explainer/` diagrams already in the repo.

---

# Adaptive AI for Patient Reactivation and Causal Impact Measurement in Outpatient Clinics

**[Your Name]**

Graduation Report — Engineering Diploma in [Your Program / Option]
[Your University]

Presented on [Defense Date], before the review panel:

| | | |
|---|---|---|
| Mr./Ms. | [President] | President |
| Mr./Ms. | [Examiner] | Examiner |
| Mr./Ms. | [Academic Supervisor] | Academic Supervisor |
| Mr. Wael Hilali | | Industrial Supervisor |
| Mr. Bilel Said | | Industrial Supervisor |

---

## Dedication

*[Personalize this section — the reference format dedicates the work to parents, family, friends, the academic community, and colleagues at the host company. Keep or replace freely.]*

## Acknowledgement

*[Personalize — thank your academic supervisor, your industrial supervisors at Velodoc, the jury, your school, and your family, following the same structure as your teammate's report.]*

---

## Table of Contents

- General introduction
- **Chapter I** — Adaptive AI for Patient Reactivation and Engagement Measurement
- **Chapter II** — System and AI Architecture
- **Chapter III** — Implementation of the Velo Engage (VeloDoc) Application
- **Chapter IV** — Evaluation and Validation
- General conclusion
- Bibliography
- Appendices

---

## List of abbreviations

| | |
|---|---|
| AI | Artificial intelligence |
| API | Application programming interface |
| AUC | Area under the curve |
| Brier | Brier score |
| CatBoost | Categorical boosting |
| CDT | Current Dental Terminology (mentioned in future-work scope) |
| DGX Spark | NVIDIA DGX Spark |
| ECE | Expected calibration error |
| EHR | Electronic health record |
| FHIR | Fast Healthcare Interoperability Resources |
| HITL | Human in the loop |
| JSON | JavaScript Object Notation |
| LLM | Large language model |
| ML | Machine learning |
| MLOps | Machine learning operations |
| NATS | Neural Autonomic Transport System (message bus) |
| OAuth | Open Authorization |
| PR-AUC | Precision-recall area under the curve |
| REST | Representational state transfer |
| ROC | Receiver operating characteristic |
| SHAP | Shapley additive explanations |
| SMS | Short Message Service |
| SaMD | Software as a Medical Device |

---

## General introduction

Outpatient clinics accumulate, silently, a large population of patients who have a legitimate clinical or operational reason to come back — a treatment plan left open, an insurance benefit about to expire, a clinical guideline recall, or simple dormancy after a long gap since the last visit — but are never proactively recontacted. Front-desk teams are structured to react to inbound demand (a patient calling to book), not to mine their own patient population for who *should* be contacted next; when outreach does happen, it is usually a blanket campaign with no personalization and no way to prove it changed anything.

This PFE internship was carried out with **Velodoc**, a healthcare AI startup, as part of the same broader company vision described elsewhere in this cohort's reports: adaptive AI for clinic operations, spanning scheduling intelligence, patient reactivation, and clinical-operational copilots. The work presented here is the **patient-reactivation and engagement-measurement** track of that vision, implemented as **Velo Engage**, branded to clinic users as **VeloDoc**.

The system finds patients with a legitimate reason to be recontacted, checks whether contacting them is legally and operationally permitted, decides — with trained machine-learning models, not a fixed rule — whether contacting them is actually worth it, reaches them on WhatsApp, and measures whether the outreach caused a real incremental booking rather than simply reaching people who would have returned anyway. It runs once a day, per clinic, and treats a **randomized holdout experiment** as a first-class architectural component, not an afterthought — the platform is built to prove its own causal impact, not just report a correlation.

This report is organized into four chapters. Chapter I presents the host company, the problem, existing approaches and their limits, the proposed solution, and the requirement analysis. Chapter II presents the system and AI architecture: the EHR integration, the daily pipeline, the model choices, and the MLOps/governance design. Chapter III describes the implementation of each service. Chapter IV presents the evaluation methodology and the results obtained, together with the project's honest limitations. A general conclusion and future perspectives close the report.

---

# Chapter I — Adaptive AI for Patient Reactivation and Engagement Measurement

### Contents
I.1 Introduction · I.2 Host company and internship context · I.3 Problem statement · I.4 Study of existing solutions · I.5 Critique of existing solutions · I.6 Proposed solution · I.7 Basic concepts · I.8 Requirement analysis · I.9 Use case diagram · I.10 Project planning and development approach · I.11 Conclusion

## I.1 Introduction

This chapter presents the internship context, the operational problem this project addresses, the study and critique of existing patient-recall approaches, the proposed solution, the underlying concepts, the requirement analysis, the use case diagram, and the project's planning and development approach.

## I.2 Host company and internship context

### I.2.1 Host company presentation

Velodoc is a healthcare artificial intelligence startup founded in 2024, operating in the hospitals and health care sector, focused on AI systems embedded directly in healthcare workflows. It addresses administrative fragmentation in healthcare — doctors, billing teams, clinic owners, and front-desk teams working with disconnected tools, causing repeated work, manual follow-up, limited operational visibility, and delays. Velodoc develops healthcare workflow copilots and operational intelligence tools, with the explicit objective of supporting healthcare teams rather than replacing clinical or operational judgment.

### I.2.2 Internship mission

The mission for this internship was the **patient-reactivation and engagement-measurement** part of Velodoc's broader vision: build a system able to (1) detect, from a clinic's own patient population, every patient with a legitimate reason to be recontacted; (2) gate that list through consent and contact-frequency rules; (3) rank survivors with trained machine-learning models rather than a static priority; (4) dispatch outreach over WhatsApp with an automatic SMS fallback; (5) measure the causal effect of that outreach through a randomized holdout, not just report correlational outcomes; and (6) expose all of this through a role-gated web console for clinic staff, owners, and administrators.

### I.2.3 Collaboration tools

The project was developed through the same collaboration setup used across the Velodoc team: Notion for specifications, GitHub for source and version control, Discord for daily communication, and a shared DGX Spark environment for GPU-bound components (the clinical-note extraction model, described in Chapter III). Development also relied on a live Epic FHIR sandbox for real, non-synthetic EHR integration testing — a deliberate choice over building an EHR emulator from scratch, discussed in §I.5.

## I.3 Problem statement

A clinic's own patient population already contains most of the "leads" it needs — patients aren't lost to a competitor, they are simply never recontacted. Several distinct situations create a legitimate reason to reach back out: a patient hasn't visited in a long time relative to their own normal cadence (dormancy); a patient has an **open, incomplete treatment plan**; a patient's insurance benefit is about to expire, with no clinical or financial reason to let the window close unused; a clinical guideline indicates a recall is due (age, condition, medication); and several other operational patterns.

Even when a clinic recognizes this, three problems remain unsolved by a simple reminder system:

1. **No personalization of *whether* to contact.** A blanket campaign to everyone with an open reason ignores that some patients are highly unlikely to attend even if booked, some would attend regardless of any nudge, and some represent much higher expected value if they return than others.
2. **No enforcement of *who may legally be contacted about what*.** Consent for one type of contact (e.g., a routine recall) does not imply consent for another (e.g., a promotional offer) — a single flat "opted in" flag is not enough.
3. **No proof of causal impact.** A clinic that sees bookings rise after a campaign cannot distinguish "the campaign worked" from "these patients would have booked anyway" without a randomized comparison group.

The central problem this project addresses: *how can a system detect legitimate re-engagement opportunities across a clinic's own patient population, gate them through real consent and contact rules, rank them by trained models of expected value and likely response, dispatch outreach automatically, and prove — not assume — that the outreach caused incremental bookings?*

## I.4 Study of existing solutions

**Manual chart review and call lists.** The traditional approach: staff periodically review charts or run ad hoc reports to find patients due for follow-up, then call them. This does not scale past a small patient panel and depends entirely on staff bandwidth.

**Generic recall/reminder systems built into EHR or practice-management software.** Most EHR platforms support a basic recall flag (e.g., "due for a 6-month cleaning") and a bulk SMS/email blast. This handles one narrow recall type well but does not unify dormancy, open treatment plans, benefit expiry, and clinical-guideline recall into a single ranked list, and does not personalize contact order by predicted outcome.

**Mass marketing/CRM tools repurposed for healthcare.** General-purpose marketing automation platforms can segment and blast messages, but they are not built around per-contact-type consent, are not integrated with a clinical EHR as source of truth, and have no notion of a causal holdout to measure real impact versus noise.

**Academic and industry work on patient no-show/engagement prediction** exists (as surveyed extensively in the sister PFE report on no-show prediction and slot recovery from this same team), but that literature is concentrated on *predicting attendance for an already-booked appointment*, not on the earlier, upstream problem this project addresses: *deciding which never-booked patient to proactively reach out to in the first place, and proving the outreach caused the booking.*

## I.5 Critique of existing solutions

Existing recall tooling is narrow (one recall type at a time), consent-blind (a single opt-in flag rather than per-purpose consent classes), and unranked (patients are contacted in registration order or by a fixed static priority, never personalized by a trained model of expected outcome). Most critically, none of the surveyed approaches build in a mechanism to *prove* the campaign caused the observed bookings — without a randomized control group, a rise in bookings after a campaign is only ever a correlation.

## I.6 Proposed solution

The proposed solution is **Velo Engage**, branded to clinic end users as **VeloDoc**. It runs, once per clinic per day, a five-stage pipeline: **detect → gate → rank → dispatch → measure**.

- **Detect**: 16 independent, YAML-defined "opportunity family" rules evaluate every patient — dormancy, open treatment plans, benefit expiry, clinical recall (backed by a knowledge graph), and others — each carrying its own consent-class requirement and priority weight. One family is not rule-based at all: it uses a lookalike/collaborative-filtering model to suggest a family a patient has never used, based on similar patients who have.
- **Gate**: candidates are filtered down to patients who have specifically consented to *that* type of contact, have not been messaged too recently or too often, and have their multiple simultaneous reasons for contact collapsed into one.
- **Rank**: five trained machine-learning models — no-show risk, booking propensity, expected revenue, causal uplift, and predicted time-to-book — combine into a single expected-value ranking. A randomly-selected slice of the ranked population is deliberately **held back from contact entirely** (the holdout arm), regardless of rank, to measure the program's true causal effect.
- **Dispatch**: the highest-ranked, non-holdout patients (a deliberately capped number per day) receive a WhatsApp message, with automatic SMS fallback if delivery fails.
- **Measure**: replies, bookings, attendance, and revenue flow back automatically via webhooks, or are recorded manually when no automated feed exists yet, closing the loop for the next day's ranking and for eventual model retraining. Recovered revenue is weighed against outreach cost to produce a real ROI figure.

The EHR (Epic, via its FHIR API) remains the system of record for clinical data; Velo Engage reads from it, computes its own operational/predictive data in its own Postgres schema, and only ever writes back real, already-approved outreach actions (a WhatsApp message, a booking record) — never a clinical fact.

This implemented scope explicitly does **not** claim: production Epic credentials for a real (non-sandbox) clinic, formal Meta WhatsApp Business template approval at commercial scale, or a fully-reviewed clinical decision-support extension into treatment-pathway recommendation (a prototype for this last item is described as future work in Chapter III).

## I.7 Basic concepts

### I.7.1 Opportunity detection

The mechanism that decides *who* has a legitimate reason to be recontacted. Implemented as YAML-defined rules rather than code specifically so a non-engineer can review and edit the logic — most families are deterministic (thresholds on dormancy days, benefit-expiry windows), one is backed by a Neo4j clinical-guideline knowledge graph, and one is backed by a trained lookalike model.

### I.7.2 Consent and guardrails

Per-class consent (contacting a patient about a clinical recall does not imply consent for a promotional offer), contact cooldowns, and frequency caps that guarantee no patient is contacted more than once a day regardless of how many opportunity families matched them simultaneously.

### I.7.3 Expected-value ranking and causal uplift

Rather than ranking by a single risk score, five trained models are combined: **no-show risk** (will this patient miss the appointment if booked), **booking propensity** (will they book at all), **expected revenue** (what is this visit worth), **causal uplift** (a T-learner estimate of the *incremental* effect of contacting this specific patient, as opposed to their baseline probability of returning anyway), and **predicted time-to-book** (a survival-analysis estimate of how long until they book). A patient predicted to book anyway, with zero incremental uplift, should be ranked low even if their raw booking-propensity score is high — this is precisely the distinction a naive single-model ranking cannot make.

### I.7.4 The causal holdout experiment

A randomly-assigned slice of the population that is deliberately never contacted, regardless of how highly they would otherwise rank. Comparing the treated group's real booking rate against the holdout group's real booking rate is the only way this system can claim its outreach *caused* incremental bookings rather than simply having reached people who would have returned on their own.

### I.7.5 Clinical note intelligence

Unstructured clinical notes pulled from Epic are processed by a medical LLM (MedGemma) to extract structured diagnoses, medications, procedures, and follow-up recommendations, gated by a content-safety model (NemoGuard) and by non-LLM validation checks before anything is stored. Only structured output is persisted; raw note text is never retained.

### I.7.6 MLOps and governance

Every model is tracked, versioned, and promoted through MLflow. Rules, guardrails, and the pipeline's daily orchestration are handled by Temporal, giving every step of the daily run durable retries and a full execution history — the same infrastructure discipline the sister no-show/slot-recovery track applies to Airflow-scheduled retraining, applied here to a long-running, always-on workflow engine instead of a batch scheduler.

## I.8 Requirement analysis

### I.8.1 System actors

| Actor | Role in the system |
|---|---|
| Clinic staff | Views opportunities, campaigns, WhatsApp conversations, and bookings; monitors day-to-day operation. |
| Clinic owner | Everything staff can see, plus revenue and the holdout experiment's causal results. |
| Clinic administrator | Everything owner can see, plus model quality/drift monitoring and pipeline operations health. |
| Patient | Receives outreach on WhatsApp; replies to book, confirm, or opt out. |

### I.8.2 Functional requirements

| ID | Functional requirement |
|---|---|
| FR1 | Detect every patient matching at least one of 16 opportunity-family rules, once per clinic per day. |
| FR2 | Gate detected opportunities by per-class patient consent, contact cooldown, and frequency cap. |
| FR3 | Collapse multiple simultaneous opportunity matches for one patient into a single contact. |
| FR4 | Score every gated candidate with five trained ML models and combine them into one ranking. |
| FR5 | Randomly assign a holdout slice that is never contacted, independent of rank. |
| FR6 | Dispatch WhatsApp outreach to the highest-ranked, non-holdout candidates, capped per day. |
| FR7 | Fall back to SMS automatically on WhatsApp delivery failure. |
| FR8 | Ingest real patient, condition, encounter, procedure, and coverage data from Epic FHIR. |
| FR9 | Extract structured clinical information from unstructured notes, gated by a safety check. |
| FR10 | Record delivery status, replies, bookings, attendance, and revenue against each campaign. |
| FR11 | Allow manual outcome marking (booked/attended) when no automated feed exists, writing to the same tables an automated event would. |
| FR12 | Compare the treated and holdout arms' real booking rates to report a causal effect. |
| FR13 | Present all of the above through a role-gated web console (staff/owner/admin tiers). |
| FR14 | Track every model's training runs, versions, and promotion status. |

### I.8.3 Non-functional requirements

| Requirement | Description |
|---|---|
| Safety | Holdout-arm patients can never be marked booked/attended through the console — doing so would corrupt the causal comparison the holdout exists to protect. |
| Traceability | Every detected opportunity, gating decision, model score, dispatch, and outcome is persisted and auditable. |
| Explainability | The no-show score is accompanied by a SHAP breakdown so staff can see why a patient is considered high-risk. |
| Multi-tenancy | The platform serves multiple clinics from one deployment with fully isolated per-clinic data. |
| Idempotency | Every write (opportunity, campaign, outcome) is upsert-based; retrying an already-applied step never duplicates or corrupts state. |
| Fault isolation | An Epic, WhatsApp, or clinical-note-extraction failure degrades gracefully and never blocks the rest of the daily pipeline. |
| Consent-first | No outreach action is ever dispatched to a patient without a matching, class-specific consent record. |

### I.8.4 Implemented scope

| Scope | Elements |
|---|---|
| Implemented | Epic FHIR integration (OAuth interactive flow + Bulk Data export), 16 YAML opportunity families, per-class consent gating, cooldown/frequency caps, five trained ranking models plus a lookalike-discovery model and a WhatsApp-reply intent classifier, randomized holdout experiment, Temporal-orchestrated daily pipeline, WhatsApp (Meta Cloud API) dispatch with Twilio SMS fallback, clinical-note extraction (MedGemma + NemoGuard) on a GPU server, MLflow-tracked model registry, a Jinja2 + React console with role-gated pages, and full multi-clinic isolation. |
| Prototype / future work | A dental treatment-pathway state-machine model (personalized next-clinical-step suggestion) — deliberately scoped as engineering prototype only, gated behind clinical-advisor review before any real use (Chapter III, §III.14). |
| Not implemented / external dependency | A real (non-sandbox) production Epic connection for a live clinic, commercial-scale Meta WhatsApp template approval, and cross-module integration with the company's separate scheduling (Velo Desk) and billing/insurance (Velo Claim) products. |

## I.9 Use case diagram

*(Produce this from the running console: two primary human actors — Clinic Staff/Owner/Admin and Patient — mirror the sister report's diagram convention. Clinic-side use cases: view opportunities, view campaigns and journey status, review model scores and SHAP explanation, mark outcome manually, view WhatsApp conversations, view revenue and holdout results (owner), view model/pipeline health (admin). Patient-side use cases: receive WhatsApp outreach, reply to book/confirm, opt out. Epic and Meta/Twilio are external systems, not use-case actors, exactly as the EHR is excluded from the sister report's diagram and explained instead through the architecture chapter.)*

## I.10 Project planning and development approach

### I.10.1 Project team

The project involved the same category of academic, industrial, and technical guidance as the sister PFE track at Velodoc: an academic supervisor for scientific orientation and report quality, industrial supervisors (Wael Hilali, Bilel Said) for technical direction and system validation, and the intern author responsible for design, implementation, testing, evaluation, and documentation.

### I.10.2 Project development phases

The work proceeded through recognizable phases even though it was run iteratively rather than as a rigid waterfall: (1) Epic integration and data foundation; (2) opportunity detection and guardrails; (3) the five ranking models and the holdout experiment; (4) orchestration, dispatch, and the console; (5) clinical-note intelligence; (6) UI modernization and a full React migration; (7) documentation and defense preparation.

### I.10.3 Iterative development approach

Each subsystem was built, tested, and verified against the real running stack before the next was layered on top — Epic integration was verified against a live sandbox patient before the ranking models were trained against its output; the React console migration was verified page-by-page against a real, signed session cookie hitting the live container, confirming zero regression in the original server-rendered pages before each new page was added.

### I.10.4 Planning timeline

*(Produce a Gantt-style figure analogous to the sister report's Figure 3, with phases: Epic integration → Opportunity detection & guardrails → Ranking models & holdout → Orchestration, dispatch & console → Clinical-note intelligence → UI modernization & React migration → Documentation & defense prep.)*

## I.11 Conclusion

This chapter presented the internship context, the operational problem of unmanaged patient re-engagement, the limits of existing recall tooling, and the proposed Velo Engage solution: a rule-gated, ML-ranked, causally-measured outreach pipeline. The next chapter presents the technical architecture.

---

# Chapter II — System and AI Architecture

### Contents
II.1 Introduction · II.2 Architectural objectives and constraints · II.3 EHR-centered data architecture · II.4 Global system architecture · II.5 Main pipeline workflows · II.6 Model architecture and technical choices · II.7 MLOps and governance architecture · II.8 Conclusion

## II.1 Introduction

This chapter presents the technical architecture: how the system is organized around Epic as the clinical source of truth, the Temporal-orchestrated daily pipeline, the five ranking models plus the discovery and intent-classification models, the causal holdout mechanism, and the MLOps governance design.

## II.2 Architectural objectives and constraints

**Epic remains the source of truth for clinical data.** Velo Engage never invents or overrides clinical facts — it reads patient, condition, encounter, procedure, and coverage data from Epic's FHIR API, and its own database stores only operational/predictive data (opportunity records, model scores, campaigns, consent, outcomes).

**Rule-based safety, ML-based ranking — never the reverse.** Anything with a direct safety or compliance consequence (consent gating, contact cooldowns, holdout-arm protection) is deterministic rule logic. Machine learning is used exclusively to *rank* or *score* within a space of options the rule layer has already deemed valid — never to decide validity itself. This single principle governs every architectural decision described in this chapter and is the same principle that, in this project's later prototype work (Chapter III, §III.14), explicitly excludes an LLM from making any clinical-suggestion decision directly.

**Fault isolation per external dependency.** Epic, Meta/Twilio, and the GPU-hosted clinical-note model are each isolated in their own service, specifically so one external system's failure mode (an expired Epic sandbox token, a WhatsApp delivery failure, a cold-starting GPU model) cannot block the rest of the daily pipeline.

**Multi-clinic isolation.** Every table, every rule evaluation, and every model score is scoped by `clinic_id`; the platform runs one Temporal workflow per clinic per day, not one shared global run.

**Auditability of the causal claim.** Because the holdout experiment is the system's central evidentiary mechanism, the architecture treats "never contact a holdout patient" as an invariant enforced at the console's write layer, not merely a convention observed by the ranking logic.

## II.3 EHR-centered data architecture

`ve_connect` is the only service that talks to Epic directly. It implements two independent authentication flows with independent token lifetimes: an **interactive OAuth (PKCE) flow** used for individual-patient FHIR reads, and a separate **SMART Backend Services (client-credentials/JWT) flow** used only for Bulk Data `$export` against a defined patient cohort (a Group). These two flows can be in completely different states at once — the interactive token can be expired while Bulk Data exports keep succeeding — because they are unrelated credentials with unrelated lifetimes; this is a real, recurring characteristic of testing against Epic's non-production sandbox, not a defect.

`mapper.py` translates raw FHIR resources (`Patient`, `Condition`, `Encounter`, `Procedure`, `Coverage`, and — for clinical-note intelligence — `DocumentReference`/`Binary`) into the fields the platform's own schema needs: ICD-10 codes, last visit date, last procedure, coverage end date, phone number. Fetching is fault-tolerant per resource type — one Epic resource type being unavailable for this app's authorized scope degrades one derived feature to a safe default rather than blocking every other resource type Epic does authorize.

A diagnostic-only endpoint exposes the *exact* raw FHIR resources the real pipeline sees for a given patient, before any mapping — used to confirm data-quality issues (e.g., sandbox test/filler clinical notes) are a property of the sandbox data, not a pipeline defect, without ever persisting the raw payload to disk.

## II.4 Global system architecture

The platform is organized as a set of small, single-purpose services coordinated by Temporal and sharing a common Postgres database as the operational source of truth:

- **`ve_connect`** — Epic FHIR integration (patient data and clinical notes).
- **`ve_orchestrator`** — the Temporal-hosted daily workflow: detect, gate, rank, dispatch.
- **`ve_reach`** — WhatsApp/SMS sending and inbound webhook handling (delivery status, replies, opt-outs).
- **`ve_measure`** — booking and revenue attribution from real-world events.
- **`ve_console`** — the web application (Jinja2 server-rendered pages and a parallel React single-page application, both serving identical data through a shared JSON API layer).
- **`ve_clinical_intel`** — clinical-note structured extraction, running on a GPU server (DGX Spark) separate from the rest of the stack.

Supporting infrastructure: **PostgreSQL** (patients, campaigns, outcomes, consent, revenue — the shared operational store nearly every service reads/writes), **Neo4j** (the clinical-recall knowledge graph queried by one opportunity family), **Redis** (a short-lived feature cache in front of Postgres during ranking), **MLflow** (every model's training runs, versions, and the production pointer the daily pipeline loads at ranking time), **Keycloak** (OIDC login for the console), **HashiCorp Vault** (every service's credentials, read once at startup with an environment-variable fallback so a transient Vault outage never blocks the pipeline), and **NATS JetStream** (the one genuinely asynchronous handoff in the system: `ve_orchestrator` publishes a dispatch-ready campaign, `ve_reach` consumes and sends it, decoupled so a slow or unavailable send never blocks the ranking pipeline itself).

Communication patterns follow a consistent rule: Postgres for shared state that any service can read directly; NATS JetStream for the one asynchronous cross-service handoff; plain HTTP for direct request/response between services with no shared database access (`ve_clinical_intel`, on the GPU server, calling `ve_connect`'s REST API); and inbound webhooks for external events (Meta delivering delivery-status and reply events to `ve_reach`). Epic never pushes anything — `ve_connect` pulls from Epic on the orchestrator's own schedule.

## II.5 Main pipeline workflows

### II.5.1 The daily detect–gate–rank–dispatch–measure workflow

Every service above is orchestrated by a single Temporal workflow (`DailyEngagementWorkflow`), running once per clinic per day, composed of retryable, independently-executed activities:

1. **Refresh data** — a best-effort pull of the latest Epic data and a recomputation of behavioral features (visit history, no-show history, message engagement). This activity deliberately swallows its own errors: an Epic hiccup should degrade gracefully, not halt the pipeline.
2. **Detect** — the 16 opportunity-family rules are evaluated against every patient's current feature row.
3. **Gate** — candidates are filtered to those with matching per-class consent, respecting cooldown and frequency-cap constraints, and collapsed to one contact per patient per day.
4. **Rank** — the five ranking models score every survivor and combine into one expected-value ranking; a randomly-selected slice is independently assigned to the holdout arm regardless of rank.
5. **Dispatch** — the highest-ranked, non-holdout candidates (a capped daily number) are sent to `ve_reach` for WhatsApp delivery, with automatic SMS fallback.
6. **Measure** — delivery status, replies, bookings, attendance, and revenue flow back automatically via webhooks (or are recorded manually where no automated feed exists), closing the loop for the next day's ranking and eventual model retraining, and producing the ROI figure shown on the console's dashboard.

### II.5.2 Opportunity detection

Sixteen independent, YAML-defined "opportunity families" — most deterministic threshold rules (dormancy days, benefit-expiry windows, open treatment-plan flags), one backed by a Neo4j clinical-guideline graph, and one backed by a lookalike/collaborative-filtering model that recommends a family a patient has never used based on similar patients who have.

### II.5.3 Guardrails and consent

Per-class consent checking (a patient consenting to a routine recall does not imply consent to a promotional contact), contact cooldowns, frequency caps, and de-duplication so a patient matching multiple opportunity families in the same run is still contacted at most once.

### II.5.4 The causal holdout experiment

A randomly-assigned slice of the ranked population that is never contacted, entirely independent of how highly it would otherwise rank. Comparing this arm's real booking rate against the treated arm's is the platform's mechanism for proving incremental causal impact rather than correlation — and this arm's protection is enforced structurally: the console's outcome-marking endpoint rejects, with an explicit `400` response and explanation shown in the UI, any attempt to mark a holdout patient as booked or attended, since doing so would corrupt the exact comparison the holdout exists to protect.

### II.5.5 WhatsApp dispatch and reply handling

WhatsApp (Meta Cloud API) is the primary channel; Twilio SMS is the automatic fallback on delivery failure. Inbound replies are parsed for booking intent and opt-out requests by a trained intent classifier, and every message (outbound and inbound) is logged for the console's conversation view.

### II.5.6 Clinical note intelligence

Unstructured clinical notes pulled from Epic (`DocumentReference`/`Binary`) are passed through a content-safety check (NemoGuard) before ever reaching the extraction model; a medical LLM (MedGemma) then extracts structured diagnoses, medications, procedures, and follow-up recommendations; non-LLM validation checks (well-formed code shapes, non-empty fields) flag anything that doesn't parse cleanly rather than silently discarding it. Only the structured output is persisted — raw note text is discarded after extraction, matching this project's no-raw-retention discipline for the most sensitive category of data it ever touches.

## II.6 Model architecture and technical choices

### II.6.1 No-show risk model

A CatBoost/LightGBM gradient-boosted classifier trained on a research-guided synthetic dataset of 110,000 UAE/KSA-style appointment records, using booking-time and historical behavioral features (prior no-show ratio, consecutive no-show streak, lead time, same-day booking flag, age, deposit status, travel time, cancellation history, VIP status, new-patient flag, urgency, neighborhood no-show rate, and provider effect, among others). Gradient-boosted trees were chosen over deep-learning alternatives for the same reason this choice is made throughout the platform's other tabular scoring tasks: strong performance on mixed categorical/numerical tabular data without heavy manual encoding, native SHAP explainability, and millisecond-scale inference cost appropriate for scoring an entire clinic's patient population daily.

### II.6.2 Booking propensity model

Estimates the probability a candidate books at all if contacted, independent of no-show risk — a patient can be very likely to book yet, once booked, still carry meaningful no-show risk; conflating the two into one score would lose exactly the distinction the ranking formula needs.

### II.6.3 Expected-value (revenue) model

Estimates the expected monetary value of a visit for a given patient/opportunity combination, so the ranking can prefer a lower-propensity but much higher-value opportunity over a high-propensity, low-value one when that trade-off is worth it.

### II.6.4 Causal uplift model (T-learner)

A two-model (treatment/control) T-learner estimating the *incremental* effect of contact for a specific patient — the probability they book *because* they were contacted, over and above their baseline probability of booking anyway. This is why the uplift score can legitimately be negative: for a patient predicted to book slightly *less* often when contacted than when left alone (a plausible real phenomenon — e.g., a contact that reads as impersonal spam to a patient who would have called in on their own), the honest estimate is negative, and the ranking formula applies a steep discount to negative-uplift candidates rather than clipping the score to zero and hiding the signal.

### II.6.5 Survival model (predicted time-to-book)

A time-to-event model estimating how long until a given patient books if contacted, letting the platform distinguish "will book soon" from "will book eventually" opportunities when the daily dispatch cap forces a choice between them.

### II.6.6 Lookalike/discovery model

Used only for one opportunity family: a collaborative-filtering-style model that recommends a family a patient has never used, based on the behavior of similar patients — the one place in opportunity *detection* (as opposed to ranking) where a model, rather than a deterministic rule, decides whether a candidate reason exists at all, since "similarity to other patients" is inherently a learned relationship rather than a fixed threshold.

### II.6.7 WhatsApp reply intent classifier

A lightweight classifier trained to distinguish booking intent, confirmation, cancellation/opt-out, and ambiguous replies from inbound WhatsApp messages, feeding the reply-handling logic in `ve_reach`.

### II.6.8 Why not a single end-to-end model, and why not an LLM for ranking

A single model predicting "will this patient book" cannot, by construction, separate *causation* from *correlation* — this is precisely the gap the dedicated uplift model and the randomized holdout close together. Equally, an LLM was deliberately not used anywhere in the ranking or detection decision itself: ranking is a structured, tabular-feature scoring problem gradient-boosted trees solve well, cheaply, and with a clean SHAP-based explanation; an LLM applied to that problem would add hallucination risk, latency, and cost while solving nothing an LLM is actually good at. The one place a language model is used at all — clinical-note extraction — is precisely the one place the problem genuinely requires understanding unstructured text, and even there it is bounded by a safety-content gate and non-LLM validation before its output is trusted.

## II.7 MLOps and governance architecture

Every model is trained via a dedicated script (`ml/training/train_*.py`), tracked in **MLflow** with its metrics, and served in production via a paired registry/scorer module (`ml/registry/*_scorer.py`) that the daily Temporal workflow loads at ranking time. Promotion from a newly-trained candidate to the production pointer (`ml/registry/promote.py`) is a deliberate, auditable step rather than automatic — mirroring, in spirit, the same "candidate must clear evaluation and audit gates before the runtime system uses it" discipline used elsewhere in the Velodoc team's MLOps designs, adapted here to a registry-pointer promotion rather than a scheduled retraining DAG, since the ranking models are retrained on a slower, less time-critical cadence than a per-message online scorer would need.

## II.8 Conclusion

This chapter presented the EHR-centered data architecture, the global service architecture, the daily detect–gate–rank–dispatch–measure pipeline, the five ranking models plus the discovery and intent models, and the MLOps governance design. The next chapter describes how this architecture was implemented.

---

# Chapter III — Implementation of the Velo Engage (VeloDoc) Application

### Contents
III.1 Introduction · III.2 Development environment and technology stack · III.3 Epic integration implementation · III.4 Orchestration implementation · III.5 Database design · III.6 Opportunity detection and guardrails implementation · III.7 Ranking model implementation · III.8 Causal holdout implementation · III.9 Communication channel implementation · III.10 Clinical note intelligence implementation · III.11 Console implementation · III.12 MLOps implementation · III.13 Dockerization and deployment · III.14 Prototype extension: dental treatment-pathway model · III.15 Conclusion

## III.1 Introduction

This chapter describes how the architecture in Chapter II was translated into a working system: the technology stack, and the implementation of each service in the pipeline, closing with an honest account of a scoped, deliberately-limited prototype extension explored beyond the core mission.

## III.2 Development environment and technology stack

| Tool / component | Role |
|---|---|
| Python | Primary language for every backend service, training script, and workflow activity. |
| FastAPI | API framework for every service (`ve_connect`, `ve_orchestrator`'s HTTP surfaces, `ve_reach`, `ve_measure`, `ve_console`, `ve_clinical_intel`). |
| Temporal | Workflow engine orchestrating the daily detect–gate–rank–dispatch pipeline, one workflow per clinic per day, with durable retries and full execution history. |
| PostgreSQL | Shared operational store: patients, campaigns, outcomes, consent, revenue. |
| Neo4j | The clinical-recall knowledge graph queried by one opportunity family. |
| Redis | Short-lived feature cache in front of Postgres during ranking. |
| MLflow | Experiment tracking and model registry for all trained models. |
| CatBoost / LightGBM / scikit-learn | The ranking, discovery, and intent-classification models. |
| MedGemma + NVIDIA NemoGuard | Clinical-note structured extraction and its content-safety gate, hosted on a DGX Spark GPU server. |
| Meta WhatsApp Business Cloud API, Twilio | Primary outreach channel and its automatic SMS fallback. |
| Epic FHIR (SMART on FHIR, Bulk Data Export) | Real patient data and clinical-note ingestion. |
| Jinja2 + React/TypeScript (Vite) | The console's two frontends, serving identical data through a shared JSON API. |
| Keycloak (OIDC) | Console authentication. |
| HashiCorp Vault | Centralized secrets, with an environment-variable fallback if unreachable. |
| NATS JetStream | The asynchronous orchestrator→reach dispatch handoff. |
| Docker / Docker Compose | Reproducible multi-service local and DGX Spark deployment. |

## III.3 Epic integration implementation

`ve_connect` implements `auth.py` (interactive PKCE OAuth), `bulk_auth.py` (SMART Backend Services JWT client-assertion for Bulk Data), `fhir_client.py` (resource fetch/search with automatic Bundle pagination), `epic_bulk.py` (the `$export` flow against a Group, polling its status URL, downloading the resulting NDJSON files, and deleting the export afterward), `mapper.py` (FHIR-to-internal-schema translation), and `adapter.py` (the write path into `staging_patients`/`patient_features`/`consent`, upserted in one transaction per patient). Two real, silent bugs were found and fixed during Epic sandbox testing: `Encounter.class` filtering initially assumed standard FHIR coding and matched zero real Epic encounters, since Epic populates it with a proprietary internal code system; and `CarePlan` fetching, rejected by the app's authorized scope in two different ways, was made fault-tolerant so one unavailable resource type degrades a single derived flag rather than blocking every other resource type the app *is* authorized for.

## III.4 Orchestration implementation

`ve_orchestrator` implements `workflows.py` (the `DailyEngagementWorkflow` Temporal definition), `activities.py` (each pipeline stage as an independently retryable activity — activities pass only IDs between each other and re-fetch their own data from Postgres, keeping every activity result well under Temporal's payload limits), `policy_engine.py` (loading and safely evaluating the YAML opportunity-family rules, with a validator that rejects a malformed policy file at load time rather than at runtime), `graph_client.py` (the Neo4j clinical-recall query), `feature_store.py` (the Redis-backed feature cache), and `historical_features.py` (a dedicated ETL recomputing the no-show model's required historical features, since patient behavioral history is not something Epic itself exposes as a ready-made feature set).

## III.5 Database design

A single PostgreSQL instance holds every operational table, with `clinic_id` on every row as the multi-tenant isolation key. Migrations are applied in strict numerical order (`infra/migrations/001_*.sql` through the current head), each migration documenting, in its own header comment, exactly what gap it closes and why — a discipline carried through every schema change made across this project, including the dental-pathway prototype's own migration (§III.14).

## III.6 Opportunity detection and guardrails implementation

Opportunity families are plain YAML files (`policies/opportunities/*.yml`), each declaring a `family` id, a `consent_class`, a `priority`, and a set of conditions evaluated against a patient's feature row by pure, independently unit-tested functions (`conditions_match`, `evaluate_policy`, `build_evidence`) — deliberately kept free of any database or Temporal dependency so the rule-matching logic itself can be tested exhaustively without standing up any infrastructure. Guardrails (consent-class checking, cooldown, frequency cap, de-duplication) are implemented as a separate gating activity applied after detection and before ranking.

## III.7 Ranking model implementation

Each of the five models follows the same paired convention: a training script (`ml/training/train_*.py`) that produces an MLflow-tracked artifact, and a registry/scorer module (`ml/registry/*_scorer.py`) with a documented `DEFAULTS` fallback used whenever a patient's feature row is incomplete — so a missing historical feature degrades to a known, safe default score rather than raising an exception or silently returning a wrong ranking. The no-show model's 32-feature contract is enforced end to end: a dedicated migration and ETL (`historical_features.py`) exist specifically to keep `patient_features` populated with every column the scorer's feature contract requires, closing a gap where several columns previously fell back to their `DEFAULTS` value for every patient regardless of that patient's real history.

## III.8 Causal holdout implementation

Holdout assignment happens inside the same ranking activity that computes the expected-value score, using a deterministic, seeded random assignment so a given patient's holdout status is reproducible for a given run rather than re-rolled arbitrarily. The console enforces the holdout arm's protection at the write layer: the outcome-marking endpoint checks a campaign's arm before accepting a "booked" or "attended" mark, returning an explicit `400` with an explanation surfaced in the UI (rather than the buttons simply not appearing) if a holdout campaign is targeted, so a coordinator understands *why* the action is refused rather than assuming a bug.

## III.9 Communication channel implementation

`ve_reach` sends WhatsApp messages via the Meta Cloud API and automatically falls back to Twilio SMS on delivery failure; inbound webhooks from Meta (delivery status, replies) are received and routed to the intent classifier for reply parsing. A real deployment constraint surfaced during this work: ngrok's free tier grants exactly one reserved public domain, which both WhatsApp's inbound webhook and Epic's OAuth redirect needed simultaneously. This was solved permanently, not with a manual workaround, by adding three proxy routes to `ve_reach` (`/auth/login`, `/auth/callback`, `/`) that forward Epic's OAuth traffic over the internal Docker network to `ve_connect`'s real handlers and relay the response verbatim — one public tunnel now serves both purposes permanently, verified live through the actual public tunnel rather than only against localhost.

## III.10 Clinical note intelligence implementation

`ve_clinical_intel` runs on a separate DGX Spark GPU server, calling `ve_connect`'s REST API to fetch notes (never given direct database access from the GPU host) and to store extractions. The extraction pipeline is: content-safety check (NemoGuard) first — a note that fails this check is never sent to the extraction model at all — then structured extraction (MedGemma, a 27-billion-parameter text-focused medical model, accessed via a streaming server-sent-events API accumulated into a full response before parsing), then non-LLM validation of the parsed structure, then storage. A real, non-obvious finding from this work: some real Epic sandbox patients' clinical notes are themselves sandbox connectivity-test filler text or repeated-character load-test artifacts, not genuine clinical documentation — explaining, correctly, why extraction sometimes returns an empty result for a given note. This was confirmed, not assumed, by inspecting the actual raw note text through a diagnostic endpoint that returns exactly what the extraction pipeline itself receives, before concluding anything was broken in the extraction logic.

## III.11 Console implementation

`ve_console` is implemented twice over the same data and the same authentication: a server-rendered Jinja2 application (the original implementation) and a React + TypeScript single-page application mounted at `/app`, both calling the *same* underlying data-fetch functions (`_overview_data()`, `_campaigns_data()`, and so on for every page) so the two frontends can never drift apart in what they display. The React migration was executed incrementally, one page verified before the next, using a genuinely-signed session cookie to test the real running container end to end — confirming every original page's behavior was unchanged *after* the migration, not merely assumed unchanged before it. Role gating (staff/owner/admin) is additive, checked by testing for either role granting a given tier rather than a separate expansion step.

## III.12 MLOps implementation

Model training scripts, MLflow experiment tracking, and the registry-promotion step (`ml/registry/promote.py`) together form the platform's MLOps surface. Every registered model version is queryable from the console's model-health page (role-gated to administrators), alongside drift and quality metrics for the no-show model specifically, since it is the model with the most mature retraining pipeline in this implementation.

## III.13 Dockerization and deployment

The full stack (Postgres, Neo4j, Redis, NATS, Temporal, Keycloak, Vault, MLflow, and every service above) is defined in a single `docker-compose.dev.yml`, with `ve_console`'s image built as a two-stage Docker build (a Node.js stage compiling the React frontend, copied into the final Python runtime image so the running container never needs Node at all). `ve_clinical_intel` and the underlying model server run on the DGX Spark GPU host, reachable from the rest of the stack over the team's shared network.

## III.14 Prototype extension: personalized dental treatment-pathway suggestion (future work, explicitly scoped as a prototype)

Beyond the core reactivation-and-measurement mission, an exploratory extension was designed and partially scaffolded: a state-machine model that suggests the clinically appropriate *next step* in a dental treatment sequence (e.g., a confirmed deep-caries diagnosis → root canal → crown), personalized per patient rather than looked up from a generic protocol.

This is deliberately treated as a **prototype, not a production feature**, for reasons consistent with this whole project's governing principle (§II.2): a wrong clinical suggestion carries real consequence, so the design places a clinician-authored, YAML-defined rule graph as the sole authority over which transitions are *valid*, with machine learning used only to *rank* among the options the graph already permits — never to invent a transition. Each patient-case's position in the graph is modeled as a Temporal workflow instance (Temporal workflows already are durable state machines, so this reuses the same orchestration engine the core pipeline runs on rather than building a second one), advanced by a signal when new procedure data arrives and resolved by a clinician's explicit accept/override decision whenever more than one transition is simultaneously valid. A sibling service (`ve_connect_dental`) was scaffolded to pull real dental procedure history from OpenDental (a practice-management system distinct from Epic, since standalone dental clinics typically do not run Epic), behind a transport-agnostic client interface so a direct-database Phase A (self-hosted, requiring no external registration) can later be swapped for OpenDental's official REST API without touching the mapping or state-machine logic above it.

Nothing produced by this prototype has been reviewed by a dental clinical advisor, and the codebase enforces this honestly rather than silently: every new file in this extension states its `prototype` status explicitly, and the design's own documentation records, as an open item, that production use requires exactly two things this internship's scope did not include — a named clinical reviewer signing off on the pathway graph, and a confirmed real dental-PMS data source for a specific pilot clinic. It is presented here only as evidence of the architecture's extensibility, not as delivered scope.

## III.15 Conclusion

This chapter described the implementation of every service in the pipeline: Epic integration, orchestration, opportunity detection and guardrails, the five ranking models, the causal holdout, WhatsApp/SMS dispatch, clinical-note intelligence, the console, MLOps, deployment, and an honestly-scoped prototype extension. The next chapter presents the evaluation and validation of the implemented system.

---

# Chapter IV — Evaluation and Validation

### Contents
IV.1 Introduction · IV.2 Evaluation methodology · IV.3 No-show model evaluation · IV.4 Other ranking models · IV.5 Guardrail and consent verification · IV.6 Console and React-migration verification · IV.7 End-to-end system testing · IV.8 Discussion and limitations · IV.9 Conclusion

## IV.1 Introduction

This chapter presents the evaluation methodology, the results actually obtained, and this project's honest limitations. Consistent with the rest of this report, every number cited below is drawn directly from this project's own repository artifacts (`ml/data/`, `ml/data/reports/`) rather than restated from memory, and every cell that depends on a metric not yet re-extracted at the time of writing is marked for you to fill from the current MLflow registry before submission, rather than filled with an invented figure.

## IV.2 Evaluation methodology

The no-show model was trained and evaluated on a research-guided synthetic dataset of **110,000 UAE/KSA-style appointment records** (file: `synthetic_no_show_uae_ksa_110k`), constructed the same way the sister PFE track's own no-show simulator was built — from probability effects extracted from outpatient no-show literature rather than arbitrary random labels — so the simulated label follows a realistic risk structure. The dataset's observed base no-show rate is **22.0%** (mean of the `no_show` column across all rows), with feature distributions summarized directly from the dataset (Table IV.1). Evaluation used held-out test splits and standard probabilistic-classification metrics (ROC-AUC, PR-AUC, Brier score, expected calibration error, precision/recall/F1), consistent with the rest of this platform's scoring tasks being trained on tabular gradient-boosted models.

**Table IV.1 — Selected feature distributions, 110k synthetic no-show dataset**

| Feature | Mean | Std | Min | Max |
|---|---|---|---|---|
| prior_no_show_ratio | 0.173 | 0.143 | 0.0 | 0.903 |
| consecutive_no_show_streak | 0.189 | 0.487 | 0.0 | 6.0 |
| lead_time_days | 11.54 | 9.23 | 0.0 | 87.0 |
| same_day_flag | 0.102 | 0.302 | 0.0 | 1.0 |
| age | 36.49 | 12.09 | 18.0 | 80.0 |
| deposit_paid | 0.383 | 0.486 | 0.0 | 1.0 |
| travel_time_minutes | 22.69 | 9.40 | 3.0 | 63.4 |
| cancellation_history_ratio | 0.143 | 0.088 | 0.0003 | 0.589 |
| vip_status | 0.090 | 0.286 | 0.0 | 1.0 |
| new_patient | 0.280 | 0.449 | 0.0 | 1.0 |
| urgency_score | 5.68 | 2.31 | 1.0 | 10.0 |
| neighbourhood_ns_rate | 0.092 | 0.038 | 0.050 | 0.226 |
| no_show (target) | 0.220 | 0.414 | 0.0 | 1.0 |

**Table IV.2 — Top feature-importance contributors (no-show model)**

| Feature | Relative importance (%) |
|---|---|
| same_day_flag | 19.62 |
| lead_time_days | 11.77 |
| specialty | 10.62 |
| prior_no_show_ratio | 9.57 |
| confirmation_status | 6.50 |
| cancellation_history_ratio | 5.40 |
| treatment_stage | 5.39 |
| deposit_paid | 4.33 |
| travel_time_minutes | 4.12 |
| whatsapp_engagement | 3.15 |

## IV.3 No-show risk model evaluation

The no-show model was evaluated across two staged configurations reflecting how much lead time is available before an appointment: a **booking-time** stage (scored the moment an appointment is created) and a **pre-appointment** stage (scored closer to the visit, with more accumulated behavioral signal available). Table IV.3 reports the two-stage evaluation actually recorded for this model.

**Table IV.3 — No-show model, two-stage evaluation**

| Stage | Threshold | ROC-AUC | PR-AUC | Brier score | Log loss |
|---|---|---|---|---|---|
| Booking-time | 0.250 | 0.7353 | 0.4900 | 0.1471 | 0.4598 |
| Pre-appointment | 0.270 | 0.7514 | 0.5336 | 0.1417 | 0.4466 |

As expected, the pre-appointment stage — scored with more accumulated signal — improves both discrimination (ROC-AUC) and probability quality (Brier score, log loss) over the booking-time stage, confirming the value of the online/behavioral feature refresh the pipeline performs before each day's ranking run (Chapter II, §II.5.1).

A second evaluation compared two candidate feature-encoding strategies for handling missing historical data — a "two-stage" approach and a "single-missingness-indicator" approach — across both the booking and pre-appointment stages, on both train and held-out test splits (Table IV.4), to decide which encoding strategy to standardize on.

**Table IV.4 — Feature-encoding strategy comparison (test split)**

| Approach | Stage | ROC-AUC | PR-AUC | Brier | ECE |
|---|---|---|---|---|---|
| Two-stage encoding | Booking | 0.6695 | 0.4552 | 0.1838 | 0.00988 |
| Single-missingness indicator | Booking | 0.6702 | 0.4565 | 0.1836 | 0.00750 |
| Two-stage encoding | Pre-appointment | 0.7333 | 0.5420 | 0.1698 | 0.01265 |
| Single-missingness indicator | Pre-appointment | 0.7327 | 0.5419 | 0.1699 | 0.01378 |

The two strategies perform nearly identically (aggregate composite scores of 6.9998 vs. 0.0 on the internal selection metric, driven mainly by a marginal calibration-error difference rather than any meaningful discrimination gap), which is itself a useful negative result: it means the simpler, more maintainable encoding strategy can be adopted without sacrificing measurable model quality — consistent with this project's general preference for the simplest design that meets the requirement, rather than the most sophisticated one.

## IV.4 Other ranking models (booking propensity, expected value, uplift, survival) and the discovery/intent models

*[Fill this section from your current MLflow registry before submission — do not restate a number from an earlier draft or from memory. For each model, report: the metric(s) appropriate to its task (ROC-AUC/PR-AUC for propensity; MAE/RMSE for expected-value regression; the qini coefficient or a similar uplift-specific metric for the T-learner uplift model, since ROC-AUC is not a meaningful metric for uplift; concordance index for the survival model; top-k precision or silhouette-style similarity metrics for the lookalike model; accuracy/F1 for the WhatsApp intent classifier), the dataset it was evaluated on, and the currently-registered MLflow version. This section is intentionally left as a template rather than populated with placeholder numbers, because — unlike the no-show model above — this report could not verify a currently-recorded evaluation artifact for these five models at the time of writing; stating a number here without that verification would misrepresent the project's actual results.]*

## IV.5 Guardrail and consent verification

The guardrail and consent-gating logic (per-class consent matching, cooldown, frequency cap, de-duplication) is covered by dedicated unit tests exercising the pure rule-matching functions directly — asserting, among other cases, that a missing feature causes a rule to correctly evaluate as non-matching rather than raising an exception, that a `contains_prefix` condition correctly matches both bare and full-precision ICD-10 codes (since synthetic seed data and real Epic data represent the same clinical category at different precision), and that nested `all`/`any` condition trees evaluate correctly. The holdout-arm protection was verified functionally against the live console: an attempt to mark a holdout campaign's outcome as booked or attended is rejected with an explicit `400` response, and the corresponding UI buttons are replaced with an explanation rather than silently hidden.

## IV.6 Console and React-migration verification

The console's dual-frontend architecture (Jinja2 and React, sharing one data-fetch layer and one JSON API) was verified end to end using a genuinely-signed session cookie — built to match the authentication middleware's exact cookie format — to exercise the real running container rather than a bypassed test harness. This confirmed: every one of the eleven migrated pages' new JSON API endpoints return real, live data consistent with the original server-rendered page (including nested cases such as the models page's full set of registered model cards and versions, and the holdout page's real per-arm booking rates); every React route loads correctly on a direct page load as well as through client-side navigation; the outcome-marking mutation writes correctly to both the bookings and outcomes tables and correctly rejects a holdout-campaign attempt through both the HTML form and the JSON API path; and — the specific regression risk a UI rewrite of this kind carries — every original Jinja route continues to return identical output after the migration, not merely before it.

## IV.7 End-to-end system testing

End-to-end verification exercised the full pipeline against a real Epic sandbox connection rather than only synthetic data: a live patient cohort was pulled through the interactive OAuth flow, opportunity families were evaluated against the resulting feature rows, guardrails were applied, the five models scored the surviving candidates, holdout assignment was applied, and a real WhatsApp message was dispatched and its delivery status received back through the live public tunnel — end to end, not simulated at any stage. The clinical-note extraction pipeline was separately verified against real Epic sandbox patients' `DocumentReference` notes, confirmed via a raw-data diagnostic endpoint to correctly distinguish "search failed" from "genuinely zero notes" for a given patient, and confirmed to correctly recognize sandbox filler/test note content as content that legitimately yields no structured extraction, rather than misreporting it as a pipeline defect.

## IV.8 Discussion and limitations

The principal limitation of this work is the same one the sister PFE track states honestly for its own model: **the no-show model, and every other ranking model in this pipeline, is trained on research-guided synthetic data, not real clinic history**, because real appointment and outreach outcome data was not available during this internship. The synthetic dataset's probability structure follows outpatient no-show literature rather than arbitrary labels, and the model's feature-importance ranking (Table IV.2) is directionally consistent with that literature (recent booking behavior, lead time, and specialty dominate, matching what published no-show studies report as the strongest predictors) — but real clinic validation, with real subgroup behavior by provider, service, and patient population, remains the necessary next step before any claim of real-world predictive accuracy.

The causal holdout experiment's design is sound and enforced structurally in the codebase, but its *statistical power* — how quickly it can detect a real effect at a given confidence level — depends on real patient volume and real booking-rate variance that a synthetic dataset cannot substitute for; this can only be assessed once the system runs against a real clinic's ongoing patient population.

The clinical-note intelligence pipeline's practical accuracy is bounded by the same limitation this project already documented honestly during development: a meaningful share of the real Epic sandbox's own clinical-note content is itself sandbox connectivity-test filler rather than genuine documentation, which understates what extraction accuracy against real clinical notes would actually look like.

Finally, several pieces of this platform's broader design are explicitly out of scope as delivered work rather than claimed as done: a production (non-sandbox) Epic connection for a real clinic, commercial-scale WhatsApp Business template approval, and the cross-module integration this platform's design anticipates with the company's separate scheduling and billing/insurance products — plus the dental treatment-pathway prototype (Chapter III, §III.14), which remains deliberately unreviewed and unshipped pending a named clinical advisor's sign-off.

## IV.9 Conclusion

This chapter presented the evaluation methodology, the no-show model's genuinely recorded two-stage and feature-encoding-strategy results, the guardrail and holdout-protection verification, the console migration's end-to-end verification, and the project's honest limitations — chiefly, the reliance on research-guided synthetic training data pending real clinic validation.

---

## General conclusion

This PFE internship focused on the design and implementation of Velo Engage (VeloDoc), a rule-gated, machine-learning-ranked, causally-measured patient-reactivation platform for outpatient clinics. The project addressed a concrete operational gap distinct from the sister PFE track's no-show/slot-recovery focus: not predicting whether an *already-booked* appointment will be attended, but deciding, from a clinic's own dormant patient population, *who should be proactively contacted at all*, and proving that the outreach caused real incremental bookings rather than merely reaching people who would have returned regardless.

The proposed solution keeps Epic as the clinical source of truth throughout, applies deterministic rule logic to every decision with a real safety or compliance consequence (consent gating, contact frequency, holdout-arm protection), and reserves machine learning for what it is genuinely good at — ranking within a space of options the rule layer has already validated. Five trained models (no-show risk, booking propensity, expected revenue, causal uplift, and predicted time-to-book) combine into a single expected-value ranking, a randomized holdout arm is enforced structurally rather than by convention, and a separate clinical-note intelligence pipeline extracts structured information from unstructured Epic notes under an explicit content-safety gate.

The evaluation presented in Chapter IV is honest about what has and has not been verified: the no-show model's two-stage and feature-encoding-strategy results are drawn directly from this project's own recorded artifacts; the guardrail, holdout-protection, and console-migration behavior were verified functionally and end to end against the real running system, including a live Epic sandbox connection and a live WhatsApp delivery round trip; and the remaining four ranking models' final metrics, together with real-clinic validation of the entire pipeline, remain the clearly identified next steps rather than claimed results.

As future perspectives, the immediate priorities are: recalibrating every ranking model against real clinic outcome data once a pilot clinic's real Epic connection and real WhatsApp Business API deployment exist; measuring the holdout experiment's actual statistical power against real patient volume; and — should the company's broader vision proceed in this direction — advancing the dental treatment-pathway prototype only behind a named clinical advisor's review of its rule graph, exactly as this report has scoped it throughout. A further perspective, consistent with the company's own stated broader vision, is integrating this platform with Velodoc's separate scheduling and billing/insurance products, so a detected re-engagement opportunity, once acted on, flows through to a real booked appointment and a real, attributable revenue outcome rather than stopping at outreach alone.

---

## Bibliography

*[Populate with the sources actually consulted — this draft references, by architectural analogy, the same category of literature the sister PFE report cites for no-show prediction, causal/uplift modeling (T-learner methodology), contextual explainability (SHAP), FHIR/SMART-on-FHIR integration patterns, and MLOps governance (concept drift, hidden technical debt in ML systems). Insert your own real citations before submission — do not copy the sister report's numbered list verbatim, since several of those sources are specific to no-show/waitlist modeling rather than to causal uplift, opportunity detection, or FHIR integration, which this report's own bibliography should cite directly.]*

---

## Appendices

### A.1 Main API endpoint groups

| Endpoint group | Purpose |
|---|---|
| `/pull-cohort`, `/pull-bulk`, `/pull-bulk-sync` (`ve_connect`) | Epic patient cohort ingestion (background and synchronous variants). |
| `/patients/{id}/clinical-notes`, `/patients/{id}/raw` (`ve_connect`) | Clinical-note retrieval and raw-FHIR diagnostic access. |
| `/auth/login`, `/auth/callback` (`ve_connect`, proxied via `ve_reach`) | Epic OAuth interactive flow. |
| `/api/v1/overview`, `/api/v1/opportunities`, `/api/v1/campaigns`, `/api/v1/campaigns/{id}` (`ve_console`) | Console JSON API — opportunities and campaign detail. |
| `/api/v1/campaigns/{id}/outcome` (`ve_console`) | Manual outcome marking (booked/attended), holdout-protected. |
| `/api/v1/whatsapp`, `/api/v1/whatsapp/messages/{id}` (`ve_console`) | Conversation log. |
| `/api/v1/holdout`, `/api/v1/revenue` (`ve_console`) | Causal experiment results and ROI (owner-gated). |
| `/api/v1/models`, `/api/v1/operations` (`ve_console`) | Model registry health and pipeline operations (admin-gated). |

### A.2 Database separation

| Database concern | Role |
|---|---|
| Clinic-scoped operational tables (Postgres) | Patients, features, consent, opportunities, campaigns, outcomes, bookings, revenue — every table keyed by `clinic_id`. |
| Neo4j | The clinical-recall knowledge graph. |
| Redis | Ranking-time feature cache (short TTL, non-authoritative). |
| MLflow | Model artifacts, metrics, and registry pointers — never patient data. |

### A.3 Model artifacts

| Artifact | Role |
|---|---|
| No-show CatBoost/LightGBM model | Predicts appointment no-show risk, feeding the expected-value ranking. |
| Booking propensity model | Predicts whether a candidate books at all if contacted. |
| Expected-value (revenue) model | Predicts the monetary value of a visit. |
| Uplift T-learner | Predicts the causal, incremental effect of contact for a given patient. |
| Survival (time-to-book) model | Predicts time until booking if contacted. |
| Lookalike/discovery model | Recommends a new opportunity family for a patient based on similar patients. |
| WhatsApp intent classifier | Classifies inbound reply intent (booking, confirmation, opt-out, ambiguous). |
| MedGemma + NemoGuard | Clinical-note structured extraction and its content-safety gate. |

### A.4 Deployment commands

```bash
docker compose -f infra/docker-compose.dev.yml up -d --build
docker compose -f infra/docker-compose.dev.yml logs -f ve_orchestrator
docker exec ve_temporal temporal schedule trigger \
  --address temporal:7233 --schedule-id daily-engagement-schedule-<clinic_id>
```

### A.5 Code structure

The main runtime modules are organized as one service per external dependency or responsibility: `services/ve_connect` (Epic), `services/ve_orchestrator` (Temporal pipeline), `services/ve_reach` (WhatsApp/SMS), `services/ve_measure` (booking/revenue attribution), `services/ve_console` (web application), `services/ve_clinical_intel` (clinical-note intelligence), `ml/` (training scripts and model registry), and `policies/opportunities/` (the YAML opportunity-family rule definitions).
