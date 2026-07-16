"""
slot_engine.py — Slot Inventory Engine
======================================
FIX: get_available_slots now skips past slots by default.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Optional

from sqlalchemy.orm import Session

from ehr_emulator.models import Appointment, Schedule, AppointmentStatus
def _dt(date_str: str, hour: int, minute: int = 0) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute)


def get_available_slots(
    session: Session,
    provider_id: int,
    date_str: str,
    slot_duration: int = 30,
    min_start: Optional[datetime] = None,
) -> List[Dict]:
    """
    Return available slot dicts for a provider on a given date.
    FIX: min_start defaults to now — past slots never returned.
    """
    if min_start is None:
        min_start = datetime.now()

    schedule = (
        session.query(Schedule)
        .filter_by(provider_id=provider_id, date=date_str, is_active=True)
        .first()
    )
    if not schedule:
        return []

    day_start = _dt(date_str, 0)
    day_end   = _dt(date_str, 23, 59)
    booked = (
        session.query(Appointment)
        .filter(
            Appointment.provider_id == provider_id,
            Appointment.start_dt >= day_start,
            Appointment.start_dt <= day_end,
            Appointment.status.in_([
                AppointmentStatus.booked.value,
                AppointmentStatus.confirmed.value,
                AppointmentStatus.checked_in.value,
            ]),
        )
        .order_by(Appointment.start_dt)
        .all()
    )

    busy: List[tuple[datetime, datetime]] = [(a.start_dt, a.end_dt) for a in booked]

    if schedule.break_start and schedule.break_end:
        busy.append((_dt(date_str, schedule.break_start), _dt(date_str, schedule.break_end)))

    busy.sort(key=lambda x: x[0])

    work_start = _dt(date_str, schedule.start_hour)
    work_end   = _dt(date_str, schedule.end_hour)

    slots  = []
    cursor = work_start
    delta  = timedelta(minutes=slot_duration)

    while cursor + delta <= work_end:
        slot_end = cursor + delta

        # FIX: skip past slots
        if cursor < min_start:
            cursor += delta
            continue

        overlaps = any(
            cursor < b_end and slot_end > b_start
            for b_start, b_end in busy
        )

        if not overlaps:
            slots.append({
                "provider_id":   provider_id,
                "date":          date_str,
                "start":         cursor.isoformat(),
                "end":           slot_end.isoformat(),
                "duration_mins": slot_duration,
                "status":        "free",
            })

        cursor += delta

    return slots


def get_micro_gaps(
    session: Session,
    provider_id: int,
    date_str: str,
    min_gap_mins: int = 10,
) -> List[Dict]:
    day_start = _dt(date_str, 0)
    day_end   = _dt(date_str, 23, 59)
    booked = (
        session.query(Appointment)
        .filter(
            Appointment.provider_id == provider_id,
            Appointment.start_dt >= day_start,
            Appointment.start_dt <= day_end,
            Appointment.status.in_([
                AppointmentStatus.booked.value,
                AppointmentStatus.confirmed.value,
            ]),
        )
        .order_by(Appointment.start_dt)
        .all()
    )

    gaps = []
    for i in range(len(booked) - 1):
        gap_start = booked[i].end_dt
        gap_end   = booked[i + 1].start_dt
        gap_mins  = int((gap_end - gap_start).total_seconds() / 60)
        if gap_mins >= min_gap_mins:
            gaps.append({
                "provider_id": provider_id,
                "date":        date_str,
                "start":       gap_start.isoformat(),
                "end":         gap_end.isoformat(),
                "gap_mins":    gap_mins,
                "between":     [booked[i].id, booked[i + 1].id],
            })

    return gaps


def check_slot_available(
    session: Session,
    provider_id: int,
    start_dt: datetime,
    duration_mins: int,
) -> tuple[bool, str]:
    end_dt      = start_dt + timedelta(minutes=duration_mins)
    date_str    = start_dt.strftime("%Y-%m-%d")
    start_hour  = start_dt.hour

    schedule = (
        session.query(Schedule)
        .filter_by(provider_id=provider_id, date=date_str, is_active=True)
        .first()
    )
    if not schedule:
        return False, "Provider has no schedule on this date"

    if start_hour < schedule.start_hour:
        return False, "Before provider working hours"
    if end_dt.hour > schedule.end_hour or (end_dt.hour == schedule.end_hour and end_dt.minute > 0):
        return False, "Extends past provider working hours"

    if schedule.break_start and schedule.break_end:
        break_s = _dt(date_str, schedule.break_start)
        break_e = _dt(date_str, schedule.break_end)
        if start_dt < break_e and end_dt > break_s:
            return False, "Overlaps with provider break"

    conflict = (
        session.query(Appointment)
        .filter(
            Appointment.provider_id == provider_id,
            Appointment.status.in_([
                AppointmentStatus.booked.value,
                AppointmentStatus.confirmed.value,
                AppointmentStatus.checked_in.value,
            ]),
            Appointment.start_dt < end_dt,
            Appointment.end_dt   > start_dt,
        )
        .first()
    )
    if conflict:
        return False, f"Conflicts with appointment {conflict.id}"

    return True, "ok"