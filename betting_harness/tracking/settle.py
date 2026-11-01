"""Settlement: fetch results and settle pending virtual bets."""

from datetime import datetime
import db


def settle_pending_bets() -> int:
    """Check all pending bets and settle them against match results.

    Returns number of bets settled.
    """
    pending = db.get_pending_bets()
    if not pending:
        return 0

    settled_count = 0
    for bet in pending:
        match_id = bet["match_id"]
        conn = db.get_conn()
        match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        conn.close()

        if not match:
            continue

        match = dict(match)
        if match["status"] != "FINISHED" or match["home_score"] is None:
            continue

        # Determine actual outcome
        if match["home_score"] > match["away_score"]:
            actual = "HOME"
        elif match["home_score"] == match["away_score"]:
            actual = "DRAW"
        else:
            actual = "AWAY"

        won = bet["outcome"] == actual
        if won:
            profit = bet["stake"] * (bet["odds_taken"] - 1.0)
        else:
            profit = -bet["stake"]

        db.settle_bet(bet["id"], won=won, profit=round(profit, 2))
        settled_count += 1

    return settled_count


def record_closing_odds() -> int:
    """Record closing odds for matches about to start (for CLV).

    Should run shortly before match start.
    """
    from collectors.odds import get_average_odds

    upcoming = db.get_upcoming_matches(hours_ahead=2)
    count = 0
    for match in upcoming:
        odds_list = get_average_odds(match["id"], "h2h")
        for o in odds_list:
            db.save_closing_odds(
                match_id=match["id"],
                market="h2h",
                outcome=o["outcome"],
                odds=o["avg_odds"],
            )
            count += 1
    return count
