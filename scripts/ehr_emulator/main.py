"""
main.py — EHR Emulator FastAPI Application
===========================================
Full REST + FHIR R4 API for testing the Velodoc Clinic Slot Optimizer plugin.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, List
import time as _time
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import sessionmaker, joinedload

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ehr_emulator.models import (
    Patient, Provider, Service, Schedule, Appointment, AppointmentEvent,
    WaitlistEntry, WebhookEndpoint, WebhookDelivery,
    AppointmentStatus, get_engine, get_session_factory, Base
)
from ehr_emulator.slot_engine  import get_available_slots, get_micro_gaps, check_slot_available
from ehr_emulator.lifecycle    import transition, log_created, LifecycleError
from ehr_emulator.fhir_mapper  import (fhir_patient, fhir_practitioner, fhir_appointment,
                          fhir_schedule, fhir_slot, fhir_bundle)
from ehr_emulator.scenarios    import run_scenario, SCENARIO_CATALOG
from ehr_emulator.seed         import run_seed
from ehr_emulator.webhooks     import dispatch_event, retry_failed, simulate_inbound_reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ehr_emulator")

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve_db_path(raw: str | None) -> str:
    candidate = raw or str(Path("data") / "ehr_emulator.db")
    p = Path(candidate).expanduser()
    if not p.is_absolute():
        p = (_REPO_ROOT / p).resolve()
    else:
        p = p.resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


DB_PATH = _resolve_db_path(os.getenv("EHR_DB_PATH"))
SessionFactory = get_session_factory(DB_PATH)


def get_session():
    return SessionFactory()


def _on_event(event_type: str, payload: dict):
    """Dispatch webhook in its own session."""
    s = get_session()
    try:
        dispatch_event(s, event_type, payload)
    except Exception as exc:
        logger.warning("Webhook dispatch failed: %s", exc)
    finally:
        s.close()


_event_rate_cache: dict = {}
 
def _make_deferred_on_event(background_tasks: BackgroundTasks):
    _pending: list =[]
 
    def _capture(event_type: str, payload: dict) -> None:
        appt_id  = payload.get("appointment_id", "unknown")
        cache_key = f"{appt_id}:{event_type}"
        now       = _time.time()
 
        last_sent = _event_rate_cache.get(cache_key, 0)
        if now - last_sent < 60:
            return
 
        _event_rate_cache[cache_key] = now
        _pending.append((event_type, payload))
 
    def _flush() -> None:
        for evt_type, evt_payload in _pending:
            _on_event(evt_type, evt_payload)
 
    if background_tasks:
        background_tasks.add_task(_flush)
 
    return _capture


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine(DB_PATH)
    Base.metadata.create_all(engine)

    def _maybe_seed():
        s = get_session()
        try:
            count = s.query(Patient).count()
            if count == 0:
                logger.info("Empty DB detected — running auto-seed in background...")
                result = run_seed(s)
                logger.info("Auto-seed background complete: %s", result)
        except Exception as e:
            logger.error("Auto-seed error: %s", e)
        finally:
            s.close()
    
    import threading
    threading.Thread(target=_maybe_seed, daemon=True).start()

    yield

    try:
        retry_failed(DB_PATH)
    except Exception:
        pass


app = FastAPI(
    title="Velodoc EHR Emulator",
    version="1.0.0",
    description="Mock EHR for UAE/KSA outpatient clinics.",
    lifespan=lifespan,
)


class CreatePatientIn(BaseModel):
    name:               str
    dob:                Optional[str]  = None
    gender:             Optional[str]  = "male"
    phone:              str
    email:              Optional[str]  = None
    preferred_language: str            = "en"
    whatsapp_opt_in:    bool           = True
    sms_opt_in:         bool           = True
    pref_time_start:    int            = 8
    pref_time_end:      int            = 18
    is_vip:             bool           = False
    distance_km:         float          = 10.0
    insurance_type:      str            = "unknown"
    estimated_travel_time_min: Optional[float] = None
    notes:              str            = ""

class CreateAppointmentIn(BaseModel):
    patient_id:   int
    provider_id:  int
    service_id:   int
    start_dt:     str
    notes:        str   = ""
    is_walk_in:   bool  = False
    idempotency_key: Optional[str] = None

class UpdateAppointmentIn(BaseModel):
    status:              str
    reason:              Optional[str] = None
    actor:               str           = "staff"
    deposit_paid:        Optional[bool] = None
    confirmation_status: Optional[str]  = None

class UpdateAppointmentRiskIn(BaseModel):
    risk_score: float
    actor: str = "online_scorer"

class RescheduleIn(BaseModel):
    new_start_dt:    str
    new_provider_id: Optional[int] = None
    actor:           str           = "staff"
    reason:          Optional[str] = None

class CreateWaitlistIn(BaseModel):
    patient_id:       int
    service_id:       int
    pref_provider_id: Optional[int] = None
    pref_time_start:  int           = 8
    pref_time_end:    int           = 18
    priority:         int           = 5
    notes:            str           = ""

class UpdateWaitlistIn(BaseModel):
    status:           Optional[str] = None
    priority:         Optional[int] = None
    pref_time_start:  Optional[int] = None
    pref_time_end:    Optional[int] = None
    notes:            Optional[str] = None

class RegisterWebhookIn(BaseModel):
    url:    str
    secret: str = Field(default_factory=lambda: str(uuid.uuid4()))

class ScenarioRunIn(BaseModel):
    scenario_id:  str
    date:         Optional[str] = None
    seed:         int           = 42

class SeedIn(BaseModel):
    seed:                  int = 42
    num_patients:          int = 180
    days_ahead:            int = 60
    appointments_per_day:  int = 6


def _parse_notes_value(notes: str | None, key: str) -> Optional[str]:
    prefix = f"{key}="
    for part in str(notes or "").replace("\n", ";").split(";"):
        item = part.strip()
        if item.lower().startswith(prefix.lower()):
            return item.split("=", 1)[1].strip()
    return None


def _age_from_dob(dob: str | None) -> Optional[int]:
    if not dob:
        return None
    try:
        born = date.fromisoformat(str(dob)[:10])
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _insurance_type(patient: Patient | None) -> str:
    raw = _parse_notes_value(patient.notes if patient else None, "insurance_type")
    v = str(raw or "unknown").strip().lower()
    if "daman" in v:
        return "daman"
    if "cchi" in v or "saudi" in v:
        return "cchi"
    if "cash" in v or "self" in v:
        return "cash"
    if "premium" in v or "vip" in v:
        return "premium"
    return v if v in {"daman", "cchi", "cash", "premium"} else "unknown"


def _travel_minutes(patient: Patient | None) -> Optional[float]:
    raw = _parse_notes_value(patient.notes if patient else None, "estimated_travel_time_min")
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass

    distance = getattr(patient, "distance_km", None)
    if distance is None:
        return None
    try:
        # City clinic approximation: 24 km/h average plus parking/check-in buffer.
        return round(max(5.0, min(120.0, 8.0 + float(distance) * 2.5)), 1)
    except (TypeError, ValueError):
        return None


def _normalise_specialty(value: str | None) -> str:
    v = str(value or "").strip().lower()
    if "dent" in v:
        return "dental"
    if "derma" in v or "skin" in v:
        return "dermatology"
    if "aesthetic" in v or "laser" in v or "botox" in v:
        return "aesthetic"
    if "ortho" in v:
        return "orthopedic"
    if "general" in v or "pediatric" in v:
        return "general"
    return "unknown"


def _normalise_branch(value: str | None) -> str:
    v = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if "abu" in v and "dhabi" in v:
        return "abu_dhabi"
    if "dubai" in v or "main" in v:
        return "dubai"
    if "riyadh" in v:
        return "riyadh"
    if "jeddah" in v:
        return "jeddah"
    if "dammam" in v:
        return "dammam"
    return "unknown"


def _patient_context(patient: Patient | None) -> dict:
    age = _age_from_dob(patient.dob if patient else None)
    travel_minutes = _travel_minutes(patient)
    return {
        "patient_dob": patient.dob if patient else None,
        "patient_age": age,
        "age": age,
        "insurance_type": _insurance_type(patient),
        "payer_type": _insurance_type(patient),
        "distance_km": getattr(patient, "distance_km", None),
        "estimated_travel_time_min": travel_minutes,
        "travel_time_minutes": travel_minutes,
    }


def _appt_dict(a: Appointment) -> dict:
    patient_ctx = _patient_context(a.patient)
    specialty = _normalise_specialty(
        a.service.specialty if a.service else a.provider.specialty if a.provider else None
    )
    return {
        "id":               a.id,
        "patient_id":       a.patient_id,
        "patient_name":     a.patient.name if a.patient else None,
        "patient_phone":    a.patient.phone if a.patient else None,
        **patient_ctx,
        "provider_id":      a.provider_id,
        "provider_name":    a.provider.name if a.provider else None,
        "provider_specialty": a.provider.specialty if a.provider else None,
        "provider_noshow_rate": a.provider.provider_noshow_rate if a.provider else None,
        "service_id":       a.service_id,
        "service_name":     a.service.name if a.service else None,
        "service_specialty": a.service.specialty if a.service else None,
        "specialty":        specialty,
        "service_duration": a.service.duration_mins if a.service else None,
        "clinic_branch":    _normalise_branch(a.provider.branch if a.provider else None),
        "appt_type":        "walkin" if a.is_walk_in else "in_person",
        "start_dt":         a.start_dt.isoformat(),
        "end_dt":           a.end_dt.isoformat(),
        "status":           a.status,
        "deposit_required": a.deposit_required,
        "deposit_paid":     a.deposit_paid,
        "deposit_amount":   a.deposit_amount,
        "confirmation_status": a.confirmation_status,
        "risk_score":       a.risk_score,
        "risk_tier":        a.risk_tier,
        "risk_reasons":     a.risk_reasons or[],
        "notes":            a.notes,
        "is_walk_in":       a.is_walk_in,
        "created_at":       a.created_at.isoformat(),
        "updated_at":       a.updated_at.isoformat() if a.updated_at else None,
    }


@app.get("/api/stats", tags=["Meta"])
def get_stats():
    s = get_session()
    try:
        return {
            "patients":     s.query(Patient).count(),
            "providers":    s.query(Provider).count(),
            "services":     s.query(Service).count(),
            "appointments": s.query(Appointment).count(),
            "waitlist":     s.query(WaitlistEntry).count(),
            "webhooks":     s.query(WebhookEndpoint).filter_by(is_active=True).count(),
        }
    finally:
        s.close()


@app.get("/api/patients", tags=["Patients"])
def list_patients(skip: int = 0, limit: int = 50):
    s = get_session()
    try:
        patients = s.query(Patient).offset(skip).limit(limit).all()
        return[
            {
                "id": p.id, "name": p.name, "phone": p.phone,
                "gender": p.gender, "dob": p.dob,
                **_patient_context(p),
                "preferred_language": p.preferred_language,
                "whatsapp_opt_in": p.whatsapp_opt_in,
                "sms_opt_in": p.sms_opt_in,
                "is_vip": p.is_vip,
                "pref_time_start": p.pref_time_start,
                "pref_time_end": p.pref_time_end,
            }
            for p in patients
        ]
    finally:
        s.close()


@app.get("/api/patients/{patient_id}", tags=["Patients"])
def get_patient(patient_id: int):
    s = get_session()
    try:
        p = s.query(Patient).get(patient_id)
        if not p:
            raise HTTPException(404, f"Patient {patient_id} not found")
        return {
            "id": p.id, "name": p.name, "phone": p.phone, "email": p.email,
            "gender": p.gender, "dob": p.dob,
            **_patient_context(p),
            "preferred_language": p.preferred_language,
            "whatsapp_opt_in": p.whatsapp_opt_in, "sms_opt_in": p.sms_opt_in,
            "is_vip": p.is_vip, "notes": p.notes,
        }
    finally:
        s.close()


@app.post("/api/patients", tags=["Patients"], status_code=201)
def create_patient(data: CreatePatientIn, background_tasks: BackgroundTasks):
    s = get_session()
    try:
        if s.query(Patient).filter_by(phone=data.phone).first():
            raise HTTPException(409, f"Phone {data.phone} already registered")
        payload = data.model_dump()
        insurance_type = payload.pop("insurance_type", "unknown")
        travel_minutes = payload.pop("estimated_travel_time_min", None)
        notes = payload.get("notes") or ""
        metadata = [f"insurance_type={insurance_type}"]
        if travel_minutes is not None:
            metadata.append(f"estimated_travel_time_min={travel_minutes}")
        payload["notes"] = "; ".join([notes.strip(), *metadata]).strip("; ")
        p = Patient(**payload)
        s.add(p); s.commit(); s.refresh(p)
        background_tasks.add_task(_on_event, "patient.updated", {"patient_id": p.id, "action": "created"})
        return {"id": p.id, "name": p.name, "phone": p.phone}
    finally:
        s.close()


@app.get("/api/providers", tags=["Providers"])
def list_providers():
    s = get_session()
    try:
        provs = s.query(Provider).filter_by(is_active=True).all()
        return[{"id": p.id, "name": p.name, "specialty": p.specialty, "gender": p.gender, "branch": p.branch} for p in provs]
    finally:
        s.close()

@app.get("/api/services", tags=["Services"])
def list_services(specialty: Optional[str] = None):
    s = get_session()
    try:
        q = s.query(Service)
        if specialty: q = q.filter_by(specialty=specialty)
        return[{"id": svc.id, "name": svc.name, "specialty": svc.specialty, "duration_mins": svc.duration_mins, "base_price": svc.base_price, "deposit_pct": svc.deposit_pct} for svc in q.all()]
    finally:
        s.close()

@app.get("/api/appointments", tags=["Appointments"])
def list_appointments(
    from_dt: Optional[str] = Query(None, alias="from"),
    to_dt: Optional[str] = Query(None, alias="to"),
    provider_id: Optional[int] = Query(None, alias="providerId"),
    patient_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0, limit: int = 100,
):
    s = get_session()
    try:
        q = s.query(Appointment).options(joinedload(Appointment.patient), joinedload(Appointment.provider), joinedload(Appointment.service))
        if from_dt: q = q.filter(Appointment.start_dt >= datetime.fromisoformat(from_dt))
        if to_dt:   q = q.filter(Appointment.start_dt <= datetime.fromisoformat(to_dt))
        if provider_id: q = q.filter_by(provider_id=provider_id)
        if patient_id:  q = q.filter_by(patient_id=patient_id)
        if status:
            statuses =[st.strip() for st in status.split(",")]
            q = q.filter(Appointment.status.in_(statuses))

        appts = q.order_by(Appointment.start_dt).offset(skip).limit(limit).all()
        return {"appointments":[_appt_dict(a) for a in appts], "total": len(appts)}
    finally:
        s.close()

@app.get("/api/appointments/{appt_id}", tags=["Appointments"])
def get_appointment(appt_id: int):
    s = get_session()
    try:
        a = s.query(Appointment).options(joinedload(Appointment.patient), joinedload(Appointment.provider), joinedload(Appointment.service)).get(appt_id)
        if not a: raise HTTPException(404, f"Appointment {appt_id} not found")
        return _appt_dict(a)
    finally:
        s.close()


@app.post("/api/appointments", tags=["Appointments"], status_code=201)
def create_appointment(data: CreateAppointmentIn, background_tasks: BackgroundTasks):
    capture = _make_deferred_on_event(background_tasks)
    s = get_session()
    result = None
    try:
        start_dt = datetime.fromisoformat(data.start_dt)
        svc = s.query(Service).get(data.service_id)
        if not svc:
            raise HTTPException(404, f"Service {data.service_id} not found")
        
        provider = s.query(Provider).get(data.provider_id)
        if not provider:
            raise HTTPException(404, f"Provider {data.provider_id} not found")
            
        if svc.specialty != provider.specialty:
            raise HTTPException(400, f"Service specialty ({svc.specialty}) does not match provider specialty ({provider.specialty})")

        end_dt  = start_dt + timedelta(minutes=svc.duration_mins)

        available, reason = check_slot_available(s, data.provider_id, start_dt, svc.duration_mins)
        if not available:
            raise HTTPException(409, f"Slot not available: {reason}")

        idem_key = data.idempotency_key or str(uuid.uuid4())
        existing = s.query(Appointment).filter_by(idempotency_key=idem_key).first()
        if existing:
            return _appt_dict(existing)

        deposit_required = svc.deposit_pct > 0
        appt = Appointment(
            patient_id       = data.patient_id,
            provider_id      = data.provider_id,
            service_id       = data.service_id,
            start_dt         = start_dt,
            end_dt           = end_dt,
            status           = AppointmentStatus.booked.value,
            deposit_required = deposit_required,
            deposit_amount   = svc.base_price * svc.deposit_pct if deposit_required else 0,
            notes            = data.notes,
            is_walk_in       = data.is_walk_in,
            idempotency_key  = idem_key,
        )
        s.add(appt)
        s.flush()
        log_created(s, appt, on_event=capture)
        s.commit()
        s.refresh(appt)
        
        appt = s.query(Appointment).options(
            joinedload(Appointment.patient),
            joinedload(Appointment.provider),
            joinedload(Appointment.service),
        ).get(appt.id)
        result = _appt_dict(appt)
    finally:
        s.close()
    return result


@app.patch("/api/appointments/{appt_id}", tags=["Appointments"])
def update_appointment_status(appt_id: int, data: UpdateAppointmentIn, background_tasks: BackgroundTasks):
    capture = _make_deferred_on_event(background_tasks)
    s = get_session()
    result = None
    try:
        appt = s.query(Appointment).get(appt_id)
        if not appt:
            raise HTTPException(404, f"Appointment {appt_id} not found")
 
        if appt.status == data.status:
            if data.deposit_paid is not None:
                appt.deposit_paid = data.deposit_paid
            if data.confirmation_status:
                appt.confirmation_status = data.confirmation_status
            s.commit()
            return {"id": appt_id, "new_status": appt.status, "ok": True, "note": "already_in_status"}
 
        allowed = {
            "booked":      ["confirmed", "cancelled", "no_show", "checked_in", "rescheduled", "fulfilled"],
            "confirmed":   ["cancelled", "no_show", "checked_in", "rescheduled", "fulfilled"],
            "checked_in":  ["fulfilled", "no_show"],
            "cancelled":   ["booked"],
            "no_show":     ["booked"],
            "fulfilled":   ["booked"],
            "rescheduled": ["booked"],
        }
        current_allowed = allowed.get(appt.status,[])
        if data.status not in current_allowed:
            return {
                "id":          appt_id,
                "ok":          False,
                "current_status": appt.status,
                "requested_status": data.status,
                "note":        f"Cannot transition from '{appt.status}' to '{data.status}'.",
                "http_status": 200, 
            }
 
        try:
            transition(
                s, appt, data.status,
                actor=data.actor, reason=data.reason,
                on_event=capture,
            )
        except LifecycleError as e:
            return {
                "id": appt_id, "ok": False,
                "current_status": appt.status,
                "requested_status": data.status,
                "note": str(e),
            }
 
        if data.deposit_paid is not None:
            appt.deposit_paid = data.deposit_paid
        if data.confirmation_status:
            appt.confirmation_status = data.confirmation_status
 
        s.commit()
        result = {"id": appt_id, "new_status": appt.status, "ok": True}
    finally:
        s.close()
    return result


@app.patch("/api/appointments/{appt_id}/risk", tags=["Appointments"])
def update_appointment_risk(appt_id: int, data: UpdateAppointmentRiskIn):
    s = get_session()
    try:
        appt = s.query(Appointment).get(appt_id)
        if not appt:
            raise HTTPException(404, f"Appointment {appt_id} not found")

        appt.risk_score = float(data.risk_score)

        s.add(
            AppointmentEvent(
                appointment_id=appt_id,
                event_type="risk_updated",
                actor=data.actor,
                payload={"risk_score": float(data.risk_score)},
            )
        )
        s.commit()

        return {
            "id": appt_id,
            "risk_score": float(appt.risk_score),
            "ok": True,
        }
    finally:
        s.close()


@app.post("/api/appointments/{appt_id}/reschedule", tags=["Appointments"])
def reschedule_appointment(appt_id: int, data: RescheduleIn, background_tasks: BackgroundTasks):
    capture = _make_deferred_on_event(background_tasks)
    s = get_session()
    result = None
    try:
        appt = s.query(Appointment).options(joinedload(Appointment.service)).get(appt_id)
        if not appt:
            raise HTTPException(404, f"Appointment {appt_id} not found")

        new_start = datetime.fromisoformat(data.new_start_dt)
        new_end   = new_start + timedelta(minutes=appt.service.duration_mins)

        # FIX: Check the NEW provider's schedule, not the old provider!
        target_provider_id = data.new_provider_id if data.new_provider_id else appt.provider_id

        available, reason = check_slot_available(s, target_provider_id, new_start, appt.service.duration_mins)
        if not available:
            raise HTTPException(409, f"New slot not available: {reason}")

        old_start = appt.start_dt
        transition(
            s, appt, AppointmentStatus.rescheduled.value,
            actor=data.actor, reason=data.reason,
            extra_payload={"old_start": old_start.isoformat(), "new_start": new_start.isoformat()},
            on_event=capture,
        )

        new_appt = Appointment(
            patient_id       = appt.patient_id,
            provider_id      = target_provider_id,  # FIX: Assing to the NEW doctor
            service_id       = appt.service_id,
            start_dt         = new_start,
            end_dt           = new_end,
            status           = AppointmentStatus.booked.value,
            deposit_required = appt.deposit_required,
            deposit_paid     = appt.deposit_paid,
            deposit_amount   = appt.deposit_amount,
            notes            = f"Rescheduled from {old_start.strftime('%Y-%m-%d %H:%M')}. {data.reason or ''}".strip(),
            idempotency_key  = str(uuid.uuid4()),
        )
        s.add(new_appt)
        s.flush()
        log_created(s, new_appt, actor=data.actor, on_event=capture)
        s.commit()

        result = {
            "old_appointment_id":  appt_id,
            "new_appointment_id":  new_appt.id,
            "new_start":           new_start.isoformat(),
            "ok":                  True,
        }
    except LifecycleError as e:
        raise HTTPException(422, str(e))
    finally:
        s.close()
    return result


@app.get("/api/slots", tags=["Schedule & Slots"])
def get_slots(
    providerId: int,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    duration_mins: int = 30,
):
    s = get_session()
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date()
        end   = datetime.strptime(to_date,   "%Y-%m-%d").date()

        all_slots =[]
        d = start
        while d <= end:
            if d.weekday() != 4:
                all_slots.extend(get_available_slots(s, providerId, d.strftime("%Y-%m-%d"), duration_mins))
            d += timedelta(days=1)

        return {"provider_id": providerId, "available_slots": all_slots, "total_free": len(all_slots)}
    finally:
        s.close()


@app.get("/api/waitlist", tags=["Waitlist"])
def get_waitlist(service_id: Optional[int] = Query(None, alias="serviceId"), provider_id: Optional[int] = Query(None, alias="providerId")):
    s = get_session()
    try:
        q = s.query(WaitlistEntry).options(joinedload(WaitlistEntry.patient), joinedload(WaitlistEntry.service))
        if service_id: q = q.filter_by(service_id=service_id)
        if provider_id:
            from sqlalchemy import or_
            q = q.filter(or_(WaitlistEntry.pref_provider_id == provider_id, WaitlistEntry.pref_provider_id == None))
        entries = q.filter_by(status="waiting").order_by(WaitlistEntry.priority, WaitlistEntry.created_at).all()
        return[
            {
                "id": e.id, "patient_id": e.patient_id, "patient_name": e.patient.name,
                "patient_phone": e.patient.phone, "service_id": e.service_id, "service_name": e.service.name,
                "service_specialty": e.service.specialty,
                "priority": e.priority, "Est_Revenue": e.service.base_price, "service_duration": e.service.duration_mins,
                "is_vip": e.patient.is_vip, "distance_km": e.patient.distance_km,
                "pref_provider_id": e.pref_provider_id, "pref_time_start": e.pref_time_start,
                "pref_time_end": e.pref_time_end, "status": e.status,
            }
            for e in entries
        ]
    finally:
        s.close()


@app.patch("/api/waitlist/{entry_id}", tags=["Waitlist"])
def update_waitlist_entry(entry_id: int, data: UpdateWaitlistIn, background_tasks: BackgroundTasks):
    s = get_session()
    try:
        entry = s.query(WaitlistEntry).get(entry_id)
        if not entry:
            raise HTTPException(404, f"Waitlist entry {entry_id} not found")
        for field, value in data.model_dump(exclude_none=True).items():
            if hasattr(entry, field):
                setattr(entry, field, value)
        try:
            s.commit()
        except Exception as lock_err:
            s.rollback()
            logger.warning("Waitlist update skipped (DB busy): %s", lock_err)
            return {"id": entry_id, "ok": True, "note": "skipped_db_busy"}
        return {"id": entry_id, "ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        s.close()

@app.post("/api/scenarios/seed", tags=["Scenarios"])
def seed_data(data: SeedIn):
    s = get_session()
    try:
        result = run_seed(s, seed=data.seed, num_patients=data.num_patients, days_ahead=data.days_ahead, appointments_per_day=data.appointments_per_day)
        return result
    finally:
        s.close()

@app.post("/webhooks/register", tags=["Webhooks"])
def register_webhook(data: RegisterWebhookIn):
    s = get_session()
    try:
        endpoint = s.query(WebhookEndpoint).filter_by(url=data.url).first()
        if endpoint:
            endpoint.secret = data.secret
            endpoint.is_active = True
        else:
            endpoint = WebhookEndpoint(url=data.url, secret=data.secret)
            s.add(endpoint)
        s.commit()
        s.refresh(endpoint)
        return {"id": endpoint.id, "url": endpoint.url, "secret": endpoint.secret}
    finally:
        s.close()

@app.post("/api/webhooks/clear-stuck", tags=["Webhooks"])
def clear_stuck_webhooks():
    from webhooks import clear_stuck_pending
    result = clear_stuck_pending(DB_PATH)
    return {"status": "ok", "cleared": result["cleared"],
            "message": f"Marked {result['cleared']} stuck deliveries as sent."}
