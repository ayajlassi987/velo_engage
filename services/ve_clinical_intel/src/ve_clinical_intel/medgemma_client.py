"""Client for the team's shared DGX model server, running MedGemma
(MODEL_NAME=med-27b — the text-only medical variant; med-4b is
multimodal/image-focused, the wrong tool for note *text*).

Protocol confirmed live from the team's own medgemma_server/example_client.py
— NOT OpenAI-compatible JSON, despite the /v1/chat/completions path:
response is Server-Sent Events, one JSON object per token
(`{"type": "token", "text": "..."}`), a closing `{"type": "done", ...}`
event, terminated by a literal `data: [DONE]` line. This client accumulates
every "token" event into the full response string, then the caller parses
that as JSON — there is no non-streaming mode confirmed to exist on this
server, so this always requests stream=true.
"""

import json
import os

import httpx

MEDGEMMA_URL = os.getenv("MEDGEMMA_URL", "http://localhost:8080")

EXTRACTION_PROMPT = """You are extracting structured medical information from a clinical note. \
Read the note below and respond with ONLY a JSON object (no markdown fences, no commentary) \
with exactly these keys: "diagnoses" (list of strings), "medications" (list of strings), \
"procedures" (list of strings), "follow_up_recommendations" (list of strings), \
"clinical_risks" (list of strings). Use an empty list for any category not mentioned in the note. \
Do not infer or add information not present in the note.

Clinical note:
{note_text}"""


def _accumulate_stream(response: httpx.Response) -> str:
    tokens = []
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            break
        event = json.loads(raw)
        if event.get("type") == "token":
            tokens.append(event["text"])
        elif event.get("type") == "error":
            raise RuntimeError(f"MedGemma server reported an error: {event}")
    return "".join(tokens)


def extract_structured_data(note_text: str) -> dict:
    """Sends a clinical note to MedGemma, returns the parsed JSON extraction.
    Raises ValueError if the model's response isn't valid JSON — the caller
    (main.py's orchestration) is responsible for flagging that rather than
    silently accepting garbage, per validation.py's role in this pipeline."""
    payload = {
        "messages": [{"role": "user", "content": EXTRACTION_PROMPT.format(note_text=note_text)}],
        "stream": True,
    }
    with httpx.Client(timeout=120.0) as client:
        with client.stream("POST", f"{MEDGEMMA_URL}/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            full_text = _accumulate_stream(response)

    try:
        return json.loads(full_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MedGemma response was not valid JSON: {exc}. Raw length: {len(full_text)}") from exc


def health_check() -> dict:
    with httpx.Client(timeout=10.0) as client:
        response = client.get(f"{MEDGEMMA_URL}/health")
        response.raise_for_status()
        return response.json()
