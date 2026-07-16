UPDATE patient_features SET clinical_recall_due_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P001';
UPDATE patient_features SET cross_specialty_gap_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P002';
UPDATE patient_features SET seasonal_event_eligible_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P003';
UPDATE patient_features SET engagement_drop_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P004';
UPDATE patient_features SET preference_match_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P005';
UPDATE patient_features SET care_gap_due_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P006';
UPDATE patient_features SET abandoned_booking_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P007';
UPDATE patient_features SET treatment_lifecycle_due_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P008';
UPDATE patient_features SET household_lifestage_eligible_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P009';
UPDATE patient_features
SET contextual_trigger_flag=TRUE,
    slot_fill_eligible_flag=TRUE,
    quality_followup_due_flag=TRUE
WHERE clinic_id='clinic_alnoor_001' AND patient_id='P010';

INSERT INTO consent (patient_id, clinic_id, consent_class, channel)
SELECT p.patient_id, p.clinic_id, consent_class, 'whatsapp'
FROM staging_patients p
CROSS JOIN (VALUES
    ('care_recall'), ('clinical_recall'), ('care_coordination'),
    ('promotional_outreach'), ('engagement'), ('preference_outreach'),
    ('digital_followup'), ('household_outreach'), ('contextual_outreach'),
    ('operational_offer'), ('quality_followup')
) classes(consent_class)
WHERE p.clinic_id='clinic_alnoor_001' AND p.patient_id LIKE 'P%'
ON CONFLICT DO NOTHING;
