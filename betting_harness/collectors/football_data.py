"""Collect football data from football-data.org (free tier)."""

import os
import requests
from datetime import datetime, timedelta
import config
import db


HEADERS = {"X-Auth-Token": ""}  # Set in _get_headers()


def _get_headers() -> dict:
    key = os.getenv("FOOTBALL_DATA_KEY", "")
    return {"X-Auth-Token": key}


def _api_get(path: str, params: dict = None) -> dict | None:
    """GET with SQLite cache."""
    cache_key = f"fd:{path}:{params}"
    cached = db.cache_get("football_data", cache_key, config.CACHE_HOURS["matches"])
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            f"{config.FOOTBALL_DATA_BASE}{path}",
            headers=_get_headers(),
            params=params or {},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        db.cache_set("football_data", cache_key, data)
        return data
    except requests.RequestException as e:
        print(f"[football_data] API error: {e}")
        return None


def fetch_upcoming(league_code: str, days_ahead: int = 3) -> list[dict]:
    """Fetch upcoming matches for a competition."""
    date_from = datetime.now().strftime("%Y-%m-%d")
    date_to = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    data = _api_get(
        f"/competitions/{league_code}/matches",
        {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED"},
    )
    if not data or "matches" not in data:
        return []
    results = []
    for m in data["matches"]:
        results.append({
            "source_id": str(m["id"]),
            "match_date": m["utcDate"],
            "home_team": m["homeTeam"]["name"] or m["homeTeam"]["shortName"],
            "away_team": m["awayTeam"]["name"] or m["awayTeam"]["shortName"],
            "status": "SCHEDULED",
        })
    return results


def fetch_results(league_code: str, days_back: int = 7) -> list[dict]:
    """Fetch finished matches for training/validation."""
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")
    data = _api_get(
        f"/competitions/{league_code}/matches",
        {"dateFrom": date_from, "dateTo": date_to, "status": "FINISHED"},
    )
    if not data or "matches" not in data:
        return []
    results = []
    for m in data["matches"]:
        score = m.get("score", {}).get("fullTime", {})
        results.append({
            "source_id": str(m["id"]),
            "match_date": m["utcDate"],
            "home_team": m["homeTeam"]["name"] or m["homeTeam"]["shortName"],
            "away_team": m["awayTeam"]["name"] or m["awayTeam"]["shortName"],
            "home_score": score.get("home"),
            "away_score": score.get("away"),
            "status": "FINISHED",
        })
    return results


def fetch_standings(league_code: str) -> list[dict]:
    """Fetch current standings/table."""
    data = _api_get(f"/competitions/{league_code}/standings")
    if not data or "standings" not in data:
        return []
    table = data["standings"][0].get("table", [])
    results = []
    for row in table:
        results.append({
            "team": row["team"]["name"] or row["team"]["shortName"],
            "position": row["position"],
            "played": row["playedGames"],
            "won": row["won"],
            "drawn": row["draw"],
            "lost": row["lost"],
            "points": row["points"],
            "goals_for": row["goalsFor"],
            "goals_against": row["goalsAgainst"],
            "goal_difference": row["goalDifference"],
        })
    return results


def fetch_team_matches(team_id: str, limit: int = 10) -> list[dict]:
    """Fetch recent matches for a specific team."""
    data = _api_get(f"/teams/{team_id}/matches", {"limit": limit, "status": "FINISHED"})
    if not data or "matches" not in data:
        return []
    results = []
    for m in data["matches"]:
        score = m.get("score", {}).get("fullTime", {})
        results.append({
            "match_date": m["utcDate"],
            "home_team": m["homeTeam"]["name"] or m["homeTeam"]["shortName"],
            "away_team": m["awayTeam"]["name"] or m["awayTeam"]["shortName"],
            "home_score": score.get("home"),
            "away_score": score.get("away"),
        })
    return results


def store_upcoming(league_code: str) -> list[int]:
    """Fetch upcoming matches and store them. Returns match IDs."""
    matches = fetch_upcoming(league_code)
    ids = []
    for m in matches:
        match_id = db.upsert_match(
            sport="football",
            league=league_code,
            match_date=m["match_date"],
            home_team=m["home_team"],
            away_team=m["away_team"],
            status=m["status"],
            source="football_data.org",
            source_id=m["source_id"],
        )
        ids.append(match_id)
    return ids


def store_results(league_code: str, days_back: int = 7) -> int:
    """Fetch and store finished matches."""
    matches = fetch_results(league_code, days_back)
    count = 0
    for m in matches:
        db.upsert_match(
            sport="football",
            league=league_code,
            match_date=m["match_date"],
            home_team=m["home_team"],
            away_team=m["away_team"],
            home_score=m["home_score"],
            away_score=m["away_score"],
            status=m["status"],
            source="football_data.org",
            source_id=m["source_id"],
        )
        count += 1
    return count



