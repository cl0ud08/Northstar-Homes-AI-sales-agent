"""Conversation agent: prompt, tool loop, and output sanitising."""

import json
import re
from typing import Optional

from openai import OpenAI

from .booking import BOOKING_TOOL, book_site_visit, normalise_slot
from .config import load_system_prompt, settings
from .schemas import BookingEvent
from .store import Session

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.llm_api_key:
            raise RuntimeError(
                "LLM_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        _client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            # Without an explicit timeout the SDK waits indefinitely, which
            # surfaces to the user as a permanently stuck "typing" indicator.
            timeout=settings.request_timeout,
            max_retries=2,
        )
    return _client


# --------------------------------------------------------------------------
# Output sanitising
# --------------------------------------------------------------------------

_MARKDOWN_PATTERNS = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),      # bold
    (re.compile(r"(?<!\w)\*(.+?)\*(?!\w)"), r"\1"),  # italics
    (re.compile(r"^#{1,6}\s*", re.M), ""),      # headers
    (re.compile(r"^\s*[-*•]\s+", re.M), ""),    # bullets
    (re.compile(r"^\s*\d+[.)]\s+", re.M), ""),  # numbered lists
    (re.compile(r"`{1,3}"), ""),                # code ticks
]


def sanitise_for_voice(text: str) -> str:
    """Strip formatting that a text-to-speech engine would mangle.

    The system prompt already forbids markdown; this is a second line of
    defence, because a model that slips once on a live call is worse than one
    that slips once in a chat window. Devanagari and Latin text pass through
    untouched — only formatting characters are removed.
    """
    cleaned = text.strip()
    for pattern, replacement in _MARKDOWN_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    # Collapse the blank lines that list-stripping leaves behind.
    cleaned = re.sub(r"\n{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


# --------------------------------------------------------------------------
# Turn handling
# --------------------------------------------------------------------------


def _build_messages(
    session: Session,
    booking_note: Optional[str] = None,
) -> list[dict]:
    """Assemble the request payload.

    Stored history holds only user and assistant turns. Tool-call messages are
    deliberately never replayed: Gemini 3.x requires a `thought_signature` on
    function-call parts that the OpenAI-compatible layer does not round-trip,
    so echoing them back produces a 400. Booking outcomes are injected as
    context instead, which is provider-agnostic and cannot be rejected.
    """
    system = load_system_prompt()

    if session.bookings:
        history_note = "\n\n".join(
            f"Booking attempt {i + 1}: {b.model_dump_json()}"
            for i, b in enumerate(session.bookings)
        )
        system += (
            "\n\n---\n\nBOOKING SYSTEM RECORD FOR THIS CONVERSATION\n"
            "These are real results from the booking system. Treat them as "
            "fact and stay consistent with them.\n\n" + history_note
        )

    if booking_note:
        system += (
            "\n\n---\n\nRESULT OF THE BOOKING YOU JUST ATTEMPTED\n"
            + booking_note
            + "\n\nReply to the customer about this outcome now, following "
            "every rule above. Do not mention systems, tools, or errors in "
            "technical terms — speak as Riya would."
        )

    history = session.messages[-settings.max_history_messages :]
    return [{"role": "system", "content": system}, *history]


def run_turn(
    session: Session,
    user_message: str,
    simulate_outage: bool = False,
) -> tuple[str, Optional[BookingEvent]]:
    """Run one conversational turn, resolving a booking tool call if made.

    Returns the sanitised reply plus the booking outcome, if any, so the UI
    can show what the tool actually returned rather than trusting the model's
    account of it.
    """
    client = get_client()
    session.add_user(user_message)

    booking_event: Optional[BookingEvent] = None

    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=_build_messages(session),
        tools=[BOOKING_TOOL],
        temperature=settings.temperature,
    )
    choice = response.choices[0].message

    if choice.tool_calls:
        for tool_call in choice.tool_calls:
            if tool_call.function.name != "book_site_visit":
                continue
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            # Guard against re-booking a slot this session already confirmed.
            # The model sometimes re-fires the tool when the customer replies
            # after a successful booking (e.g. giving their name), which then
            # collides with the booking it just made. Compared on the
            # normalised slot key, because the model rarely phrases the same
            # slot identically twice ("2 pm" vs "2:00 pm" vs "this Sunday").
            requested_key = normalise_slot(
                args.get("date_text", ""), args.get("time_text", "")
            )
            already = next(
                (
                    b
                    for b in session.bookings
                    if b.status == "CONFIRMED"
                    and normalise_slot(b.requested_slot, "") == requested_key
                ),
                None,
            )
            if already is not None:
                booking_event = already
                continue

            booking_event = book_site_visit(
                date_text=args.get("date_text", ""),
                time_text=args.get("time_text", ""),
                simulate_outage=simulate_outage,
            )
            session.bookings.append(booking_event)

        # Second pass without tools: the model now writes its reply knowing the
        # outcome, and cannot fire the booking a second time.
        note = (
            booking_event.model_dump_json()
            if booking_event
            else "No booking was made."
        )
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=_build_messages(session, booking_note=note),
            temperature=settings.temperature,
        )
        choice = response.choices[0].message

    reply = sanitise_for_voice(choice.content or "")
    if not reply:
        reply = "Sorry, could you say that again?"

    session.add_assistant(reply)
    return reply, booking_event