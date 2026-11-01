"""Collect NBA data from balldontlie.io (free tier)."""

import os
import requests
from datetime import datetime, timedelta
import config
import db


def _get_headers() -> dict:
    key = os.getenv("BALLDONTLIE_API_KEY", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _api_get(path: str, params: dict = None) -> dict | None:
    """GET with SQLite cache."""
    cache_key = f"bdl:{path}:{params}"
    cached = db.cache_get("balldontlie", cache_key, config.CACHE_HOURS["matches"])
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            f"{config.BALLDONTLIE_BASE}{path}",
            headers=_get_headers(),
            params=params or {},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        db.cache_set("balldontlie", cache_key, data)
        return data
    except requests.RequestException as e:
        print(f"[balldontlie] API error: {e}")
        return None


def fetch_upcoming_games(days_ahead: int = 3) -> list[dict]:
    """Fetch upcoming NBA games."""
    dates = []
    for d in range(days_ahead + 1):
        date_str = (datetime.now() + timedelta(days=d)).strftime("%Y-%m-%d")
        dates.append(date_str)

    all_games = []
    for date_str in dates:
        data = _api_get("/games", {"dates[]": date_str, "per_page": 100})
        if not data or "data" not in data:
            continue
        for g in data["data"]:
            home = g.get("home_team", {})
            visitor = g.get("visitor_team", {})
            all_games.append({
                "source_id": str(g["id"]),
                "match_date": f"{date_str}T00:00:00Z",
                "home_team": home.get("full_name", home.get("name", "")),
                "away_team": visitor.get("full_name", visitor.get("name", "")),
                "status": "SCHEDULED",
                "home_team_id": home.get("id"),
                "away_team_id": visitor.get("id"),
            })
    return all_games


def fetch_game_results(days_back: int = 7) -> list[dict]:
    """Fetch finished NBA games."""
    dates = []
    for d in range(days_back + 1):
        date_str = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
        dates.append(date_str)

    all_games = []
    for date_str in dates:
        data = _api_get("/games", {"dates[]": date_str, "per_page": 100})
        if not data or "data" not in data:
            continue
        for g in data["data"]:
            if g.get("status") != "Final":
                continue
            home = g.get("home_team", {})
            visitor = g.get("visitor_team", {})
            all_games.append({
                "source_id": str(g["id"]),
                "match_date": f"{date_str}T00:00:00Z",
                "home_team": home.get("full_name", home.get("name", "")),
                "away_team": visitor.get("full_name", visitor.get("name", "")),
                "home_score": g.get("home_team_score"),
                "away_score": g.get("visitor_team_score"),
                "status": "FINISHED",
            })
    return all_games


def fetch_team_stats(team_id: int, season: int = None) -> dict | None:
    """Fetch season averages for a team."""
    if season is None:
        season = datetime.now().year
    data = _api_get("/season_averages", {"season": season, "team_ids[]": team_id})
    if not data or "data" not in data or not data["data"]:
        return None
    stats = data["data"][0]
    return {
        "games_played": stats.get("games_played"),
        "pts": stats.get("pts"),
        "reb": stats.get("reb"),
        "ast": stats.get("ast"),
        "fg_pct": stats.get("fg_pct"),
        "fg3_pct": stats.get("fg3_pct"),
        "ft_pct": stats.get("ft_pct"),
        "turnover": stats.get("turnover"),
        "plus_minus": stats.get("plus_minus"),
    }


def store_upcoming() -> list[int]:
    """Fetch upcoming NBA games and store them. Returns match IDs."""
    games = fetch_upcoming_games()
    ids = []
    for g in games:
        match_id = db.upsert_match(
            sport="basketball",
            league="NBA",
            match_date=g["match_date"],
            home_team=g["home_team"],
            away_team=g["away_team"],
            status=g["status"],
            source="balldontlie.io",
            source_id=g["source_id"],
        )
        ids.append(match_id)
    return ids


def store_results(days_back: int = 7) -> int:
    """Fetch and store NBA results."""
    games = fetch_game_results(days_back)
    count = 0
    for g in games:
        db.upsert_match(
            sport="basketball",
            league="NBA",
            match_date=g["match_date"],
            home_team=g["home_team"],
            away_team=g["away_team"],
            home_score=g["home_score"],
            away_score=g["away_score"],
            status=g["status"],
            source="balldontlie.io",
            source_id=g["source_id"],
        )
        count += 1
    return count
