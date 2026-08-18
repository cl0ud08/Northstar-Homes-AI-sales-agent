"""FastAPI application for the Northstar Homes sales agent."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent import run_turn
from .analytics import extract_analytics
from .schemas import ChatRequest, ChatResponse, ConversationAnalytics
from .store import store

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="Northstar Homes — AI Sales Agent",
    description="Conversational agent for Northstar One, Sector 79 Gurugram.",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    session = store.get_or_create(request.session_id)

    try:
        reply, booking_event = run_turn(
            session=session,
            user_message=request.message,
            simulate_outage=request.simulate_outage,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # upstream provider failure
        raise HTTPException(
            status_code=502,
            detail=f"Model provider request failed: {exc}",
        ) from exc

    return ChatResponse(
        session_id=session.session_id,
        reply=reply,
        booking_event=booking_event,
    )


@app.post("/api/end/{session_id}", response_model=ConversationAnalytics)
def end_conversation(session_id: str) -> ConversationAnalytics:
    """Close the conversation and return the extracted lead record."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    try:
        analytics = extract_analytics(session)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Analytics extraction failed: {exc}",
        ) from exc

    session.analytics = analytics
    return analytics


@app.post("/api/reset/{session_id}")
def reset(session_id: str) -> dict:
    store.reset(session_id)
    return {"status": "reset", "session_id": session_id}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
