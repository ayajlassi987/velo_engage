# 14. The React Frontend (`services/ve_console/frontend/`)

## Purpose

A modern, more polished UI became an explicit goal in its own right (blue
theme, VeloDoc rebrand, smoother interactions — file 10's rebrand section)
— beyond what incremental CSS/theme edits to the existing Jinja templates
could deliver on their own. Rather than a risky all-at-once rewrite of a
console actively being used against real Epic data, this was built and
verified as **a second, parallel frontend that coexists with the original
one**, migrated one page at a time.

## The core rule: nothing on the Jinja side changed

This is the single most important fact about this subsystem. Every
original route in `main.py`, every Jinja template, every existing test —
all untouched. The React app is **entirely additive**:

- New routes only (`/app/*` for the SPA shell, `/api/v1/*` for JSON data).
- No existing route's behavior, response shape, or auth requirement was
  altered.
- Verified directly, not assumed: a genuinely-signed session cookie
  (built with Starlette's own `itsdangerous` signer, matching
  `SessionMiddleware`'s exact format) was used to hit the real running
  container end-to-end, confirming every original Jinja route still
  returns identical output *after* the migration, not just before it.

## Zero duplicated business logic

Every page's Jinja route was refactored — not rewritten — to separate
"fetch the data" from "render HTML." Each route now looks like:

```python
def _campaigns_data(clinic_id, q, arm, status, limit) -> dict:
    ...exact same SQL that was already there...
    return {"rows": rows, "summary": summary, "filters": {...}}

@app.get("/campaigns")
def campaigns(request, ...):
    data = _campaigns_data(...)
    return render(request, "list.html", ..., **data)

@app.get("/api/v1/campaigns")
def api_campaigns(request, ...):
    return _json_safe(_campaigns_data(...))
```

The HTML route and the JSON route call the *same* function. There is
exactly one place that knows how to compute each page's data, regardless
of which frontend asks for it. This pattern was applied to all 11 pages
(`_overview_data`, `_opportunities_data`, `_campaigns_data`,
`_campaign_detail_data`, `_whatsapp_data`, `_message_detail_data`,
`_clinical_summaries_data`, `_bookings_data`, `_revenue_data`,
`_holdout_data`, `_models_data`, `_operations_data`) and to the one
mutation that exists (`_mark_campaign_outcome()`, shared between the HTML
form's `POST /campaigns/{id}/outcome` and the JSON `POST /api/v1/campaigns/
{id}/outcome`).

`_json_safe()` (`main.py`) recursively converts the `Decimal`/`datetime`
values psycopg2 returns into JSON-serializable `float`/ISO-string — needed
because the stdlib JSON encoder can't handle them directly, and this
project's existing `/api/summary` endpoint only had a flat, one-level
version of the same conversion.

## Auth: reused exactly, not reimplemented

An explicit decision, not a default: **no tokens, no new auth code.**
React calls the API with `fetch(url, { credentials: "include" })`, which
sends the same Keycloak-issued session cookie every Jinja page already
relies on. `services/ve_console/frontend/src/api/client.ts` centralizes
this, plus one behavior a JSON client needs that an HTML page doesn't: on
a `401`, redirect the browser to `/login` itself (`window.location.href`)
rather than trying to render a broken app shell.

This required one narrow, additive change to `main.py`'s `require_login`
middleware: previously, *any* unauthenticated request to a non-public path
got redirected to `/login` — including, in principle, a `/api/*` call. A
redirect response is fine for a browser navigating to an HTML page; it's
wrong for `fetch()`, which would otherwise silently follow the redirect
and try to parse the login page's HTML as JSON. The fix: if the path
starts with `/api/`, return a plain `401` JSON response instead. This
changes nothing for `/api/summary`'s pre-existing behavior, since that
endpoint is only ever called from a page that already required login to
load in the first place — the unauthenticated case was previously
unreachable in practice for it, so redefining it is safe.

## Where things live and how the build works

```
services/ve_console/frontend/          # Vite + React + TypeScript project
  src/
    api/
      client.ts        # apiGet/apiPost — fetch wrapper, 401 handling
      types.ts          # one interface per page's JSON shape
      listTypes.ts       # generic Row/ColumnDef/Summary types for list pages
    hooks/
      useSession.ts       # fetches /api/v1/session once on mount
      useLiveRefresh.ts    # 15s polling, mirrors static/app.js exactly
      useListData.ts        # combines useLiveRefresh with URL-based filters
    components/
      layout/               # AppShell, Sidebar, Topbar
      ui/                     # DataTable, SummaryCards, Badge, JourneyRail, EmptyState
    pages/                     # one file per migrated page
    lib/format.ts               # formatMoney/formatPercent/formatDateTime/titleCase —
                                  # mirrors main.py's Jinja filters exactly
  theme.css                      # identical copy of static/styles.css
  vite.config.ts                  # base: '/app/', outDir: ../src/ve_console/react_dist
```

`services/ve_console/Dockerfile` is a two-stage build: a `node:22-slim`
stage runs `npm install && npm run build`, producing static assets; the
final Python image just `COPY --from=frontend`s that output in. The
running container never needs Node at all — only the build step does.
`main.py` mounts the built `assets/` directory under `/app/assets` and
serves `index.html` for every other `/app/*` path (a catch-all route,
`react_app()`), so React Router's client-side routes work correctly even
on a direct page load or browser refresh — the same pattern any SPA
behind a real backend needs for deep-linkable URLs.

## Component architecture — built once, reused everywhere

Rather than hand-build markup per page, a small set of shared components
mirror the Jinja side's own reusable pieces exactly:

- **`AppShell`/`Sidebar`/`Topbar`** — the equivalent of `base.html`. Same
  classes (`.sidebar`, `.topbar`, `.primary-nav`), same role-based nav
  item visibility (owner/admin tiers, matching `auth.py`'s roles). Sidebar
  links use React Router's `NavLink` (client-side navigation, no full
  reload) for every migrated page.
- **`DataTable`** — mirrors `macros.html`'s `data_table()` macro exactly:
  the same column-`kind` system (`text`/`badge`/`family`/`datetime`/
  `campaign`/`score`/`boolean`/`paid`/`money`/`money_with_currency`/
  `mono`/`list`/`flags`), same per-cell class names, same empty state.
  Every list page (Opportunities, Campaigns, Bookings, Revenue, Clinical
  Summaries) just declares its own `ColumnDef[]` and reuses this.
- **`SummaryCards`** — mirrors `macros.html`'s `summary_cards()` macro's
  formatting rules (which summary keys are money, which are percentages).
- **`JourneyRail`** — shared between Campaign Detail and Message Detail
  (both show a step-by-step progress rail; this was one component in the
  Jinja templates too, just copy-pasted markup rather than a real macro —
  the React version made it a real shared component).
- **`useListData`** — combines `useLiveRefresh` with React Router's
  `useSearchParams`, so a list page's filters live in the URL exactly like
  the old GET-based filter forms did (bookmarkable, shareable, and
  refreshed on the same 15s cadence as everything else).

## Migration order and how each page was verified

Overview first (the simplest page, proving the whole pattern end-to-end),
then every remaining page in one pass: Opportunities, Campaigns (list +
detail), WhatsApp (+ message detail), Clinical Summaries, Bookings,
Revenue, Holdout, Models, Operations. For each: extract the data function,
add the `/api/v1/*` route, build the React page against it, then verify
with the signed-cookie technique described above — checking real response
content (not just HTTP status), not assuming a `200` meant the data was
actually correct. `/api/v1/models`' 8 model cards and 37 registered
versions, and `/api/v1/holdout`'s real per-arm booking rates, were checked
against the live database directly as part of this.

## Why these specific decisions

- **Coexistence over replacement.** The single biggest risk in a UI
  rewrite is silently breaking something that was working. Building a
  parallel frontend against the same backend, verified page by page,
  means the original app was never at risk of regressing — at any point
  during the migration, every real user was still being served by
  fully-tested, unchanged Jinja pages.
- **Shared data functions, not shared code cranked through decorators.**
  Extracting `_xxx_data()` functions is the simplest possible way to
  guarantee both frontends can never drift apart in what they show — a
  bug fix or a new filter only has to happen once.
- **No new auth model.** Introducing a token-based flow alongside the
  existing session-cookie one would have doubled the auth surface for no
  functional benefit here — the session cookie already works, is already
  tested, and both frontends run on the same origin.
- **Reuse the exact CSS, not a redesign-during-migration.** Keeping
  `theme.css` byte-identical to `static/styles.css` means the two
  frontends are visually indistinguishable — the migration is purely
  architectural, not a simultaneous design change, which would have made
  it much harder to tell "did this break because of the rewrite" from
  "did this break because the design changed."
