"""Collect odds from The Odds API (free tier)."""

import os
import requests
from datetime import datetime
import config
import db


SPORT_KEYS = {
    "FL1": "soccer_france_ligue_one",
    "NBA": "basketball_nba",
}


def _api_get(sport_key: str, regions: str = "eu", markets: str = "h2h") -> list[dict] | None:
    """GET odds from The Odds API with cache."""
    cache_key = f"odds:{sport_key}:{regions}:{markets}"
    cached = db.cache_get("odds_api", cache_key, config.CACHE_HOURS["odds"])
    if cached is not None:
        return cached
    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        print("[odds] ODDS_API_KEY not set")
        return None
    try:
        resp = requests.get(
            f"{config.ODDS_API_BASE}/sports/{sport_key}/odds",
            params={
                "apiKey": api_key,
                "regions": regions,
                "markets": markets,
                "oddsFormat": "decimal",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        db.cache_set("odds_api", cache_key, data)
        return data
    except requests.RequestException as e:
        print(f"[odds] API error: {e}")
        return None


def fetch_odds(league_code: str) -> list[dict]:
    """Fetch odds for a league, return normalized list."""
    sport_key = SPORT_KEYS.get(league_code)
    if not sport_key:
        print(f"[odds] No sport key for league {league_code}")
        return []
    data = _api_get(sport_key)
    if not data:
        return []
    results = []
    for event in data:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        commence = event.get("commence_time", "")
        for bookmaker in event.get("bookmakers", []):
            bk_name = bookmaker.get("key", "unknown")
            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "h2h")
                for outcome in market.get("outcomes", []):
                    results.append({
                        "home_team": home,
                        "away_team": away,
                        "commence_time": commence,
                        "bookmaker": bk_name,
                        "market": market_key,
                        "outcome": outcome.get("name", "").upper(),
                        "odds": outcome.get("price"),
                    })
    return results


def store_odds(league_code: str) -> int:
    """Fetch and store odds snapshots for a league. Returns count stored."""
    odds_list = fetch_odds(league_code)
    count = 0
    sport = "football" if league_code.startswith(("FL", "PL", "PD", "SA", "BL")) else "basketball"
    for o in odds_list:
        # Find matching match_id
        conn = db.get_conn()
        row = conn.execute(
            """SELECT id FROM matches
               WHERE sport=? AND league=?
               AND (home_team LIKE ? OR away_team LIKE ?)
               AND match_date LIKE ?
               LIMIT 1""",
            (sport, league_code, f"%{o['home_team']}%", f"%{o['away_team']}%", f"{o['commence_time'][:10]}%"),
        ).fetchone()
        conn.close()
        if row:
            db.save_odds(
                match_id=row["id"],
                bookmaker=o["bookmaker"],
                market=o["market"],
                outcome=o["outcome"],
                odds=o["odds"],
            )
            count += 1
    return count


def get_average_odds(match_id: int, market: str = "h2h") -> list[dict]:
    """Get average odds per outcome for a match (from DB)."""
    return db.get_latest_odds(match_id, market)


def estimate_implied_probabilities(odds_list: list[dict]) -> dict[str, float]:
    """Convert odds to implied probabilities, remove overround."""
    if not odds_list:
        return {}
    probs = {}
    for o in odds_list:
        outcome = o["outcome"]
        avg_odds = o["avg_odds"]
        if avg_odds and avg_odds > 1:
            probs[outcome] = 1.0 / avg_odds
    # Remove overround (normalize)
    total = sum(probs.values())
    if total > 0:
        probs = {k: v / total for k, v in probs.items()}
    return probs
