"""Request, response, and analytics schemas."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Chat API
# --------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=2000)
    # Lets the UI force a booking-system outage on demand so the failure path
    # can be demonstrated reliably instead of waited for.
    simulate_outage: bool = False


class BookingEvent(BaseModel):
    """Surfaced to the UI so the booking tool call is visible, not hidden."""

    status: Literal["CONFIRMED", "SLOT_UNAVAILABLE", "SYSTEM_ERROR"]
    requested_slot: str
    confirmed_slot: Optional[str] = None
    alternatives: list[str] = []
    reference: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    booking_event: Optional[BookingEvent] = None
    ended: bool = False


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------

Language = Literal["english", "hindi", "hinglish", "unknown"]
Configuration = Literal["2BHK", "3BHK", "both", "undecided"]
BudgetFit = Literal["within", "below", "above", "unknown"]
Purpose = Literal["end_use", "investment", "unknown"]
Timeline = Literal["immediate", "3_months", "6_months", "exploratory", "unknown"]
InterestLevel = Literal["high", "medium", "low"]
VisitStatus = Literal[
    "booked", "pending_confirmation", "declined", "not_discussed"
]


class ConversationAnalytics(BaseModel):
    """Post-conversation lead record.

    Field choice is driven by what a sales rep needs before picking up the
    phone, not by what is easy to extract. `interest_reasoning` makes the
    score auditable; `questions_unanswered` doubles as the rep's briefing note.
    """

    lead_name: Optional[str] = None
    contact_number: Optional[str] = None

    language_preference: Language = "unknown"
    configuration_interest: Configuration = "undecided"

    budget_stated: Optional[str] = None
    budget_fit: BudgetFit = "unknown"
    purpose: Purpose = "unknown"
    timeline: Timeline = "unknown"

    interest_level: InterestLevel = "low"
    interest_reasoning: str = ""

    objections_raised: list[str] = []
    questions_unanswered: list[str] = []

    site_visit_status: VisitStatus = "not_discussed"
    site_visit_datetime: Optional[str] = None
    booking_failed: bool = False

    follow_up_required: bool = False
    follow_up_window: Optional[str] = None

    escalation_required: bool = False
    do_not_contact: bool = False

    conversation_summary: str = ""
