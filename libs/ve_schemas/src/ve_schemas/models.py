from datetime import date, datetime
from enum import Enum
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class ConsentClass(str, Enum):
    CARE_RECALL = "care_recall"
    MARKETING = "marketing"


class TreatmentArm(str, Enum):
    TREATED = "treated"
    HOLDOUT = "holdout"


class Channel(str, Enum):
    WHATSAPP = "whatsapp"
    SMS = "sms"
    EMAIL = "email"


class PatientRecord(BaseModel):
    patient_id: str
    clinic_id: str
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_e164: str
    language: str = "ar"
    condition_codes: list[str] = Field(default_factory=list)
    last_visit_date: Optional[date] = None
    last_procedure_type: Optional[str] = None
    open_treatment_plan: bool = False
    coverage_period_end_date: Optional[date] = None
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class PatientFeatures(BaseModel):
    patient_id: str
    clinic_id: str
    days_since_last_visit: Optional[int] = None
    visit_cadence_baseline: int = 180
    last_procedure_type: Optional[str] = None
    last_procedure_date: Optional[date] = None
    open_treatment_plan_flag: bool = False
    coverage_period_end_date: Optional[date] = None
    condition_codes: list[str] = Field(default_factory=list)
    age: Optional[int] = None
    sex: Optional[str] = None
    as_of_timestamp: datetime = Field(default_factory=datetime.utcnow)


class Opportunity(BaseModel):
    opportunity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    patient_id: str
    clinic_id: str
    family: str
    consent_class: ConsentClass
    priority_score: float = 0.0
    triggered_at: datetime = Field(default_factory=datetime.utcnow)
    rule_name: str
    rule_evidence: dict = Field(default_factory=dict)


class Campaign(BaseModel):
    campaign_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    opportunity_id: str
    patient_id: str
    clinic_id: str
    family: str
    channel: Channel = Channel.WHATSAPP
    treatment_arm: TreatmentArm
    template_id: Optional[str] = None
    template_vars: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    dispatched_at: Optional[datetime] = None


class Outcome(BaseModel):
    campaign_id: str
    patient_id: str
    delivered: bool = False
    read: bool = False
    replied: bool = False
    booked: bool = False
    attended: bool = False
    revenue: Decimal = Decimal("0.00")
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
