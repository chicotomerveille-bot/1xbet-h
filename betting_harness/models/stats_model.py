"""Statistical probability models.

Football: Poisson model based on goals scored/conceded.
NBA: Elo rating adjusted for home court and rest.
"""

import math
from typing import Optional
import db


# ── Football: Poisson Model ───────────────────────────────────────

def poisson_prob(lmbda: float, k: int) -> float:
    """Poisson probability P(X=k) given lambda."""
    return math.exp(-lmbda) * (lmbda ** k) / math.factorial(k)


def football_expected_goals(home_team: str, away_team: str) -> tuple[float, float]:
    """Estimate expected goals for home and away teams using team stats."""
    home_stats = db.get_latest_team_stats("football", home_team)
    away_stats = db.get_latest_team_stats("football", away_team)

    # League averages (fallback: 1.35 goals per team per match)
    LEAGUE_AVG_HOME = 1.45
    LEAGUE_AVG_AWAY = 1.15
    DEFAULT_LAMBDA = 1.35

    if home_stats and away_stats and home_stats.get("played", 0) > 0:
        # Attack strength
        home_attack = (home_stats["goals_for"] / home_stats["played"]) / LEAGUE_AVG_HOME
        away_attack = (away_stats["goals_for"] / away_stats["played"]) / LEAGUE_AVG_AWAY
        # Defense weakness
        home_def = (home_stats["goals_against"] / home_stats["played"]) / LEAGUE_AVG_AWAY
        away_def = (away_stats["goals_against"] / away_stats["played"]) / LEAGUE_AVG_HOME

        home_xg = LEAGUE_AVG_HOME * home_attack * away_def
        away_xg = LEAGUE_AVG_AWAY * away_attack * home_def
    else:
        # No stats — use league averages with home advantage
        home_xg = LEAGUE_AVG_HOME
        away_xg = LEAGUE_AVG_AWAY

    return max(home_xg, 0.1), max(away_xg, 0.1)


def football_match_probs(home_team: str, away_team: str,
                         max_goals: int = 10) -> dict[str, float]:
    """Compute P(Home), P(Draw), P(Away) via Poisson score matrix."""
    home_xg, away_xg = football_expected_goals(home_team, away_team)

    p_home = p_draw = p_away = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p_ij = poisson_prob(home_xg, i) * poisson_prob(away_xg, j)
            if i > j:
                p_home += p_ij
            elif i == j:
                p_draw += p_ij
            else:
                p_away += p_ij

    total = p_home + p_draw + p_away
    return {
        "HOME": round(p_home / total, 4),
        "DRAW": round(p_draw / total, 4),
        "AWAY": round(p_away / total, 4),
    }


# ── Basketball (NBA): Elo Model ───────────────────────────────────

def elo_expected(rating_a: float, rating_b: float, home_advantage: float = 100.0) -> float:
    """Elo expected score for team A vs team B (A is home)."""
    diff = rating_a + home_advantage - rating_b
    return 1.0 / (1.0 + 10 ** (-diff / 400.0))


def compute_elo_from_stats(team: str) -> float:
    """Compute a pseudo-Elo from stored team stats."""
    stats = db.get_latest_team_stats("basketball", team)
    if not stats or stats.get("played", 0) == 0:
        return 1500.0  # Default Elo
    win_rate = stats["won"] / stats["played"]
    pts_diff = (stats["goals_for"] - stats["goals_against"]) / stats["played"]
    # Simple Elo approximation from win rate and point differential
    elo = 1500 + (win_rate - 0.5) * 400 + pts_diff * 2.0
    return round(elo, 1)


def basketball_match_probs(home_team: str, away_team: str) -> dict[str, float]:
    """Compute P(Home) and P(Away) via Elo. NBA has no draw."""
    home_elo = compute_elo_from_stats(home_team)
    away_elo = compute_elo_from_stats(away_team)
    p_home = elo_expected(home_elo, away_elo)
    p_away = 1.0 - p_home
    return {
        "HOME": round(p_home, 4),
        "AWAY": round(p_away, 4),
    }


# ── Unified Interface ─────────────────────────────────────────────

def get_match_probabilities(sport: str, home_team: str, away_team: str) -> dict[str, float]:
    """Return model probabilities for a match based on sport."""
    if sport == "football":
        return football_match_probs(home_team, away_team)
    elif sport == "basketball":
        return basketball_match_probs(home_team, away_team)
    else:
        raise ValueError(f"Unknown sport: {sport}")


# ── Brier Score for Validation ────────────────────────────────────

def brier_score(predicted: dict[str, float], actual_outcome: str) -> float:
    """Multi-class Brier score for a single match."""
    score = 0.0
    for outcome, prob in predicted.items():
        target = 1.0 if outcome == actual_outcome else 0.0
        score += (prob - target) ** 2
    return score


def evaluate_on_history(sport: str, league: str, sample_size: int = 50) -> dict:
    """Evaluate the statistical model on historical matches."""
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT * FROM matches WHERE sport=? AND league=? AND status='FINISHED'
           ORDER BY match_date DESC LIMIT ?""",
        (sport, league, sample_size),
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "No historical matches in DB"}

    total_brier = 0.0
    n = 0
    for row in rows:
        m = dict(row)
        if m["home_score"] is None or m["away_score"] is None:
            continue
        if sport == "football":
            if m["home_score"] > m["away_score"]:
                outcome = "HOME"
            elif m["home_score"] == m["away_score"]:
                outcome = "DRAW"
            else:
                outcome = "AWAY"
        else:
            outcome = "HOME" if m["home_score"] > m["away_score"] else "AWAY"

        probs = get_match_probabilities(sport, m["home_team"], m["away_team"])
        total_brier += brier_score(probs, outcome)
        n += 1

    if n == 0:
        return {"error": "No valid matches to evaluate"}

    return {
        "n_matches": n,
        "avg_brier": round(total_brier / n, 4),
        "interpretation": "Lower is better. 0.33 ≈ random for 3-class, 0.25 for 2-class.",
    }
