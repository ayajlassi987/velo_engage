"""
Loads the trained intent classifier and classifies incoming WhatsApp messages.
Returns an intent label + confidence score.
"""

import os
import pickle
import mlflow
import mlflow.sklearn
from functools import lru_cache

from ml.registry._stage_loader import resolve_production_version

MLFLOW_URI  = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME  = "ve_intent_v1"
CONFIDENCE_THRESHOLD = 0.45   # below this → UNKNOWN


@lru_cache(maxsize=1)
def _load_model():
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.MlflowClient()
    resolved = resolve_production_version(client, MODEL_NAME)
    return mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{resolved.version}")


def classify(text: str) -> dict:
    """
    Returns {"intent": str, "confidence": float, "raw_text": str}
    Intent is one of:
      BOOK_APPOINTMENT, CANCEL_APPOINTMENT, RESCHEDULE_APPOINTMENT,
      CONFIRM_APPOINTMENT, VIEW_APPOINTMENTS, CLINIC_FAQ,
      GREETING, THANKS, UNKNOWN
    """
    if not text or not text.strip():
        return {"intent": "UNKNOWN", "confidence": 0.0, "raw_text": text}

    model = _load_model()
    clean = text.strip().lower()
    proba = model.predict_proba([clean])[0]
    classes = model.classes_
    top_idx = proba.argmax()
    top_conf = float(proba[top_idx])
    top_intent = classes[top_idx]

    if top_conf < CONFIDENCE_THRESHOLD:
        top_intent = "UNKNOWN"

    return {
        "intent":     top_intent,
        "confidence": round(top_conf, 3),
        "raw_text":   text,
    }