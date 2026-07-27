"""Computes the STAGE1_FEATURES columns ml/registry/scorer.py has always
required but patient_features never populated with real values (see
infra/migrations/018_noshow_historical_features.sql) — until this runs,
every one of these was silently substituted with scorer.py's DEFAULTS
constant for every patient, every score.

Honest limitations, not fixed here because the data to fix them doesn't
exist anywhere in this schema:
  - provider_noshow_rate / provider_schedule_change: no provider entity
    (bookings has no provider_id column).
  - temp_above_45c: no weather data source.
  - hist_late_cancel_count_90d: bookings.status only ever transitions
    booked -> attended (see ve_measure.booking_listener.record_booking) —
    there's no distinct cancellation event, so a genuine no-show and a
    booking that was properly cancelled in advance look identical here.
    "no-show" below is therefore a documented proxy (booked, appointment
    date has passed, never marked attended), the same
    rule-based-proxy-over-fabrication approach already used for family I.
"""

CLINIC_FEATURE_SQL = """
WITH booking_stats AS (
    SELECT
        patient_id, clinic_id,
        COUNT(*) FILTER (
            WHERE status='attended' AND appointment_date >= now() - interval '90 days'
        ) AS kept_90d,
        COUNT(*) FILTER (
            WHERE status='booked' AND appointment_date < now()
              AND appointment_date >= now() - interval '90 days'
        ) AS noshow_90d,
        COUNT(*) FILTER (
            WHERE status='attended' AND appointment_date >= now() - interval '365 days'
        ) AS kept_365d,
        COUNT(*) FILTER (
            WHERE status='booked' AND appointment_date < now()
              AND appointment_date >= now() - interval '365 days'
        ) AS noshow_365d,
        MAX(appointment_date) FILTER (WHERE status='booked' AND appointment_date < now()) AS last_noshow_date,
        MAX(appointment_date) FILTER (WHERE status='attended') AS last_kept_date,
        MAX(appointment_date) AS latest_appointment_date
    FROM bookings
    WHERE clinic_id = %(clinic_id)s
    GROUP BY patient_id, clinic_id
),
reply_stats AS (
    SELECT
        c.patient_id, c.clinic_id,
        COUNT(DISTINCT c.campaign_id) AS dispatched_count,
        COUNT(DISTINCT fr.campaign_id) AS replied_count,
        AVG(EXTRACT(EPOCH FROM (fr.first_reply_at - c.dispatched_at)) / 60.0) AS avg_latency_min
    FROM campaigns c
    LEFT JOIN (
        SELECT campaign_id, MIN(received_at) AS first_reply_at
        FROM inbound_messages GROUP BY campaign_id
    ) fr ON fr.campaign_id = c.campaign_id
    WHERE c.clinic_id = %(clinic_id)s AND c.dispatched_at IS NOT NULL
    GROUP BY c.patient_id, c.clinic_id
),
target AS (
    SELECT DISTINCT patient_id, clinic_id FROM patient_features WHERE clinic_id = %(clinic_id)s
)
UPDATE patient_features pf SET
  hist_noshow_rate_90d = COALESCE(bs.noshow_90d::float / NULLIF(bs.noshow_90d + bs.kept_90d, 0), 0.15),
  hist_noshow_rate_365d = COALESCE(bs.noshow_365d::float / NULLIF(bs.noshow_365d + bs.kept_365d, 0), 0.15),
  hist_noshow_count_90d = COALESCE(bs.noshow_90d, 0),
  hist_kept_count_90d = COALESCE(bs.kept_90d, 0),
  days_since_last_noshow = COALESCE(EXTRACT(DAY FROM now() - bs.last_noshow_date)::int, 365),
  days_since_last_kept = COALESCE(EXTRACT(DAY FROM now() - bs.last_kept_date)::int, 365),
  hist_wa_confirm_rate = COALESCE(rs.replied_count::float / NULLIF(rs.dispatched_count, 0), 0.5),
  hist_avg_reply_latency_min = COALESCE(rs.avg_latency_min, 60.0),
  is_followup = CASE
    WHEN pf.days_since_last_visit IS NOT NULL AND pf.days_since_last_visit < pf.visit_cadence_baseline
    THEN 1 ELSE 0
  END,
  lead_time_days_log = ln(1 + GREATEST(pf.lead_time_days, 0)::numeric),
  hour_bucket = CASE
    WHEN bs.latest_appointment_date IS NULL THEN pf.time_of_day
    WHEN EXTRACT(HOUR FROM bs.latest_appointment_date) < 12 THEN 'morning'
    WHEN EXTRACT(HOUR FROM bs.latest_appointment_date) < 17 THEN 'afternoon'
    ELSE 'evening'
  END,
  as_of_timestamp = now()
FROM target
LEFT JOIN booking_stats bs ON bs.patient_id = target.patient_id AND bs.clinic_id = target.clinic_id
LEFT JOIN reply_stats rs ON rs.patient_id = target.patient_id AND rs.clinic_id = target.clinic_id
WHERE pf.patient_id = target.patient_id AND pf.clinic_id = target.clinic_id
"""


def refresh_historical_features(cur, clinic_id: str) -> int:
    """Recomputes the 11 genuinely-derivable historical features for every
    patient in a clinic from real bookings/outcomes/message history. Caller
    owns the connection/commit (matches feature_store.fetch_patient_features's
    convention of accepting a cursor rather than opening its own)."""
    cur.execute(CLINIC_FEATURE_SQL, {"clinic_id": clinic_id})
    return cur.rowcount
