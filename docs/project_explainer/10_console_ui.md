# 10. The Console (`ve_console`)

## Purpose

The web app clinic staff and owners actually look at — every other
document in this folder describes machinery that runs invisibly; this is
where it becomes visible and actionable.

## Two frontends, same backend, same look — by design

Every page listed below is now served by a React SPA (`services/ve_console/
frontend/`, mounted at `/app`) that calls a parallel set of JSON endpoints
(`/api/v1/*`). The **original server-rendered Jinja templates still exist,
unchanged, at their original routes** — nothing was deleted or rewired.
Each JSON endpoint reuses the *exact same* data-fetch function the Jinja
route already called (e.g. `_overview_data()`, `_campaigns_data()` in
`main.py`) — extracted once, called by both, so there's one source of
truth per page regardless of which frontend renders it. The `/api/v1/campaigns/
{id}/outcome` mutation similarly shares its write logic
(`_mark_campaign_outcome()`) with the original HTML form endpoint.

Both frontends use the identical CSS (`theme.css` in the React app is the
same stylesheet as `static/styles.css`) — same classes, same components,
same blue theme — so a React page and its Jinja equivalent are visually
indistinguishable. Auth is unchanged too: React never handles a token
itself, it just calls the API with `credentials: "include"`, riding the
same Keycloak session cookie the Jinja pages already use. See file 14 for
the full React architecture — build pipeline, component structure,
routing, and why each of those decisions was made.

## Pages

| Route | Shows | Access |
| --- | --- | --- |
| `/overview` | KPI summary cards + funnel | Any logged-in user |
| `/opportunities` | Every detected opportunity (file 2), which family, priority | Any logged-in user |
| `/campaigns`, `/campaigns/{id}` | Every campaign, and a per-patient detail page — journey rail (targeted → sent → delivered → read → replied → booked → attended), the 5 model scores (file 4), SHAP explanation for the no-show score, manual outcome-marking buttons | Any logged-in user |
| `/whatsapp`, `/whatsapp/messages/{id}` | Outbound/inbound WhatsApp message log | Any logged-in user |
| `/clinical-summaries` | MedGemma-extracted structured clinical data (file 9) | Any logged-in user |
| `/bookings` | The `bookings` table — real appointment attribution | Any logged-in user |
| `/revenue` | Recovered/outstanding revenue, ROI | **Owner** only |
| `/holdout` | The causal experiment's results (file 5) | **Owner** only |
| `/models` | Model quality metrics, drift monitoring, SHAP | **Admin** only |
| `/operations` | Pipeline health | **Admin** only |
| `/api/summary` | JSON version of the KPI cards, used by live refresh | Any logged-in user |

Role gating (`require_owner`/`require_admin` in `auth.py`) is additive —
admin implies everything owner can see, checked by testing for *either*
role granting that tier, not by a separate "admin implies owner"
expansion step.

## Auth

