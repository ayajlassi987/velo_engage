# VE Agent — STUB, not deployed

The master spec names "VE Agent" as a LangGraph orchestrator tying
detection → decision → communication → monitoring together, driven by
Temporal crons and NATS subscriptions.

**In the live system, `services/ve_orchestrator` (Temporal) is this
orchestrator.** It already runs the real daily workflow — rules evaluation,
consent/frequency gating, holdout assignment, and dispatch to `ve_reach` —
on a durable, retry-safe schedule. That is deliberate: Temporal gives
step-level retries, durable timers, and replay-safe history for free, which
a hand-rolled LangGraph loop would have to reimplement.

This package exists only so the module named in the architecture diagram
has a concrete home, and to show the same detect → guard → decide →
dispatch → monitor shape expressed as a LangGraph `StateGraph`
(`src/ve_agent/graph.py`). **It is not built, not in `docker-compose.dev.yml`,
not in the root `uv` workspace, and nothing in the live pipeline imports it.**
Running `graph.py` executes the shape of the loop against read-only queries
and stub node functions — it does not gate real consent, assign real
holdout arms, or dispatch real campaigns.

If this ever needs to become the live orchestrator instead of Temporal,
each node in `graph.py` would need to call the real functions already in
`ve_orchestrator/activities.py` and `ve_orchestrator/policy_engine.py`
rather than the placeholders here, and the whole graph would need Temporal's
durability replaced with LangGraph's own checkpointing.
