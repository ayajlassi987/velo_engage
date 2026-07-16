"""
lifecycle.py — Appointment State Machine + Event Logger
========================================================
Enforces valid status transitions and records every change
as an immutable AppointmentEvent for audit + webhook dispatch.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Callable

from sqlalchemy.orm import Session

from ehr_emulator.models import Appointment, AppointmentEvent, AppointmentStatus

# Valid transitions: {from_status: [allowed_to_statuses]}
TRANSITIONS: dict[str, list[str]] = {
    AppointmentStatus.booked.value:      [
        AppointmentStatus.confirmed.value,
        AppointmentStatus.cancelled.value,
        AppointmentStatus.no_show.value,
        AppointmentStatus.checked_in.value,
        AppointmentStatus.rescheduled.value,
        AppointmentStatus.fulfilled.value,
    ],
    AppointmentStatus.confirmed.value:   [
        AppointmentStatus.cancelled.value,
        AppointmentStatus.no_show.value,
        AppointmentStatus.checked_in.value,
        AppointmentStatus.rescheduled.value,
        AppointmentStatus.fulfilled.value,
    ],
    AppointmentStatus.checked_in.value:  [
        AppointmentStatus.fulfilled.value,
        AppointmentStatus.no_show.value,    # edge case
    ],
    # Terminal states — now allowing reset back to booked
    AppointmentStatus.cancelled.value:   [AppointmentStatus.booked.value],
    AppointmentStatus.no_show.value:     [AppointmentStatus.booked.value],
    AppointmentStatus.fulfilled.value:   [AppointmentStatus.booked.value],
    AppointmentStatus.rescheduled.value: [AppointmentStatus.booked.value],
}


class LifecycleError(Exception):
    pass


def transition(
    session: Session,
    appointment: Appointment,
    new_status: str,
    actor: str = "system",
    reason: Optional[str] = None,
    extra_payload: Optional[dict] = None,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> AppointmentEvent:
    """
    Transition an appointment to a new status.

    Args:
        session:       SQLAlchemy session (caller commits)
        appointment:   The Appointment ORM object
        new_status:    Target status string
        actor:         Who triggered the change (staff/system/patient)
        reason:        Human-readable reason (for cancel/no_show)
        extra_payload: Additional data to store in the event
        on_event:      Optional callback(event_type, payload) for webhook dispatch

    Returns:
        The created AppointmentEvent

    Raises:
        LifecycleError if the transition is not allowed
    """
    old_status = appointment.status
    allowed    = TRANSITIONS.get(old_status, [])

    if new_status not in allowed:
        raise LifecycleError(
            f"Cannot transition appointment {appointment.id} "
            f"from '{old_status}' to '{new_status}'. "
            f"Allowed: {allowed or 'none (terminal state)'}"
        )

    # Apply cancellation / no-show reasons
    if new_status == AppointmentStatus.cancelled.value and reason:
        appointment.cancellation_reason = reason
    if new_status == AppointmentStatus.no_show.value and reason:
        appointment.no_show_reason = reason

    appointment.status     = new_status
    appointment.updated_at = datetime.utcnow()

    event_type = _event_name(new_status)
    payload    = {
        "appointment_id": appointment.id,
        "patient_id":     appointment.patient_id,
        "provider_id":    appointment.provider_id,
        "service_id":     appointment.service_id,
        "start_dt":       appointment.start_dt.isoformat(),
        "old_status":     old_status,
        "new_status":     new_status,
        "actor":          actor,
        "reason":         reason,
        **(extra_payload or {}),
    }

    event = AppointmentEvent(
        appointment_id  = appointment.id,
        event_type      = event_type,
        old_status      = old_status,
        new_status      = new_status,
        actor           = actor,
        payload         = payload,
    )
    session.add(event)

    if on_event:
        on_event(event_type, payload)

    return event


def _event_name(status: str) -> str:
    mapping = {
        AppointmentStatus.confirmed.value:   "appointment.confirmed",
        AppointmentStatus.cancelled.value:   "appointment.cancelled",
        AppointmentStatus.no_show.value:     "appointment.no_show",
        AppointmentStatus.checked_in.value:  "appointment.checked_in",
        AppointmentStatus.fulfilled.value:   "appointment.fulfilled",
        AppointmentStatus.rescheduled.value: "appointment.rescheduled",
    }
    return mapping.get(status, f"appointment.{status}")


def log_created(
    session: Session,
    appointment: Appointment,
    actor: str = "system",
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> AppointmentEvent:
    """Log the initial creation event (no status transition needed)."""
    payload = {
        "appointment_id": appointment.id,
        "patient_id":     appointment.patient_id,
        "provider_id":    appointment.provider_id,
        "service_id":     appointment.service_id,
        "start_dt":       appointment.start_dt.isoformat(),
        "status":         appointment.status,
        "actor":          actor,
    }
    event = AppointmentEvent(
        appointment_id = appointment.id,
        event_type     = "appointment.created",
        old_status     = None,
        new_status     = appointment.status,
        actor          = actor,
        payload        = payload,
    )
    session.add(event)

    if on_event:
        on_event("appointment.created", payload)

    return event