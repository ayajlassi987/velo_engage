"""
models.py — SQLAlchemy ORM models for the EHR Emulator
"""
from __future__ import annotations
import os
import enum
from datetime import datetime
from pathlib import Path
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, Enum as SAEnum, JSON, create_engine
)
from sqlalchemy.orm import relationship, declarative_base, sessionmaker

Base = declarative_base()

# ── Enums ──────────────────────────────────────────────────────────────────

class AppointmentStatus(str, enum.Enum):
    booked      = "booked"
    confirmed   = "confirmed"
    cancelled   = "cancelled"
    no_show     = "no_show"
    checked_in  = "checked_in"
    fulfilled   = "fulfilled"
    rescheduled = "rescheduled"

class Specialty(str, enum.Enum):
    dental    = "dental"
    derma     = "derma"
    aesthetic = "aesthetic"

class Language(str, enum.Enum):
    ar = "ar"
    en = "en"

class RiskTier(str, enum.Enum):
    low    = "low"
    medium = "medium"
    high   = "high"

# ── Domain Models ──────────────────────────────────────────────────────────

class Patient(Base):
    __tablename__ = "patients"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    name               = Column(String(200), nullable=False)
    dob                = Column(String(10))          
    gender             = Column(String(10))          
    phone              = Column(String(30), unique=True)
    email              = Column(String(200))
    preferred_language = Column(String(5), default="en")
    whatsapp_opt_in    = Column(Boolean, default=True)
    sms_opt_in         = Column(Boolean, default=True)
    pref_time_start    = Column(Integer, default=8)   
    pref_time_end      = Column(Integer, default=18)  
    pref_provider_id   = Column(Integer, ForeignKey("providers.id"), nullable=True)
    pref_provider_gender = Column(String(10), nullable=True)
    is_vip             = Column(Boolean, default=False)
    distance_km        = Column(Float, default=10.0)
    notes              = Column(Text, default="")
    created_at         = Column(DateTime, default=datetime.utcnow)

    appointments = relationship("Appointment", back_populates="patient", foreign_keys="Appointment.patient_id")
    waitlist     = relationship("WaitlistEntry", back_populates="patient")

class Provider(Base):
    __tablename__ = "providers"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    name      = Column(String(200), nullable=False)
    specialty = Column(String(30), nullable=False)
    gender    = Column(String(10), default="male")
    branch    = Column(String(100), default="Main Clinic")
    is_active = Column(Boolean, default=True)
    # Provider-level empirical no-show rate (0.0 - 1.0) used by seed generator
    provider_noshow_rate = Column(Float, default=0.10)

    schedules    = relationship("Schedule", back_populates="provider")
    appointments = relationship("Appointment", back_populates="provider")

class Service(Base):
    __tablename__ = "services"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    name           = Column(String(200), nullable=False)
    specialty      = Column(String(30), nullable=False)
    duration_mins  = Column(Integer, nullable=False)
    buffer_mins    = Column(Integer, default=0)    
    base_price     = Column(Float, default=0.0)
    requires_room  = Column(String(50), nullable=True)  
    deposit_pct    = Column(Float, default=0.0)         

    appointments = relationship("Appointment", back_populates="service")
    waitlist     = relationship("WaitlistEntry", back_populates="service")

class Schedule(Base):
    __tablename__ = "schedules"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    date        = Column(String(10), nullable=False)   
    start_hour  = Column(Integer, default=8)
    end_hour    = Column(Integer, default=18)
    break_start = Column(Integer, nullable=True)       
    break_end   = Column(Integer, nullable=True)       
    is_active   = Column(Boolean, default=True)

    provider = relationship("Provider", back_populates="schedules")

class Appointment(Base):
    __tablename__ = "appointments"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    patient_id      = Column(Integer, ForeignKey("patients.id"), nullable=False)
    provider_id     = Column(Integer, ForeignKey("providers.id"), nullable=False)
    service_id      = Column(Integer, ForeignKey("services.id"), nullable=False)
    start_dt        = Column(DateTime, nullable=False)
    end_dt          = Column(DateTime, nullable=False)
    status          = Column(String(30), default=AppointmentStatus.booked.value)
    cancellation_reason = Column(Text, nullable=True)
    no_show_reason  = Column(Text, nullable=True)
    deposit_required = Column(Boolean, default=False)
    deposit_paid     = Column(Boolean, default=False)
    deposit_amount   = Column(Float, default=0.0)
    confirmation_status = Column(String(30), default="pending")  
    risk_score       = Column(Float, nullable=True)
    risk_tier        = Column(String(10), nullable=True)
    risk_reasons     = Column(JSON, default=list)
    notes            = Column(Text, default="")
    is_walk_in       = Column(Boolean, default=False)
    idempotency_key  = Column(String(100), nullable=True, unique=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient  = relationship("Patient", back_populates="appointments", foreign_keys=[patient_id])
    provider = relationship("Provider", back_populates="appointments")
    service  = relationship("Service", back_populates="appointments")
    events   = relationship("AppointmentEvent", back_populates="appointment")

class AppointmentEvent(Base):
    __tablename__ = "appointment_events"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=False)
    event_type     = Column(String(60), nullable=False)
    old_status     = Column(String(30), nullable=True)
    new_status     = Column(String(30), nullable=True)
    actor          = Column(String(100), default="system")
    payload        = Column(JSON, default=dict)
    created_at     = Column(DateTime, default=datetime.utcnow)

    appointment = relationship("Appointment", back_populates="events")

