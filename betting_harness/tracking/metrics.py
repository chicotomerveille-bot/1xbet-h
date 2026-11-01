"""Performance metrics: ROI, win rate, CLV, Brier score, model comparison."""

import db
import config


def overall_metrics() -> dict:
    """Compute overall performance metrics."""
    bets = db.get_all_bets()
    settled = [b for b in bets if b["status"] in ("WON", "LOST")]

    if not settled:
        return {
            "total_bets": 0,
            "settled": 0,
            "pending": len([b for b in bets if b["status"] == "PENDING"]),
            "roi": 0.0,
            "profit": 0.0,
            "win_rate": 0.0,
            "bankroll": config.INITIAL_BANKROLL,
            "initial_bankroll": config.INITIAL_BANKROLL,
        }

    total_stake = sum(b["stake"] for b in settled)
    total_profit = sum(b["profit"] for b in settled)
    wins = len([b for b in settled if b["status"] == "WON"])
    roi = total_profit / total_stake if total_stake > 0 else 0.0

    # Current bankroll
    from decision.bankroll import get_current_bankroll
    bankroll = get_current_bankroll()

    return {
        "total_bets": len(bets),
        "settled": len(settled),
        "pending": len([b for b in bets if b["status"] == "PENDING"]),
        "roi": round(roi, 4),
        "profit": round(total_profit, 2),
        "win_rate": round(wins / len(settled), 4),
        "wins": wins,
        "losses": len(settled) - wins,
        "total_stake": round(total_stake, 2),
        "bankroll": bankroll,
        "initial_bankroll": config.INITIAL_BANKROLL,
    }


def clv_metrics() -> dict:
    """Compute Closing Line Value for settled bets.

    CLV = odds_taken - closing_odds. Positive CLV means you got a better price
    than the market close, which is the most reliable skill indicator.
    """
    bets = db.get_all_bets()
    settled = [b for b in bets if b["status"] in ("WON", "LOST")]

    conn = db.get_conn()
    clv_values = []
    for bet in settled:
        row = conn.execute(
            "SELECT odds FROM closing_odds WHERE match_id=? AND market=? AND outcome=?",
            (bet["match_id"], bet["market"], bet["outcome"]),
        ).fetchone()
        if row:
            clv = bet["odds_taken"] - row["odds"]
            clv_values.append(clv)
    conn.close()

    if not clv_values:
        return {"clv_avg": None, "clv_positive_pct": None, "n_with_clv": 0}

    avg_clv = sum(clv_values) / len(clv_values)
    positive = len([c for c in clv_values if c > 0]) / len(clv_values)

    return {
        "clv_avg": round(avg_clv, 4),
        "clv_positive_pct": round(positive, 4),
        "n_with_clv": len(clv_values),
    }


def model_comparison() -> dict:
    """Compare prediction sources by Brier score on settled matches."""
    conn = db.get_conn()

    # Get all settled bets with their match results
    settled = conn.execute(
        """SELECT vb.*, m.home_score, m.away_score, m.sport
           FROM virtual_bets vb
           JOIN matches m ON vb.match_id = m.id
           WHERE vb.status IN ('WON','LOST')"""
    ).fetchall()

    # For each source, compute Brier on those matches
    sources = ["stats"] + [config.LLM_MODEL_1, config.LLM_MODEL_2, config.LLM_MODEL_3, "jev", "fused"]
    comparison = {}

    for source in sources:
        total_brier = 0.0
        n = 0
        for bet in settled:
            bet = dict(bet)
            preds = conn.execute(
                "SELECT * FROM predictions WHERE match_id=? AND source=? ORDER BY created_at DESC LIMIT 1",
                (bet["match_id"], source),
            ).fetchall()
            if not preds:
                continue
            pred = dict(preds[0])
            # Actual outcome
            if bet["home_score"] > bet["away_score"]:
                actual = "HOME"
            elif bet["home_score"] == bet["away_score"]:
                actual = "DRAW"
            else:
                actual = "AWAY"
            # Brier
            outcomes = ["HOME", "DRAW", "AWAY"] if bet["sport"] == "football" else ["HOME", "AWAY"]
            brier = 0.0
            for o in outcomes:
                p = pred.get("probability", 0.5) if o == pred.get("outcome") else (1 - pred.get("probability", 0.5)) / (len(outcomes) - 1)
                t = 1.0 if o == actual else 0.0
                brier += (p - t) ** 2
            total_brier += brier
            n += 1

        if n > 0:
            comparison[source] = {
                "avg_brier": round(total_brier / n, 4),
                "n_evaluated": n,
            }
        else:
            comparison[source] = {"avg_brier": None, "n_evaluated": 0}

    conn.close()
    return comparison


def daily_summary() -> dict:
    """Summary of today's activity."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    conn = db.get_conn()
    bets_today = conn.execute(
        "SELECT * FROM virtual_bets WHERE placed_at LIKE ?", (today + "%",)
    ).fetchall()
    conn.close()

    bets = [dict(b) for b in bets_today]
    settled_today = [b for b in bets if b["status"] in ("WON", "LOST")]

    return {
        "date": today,
        "bets_placed": len(bets),
        "bets_settled": len(settled_today),
        "profit_today": round(sum(b["profit"] or 0 for b in settled_today), 2),
        "cap_remaining": config.MAX_BETS_PER_DAY - len(bets),
    }
