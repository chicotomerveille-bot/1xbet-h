"""Virtual bankroll management.

Fixed 1% stake per bet. No martingale. Track bankroll across all bets.
"""

import db
import config


def get_current_bankroll() -> float:
    """Compute current bankroll from bet history."""
    bets = db.get_all_bets()
    bankroll = config.INITIAL_BANKROLL
    for b in bets:
        if b["status"] == "WON":
            bankroll += b["profit"]
        elif b["status"] == "LOST":
            bankroll += b["profit"]  # profit is negative
    return round(bankroll, 2)


def calculate_stake(bankroll: float) -> float:
    """Fixed percentage stake. No martingale."""
    stake = bankroll * config.STAKE_PCT
    stake = min(stake, bankroll * config.MAX_STAKE_PCT)
    return round(stake, 2)


def bankroll_history() -> list[dict]:
    """Return bankroll after each settled bet (for curve plotting)."""
    bets = db.get_all_bets(status="WON") + db.get_all_bets(status="LOST")
    bets.sort(key=lambda b: b.get("settled_at", b.get("placed_at", "")))

    history = []
    bankroll = config.INITIAL_BANKROLL
    history.append({"date": "start", "bankroll": bankroll})
    for b in bets:
        bankroll += b["profit"]
        history.append({
            "date": b.get("settled_at", ""),
            "bankroll": round(bankroll, 2),
            "bet_id": b["id"],
            "profit": b["profit"],
        })
    return history