class WaitlistEntry(Base):
    __tablename__ = "waitlist"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    patient_id          = Column(Integer, ForeignKey("patients.id"), nullable=False)
    service_id          = Column(Integer, ForeignKey("services.id"), nullable=False)
    pref_provider_id    = Column(Integer, ForeignKey("providers.id"), nullable=True)
    pref_time_start     = Column(Integer, default=8)
    pref_time_end       = Column(Integer, default=18)
    priority            = Column(Integer, default=5)    
    is_vip              = Column(Boolean, default=False)
    notes               = Column(Text, default="")
    status              = Column(String(20), default="waiting")   
    offer_expires_at    = Column(DateTime, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)

    patient  = relationship("Patient", back_populates="waitlist")
    service  = relationship("Service", back_populates="waitlist")
    provider = relationship("Provider", foreign_keys=[pref_provider_id])

class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    url        = Column(String(500), nullable=False)
    secret     = Column(String(200), nullable=False)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    deliveries = relationship("WebhookDelivery", back_populates="endpoint")

class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    endpoint_id     = Column(Integer, ForeignKey("webhook_endpoints.id"), nullable=False)
    event_type      = Column(String(60), nullable=False)
    payload         = Column(JSON, nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    status          = Column(String(20), default="pending")  
    attempts        = Column(Integer, default=0)
    response_code   = Column(Integer, nullable=True)
    last_attempt_at = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    endpoint = relationship("WebhookEndpoint", back_populates="deliveries")

class Slot(Base):
    """
    Explicit slot representation for the state machine and row-level locking.
    """
    __tablename__ = "slots"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    start_dt    = Column(DateTime, nullable=False, index=True)
    end_dt      = Column(DateTime, nullable=False)
    status      = Column(String(30), default="free") # free, offered, booked, filled, expired
    version     = Column(Integer, default=1)         # for optimistic locking
    created_at  = Column(DateTime, default=datetime.utcnow)

class ScheduledJob(Base):
    """
    Database-backed event queue.
    """
    __tablename__ = "scheduled_jobs"
    
    id         = Column(Integer, primary_key=True, autoincrement=True)
    job_type   = Column(String(100), nullable=False)
    payload    = Column(JSON, default=dict)
    run_at     = Column(DateTime, nullable=False, index=True)
    status     = Column(String(30), default="pending") # pending, done, failed
    created_at = Column(DateTime, default=datetime.utcnow)

class IdempotencyKey(Base):
    """
    Stores tool execution results to prevent duplicate actions.
    """
    __tablename__ = "idempotency_keys"
    
    key        = Column(String(100), primary_key=True)
    result     = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

class EventLog(Base):
    """
    Immutable event store — audit trail for all system actions.
    INSERT-only: no UPDATE or DELETE allowed at application level.
    """
    __tablename__ = "event_log"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    event_type     = Column(String(80), nullable=False, index=True)
    entity_type    = Column(String(40), nullable=True)   # "appointment", "patient", "slot", "offer"
    entity_id      = Column(Integer, nullable=True)
    actor          = Column(String(100), default="system")
    action         = Column(String(100), nullable=False)  # "created", "cancelled", "offer_sent", etc.
    payload        = Column(JSON, default=dict)
    idempotency_key = Column(String(100), nullable=True, unique=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

# ── DB setup ───────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve_db_path(db_path: str | None = None) -> str:
    raw = db_path or os.getenv("EHR_DB_PATH") or str(Path("data") / "ehr_emulator.db")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (_REPO_ROOT / p).resolve()
    else:
        p = p.resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _get_database_url() -> str | None:
    """Check for PostgreSQL connection string in environment."""
    return os.getenv("EHR_DATABASE_URL") or os.getenv("DATABASE_URL")


def get_engine(db_path: str | None = None):
    """
    Create SQLAlchemy engine.
    Priority:
      1. EHR_DATABASE_URL env → PostgreSQL
      2. db_path / EHR_DB_PATH → SQLite (development fallback)
    """
    from sqlalchemy import event as _sa_event
    from sqlalchemy.pool import NullPool

    pg_url = _get_database_url()

    if pg_url and pg_url.startswith("postgres"):
        # ── PostgreSQL mode ──────────────────────────────────────────
        engine = create_engine(
            pg_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
        import logging
        logging.getLogger(__name__).info("EHR Emulator using PostgreSQL")
        return engine

    # ── SQLite fallback (development) ────────────────────────────────
    resolved_db_path = _resolve_db_path(db_path)
    engine = create_engine(
        f"sqlite:///{resolved_db_path}",
        connect_args={
            "check_same_thread": False, 
            "timeout": 30, 
            "isolation_level": "IMMEDIATE"
        },
        poolclass=NullPool,
    )
    @_sa_event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA busy_timeout=30000")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")
    return engine

def get_session_factory(db_path: str | None = None):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)