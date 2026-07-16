"""
fhir_mapper.py — FHIR R4 Resource Mapper
=========================================
Converts EHR emulator internal models to FHIR R4 compliant JSON structures.
Implements: Patient, Practitioner, Appointment, Schedule, Slot
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Any

from ehr_emulator.models import (
    Patient, Provider, Appointment, Schedule,
    AppointmentStatus
)

BASE_URL = "http://ehr-emulator/fhir"


def fhir_patient(p: Patient) -> Dict[str, Any]:
    resource: Dict[str, Any] = {
        "resourceType": "Patient",
        "id":           str(p.id),
        "meta":         {"profile": ["http://hl7.org/fhir/StructureDefinition/Patient"]},
        "name": [{"use": "official", "text": p.name}],
        "telecom": [{"system": "phone", "value": p.phone, "use": "mobile"}],
        "gender": p.gender or "unknown",
        "extension": [
            {
                "url":         "http://velodoc.ai/fhir/StructureDefinition/preferred-language",
                "valueCode":   p.preferred_language,
            },
            {
                "url":          "http://velodoc.ai/fhir/StructureDefinition/whatsapp-opt-in",
                "valueBoolean": p.whatsapp_opt_in,
            },
            {
                "url":          "http://velodoc.ai/fhir/StructureDefinition/is-vip",
                "valueBoolean": p.is_vip,
            },
        ],
    }
    if p.dob:
        resource["birthDate"] = p.dob
    if p.email:
        resource["telecom"].append({"system": "email", "value": p.email})
    return resource


def fhir_practitioner(prov: Provider) -> Dict[str, Any]:
    return {
        "resourceType": "Practitioner",
        "id":           str(prov.id),
        "name":         [{"use": "official", "text": prov.name}],
        "gender":       prov.gender or "unknown",
        "qualification": [
            {
                "code": {
                    "coding": [{
                        "system":  "http://velodoc.ai/fhir/specialty",
                        "code":    prov.specialty,
                        "display": prov.specialty.capitalize(),
                    }]
                }
            }
        ],
        "extension": [
            {"url": "http://velodoc.ai/fhir/branch", "valueString": prov.branch},
        ],
    }


def fhir_appointment(appt: Appointment) -> Dict[str, Any]:
    status_map = {
        AppointmentStatus.booked.value:      "booked",
        AppointmentStatus.confirmed.value:   "booked",       # FHIR uses "booked" for confirmed
        AppointmentStatus.cancelled.value:   "cancelled",
        AppointmentStatus.no_show.value:     "noshow",
        AppointmentStatus.checked_in.value:  "arrived",
        AppointmentStatus.fulfilled.value:   "fulfilled",
        AppointmentStatus.rescheduled.value: "cancelled",    # old slot is cancelled in FHIR model
    }

    resource: Dict[str, Any] = {
        "resourceType":    "Appointment",
        "id":              str(appt.id),
        "status":          status_map.get(appt.status, "booked"),
        "start":           appt.start_dt.isoformat() + "Z",
        "end":             appt.end_dt.isoformat() + "Z",
        "minutesDuration": int((appt.end_dt - appt.start_dt).total_seconds() / 60),
        "serviceType": [
            {
                "coding": [{
                    "system":  "http://velodoc.ai/fhir/service",
                    "code":    str(appt.service_id),
                    "display": appt.service.name if appt.service else str(appt.service_id),
                }]
            }
        ],
        "participant": [
            {
                "actor":  {"reference": f"Patient/{appt.patient_id}",
                           "display":   appt.patient.name if appt.patient else ""},
                "status": "accepted",
            },
            {
                "actor":  {"reference": f"Practitioner/{appt.provider_id}",
                           "display":   appt.provider.name if appt.provider else ""},
                "status": "accepted",
            },
        ],
        "extension": [
            {"url": "http://velodoc.ai/fhir/deposit-required",  "valueBoolean": appt.deposit_required},
            {"url": "http://velodoc.ai/fhir/deposit-paid",      "valueBoolean": appt.deposit_paid},
            {"url": "http://velodoc.ai/fhir/confirmation-status", "valueString": appt.confirmation_status},
        ],
    }

    if appt.cancellation_reason:
        resource["cancelationReason"] = {
            "text": appt.cancellation_reason
        }

    return resource


def fhir_schedule(schedule: Schedule, provider: Provider) -> Dict[str, Any]:
    start_dt = datetime.strptime(schedule.date, "%Y-%m-%d").replace(hour=schedule.start_hour)
    end_dt   = datetime.strptime(schedule.date, "%Y-%m-%d").replace(hour=schedule.end_hour)

    return {
        "resourceType": "Schedule",
        "id":           str(schedule.id),
        "active":       schedule.is_active,
        "actor": [
            {"reference": f"Practitioner/{provider.id}", "display": provider.name}
        ],
        "planningHorizon": {
            "start": start_dt.isoformat() + "Z",
            "end":   end_dt.isoformat() + "Z",
        },
        "extension": [
            {"url": "http://velodoc.ai/fhir/break-start", "valueInteger": schedule.break_start},
            {"url": "http://velodoc.ai/fhir/break-end",   "valueInteger": schedule.break_end},
        ],
    }


def fhir_slot(slot_dict: dict, schedule_id: int) -> Dict[str, Any]:
    return {
        "resourceType": "Slot",
        "id":           f"slot-{schedule_id}-{slot_dict['start'].replace(':', '-')}",
        "schedule":     {"reference": f"Schedule/{schedule_id}"},
        "status":       slot_dict["status"],   # "free" | "busy"
        "start":        slot_dict["start"] + "Z",
        "end":          slot_dict["end"] + "Z",
    }


def fhir_bundle(resource_type: str, resources: List[Dict]) -> Dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type":         "searchset",
        "total":        len(resources),
        "entry":        [
            {
                "fullUrl":  f"{BASE_URL}/{resource_type}/{r.get('id', i)}",
                "resource": r,
            }
            for i, r in enumerate(resources)
        ],
    }