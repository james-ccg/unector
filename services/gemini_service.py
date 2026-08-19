"""
This module is the MOST IMPORTANT part of the project - runs on the Gemini API:
1. Extracts structured data (JSON) from the RATE CON (RC) PDF
2. Checks load photos (securement, seal, temperature) against the RC/BOL
3. Compares the BOL document(s) against the RC to check for a match

SDK: google-genai (the official new Python SDK, `pip install google-genai`)
Model: "gemini-3.5-flash-lite" - Google's fastest, lowest-latency model,
purpose-built for high-throughput document extraction like this. Much
quicker than the full Flash models, at a lower cost too. If you need higher
quality on messy/handwritten documents, swap to "gemini-flash-latest" instead.
"""
import json
import time

from google import genai
from google.genai import types
from google.genai.errors import ServerError
from config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)

MODEL = "gemini-3.5-flash-lite"

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 3  # doubles each retry: 3s, 6s, 12s

# Forces Gemini to return JSON via "response_mime_type" - avoids having to
# strip ```json code fences from the response.
JSON_CONFIG = types.GenerateContentConfig(
    response_mime_type="application/json",
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)


def _generate_with_retry(**kwargs):
    """Calls Gemini, retrying a few times if the server is temporarily
    overloaded (503). Most 503s clear up within a few seconds, so a short
    retry loop here is much better than surfacing the error to the driver."""
    delay = RETRY_BACKOFF_SECONDS
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return client.models.generate_content(**kwargs)
        except ServerError:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(delay)
            delay *= 2


def _parts_from_files(files: list[tuple[bytes, str]]) -> list:
    """Turns a list of (raw_bytes, mime_type) into Gemini content parts.
    Used for both single images/PDFs and multi-photo submissions (e.g. an
    album containing the load photo, seal photo, reefer display, and BOL
    paperwork all together)."""
    return [types.Part.from_bytes(data=data, mime_type=mime_type) for data, mime_type in files]


# ------------------------------------------------------------------
# 1. RC extraction
# ------------------------------------------------------------------
RC_EXTRACTION_PROMPT = """This is a RATE CONFIRMATION (RC) document sent by a trucking broker.
Find the following fields in the document and return ONLY JSON:

{
  "load_id": "the broker's load/order number",
  "broker_name": "broker company name",
  "broker_contact_email": "if present in the document",
  "carrier_name": "the carrier company name (the trucking company hired for this load), if shown",
  "pu_address": "the FULL pickup address as a multi-line block, e.g. 'Company Name\\nStreet address\\nCity, ST ZIP' - keep it exactly as formatted in the document, using \\n between lines",
  "pu_date": "pickup date, exactly as written (e.g. '7/28/2026')",
  "pu_time": "pickup time, ALWAYS formatted as HH:MM with a colon (24-hour clock) - e.g. a document showing '1500' or '3:00 PM' must both become '15:00'. If the document indicates this is a hard deadline (words like 'by', 'no later than', 'must arrive by'), prefix the value with 'By ' (e.g. 'By 15:30'). If the document indicates a scheduled appointment (words like 'Apt', 'Appointment', 'FCFS Apt'), append ' Apt' to the value (e.g. '11:00 Apt'). Otherwise return just 'HH:MM' with no prefix or suffix.",
  "pu_reference": "pickup reference/PU number if shown (e.g. a PU# or BOL#)",
  "del_address": "the FULL delivery address as a multi-line block, same format as pu_address",
  "del_date": "delivery date, exactly as written",
  "del_time": "delivery time, formatted with the exact same HH:MM + 'By '/' Apt' rules as pu_time above",
  "weight": "shipment weight, exactly as written (e.g. '40,000')",
  "commodity": "type of freight",
  "reefer_temp": "temperature setting if reefer (e.g. '34F'), otherwise null",
  "rate_amount": "total rate (number, no $ sign)",
  "special_notes_summary": "A SHORT 1-3 sentence summary (in your own words) of the load-specific instructions the DRIVER must act on for THIS shipment - e.g. seal requirements, strap/loadbar requirements, temperature handling instructions, scale requirements, check-in/tracking requirements. Do NOT include generic broker-carrier legal boilerplate that would appear on every load from this broker regardless of shipment (e.g. general payment terms, quick pay program details, insurance/additional-insured clauses, dispute resolution language, general FMCSA/DOT compliance clauses, double-brokering clauses). If there is nothing load-specific to summarize, use an empty string.",
  "detention_terms": "detention/layover terms if stated, otherwise null"
}

If a field is not found in the document, set its value to null. Do not guess."""


def extract_rc_data(pdf_bytes: bytes) -> dict:
    """Takes RC PDF bytes, returns structured JSON."""
    response = _generate_with_retry(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            RC_EXTRACTION_PROMPT,
        ],
        config=JSON_CONFIG,
    )
    return _parse_json_response(response)


