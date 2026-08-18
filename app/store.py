"""In-memory session store.

Deliberately not a database. The assignment asks for conversation memory, not
persistence, and a dict keeps the runnable surface to `uvicorn app.main:app`.
Sessions are lost on restart — noted as a known limitation in the README.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .schemas import BookingEvent, ConversationAnalytics


@dataclass
class Session:
    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    bookings: list[BookingEvent] = field(default_factory=list)
    analytics: Optional[ConversationAnalytics] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    def transcript(self) -> str:
        """Flatten to a readable transcript for the analytics pass."""
        lines = []
        for m in self.messages:
            role = m.get("role")
            content = m.get("content")
            if role in ("user", "assistant") and content:
                speaker = "Customer" if role == "user" else "Riya"
                lines.append(f"{speaker}: {content}")
        return "\n".join(lines)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, session_id: Optional[str]) -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        new_id = session_id or uuid.uuid4().hex[:12]
        session = Session(session_id=new_id)
        self._sessions[new_id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


store = SessionStore()
