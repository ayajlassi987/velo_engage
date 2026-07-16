# ve_measure

`ve_measure` consumes durable JetStream events from `events.>` and links
bookings and paid revenue to the most recent campaign for the same patient and
clinic within the configured attribution window (30 days by default).

## Event envelope

Publish JSON to `events.<EventType>`. The listener accepts fields inside
`data` or at the top level.

```json
{
  "event_id": "evt-booking-001",
  "event_type": "AppointmentConfirmed",
  "occurred_at": "2026-06-29T16:00:00Z",
  "data": {
    "booking_id": "booking-001",
    "patient_id": "patient_001",
    "clinic_id": "clinic_alnoor_001",
    "appointment_date": "2026-07-05T09:00:00Z"
  }
}
```

Supported event types:

- `AppointmentConfirmed`: requires booking, patient, clinic, and appointment IDs/dates.
- `AppointmentCompleted`: marks the booking attended; `appointment_date` may be
  omitted when the confirmed booking already exists.
- `Invoice`: requires invoice, patient, clinic, amount, and currency.
- `Payment`: uses the invoice shape and marks its revenue paid.
- `Procedure`: requires a procedure or invoice ID plus patient, clinic, amount, and currency.

Billing events can include `booking_id` to make the booking-to-revenue link
explicit. Without it, the service uses the most recent attributed booking for
the patient and clinic within the attribution window.
