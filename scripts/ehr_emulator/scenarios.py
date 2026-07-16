"""
scenarios.py — Scenario Runner
================================
Applies realistic probabilistic events to the schedule.
Each scenario is deterministic given the same seed.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, date
from typing import Optional, Callable

from sqlalchemy.orm import Session

from ehr_emulator.models import Appointment, AppointmentStatus, WaitlistEntry, Patient, Service
from ehr_emulator.lifecycle import transition, LifecycleError

# ── Scenario catalog ──────────────────────────────────────────────────────

SCENARIO_CATALOG = {
    "normal_day": {
        "name": "Normal Day",
        "description": "Typical clinic day. ~15% no-show, 10% cancel, rest fulfilled.",
        "params": {"noshow_prob": 0.15, "cancel_prob": 0.10, "cancel_lead_hours": 4},
    },
    "high_noshow_evening": {
        "name": "High No-Show (Evening)",
        "description": "Evening slots have 40% no-show. Morning normal.",
        "params": {"noshow_prob": 0.40, "cancel_prob": 0.08, "evening_only": True},
    },
    "aesthetic_deposit": {
        "name": "Aesthetic Premium (Deposit Test)",
        "description": "High-revenue aesthetic slots. ~50% require deposit. Of those, 30% don't pay → cancel.",
        "params": {"noshow_prob": 0.10, "deposit_non_pay_cancel_prob": 0.30},
    },
    "mass_cancellations": {
        "name": "Mass Cancellations",
        "description": "Burst of 5–8 cancellations in a 2-hour window. Stress test for slot-fill.",
        "params": {"cancel_count": 7, "window_hours": 2},
    },
    "walk_in_overload": {
        "name": "Walk-in Overload",
        "description": "3–5 walk-ins inserted mid-day, creating micro-gaps and pressure.",
        "params": {"walk_in_count": 4, "noshow_prob": 0.12},
    },
    "provider_late_start": {
        "name": "Provider Late Start",
        "description": "One provider starts 90 min late. First 3 appointments need reschedule.",
        "params": {"late_mins": 90, "affected_count": 3},
    },
    "clinic_promotion": {
        "name": "Clinic Promotion",
        "description": "Sudden waitlist growth (10 new entries). High acceptance rate.",
        "params": {"new_waitlist": 10, "accept_prob": 0.80},
    },
}


def run_scenario(
    session: Session,
    scenario_id: str,
    target_date: Optional[str] = None,
    seed: int = 42,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> dict:
    """
    Run a named scenario against the given date.
    Returns a summary of what happened.
    """
    if scenario_id not in SCENARIO_CATALOG:
        raise ValueError(f"Unknown scenario: '{scenario_id}'. Available: {list(SCENARIO_CATALOG.keys())}")

    scenario = SCENARIO_CATALOG[scenario_id]
    params   = scenario["params"]
    rng      = random.Random(seed)

    date_str = target_date or date.today().strftime("%Y-%m-%d")
    d        = datetime.strptime(date_str, "%Y-%m-%d").date()

    day_start = datetime.combine(d, datetime.min.time())
    day_end   = datetime.combine(d, datetime.max.time())

    # Get today's booked/confirmed appointments
    appts = (
        session.query(Appointment)
        .filter(
            Appointment.start_dt >= day_start,
            Appointment.start_dt <= day_end,
            Appointment.status.in_([AppointmentStatus.booked.value, AppointmentStatus.confirmed.value]),
        )
        .order_by(Appointment.start_dt)
        .all()
    )

    log = []

    # ── Normal Day ─────────────────────────────────────────────────────
    if scenario_id == "normal_day":
        for appt in appts:
            r = rng.random()
            if r < params["cancel_prob"]:
                _safe_transition(session, appt, AppointmentStatus.cancelled.value,
                                 reason="Patient cancelled (normal day)", on_event=on_event)
                log.append({"appt": appt.id, "action": "cancelled"})
            elif r < params["cancel_prob"] + params["noshow_prob"]:
                _safe_transition(session, appt, AppointmentStatus.no_show.value,
                                 reason="No-show (normal day)", on_event=on_event)
                log.append({"appt": appt.id, "action": "no_show"})
            else:
                _safe_transition(session, appt, AppointmentStatus.fulfilled.value, on_event=on_event)
                log.append({"appt": appt.id, "action": "fulfilled"})

    # ── High No-Show Evening ───────────────────────────────────────────
    elif scenario_id == "high_noshow_evening":
        for appt in appts:
            is_evening = appt.start_dt.hour >= 16
            noshow_p   = params["noshow_prob"] if is_evening else 0.12
            r = rng.random()
            if r < 0.08:
                _safe_transition(session, appt, AppointmentStatus.cancelled.value,
                                 reason="Cancellation", on_event=on_event)
                log.append({"appt": appt.id, "action": "cancelled"})
            elif r < 0.08 + noshow_p:
                _safe_transition(session, appt, AppointmentStatus.no_show.value,
                                 reason=f"No-show ({'evening' if is_evening else 'day'} slot)",
                                 on_event=on_event)
                log.append({"appt": appt.id, "action": "no_show", "evening": is_evening})
            else:
                _safe_transition(session, appt, AppointmentStatus.fulfilled.value, on_event=on_event)
                log.append({"appt": appt.id, "action": "fulfilled"})

    # ── Aesthetic Deposit ─────────────────────────────────────────────
    elif scenario_id == "aesthetic_deposit":
        for appt in appts:
            if appt.deposit_required and not appt.deposit_paid:
                if rng.random() < params["deposit_non_pay_cancel_prob"]:
                    _safe_transition(session, appt, AppointmentStatus.cancelled.value,
                                     reason="Deposit not paid within deadline", on_event=on_event)
                    log.append({"appt": appt.id, "action": "cancelled_no_deposit"})
                    continue
            r = rng.random()
            if r < params["noshow_prob"]:
                _safe_transition(session, appt, AppointmentStatus.no_show.value, on_event=on_event)
                log.append({"appt": appt.id, "action": "no_show"})
            else:
                _safe_transition(session, appt, AppointmentStatus.fulfilled.value, on_event=on_event)
                log.append({"appt": appt.id, "action": "fulfilled"})

    # ── Mass Cancellations ────────────────────────────────────────────
    elif scenario_id == "mass_cancellations":
        burst_targets = rng.sample(appts, min(params["cancel_count"], len(appts)))
        for appt in appts:
            if appt in burst_targets:
                _safe_transition(session, appt, AppointmentStatus.cancelled.value,
                                 reason="Mass cancellation event", on_event=on_event)
                log.append({"appt": appt.id, "action": "cancelled_burst"})
            else:
                _safe_transition(session, appt, AppointmentStatus.fulfilled.value, on_event=on_event)
                log.append({"appt": appt.id, "action": "fulfilled"})

    # ── Walk-in Overload ──────────────────────────────────────────────
    elif scenario_id == "walk_in_overload":
        # Fulfill most, then insert walk-ins (handled in main.py via POST /appointments)
        for appt in appts:
            r = rng.random()
            if r < 0.12:
                _safe_transition(session, appt, AppointmentStatus.no_show.value, on_event=on_event)
                log.append({"appt": appt.id, "action": "no_show"})
            else:
                _safe_transition(session, appt, AppointmentStatus.fulfilled.value, on_event=on_event)
                log.append({"appt": appt.id, "action": "fulfilled"})

    # ── Provider Late Start ───────────────────────────────────────────
    elif scenario_id == "provider_late_start":
        if appts:
            # Pick the provider with the most appointments
            from collections import Counter
            prov_counts = Counter(a.provider_id for a in appts)
            busy_prov   = prov_counts.most_common(1)[0][0]
            prov_appts  = [a for a in appts if a.provider_id == busy_prov]
            affected    = prov_appts[:params["affected_count"]]

            for appt in appts:
                if appt in affected:
                    # Reschedule by pushing late_mins forward
                    from datetime import timedelta
                    _safe_transition(session, appt, AppointmentStatus.rescheduled.value,
                                     reason=f"Provider started {params['late_mins']} min late",
                                     on_event=on_event)
                    log.append({"appt": appt.id, "action": "rescheduled_provider_late"})
                else:
                    _safe_transition(session, appt, AppointmentStatus.fulfilled.value, on_event=on_event)
                    log.append({"appt": appt.id, "action": "fulfilled"})

    # ── Clinic Promotion ──────────────────────────────────────────────
    elif scenario_id == "clinic_promotion":
        # Add new waitlist entries
        all_patients = session.query(Patient).all()
        all_services = session.query(Service).all()
        added = 0
        for _ in range(params["new_waitlist"]):
            p = rng.choice(all_patients)
            s = rng.choice(all_services)
            wl = WaitlistEntry(
                patient_id      = p.id,
                service_id      = s.id,
                pref_time_start = rng.choice([9, 10, 11]),
                pref_time_end   = rng.choice([16, 17, 18]),
                priority        = rng.randint(1, 5),
                is_vip          = p.is_vip,
                notes           = "Added via clinic promotion",
            )
            session.add(wl)
            added += 1
        log.append({"action": "waitlist_added", "count": added})

        # Fulfill normal day
        for appt in appts:
            if rng.random() < 0.12:
                _safe_transition(session, appt, AppointmentStatus.no_show.value, on_event=on_event)
                log.append({"appt": appt.id, "action": "no_show"})
            else:
                _safe_transition(session, appt, AppointmentStatus.fulfilled.value, on_event=on_event)
                log.append({"appt": appt.id, "action": "fulfilled"})

    session.commit()

    # Build summary
    summary = {c: 0 for c in ["fulfilled", "cancelled", "no_show", "rescheduled",
                               "cancelled_no_deposit", "cancelled_burst",
                               "rescheduled_provider_late", "waitlist_added"]}
    for entry in log:
        action = entry.get("action", "")
        if action in summary:
            summary[action] += 1

    return {
        "scenario":   scenario_id,
        "name":       scenario["name"],
        "date":       date_str,
        "total_appointments_affected": len(appts),
        "summary":    {k: v for k, v in summary.items() if v > 0},
        "events":     log,
    }


def _safe_transition(session, appt, new_status, reason=None, on_event=None):
    try:
        transition(session, appt, new_status, actor="scenario_runner",
                   reason=reason, on_event=on_event)
    except LifecycleError:
        pass  # already in terminal state — skip silently