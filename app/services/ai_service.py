"""
Gemini integration for turning a merchant's raw WhatsApp text/voice note into
a structured task.

NOTE ON SDK VERSION: this uses the `google-genai` package's `Client` /
`generate_content` interface as of this writing. This sandbox has no network
access to Google's API, so the exact call shape below has NOT been verified
against a live call — verify against https://ai.google.dev/gemini-api/docs
before relying on it, and adjust `_call_gemini_text` / `_call_gemini_audio`
if the SDK has moved on. Everything downstream (schema validation, retry,
error handling) is independent of that detail and IS tested.
"""
import json
import logging

from google import genai
from google.genai import types
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.schemas.ai import AITaskExtraction

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


class AIParsingError(Exception):
    pass


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


SYSTEM_PROMPT = """You convert a farmer's, merchant's, or agribusiness's request \
(from WhatsApp text or a voice note) into a structured agricultural service \
request for a Nigerian marketplace. Preserve support for ordinary micro-jobs.

Respond with ONLY a JSON object, no markdown fences, no commentary, matching \
exactly this shape:
{
  "title": "short descriptive title, max 255 chars",
  "category": "one short category, e.g. Design, Writing, Data Entry, Delivery, Research, Tutoring",
  "requirements": "a clear restatement of what the merchant needs done",
  "complexity": "SIMPLE" | "MODERATE" | "COMPLEX",
  "suggested_payout": <number, NGN, a fair market rate for a Nigerian student for this task>,
  "currency": "NGN",
  "service_category": "TRANSPORT" | "LABOUR" | "TRACTOR_RENTAL" | "VETERINARY" | "IRRIGATION" | "WAREHOUSING" | "SOIL_TESTING" | "EXTENSION_SUPPORT" | "OTHER" | null,
  "farm_location": {"label": null, "address": null, "state": null, "local_government_area": null, "latitude": null, "longitude": null} | null,
  "agricultural_details": {
    "crop_type": null, "livestock_type": null, "acreage": null,
    "quantity": null, "quantity_unit": null, "urgency": null,
    "equipment_type": null, "duration_hours": null, "worker_count": null,
    "transport": {"pickup": {...location fields...}, "dropoff": {...location fields...}, "commodity": null, "load_quantity": null, "load_unit": null, "vehicle_type": null} | null,
    "additional": {}
  }
}

If the merchant's message is too vague to extract a real task, still do your \
best to produce a reasonable structured guess — the requester will review and \
confirm it before publication. Never invent precise coordinates, acreage, \
quantities, dates, or transport endpoints; use null when they were not given."""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _call_gemini_text(text: str) -> str:
    client = get_client()
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[SYSTEM_PROMPT, f"Merchant message:\n{text}"],
    )
    return response.text


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _call_gemini_audio(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    client = get_client()
    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[SYSTEM_PROMPT, audio_part],
    )
    return response.text


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def extract_task_from_text(text: str) -> tuple[AITaskExtraction, dict]:
    raw = _call_gemini_text(text)
    return _validate(raw)


def extract_task_from_audio(audio_bytes: bytes, mime_type: str = "audio/ogg") -> tuple[AITaskExtraction, dict]:
    raw = _call_gemini_audio(audio_bytes, mime_type)
    return _validate(raw)


def _validate(raw_response: str) -> tuple[AITaskExtraction, dict]:
    cleaned = _strip_code_fences(raw_response)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("Gemini response was not valid JSON: %s", raw_response)
        raise AIParsingError(f"Gemini response was not valid JSON: {e}") from e

    try:
        extraction = AITaskExtraction.model_validate(data)
    except ValidationError as e:
        logger.error("Gemini response failed schema validation: %s", e)
        raise AIParsingError(f"Gemini response failed schema validation: {e}") from e

    return extraction, data