Keycloak OIDC, hand-rolled rather than pulling in a library like authlib —
only two HTTP calls are actually needed (token exchange, JWKS fetch for
signature verification), both via stdlib `urllib` plus PyJWT. A single
Keycloak realm serves two distinct issuer URLs: `KEYCLOAK_ISSUER` (external,
what the browser is redirected to and what ends up in the token's `iss`
claim) vs. `KEYCLOAK_ISSUER_INTERNAL` (what this container uses to reach
Keycloak directly over the Docker network — `localhost` from inside the
container wouldn't reach the Keycloak container).

## "Live" refresh — two implementations, same behavior

The Jinja pages' version (`static/app.js`): every 15 seconds, re-fetches
the current page's own URL with header `X-VE-Live-Refresh: 1`, and the
server (`main.py`'s `render()`) responds with just the data fragment
needed rather than a full page. This predates the React migration (file
14) — a pragmatic way to get "live-updating dashboard" behavior out of a
server-rendered app before there was a JSON API to poll instead. The React
version (`useLiveRefresh` hook) reimplements the identical cadence and
pause-when-hidden/pause-while-typing behavior against the new `/api/v1/*`
JSON endpoints — see file 14 for why both had to match exactly.

## Rebrand: VeloDoc

The console's user-facing brand is **VeloDoc** (sidebar, page titles,
login screen, browser theme-color) — distinct from "Velo Engage," which
stays the name of the overall project/platform (repo name, service names
like `ve_orchestrator`, this documentation folder's own narrative). Only
static UI chrome was rebranded; the per-clinic name shown throughout the
console (`{{ clinic_name }}` / `session.clinic.name` — "Al Noor Clinic,"
"Riverside Dental Group") is real tenant data and was deliberately left
alone, since conflating a customer's clinic name with the platform's own
brand would undo the multi-clinic work in file 11. Also shipped in the
same pass: a full blue color palette (`--brand`/`--brand-dark`/
`--brand-soft`/`--brand-bright` in `theme.css`) replacing the earlier
green-based chrome, while deliberately *not* touching status-semantic
colors (green still means done/healthy/attended, amber still holdout/
warning, coral still failed/opt-out) — overriding those to match the new
brand color would have made the UI harder to read, not more modern.

## Manual outcome marking

`POST /campaigns/{id}/outcome` — a real gap-closer, not originally part of
the pipeline. Coordinators use this when a patient calls in or shows up
outside the system's own automated channels (Epic booking write-back
doesn't exist yet — file 13). Two buttons on the campaign detail page,
"Mark as booked" / "Mark as attended," hidden once already true.

- Writes to **both** `bookings` and `outcomes` — not just `outcomes` — the
  same two tables a real `AppointmentConfirmed`/`AppointmentCompleted`
  event would populate (`ve_measure`'s `booking_listener.py`). The KPI cards
  and `/bookings` page count rows in `bookings`, not `outcomes.booked`
  directly; an earlier version of this feature only touched `outcomes` and
  silently never showed up anywhere else in the console.
- The "Mark as attended" form has an **optional** revenue amount field. If
  filled in, it also writes a `revenue_attributions` invoice row and
  refreshes `outcomes.revenue` — mirroring `ve_measure`'s real invoice-event
  path. If left blank, the campaign page shows **"No invoice recorded
  yet"**, not "$0.00" — a real UX fix: `outcomes.revenue` defaulting to 0
  looked identical to "genuinely zero revenue," which read as a broken
  feature rather than "nobody's entered an invoice yet."
- **Rejects holdout campaigns outright** (`400`, with an explanation shown
  in the UI instead of the buttons) — marking a holdout patient
  booked/attended would corrupt the causal comparison the holdout arm
  exists to measure, exactly like an accidental real dispatch would (file 5).
- Every write is idempotent (matches `upsert_outcome`'s OR-merge semantics)
  — clicking the same button twice doesn't duplicate a booking row or
  clobber an earlier timestamp with a later one.

## The "Model scores" panel

A dedicated section on the campaign detail page showing all 5 ranking
models' outputs (file 4) as labeled cards — expected value, no-show risk
(with a mini progress bar, colored coral above 50%), booking propensity,
predicted revenue, uplift (colored coral when negative, with a caption
explaining the 10x discount it triggers), predicted days-to-book. Added
because these scores were being computed and stored on every campaign row
but had no UI surface at all — only the rule's static `priority_score` and
a SHAP breakdown for the no-show score specifically were ever shown.

## Why this design

- **Server-rendered first, React added later — not a contradiction.**
  The original design was deliberately *not* a SPA: this console started
  as read-mostly with a handful of simple mutations, and a full frontend
  build pipeline would have been disproportionate machinery for what a
  15-second poll and server-side templating already handled well. That
  calculus changed when a modern, more polished UI became an explicit
  goal in its own right (file 14) — at that point a proper component
  framework earned its cost. The original reasoning wasn't wrong for what
  it was optimizing for at the time; the goal changed, not the analysis.
- **Owner/admin tiers, not a single flat "logged in" gate.** Revenue and
  the causal holdout results are commercially/statistically sensitive in a
  way opportunity/campaign browsing isn't — worth a real role boundary,
  not just an honor system.
- **Manual marking writes to the same tables real automation would**,
  specifically so that whichever comes online first — a real Epic
  Appointment integration, or a coordinator's manual entry — the rest of
  the console (KPIs, bookings list, revenue) doesn't need two different
  code paths to display the result.
