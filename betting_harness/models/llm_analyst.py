"""AI analyst module: sends structured match context to LLMs via FreeLLMAPI
(local proxy for 30+ free providers), requests strict JSON probability output,
validates responses.

FreeLLMAPI runs locally at FREELLMAPI_BASE_URL and aggregates free tiers from
Gemini, Qwen, Llama, Mistral, Nemotron, GPT-OSS, and many more.
"""

import os
import json
import requests
from typing import Optional
import config


# ── Prompt Template ───────────────────────────────────────────────

PROMPT_TEMPLATE = """You are a professional sports analyst. Analyze this match and give your probability estimates.

## Match
- Sport: {sport}
- League: {league}
- Home: {home_team}
- Away: {away_team}
- Date: {match_date}

## Statistical Model Estimate
{stats_summary}

## Team Statistics (Home)
{home_stats}

## Team Statistics (Away)
{away_stats}

## Current Odds (average market)
{odds_summary}

## Context
{context}

## Instructions
Analyze the match considering:
1. Recent form and momentum
2. Head-to-head tendencies
3. Home/away performance patterns
4. Any contextual factors (injuries, schedule, motivation)

Respond with STRICT JSON only. No markdown, no explanation outside JSON.
For football (3 outcomes), use: {{"home": 0.45, "draw": 0.25, "away": 0.30}}
For basketball (2 outcomes), use: {{"home": 0.55, "away": 0.45}}

The probabilities must sum to 1.0 (±0.02).

JSON output:"""


def build_context_str(match: dict, stats_probs: dict, home_stats: dict,
                      away_stats: dict, odds: list, extra_context: str = "") -> str:
    """Build the prompt from match data."""
    stats_str = ", ".join(f"{k}: {v:.1%}" for k, v in stats_probs.items())

    def _fmt_stats(s: dict) -> str:
        if not s:
            return "No data"
        parts = []
        for key in ("played", "won", "drawn", "lost", "goals_for", "goals_against", "points", "form"):
            if key in s and s[key] is not None:
                parts.append(f"{key}: {s[key]}")
        return ", ".join(parts) if parts else "No data"

    odds_str = ", ".join(f"{o['outcome']}: {o['avg_odds']:.2f}" for o in odds) if odds else "No odds"

    return PROMPT_TEMPLATE.format(
        sport=match.get("sport", ""),
        league=match.get("league", ""),
        home_team=match.get("home_team", ""),
        away_team=match.get("away_team", ""),
        match_date=match.get("match_date", ""),
        stats_summary=stats_str,
        home_stats=_fmt_stats(home_stats),
        away_stats=_fmt_stats(away_stats),
        odds_summary=odds_str,
        context=extra_context or "No additional context.",
    )


# ── FreeLLMAPI Client ─────────────────────────────────────────────

def call_freellmapi(prompt: str, model: str = None) -> Optional[str]:
    """Call FreeLLMAPI local proxy, return raw response text.

    FreeLLMAPI is OpenAI-compatible and aggregates 30+ free providers.
    Uses config.FREELLMAPI_BASE_URL and config.FREELLMAPI_API_KEY.
    """
    if not config.FREELLMAPI_API_KEY:
        print("[llm] FREELLMAPI_API_KEY not set")
        return None
    if model is None:
        model = config.LLM_MODEL_1

    try:
        resp = requests.post(
            f"{config.FREELLMAPI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.FREELLMAPI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": config.LLM_MAX_TOKENS,
                "temperature": config.LLM_TEMPERATURE,
                "response_format": {"type": "json_object"},
            },
            timeout=config.LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        print(f"[llm] FreeLLMAPI error ({model}): {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"[llm] FreeLLMAPI parse error ({model}): {e}")
        return None


def call_llm(prompt: str, model: str = None) -> Optional[str]:
    """Generic LLM call. Tries FreeLLMAPI first, falls back to direct APIs."""
    # Try FreeLLMAPI
    result = call_freellmapi(prompt, model)
    if result:
        return result

    # Fallback: direct DeepSeek
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if api_key:
        try:
            resp = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": config.LLM_MAX_TOKENS,
                    "temperature": config.LLM_TEMPERATURE,
                    "response_format": {"type": "json_object"},
                },
                timeout=config.LLM_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            pass

    # Fallback: direct Gemini
    api_key = os.getenv("GEMINI_API_KEY", "")
    if api_key:
        try:
            resp = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": config.LLM_MAX_TOKENS,
                        "temperature": config.LLM_TEMPERATURE,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=config.LLM_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            pass

    return None


# ── JSON Validation ───────────────────────────────────────────────

def parse_llm_response(raw: str, sport: str) -> Optional[dict[str, float]]:
    """Parse and validate LLM JSON response. Returns normalized probabilities or None."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{[^{}]+\}', raw)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    key_map = {
        "home": "HOME", "h": "HOME", "home_win": "HOME", "1": "HOME",
        "draw": "DRAW", "d": "DRAW", "x": "DRAW", "tie": "DRAW",
        "away": "AWAY", "a": "AWAY", "away_win": "AWAY", "2": "AWAY",
    }
    probs = {}
    for k, v in data.items():
        normalized = key_map.get(k.lower().strip())
        if normalized and isinstance(v, (int, float)) and 0 <= v <= 1:
            probs[normalized] = float(v)

    if not probs:
        return None

    total = sum(probs.values())
    if total < 0.8 or total > 1.2:
        print(f"[llm] Probabilities sum to {total:.3f}, expected ~1.0")
        return None

    return {k: round(v / total, 4) for k, v in probs.items()}


# ── Multi-Model Analysis ──────────────────────────────────────────

def analyze_match(match: dict, stats_probs: dict, home_stats: dict,
                  away_stats: dict, odds: list,
                  extra_context: str = "") -> dict[str, dict[str, float]]:
    """Run AI analysis using multiple FreeLLMAPI models.

    Returns {model_name: {outcome: prob}} for each model that responded.
    """
    prompt = build_context_str(match, stats_probs, home_stats, away_stats, odds, extra_context)
    results = {}

    # Model 1: auto-router (picks the best available)
    raw1 = call_llm(prompt, config.LLM_MODEL_1)
    probs1 = parse_llm_response(raw1, match.get("sport", ""))
    if probs1:
        results[config.LLM_MODEL_1] = probs1

    # Model 2: gemini-flash (fast)
    raw2 = call_llm(prompt, config.LLM_MODEL_2)
    probs2 = parse_llm_response(raw2, match.get("sport", ""))
    if probs2:
        results[config.LLM_MODEL_2] = probs2

    # Model 3: qwen3.8-27b (strong reasoning)
    raw3 = call_llm(prompt, config.LLM_MODEL_3)
    probs3 = parse_llm_response(raw3, match.get("sport", ""))
    if probs3:
        results[config.LLM_MODEL_3] = probs3

    return results
