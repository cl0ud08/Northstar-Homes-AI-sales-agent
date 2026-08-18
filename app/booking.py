"""Simulated site-visit booking system.

There is no real CRM behind this. Outcomes are deterministic so that the
failure paths can be demonstrated and tested on demand rather than waited for:

    CONFIRMED         default
    SLOT_UNAVAILABLE  the requested slot collides with a pre-booked one
    SYSTEM_ERROR      the caller forces an outage (UI toggle / test flag)

Pre-booking Sunday 11am mirrors scenario S8 in docs/behaviour-spec.md, so the
clash path can be triggered by asking for that exact slot.
"""

import re
import uuid

from .schemas import BookingEvent

# Slots already taken. Normalised to "<weekday> <hh:mm>" in 24h form.
PRE_BOOKED: set[str] = {
    "sunday 11:00",
    "saturday 16:00",
}

# Offered when a requested slot clashes.
FALLBACK_SLOTS: list[str] = [
    "Sunday at two in the afternoon",
    "Saturday at eleven in the morning",
    "Monday at five in the evening",
]

_WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def normalise_slot(date_text: str, time_text: str) -> str:
    """Reduce loose natural-language slot text to '<weekday> <hh:mm>'.

    The model passes whatever the customer said ("this Sunday", "11 am"), so
    this is lenient by design. Anything it cannot parse falls through and is
    treated as a free slot, which is the safe direction to fail in.
    """
    blob = f"{date_text} {time_text}".lower()

    day = next((d for d in _WEEKDAYS if d in blob), "")

    hour = None
    match = re.search(r"(\d{1,2})\s*[:.]?\s*(\d{2})?\s*(am|pm)?", blob)
    if match:
        hour = int(match.group(1))
        meridiem = match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0

    if not day or hour is None:
        return blob.strip()

    return f"{day} {hour:02d}:00"


def book_site_visit(
    date_text: str,
    time_text: str,
    simulate_outage: bool = False,
) -> BookingEvent:
    """Attempt a booking and return the outcome.

    Never raises. The agent needs a structured result it can talk about, not
    an exception it has to guess at.
    """
    requested = f"{date_text} {time_text}".strip()

    if simulate_outage:
        return BookingEvent(
            status="SYSTEM_ERROR",
            requested_slot=requested,
        )

    slot_key = normalise_slot(date_text, time_text)

    if slot_key in PRE_BOOKED:
        return BookingEvent(
            status="SLOT_UNAVAILABLE",
            requested_slot=requested,
            alternatives=FALLBACK_SLOTS[:2],
        )

    PRE_BOOKED.add(slot_key)
    return BookingEvent(
        status="CONFIRMED",
        requested_slot=requested,
        confirmed_slot=requested,
        reference=f"NS-{uuid.uuid4().hex[:6].upper()}",
    )


# Tool schema handed to the model.
BOOKING_TOOL = {
    "type": "function",
    "function": {
        "name": "book_site_visit",
        "description": (
            "Reserve a site visit slot at Northstar One, Sector 79 Gurugram. "
            "Call this only after the customer has agreed to a specific day "
            "and time. Returns CONFIRMED, SLOT_UNAVAILABLE (with alternative "
            "slots to offer), or SYSTEM_ERROR (booking system is down — take "
            "the customer's name and number so the team can confirm later)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date_text": {
                    "type": "string",
                    "description": "Day as the customer said it, e.g. 'Sunday'.",
                },
                "time_text": {
                    "type": "string",
                    "description": "Time as the customer said it, e.g. '11 am'.",
                },
            },
            "required": ["date_text", "time_text"],
        },
    },
}