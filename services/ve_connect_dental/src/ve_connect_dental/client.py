"""Dental PMS client — abstracted so the transport (direct MySQL today,
OpenDental's REST API once a Developer/Customer Key exists — see README.md
Phase A vs Phase B) can be swapped without touching mapper.py or anything
downstream. Every implementation returns the same shape: plain dicts keyed
by the field names in FIELDS below, never the source system's raw column
names, so mapper.py has exactly one input shape to handle regardless of
which client produced it.

Table/column names in OpenDentalMySQLClient reflect OpenDental's commonly
documented schema at the time this was written (procedurelog/procedurecode/
appointment/patient) — CONFIRM these against your own instance's real
schema (README.md Phase A, step 3) before trusting them. A mismatch should
fail loudly as a SQL error, not silently return an empty/wrong result — this
mirrors this project's existing discipline of never trusting an unverified
external identifier or schema assumption (see ve_connect's Epic Group ID
lesson in PROJECT_STATUS.md).
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class DentalPMSClient(ABC):
    """One method per resource this service needs. Anything beyond
    patient/procedures/appointments is out of scope until a real pathway
    needs it."""

    @abstractmethod
    def get_patient(self, patient_id: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def get_procedures(self, patient_id: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def get_appointments(self, patient_id: str) -> list[dict[str, Any]]:
        ...


class OpenDentalMySQLClient(DentalPMSClient):
    """Phase A transport — direct read access to a self-hosted OpenDental
    MySQL database (README.md Phase A). Never used against OpenDental Cloud
    (hosted instances don't expose direct DB access at all); Phase B's
    OpenDentalAPIClient (not yet implemented) is the transport for those."""

    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self._conn_kwargs = dict(host=host, port=port, database=database, user=user, password=password)

    def _connect(self):
        # Imported lazily so this module can be imported (and its pure
        # mapping/interface pieces tested) without pymysql installed —
        # mirrors this project's general preference for not forcing a heavy
        # dependency onto code paths that don't need it at import time.
        import pymysql
        import pymysql.cursors

        return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **self._conn_kwargs)

    def get_patient(self, patient_id: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT PatNum, LName, FName, Birthdate FROM patient WHERE PatNum = %s",
                (patient_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "patient_id": str(row["PatNum"]),
            "last_name": row["LName"],
            "first_name": row["FName"],
            "birthdate": row["Birthdate"],
        }

    def get_procedures(self, patient_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT pl.ProcNum, pl.ProcDate, pl.ProcStatus, pl.ToothNum, pl.Surf,
                       pc.ProcCode
                FROM procedurelog pl
                JOIN procedurecode pc ON pc.CodeNum = pl.CodeNum
                WHERE pl.PatNum = %s
                ORDER BY pl.ProcDate ASC
                """,
                (patient_id,),
            )
            rows = cur.fetchall()
        return [
            {
                "procedure_id": str(row["ProcNum"]),
                "cdt_code": row["ProcCode"],
                "tooth": row["ToothNum"] or None,
                "surface": row["Surf"] or None,
                "procedure_date": row["ProcDate"],
                # OpenDental's ProcStatus is a small integer enum
                # (1=Treatment Planned, 2=Complete, ...) — mapped to a
                # human string in mapper.py, not here, so this client stays
                # a thin passthrough with no business interpretation of the
                # source system's codes.
                "status_code": row["ProcStatus"],
            }
            for row in rows
        ]

    def get_appointments(self, patient_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT AptNum, AptDateTime, AptStatus FROM appointment WHERE PatNum = %s ORDER BY AptDateTime ASC",
                (patient_id,),
            )
            rows = cur.fetchall()
        return [
            {
                "appointment_id": str(row["AptNum"]),
                "scheduled_at": row["AptDateTime"],
                "status_code": row["AptStatus"],
            }
            for row in rows
        ]


class OpenDentalAPIClient(DentalPMSClient):
    """Phase B transport — not yet implemented. Placeholder so the swap
    described in README.md Phase B (step 9) has a concrete class to fill in
    once a Developer Key + a clinic's Customer Key exist. Deliberately
    raises rather than silently behaving like the MySQL client with
    different semantics."""

    def __init__(self, base_url: str, developer_key: str, customer_key: str):
        self.base_url = base_url
        self.developer_key = developer_key
        self.customer_key = customer_key

    def get_patient(self, patient_id: str) -> dict[str, Any] | None:
        raise NotImplementedError("OpenDentalAPIClient is Phase B — build once Developer/Customer Keys exist")

    def get_procedures(self, patient_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("OpenDentalAPIClient is Phase B — build once Developer/Customer Keys exist")

    def get_appointments(self, patient_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("OpenDentalAPIClient is Phase B — build once Developer/Customer Keys exist")
