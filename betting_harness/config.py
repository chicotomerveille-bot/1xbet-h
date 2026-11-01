"""Configuration for the Sports Betting Harness."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ── Sports & Leagues ──────────────────────────────────────────────
ACTIVE_SPORTS = ["football", "basketball"]

LEAGUES = {
    "football": {
        "FL1": {
            "api_name": "FL1",
            "country": "France",
            "api_code": 2015,  # football-data.org competition code
        },
        # Add more leagues as needed
        # "PL": {"api_name": "Premier League", "country": "England", "api_code": 2021},
    },
    "basketball": {
        "NBA": {
            "api_name": "NBA",
            "country": "USA",
        },
    },
}

# ── Virtual Bankroll ──────────────────────────────────────────────
INITIAL_BANKROLL = 1000.0  # units
STAKE_PCT = 0.01  # 1% of bankroll per bet
MAX_BETS_PER_DAY = 10
MAX_STAKE_PCT = 0.05  # Never stake more than 5% on one bet

# ── Value Bet Thresholds ──────────────────────────────────────────
VALUE_THRESHOLD = 0.05  # 5% minimum value to place a bet
MIN_ODDS = 1.20  # Minimum odds to consider
MAX_ODDS = 15.00  # Maximum odds to consider

# ── Model Weights (fusion of stats + AI) ──────────────────────────
STATS_WEIGHT = 0.6  # Weight of statistical model
AI_WEIGHT = 0.4  # Weight of AI models

# ── Model Agreement ───────────────────────────────────────────────
MIN_AGREEMENT = 0.3  # Minimum agreement between models (0-1)
DISAGREEMENT_THRESHOLD = 0.25  # If spread > this, skip the bet

# ── Database ──────────────────────────────────────────────────────
DB_PATH = BASE_DIR / "betting.db"

# ── API Cache (hours) ─────────────────────────────────────────────
CACHE_HOURS = {
    "matches": 6,
    "odds": 2,
    "stats": 24,
    "news": 12,
}

# ── LLM Configuration ─────────────────────────────────────────────
LLM_TIMEOUT = 20  # seconds
LLM_MAX_TOKENS = 2000
LLM_TEMPERATURE = 0.1  # Low temperature for consistent outputs

# FreeLLMAPI (local proxy for free LLM providers)
FREELLMAPI_BASE_URL = os.getenv("FREELLMAPI_BASE_URL", "http://localhost:31415/v1")
FREELLMAPI_API_KEY = os.getenv("FREELLMAPI_API_KEY", "")
LLM_MODEL_1 = os.getenv("LLM_MODEL_1", "auto")
LLM_MODEL_2 = os.getenv("LLM_MODEL_2", "gemini-flash")
LLM_MODEL_3 = os.getenv("LLM_MODEL_3", "qwen3.8-27b")

# ── Data Sources ──────────────────────────────────────────────────
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
BALLDONTLIE_BASE = "https://api.balldontlie.io/v1"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# ── Logging ───────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "betting_harness.log"
