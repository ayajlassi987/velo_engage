"""
Translates raw Epic FHIR R4 resources → PatientFeatures schema.

Epic-specific notes:
- Condition codes: in resource.code.coding[] with ICD-10 system URI
- Encounter class: "ambulatory" / "outpatient" = clinic visit
- CarePlan.status = "active" = open treatment plan
- Coverage.period.end = insurance expiry date
"""

from datetime import date, datetime
from typing import Optional


def _parse_date(val) -> Optional[date]:
    if not val: return None
    try: return datetime.fromisoformat(val.replace("Z","+00:00")).date()
    except: 
        try: return date.fromisoformat(val[:10])
        except: return None


def _days_ago(d: Optional[date]) -> Optional[int]:
    return (date.today() - d).days if d else None


def extract_icd10_codes(conditions: list[dict]) -> list[str]:
    codes = []
    for c in conditions:
        status = c.get("clinicalStatus",{}).get("coding",[{}])[0].get("code","")
        if status not in ("active","recurrence","relapse"): continue
        for coding in c.get("code",{}).get("coding",[]):
            if "icd-10" in coding.get("system","").lower():
                codes.append(coding.get("code",""))
    return list(set(codes))


def extract_last_visit(encounters: list[dict]) -> Optional[date]:
    # Dropped the Encounter.class check that was here — confirmed live
    # against real Epic data that Epic populates `class` with its own
    # internal proprietary coding system (e.g. system
    # "urn:oid:1.2.840.114350...", code "13", display "Support OP
    # Encounter"), not the standard FHIR v3-ActCode values
    # ("ambulatory"/"outpatient") this originally checked for — the filter
    # matched zero real Epic encounters and silently dropped every visit
    # date. `status: finished` (already filtered at the API call itself)
    # is a sufficient signal that this was a real completed visit.
    dates = []
    for enc in encounters:
        if enc.get("status") not in ("finished","completed"): continue
        d = _parse_date(enc.get("period",{}).get("end"))
        if d: dates.append(d)
    return max(dates) if dates else None


def extract_last_procedure(procedures: list[dict]) -> tuple[Optional[str], Optional[date]]:
    completed = []
    for p in procedures:
        if p.get("status") != "completed": continue
        d = _parse_date(p.get("performedDateTime") or p.get("performedPeriod",{}).get("end"))
        display = p.get("code",{}).get("text") or p.get("code",{}).get("coding",[{}])[0].get("display","")
        if d: completed.append((d, display))
    if not completed: return None, None
    latest = max(completed, key=lambda x: x[0])
    return latest[1], latest[0]


def extract_coverage_end(coverages: list[dict]) -> Optional[date]:
    ends = [_parse_date(c.get("period",{}).get("end")) for c in coverages
            if c.get("status")=="active" and c.get("period",{}).get("end")]
    return max(ends) if ends else None


def extract_phone(patient: dict) -> Optional[str]:
    for use in ("mobile","home","work"):
        for t in patient.get("telecom",[]):
            if t.get("system")=="phone" and t.get("use")==use: return t.get("value")
    for t in patient.get("telecom",[]):
        if t.get("system")=="phone": return t.get("value")
    return None


def map_patient_to_features(patient, conditions, encounters, procedures,
                             careplans, coverages, clinic_id, cadence_baseline_days=120) -> dict:
    last_visit = extract_last_visit(encounters)
    proc_type, proc_date = extract_last_procedure(procedures)
    dob = _parse_date(patient.get("birthDate"))

    return {
        "patient_id": patient.get("id",""),
        "clinic_id": clinic_id,
        "days_since_last_visit": _days_ago(last_visit),
        "visit_cadence_baseline": cadence_baseline_days,
        "last_procedure_type": proc_type,
        "last_procedure_date": proc_date,
        "open_treatment_plan_flag": any(cp.get("status")=="active" for cp in careplans),
        "coverage_period_end_date": extract_coverage_end(coverages),
        "condition_codes": extract_icd10_codes(conditions),
        "age": (_days_ago(dob)//365) if dob else None,
        "sex": patient.get("gender"),
        # staging_patients extras (prefixed with _ so adapter can split them out)
        "_first_name": next((n.get("given",[""])[0] for n in patient.get("name",[]) if n.get("use")=="official"),""),
        "_last_name": next((n.get("family","") for n in patient.get("name",[]) if n.get("use")=="official"),""),
        "_date_of_birth": dob,
        "_phone_e164": extract_phone(patient),
        "_language": next((c.get("language",{}).get("coding",[{}])[0].get("code","ar")
                          for c in patient.get("communication",[]) if c.get("preferred")), "ar"),
        "_last_visit_date": last_visit,
    }