"""Post-conversation analytics extraction.

Runs as a separate pass over the finished transcript rather than as running
state during the conversation. Two reasons: the sales agent's job is to talk,
not to fill a form mid-sentence, and a whole-transcript view produces better
judgements on interest level than incremental guessing.
"""

import json
from typing import Optional

from pydantic import ValidationError

from .agent import get_client
from .config import settings
from .schemas import ConversationAnalytics
from .store import Session

EXTRACTION_PROMPT = """You extract structured lead data from a completed sales conversation for Northstar Homes, a real-estate company.

Return ONLY a JSON object. No preamble, no explanation, no markdown fences.

Fields and allowed values:

lead_name              string or null
contact_number         string or null
language_preference    "english" | "hindi" | "hinglish" | "unknown"
configuration_interest "2BHK" | "3BHK" | "both" | "undecided"
budget_stated          string or null      (verbatim, e.g. "1.4 cr")
budget_fit             "within" | "below" | "above" | "unknown"
purpose                "end_use" | "investment" | "unknown"
timeline               "immediate" | "3_months" | "6_months" | "exploratory" | "unknown"
interest_level         "high" | "medium" | "low"
interest_reasoning     one sentence justifying the interest level
objections_raised      array of strings from: price, location, trust, timing, other
questions_unanswered   array of strings — questions the customer asked that the agent could not answer
site_visit_status      "booked" | "pending_confirmation" | "declined" | "not_discussed"
site_visit_datetime    string or null
booking_failed         boolean
follow_up_required     boolean
follow_up_window       string or null      (e.g. "tomorrow evening", "6 months")
escalation_required    boolean
do_not_contact         boolean
conversation_summary   two sentences for the sales rep

Rules:
- Only record what was actually said. Never infer a budget or timeline that was not stated.
- budget_fit compares the stated budget against 2 BHK from 1.35 crore and 3 BHK from 1.75 crore.
- do_not_contact is true ONLY for an explicit request to stop contact. "Not interested right now" is not a stop request.
- site_visit_status is "pending_confirmation" when a booking was attempted but the system failed.
- language_preference reflects what the customer used, not the agent.
- interest_level: "high" if a visit was booked or strong intent shown, "low" if they disengaged or asked to stop.
- Every field must use exactly one of the allowed values listed above. Never invent a value. If unsure, use the "unknown" or null option for that field.
"""


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


def extract_analytics(session: Session) -> ConversationAnalytics:
    """Extract a lead record from the session transcript.

    Falls back to an empty-but-valid record if the model returns something
    unparseable, so a bad extraction never takes the endpoint down.
    """
    transcript = session.transcript()
    if not transcript:
        return ConversationAnalytics(
            conversation_summary="No conversation took place."
        )

    booking_note = ""
    if session.bookings:
        outcomes = ", ".join(b.status for b in session.bookings)
        booking_note = f"\n\nBooking system outcomes this session: {outcomes}"

    client = get_client()
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": f"Conversation transcript:\n\n{transcript}{booking_note}",
            },
        ],
        temperature=settings.analytics_temperature,
    )

    raw = _strip_fences(response.choices[0].message.content or "{}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ConversationAnalytics(
            conversation_summary="Extraction failed to return valid JSON.",
            interest_reasoning="Unavailable.",
        )

    try:
        analytics = ConversationAnalytics(**data)
    except ValidationError as exc:
        # Salvage field by field. Filtering by key name alone is not enough:
        # a single out-of-enum value would otherwise discard the whole record,
        # including do_not_contact, which is the costliest field to lose.
        print(f"[analytics] validation failed, salvaging fields: {exc}")
        print(f"[analytics] raw model output: {data}")

        valid: dict = {}
        for key, value in data.items():
            if key not in ConversationAnalytics.model_fields:
                continue
            try:
                ConversationAnalytics(**{key: value})
            except ValidationError:
                continue
            valid[key] = value

        analytics = ConversationAnalytics(**valid)
        if not analytics.conversation_summary:
            analytics.conversation_summary = (
                "Partial extraction — some fields could not be read."
            )

    # A removal request cannot coexist with a scheduled follow-up. Enforced in
    # code rather than left to the extractor: calling someone who asked to be
    # removed is the most damaging error this record can produce.
    if analytics.do_not_contact:
        analytics.follow_up_required = False
        analytics.follow_up_window = None

    # The booking system is the source of truth here, not the model's reading.
    if session.bookings:
        latest = session.bookings[-1]
        analytics.booking_failed = any(
            b.status != "CONFIRMED" for b in session.bookings
        )
        if latest.status == "CONFIRMED":
            analytics.site_visit_status = "booked"
            analytics.site_visit_datetime = latest.confirmed_slot
        elif latest.status == "SYSTEM_ERROR":
            analytics.site_visit_status = "pending_confirmation"

    return analytics