# ------------------------------------------------------------------
# 2. Load photo check (securement, seal, temperature, weight vs BOL)
# ------------------------------------------------------------------
LOAD_CHECK_PROMPT = """You are a professional freight dispatch assistant reviewing photos a driver
just sent after loading. You may receive several photos together: the loaded freight, the
trailer seal, the reefer temperature display, and/or the BOL (Bill of Lading) paperwork - use
whichever of these are actually present in the images provided; skip a task if the photo needed
for it wasn't sent.

Reference data from the Rate Confirmation (RC) for this load:
{rc_json}

Go through these four checks, in this exact order:
1. **Load securement** - is the freight strapped/lashed and loaded safely? Return status as "Excellent", "Good", or describe issues.
2. **Seal number** - Extract seal numbers from BOL and photos if visible. Return both values and match status.
3. **Temperature** - Extract temperature from RC, BOL, and photos if visible. Return all three values and match status.
4. **Documentation** - If BOL/paperwork is visible, count the pages. Compare to RC page count if available. Return status.

Return ONLY this JSON:
{{
  "loading_ok": true/false,
  "task1_securement": {{
    "status": "status description (e.g., 'Excellent', 'Good', 'Issues found')"
  }},
  "task2_seal": {{
    "bol": "seal number from BOL or null",
    "photos": "seal number from photos or null",
    "status": "Match or description"
  }},
  "task3_temperature": {{
    "rc": "temperature from RC or 'didn't show'",
    "bol": "temperature from BOL or 'didn't show'",
    "photos": "temperature from photos or 'didn't show'",
    "status": "Match or description"
  }},
  "task4_documentation": {{
    "rc": "page count from RC or 'not specified'",
    "bol": "page count from BOL photos or 'not visible'",
    "status": "status description (e.g., 'It's okay', 'Match', 'Missing pages')"
  }},
  "issues": ["a short description of each real problem found, in English - empty list if none"]
}}"""


def check_load_picture(rc_json: dict, files: list[tuple[bytes, str]]) -> dict:
    """Checks one or more load-related photos (load, seal, reefer display, BOL) together
    against the RC. `files` is a list of (raw_bytes, mime_type) tuples."""
    prompt = LOAD_CHECK_PROMPT.format(
        rc_json=json.dumps(rc_json, ensure_ascii=False),
        weight=rc_json.get("weight") or "not specified",
    )
    response = _generate_with_retry(
        model=MODEL,
        contents=[*_parts_from_files(files), prompt],
        config=JSON_CONFIG,
    )
    return _parse_json_response(response)


# ------------------------------------------------------------------
# 3. BOL vs RC comparison
# ------------------------------------------------------------------
BOL_COMPARE_PROMPT = """You are a professional freight dispatch assistant. You are given data
extracted from a RATE CONFIRMATION (RC) as JSON, and one or more photos of the BOL (Bill of
Lading) and related documents (e.g. a seal photo) sent by the driver.

RC data:
{rc_json}

Check each of the following and return structured data:
1. **Weight comparison** - Extract both BOL weight and RC weight. If BOL weight ≤ RC weight, status is "okay" or "good". If BOL > RC, status should note the issue.
2. **Delivery address** - Extract both BOL delivery address and RC delivery address. Compare them and determine if they match.
3. **Temperature** - If temperature is shown in either RC or BOL or photos, extract it. Note if one source doesn't show it.
4. **Seal number** - Extract seal numbers from BOL and photos if visible. Check if they match.

Return ONLY this JSON:
{{
  "match": true or false (overall match status),
  "weight": {{
    "bol": "weight from BOL (e.g., '33000lbs')",
    "rc": "weight from RC (e.g., '45000')",
    "status": "status description (e.g., 'Okay', 'Good', 'BOL exceeds RC')"
  }},
  "delivery_address": {{
    "bol": "delivery address from BOL",
    "rc": "delivery address from RC",
    "status": "Match or description of difference",
    "emoji": "✅ if match, ⚠️ if issue"
  }},
  "temperature": {{
    "rc": "temperature from RC or 'didn't show'",
    "bol": "temperature from BOL or 'didn't show'",
    "status": "recommendation (e.g., 'We should follow bol!', 'Match', 'Not specified')"
  }},
  "seal": {{
    "match": true or false,
    "summary": "brief summary of seal match status"
  }},
  "mismatches": ["list of any critical issues"],
  "bol_extracted": {{"pu_address": "...", "del_address": "...", "commodity": "...", "weight": "..."}}
}}"""


def compare_bol_with_rc(rc_json: dict, files: list[tuple[bytes, str]]) -> dict:
    """Compares one or more BOL-related photos/documents against the RC JSON.
    `files` is a list of (raw_bytes, mime_type) tuples."""
    prompt = BOL_COMPARE_PROMPT.format(
        rc_json=json.dumps(rc_json, ensure_ascii=False),
        weight=rc_json.get("weight") or "not specified",
    )
    response = _generate_with_retry(
        model=MODEL,
        contents=[*_parts_from_files(files), prompt],
        config=JSON_CONFIG,
    )
    return _parse_json_response(response)


def _parse_json_response(response) -> dict:
    """Converts Gemini's response into JSON (comes back clean with
    response_mime_type=json, but code fences are stripped as a safety net anyway)."""
    raw = (response.text or "").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse Gemini's response as JSON: {e}\nResponse: {raw[:500]}")
