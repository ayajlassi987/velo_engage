"""
seed.py — EHR Emulator Data Generator (risk‑controlled for online scorer)
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, date
from typing import List

from sqlalchemy.orm import Session

from ehr_emulator.models import (
    Patient, Provider, Service, Schedule,
    Appointment, AppointmentEvent, AppointmentStatus, WaitlistEntry,
)

# ---- Existing constants (unchanged) ----
ARABIC_FIRST_M = ["Ahmed", "Mohamed", "Khalid", "Omar", "Ali", "Hassan", "Youssef", "Saeed"]
ARABIC_FIRST_F = ["Fatima", "Aisha", "Maryam", "Sara", "Nour", "Layla", "Hessa", "Reem"]
EXPAT_FIRST_M  = ["James", "David", "Carlos", "Raj", "Kumar", "Michael", "Liam", "Nathan"]
EXPAT_FIRST_F  = ["Sarah", "Emma", "Priya", "Sofia", "Anna", "Jessica", "Maria", "Linda"]
LAST_NAMES_AR  = ["Al-Rashidi", "Al-Mansouri", "Al-Hamdan", "Al-Farsi", "Al-Otaibi", "Al-Zahrani"]
LAST_NAMES_EX  = ["Patel", "Smith", "Williams", "Garcia", "Kumar", "Johnson", "Brown", "Taylor"]
PHONE_PREFIXES = ["+97150", "+97155", "+97156", "+97158", "+96650", "+96655"]
INSURANCE_TYPES = ["daman", "cchi", "cash", "premium"]

PROVIDERS_SEED = [
    {"name": "Dr. Ahmed Al-Rashidi", "specialty": "dental",  "gender": "male"},
    {"name": "Dr. Sara Mansouri",    "specialty": "dental",  "gender": "female"},
    {"name": "Dr. James Williams",   "specialty": "derma",   "gender": "male"},
    {"name": "Dr. Fatima Al-Hamdan", "specialty": "dental",  "gender": "female"},
    {"name": "Dr. Carlos Garcia",    "specialty": "derma",   "gender": "male"},
    {"name": "Dr. Priya Patel",      "specialty": "dental",  "gender": "female"},
]

SERVICES_SEED = [
    {"name": "Dental Check-up",      "specialty": "dental", "duration_mins": 30,  "base_price": 150,  "deposit_pct": 0.0},
    {"name": "Dental Cleaning",      "specialty": "dental", "duration_mins": 45,  "base_price": 250,  "deposit_pct": 0.0},
    {"name": "Root Canal Treatment", "specialty": "dental", "duration_mins": 90,  "base_price": 1200, "deposit_pct": 0.20},
    {"name": "Skin Consultation",    "specialty": "derma",  "duration_mins": 30,  "base_price": 200,  "deposit_pct": 0.0},
    {"name": "Laser Treatment",      "specialty": "derma",  "duration_mins": 60,  "base_price": 800,  "deposit_pct": 0.10},
    {"name": "Botox Injection",      "specialty": "derma",  "duration_mins": 45,  "base_price": 1500, "deposit_pct": 0.20},
]

EXTRA_SERVICES = [
    {"name": "Orthodontics Consultation", "specialty": "dental", "duration_mins": 40, "base_price": 350, "deposit_pct": 0.0},
    {"name": "Pediatric Check-up",        "specialty": "general", "duration_mins": 30, "base_price": 120, "deposit_pct": 0.0},
    {"name": "General Consultation",      "specialty": "general", "duration_mins": 20, "base_price": 100, "deposit_pct": 0.0},
]

def _gen_phone(rng: random.Random, phone_set: set) -> str:
    for _ in range(50):
        phone = rng.choice(PHONE_PREFIXES) + str(rng.randint(1000000, 9999999))
        if phone not in phone_set:
            phone_set.add(phone)
            return phone
    return rng.choice(PHONE_PREFIXES) + str(rng.randint(1000000, 9999999))

def _gen_patient(rng: random.Random, phone_set: set, risk_tier: str) -> dict:
    is_arabic = rng.random() < 0.65
    gender    = rng.choice(["male", "female"])
    lang      = "ar" if is_arabic else "en"
    first = (rng.choice(ARABIC_FIRST_M if gender == "male" else ARABIC_FIRST_F) if is_arabic
             else rng.choice(EXPAT_FIRST_M if gender == "male" else EXPAT_FIRST_F))
    last  = rng.choice(LAST_NAMES_AR) if is_arabic else rng.choice(LAST_NAMES_EX)
    # VIP flag based on risk tier (high risk patients are not VIP)
    is_vip = (risk_tier == "low" and rng.random() < 0.2) or (risk_tier == "medium" and rng.random() < 0.05)
    distance_km = round(rng.uniform(1.0, 50.0), 1)
    insurance_type = rng.choices(
        INSURANCE_TYPES,
        weights=[0.35, 0.25, 0.25, 0.15],
        k=1,
    )[0]
    travel_minutes = round(max(5.0, min(120.0, 8.0 + distance_km * 2.5)), 1)
    return {
        "name":               f"{first} {last}",
        "dob":                f"{rng.randint(1970, 2000)}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
        "gender":             gender,
        "phone":              _gen_phone(rng, phone_set),
        "preferred_language": lang,
        "whatsapp_opt_in":    True,
        "sms_opt_in":         True,
        "is_vip":             is_vip,
        "distance_km":        distance_km,
        "notes":              f"insurance_type={insurance_type}; estimated_travel_time_min={travel_minutes}",
    }

def _create_past_appointments_for_patient(
    session: Session,
    patient: Patient,
    risk_tier: str,
    rng: random.Random,
    providers: List[Provider],
    services: List[Service],
    today: date,
    max_days_ago: int = 60,   # use 2 months
):
    num_past = rng.randint(3, 5)
    for _ in range(num_past):
        days_ago = rng.randint(5, max_days_ago)
        d = today - timedelta(days=days_ago)
        while d.weekday() == 4:
            d -= timedelta(days=1)
        prov = rng.choice(providers)
        svc = rng.choice([s for s in services if s.specialty == prov.specialty])
        hour = rng.choice([9, 10, 11, 14, 15, 16])
        start_dt = datetime(d.year, d.month, d.day, hour, 0)
        end_dt = start_dt + timedelta(minutes=svc.duration_mins)

        if risk_tier == "high":
            status = AppointmentStatus.no_show.value if rng.random() < 0.6 else AppointmentStatus.fulfilled.value
        elif risk_tier == "medium":
            status = AppointmentStatus.no_show.value if rng.random() < 0.3 else AppointmentStatus.fulfilled.value
        else:
            status = AppointmentStatus.no_show.value if rng.random() < 0.1 else AppointmentStatus.fulfilled.value

        appt = Appointment(
            patient_id=patient.id,
            provider_id=prov.id,
            service_id=svc.id,
            start_dt=start_dt,
            end_dt=end_dt,
            status=status,
            confirmation_status="confirmed",
        )
        session.add(appt)

def _create_online_scorer_state_for_appointment(
    appointment_id: int,
    r0: float = 0.2,
):
    import sqlite3
    from src.common.db_paths import get_velodoc_db_path
    from datetime import datetime
    try:
        conn = sqlite3.connect(get_velodoc_db_path(), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            INSERT OR REPLACE INTO online_scorer_state
            (appointment_id, r0, rt, event_history, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (appointment_id, r0, r0, "[]", datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: Could not insert state for appt {appointment_id}: {e}")

def _create_online_scorer_events_for_patient(
    appointment_id: int,
    risk_tier: str,
    rng: random.Random,
    start_dt: datetime,
    created_at: datetime,
):
    import sqlite3
    from src.common.db_paths import get_velodoc_db_path

    # Determine event type based on risk tier
    if risk_tier == "low":
        # 80% confirm, 20% ambiguous (no reply will come from absence of event)
        if rng.random() < 0.8:
            text = rng.choice(["1", "confirm", "yes", "ok", "sure"])
            event_type = "reply"
        else:
            text = rng.choice(["maybe", "i'll try", "not sure", "? "])
            event_type = "reply"
    elif risk_tier == "medium":
        # 30% confirm, 40% ambiguous, 30% no event (skip)
        r = rng.random()
        if r < 0.3:
            text = rng.choice(["1", "confirm", "yes"])
            event_type = "reply"
        elif r < 0.7:
            text = rng.choice(["maybe", "can't confirm yet", "i'll let you know"])
            event_type = "reply"
        else:
            return  # no event
    else:  # high risk
        # 70% no event, 30% cancel/skip
        if rng.random() < 0.3:
            text = rng.choice(["cancel", "2", "no", "cant come", "emergency"])
            event_type = "reply"
        else:
            return  # no event

    # Compute latency only if we have a reply
    max_delay = (start_dt - created_at).total_seconds()
    if max_delay < 3600:
        return
    sent_at = created_at + timedelta(seconds=rng.randint(3600, int(max_delay) - 3600))
    reply_at = sent_at + timedelta(minutes=rng.randint(1, 120))

    event = {
        "type": event_type,
        "text": text,
        "timestamp": reply_at.isoformat(),
        "sent_at": sent_at.isoformat(),
    }
    hours_until = (start_dt - reply_at).total_seconds() / 3600.0

    try:
        velodoc_db = get_velodoc_db_path()
        conn = sqlite3.connect(velodoc_db, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            INSERT INTO online_scorer_events
            (appointment_id, event_type, text, timestamp, sent_at, hours_until_appt, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            appointment_id, event_type, text, reply_at.isoformat(),
            sent_at.isoformat(), hours_until, str(event)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: Could not insert online scorer event: {e}")

def run_seed(
    session: Session,
    seed: int = 42,
    num_patients: int = 60,
    days_past: int = 60,          # 2 months (approx)
    days_future: int = 90,        # 3 months (approx)
    appointments_per_day: int = 3,
) -> dict:
    rng = random.Random(seed)
    today = date.today()

    # Wipe existing data
    for model in [WaitlistEntry, AppointmentEvent, Appointment, Schedule, Patient, Service, Provider]:
        try:
            session.query(model).delete()
        except Exception:
            pass
    session.commit()

    # ---- Providers ----
    providers: List[Provider] = []
    for p in PROVIDERS_SEED:
        prov = Provider(**p, branch="Velodoc Clinic - Main Branch", provider_noshow_rate=0.10)
        session.add(prov)
        providers.append(prov)
    session.flush()

    # ---- Services ----
    services: List[Service] = []
    for s in SERVICES_SEED + EXTRA_SERVICES:
        svc = Service(**s)
        session.add(svc)
        services.append(svc)
    session.flush()

    # ---- Risk tier distribution (high=10%, medium=40%, low=50%) ----
    num_high = int(num_patients * 0.10)
    num_medium = int(num_patients * 0.40)
    num_low = num_patients - num_high - num_medium
    tier_list = (["high"] * num_high) + (["medium"] * num_medium) + (["low"] * num_low)
    rng.shuffle(tier_list)

    # ---- Create patients and past appointments ----
    phone_set = set()
    # Ayoub Walha (high risk, always present)
    ayoub = Patient(
        name="Ayoub Walha",
        dob="1995-05-15",
        gender="male",
        phone="+21652912620",
        preferred_language="en",
        whatsapp_opt_in=True,
        sms_opt_in=True,
        is_vip=True,
        distance_km=25.0,
        notes="Test Patient; insurance_type=cash; estimated_travel_time_min=70",
    )
    session.add(ayoub)
    session.flush()
    phone_set.add(ayoub.phone)
    _create_past_appointments_for_patient(session, ayoub, "high", rng, providers, services, today, days_past)

    patients = [ayoub]
    patient_tier = {}
    patient_tier[ayoub.id] = "high"
    for i, tier in enumerate(tier_list):
        data = _gen_patient(rng, phone_set, tier)
        p = Patient(**data)
        session.add(p)
        session.flush()
        patient_tier[p.id] = tier
        _create_past_appointments_for_patient(session, p, tier, rng, providers, services, today, days_past)
        patients.append(p)

    session.flush()

    # ---- Schedules (from days_past ago to days_future ahead) ----
    for day_offset in range(-days_past, days_future + 1):
        d = today + timedelta(days=day_offset)
        if d.weekday() == 4:  # Friday off
            continue
        for prov in providers:
            session.add(Schedule(provider_id=prov.id, date=d.strftime("%Y-%m-%d"), start_hour=8, end_hour=20))
    session.flush()

    # ---- Future appointments (days_future ahead) ----
    for day_offset in range(1, days_future + 1):
        d = today + timedelta(days=day_offset)
        if d.weekday() == 4:
            continue
        for prov in providers:
            matching_services = [s for s in services if s.specialty == prov.specialty]
            if not matching_services:
                continue
            num_appts = rng.randint(1, appointments_per_day)
            for _ in range(num_appts):
                patient = rng.choice(patients)
                svc = rng.choice(matching_services)
                hour = rng.choice([9, 10, 11, 14, 15, 16])
                start_dt = datetime(d.year, d.month, d.day, hour, 0)
                end_dt = start_dt + timedelta(minutes=svc.duration_mins)
                status = AppointmentStatus.booked.value
                if day_offset == 1:
                    status = AppointmentStatus.confirmed.value
                appt = Appointment(
                    patient_id=patient.id,
                    provider_id=prov.id,
                    service_id=svc.id,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    status=status,
                    confirmation_status="pending" if status == "booked" else "confirmed",
                )
                session.add(appt)
    session.flush()

    # ---- Waitlist (optional) ----
    for _ in range(20):
        patient = rng.choice(patients)
        service = rng.choice(services)
        session.add(WaitlistEntry(
            patient_id=patient.id,
            service_id=service.id,
            priority=rng.randint(1, 5),
            is_vip=patient.is_vip,
            status="waiting",
        ))
    session.flush()

    session.commit()

    # ---- Ensure online_scorer tables exist (in case plugin hasn't run yet) ----
    try:
        import sqlite3
        from src.common.db_paths import get_velodoc_db_path
        velodoc_db = get_velodoc_db_path()
        conn = sqlite3.connect(velodoc_db, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS online_scorer_state (
                appointment_id INTEGER PRIMARY KEY,
                r0 REAL NOT NULL,
                rt REAL NOT NULL,
                event_history TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS online_scorer_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                text TEXT,
                timestamp TEXT NOT NULL,
                sent_at TEXT,
                hours_until_appt REAL,
                raw_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: Could not ensure online_scorer tables: {e}")

    # ---- Add online scorer state and events for all past appointments ----
    past_appointments = session.query(Appointment).filter(
        Appointment.start_dt < datetime.combine(today, datetime.min.time())
    ).all()
    for appt in past_appointments:
        tier = patient_tier.get(appt.patient_id, "low")
        _create_online_scorer_state_for_appointment(appt.id, r0=0.2)
        _create_online_scorer_events_for_patient(
            appt.id, tier, rng, appt.start_dt, appt.created_at
        )

    # ---- Reporting counts ----
    past_appts = session.query(Appointment).filter(Appointment.start_dt < datetime.combine(today, datetime.min.time())).count()
    past_fulfilled = session.query(Appointment).filter(
        Appointment.start_dt < datetime.combine(today, datetime.min.time()),
        Appointment.status == AppointmentStatus.fulfilled.value
    ).count()
    past_noshow = session.query(Appointment).filter(
        Appointment.start_dt < datetime.combine(today, datetime.min.time()),
        Appointment.status == AppointmentStatus.no_show.value
    ).count()

    return {
        "status": "ok",
        "seeded_patients": len(patients),
        "providers": len(providers),
        "days_past": days_past,
        "days_future": days_future,
        "past_appointments": past_appts,
        "past_fulfilled": past_fulfilled,
        "past_noshow": past_noshow,
        "waitlist_entries": session.query(WaitlistEntry).count(),
    }

if __name__ == "__main__":
    from ehr_emulator.models import get_session_factory
    import os
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    default_db = str((repo_root / "data" / "ehr_emulator.db").resolve())
    db_path = os.getenv("EHR_DB_PATH", default_db)
    factory = get_session_factory(db_path)
    session = factory()
    try:
        print(f"Seeding {db_path}...")
        res = run_seed(session)
        print(f"Done: {res}")
    finally:
        session.close()
