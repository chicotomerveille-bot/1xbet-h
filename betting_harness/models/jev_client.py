"""Jev client (optional, early access).

Jev is in early access with a waitlist. This module provides a typed-question
interface for probability estimation. The project must work without Jev.

If JEV_API_KEY is set and access is granted, this module will return probabilities.
Otherwise it returns None and the system uses only stats + DeepSeek + Gemini.
"""

import os
import json
import requests
from typing import Optional
import config


JEV_BASE = "https://api.jev.ai/v1"  # Placeholder — verify with actual docs


def is_available() -> bool:
    """Check if Jev access is configured."""
    return bool(os.getenv("JEV_API_KEY", ""))


def ask_probability(affirmation: str) -> Optional[float]:
    """Ask Jev: 'what is the probability that this is true?' Returns 0-1 or None."""
    api_key = os.getenv("JEV_API_KEY", "")
    if not api_key:
        return None
    try:
        resp = requests.post(
            f"{JEV_BASE}/questions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "type": "probability",
                "affirmation": affirmation,
                "format": "json",
            },
            timeout=config.LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        prob = data.get("probability")
        if prob is not None and 0 <= prob <= 1:
            return float(prob)
        return None
    except requests.RequestException as e:
        print(f"[jev] API error: {e}")
        return None


def analyze_match_jev(match: dict, stats_probs: dict) -> Optional[dict[str, float]]:
    """Use Jev to get probability estimates for a match."""
    if not is_available():
        return None

    home = match.get("home_team", "")
    away = match.get("away_team", "")
    sport = match.get("sport", "")

    if sport == "football":
        outcomes = {
            "HOME": f"{home} will beat {away}",
            "DRAW": f"{home} and {away} will draw",
            "AWAY": f"{away} will beat {home}",
        }
    else:
        outcomes = {
            "HOME": f"{home} will beat {away}",
            "AWAY": f"{away} will beat {home}",
        }

    probs = {}
    for outcome, affirmation in outcomes.items():
        p = ask_probability(affirmation)
        if p is not None:
            probs[outcome] = round(p, 4)

    if not probs:
        return None

    # Normalize
    total = sum(probs.values())
    if total > 0:
        probs = {k: round(v / total, 4) for k, v in probs.items()}

    return probs
