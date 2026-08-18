"""Configuration loaded from environment variables.

The agent talks to any OpenAI-compatible chat completions endpoint, so switching
providers (Gemini, Groq, OpenAI, a local vLLM server) is an .env change rather
than a code change. See .env.example for tested combinations.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_PATH = BASE_DIR / "prompts" / "system_prompt.md"


class Settings:
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv(
        "LLM_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    llm_model: str = os.getenv("LLM_MODEL", "gemini-2.0-flash")

    # Reply temperature. Kept low-ish: this agent must stay on script around
    # prices and refusals, but flat 0.0 makes it repeat refusal wording verbatim.
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.4"))

    # Analytics extraction is a structured task, so it runs deterministically.
    analytics_temperature: float = 0.0

    max_history_messages: int = int(os.getenv("MAX_HISTORY_MESSAGES", "40"))
    
    # Seconds before a provider call is abandoned. Kept generous enough for a
    # slow first token, short enough that a hung call fails visibly.
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "30"))


settings = Settings()


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """Read the system prompt from disk once and cache it.

    The prompt lives in prompts/system_prompt.md rather than in a Python string
    so it can be reviewed and diffed as its own artifact.
    """
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"System prompt not found at {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")
