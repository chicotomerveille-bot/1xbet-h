"""Value bet calculation and virtual bet selection.

Value = probability * odds - 1.
Bet only when value exceeds threshold AND models agree sufficiently.
"""

import db
import config


def compute_value(probability: float, odds: float) -> float:
    """Compute edge: value = p * odds - 1."""
    if odds <= 1.0:
        return -1.0
    return probability * odds - 1.0


def models_agreement(all_probs: list[dict[str, float]]) -> float:
    """Measure agreement between models. Returns 0-1 (1 = perfect agreement).

    Uses the average pairwise total variation distance.
    """
    if len(all_probs) < 2:
        return 1.0  # Single model — no disagreement

    outcomes = set()
    for p in all_probs:
        outcomes.update(p.keys())

    total_agreement = 0.0
    pairs = 0
    for i in range(len(all_probs)):
        for j in range(i + 1, len(all_probs)):
            diff = 0.0
            for o in outcomes:
                pi = all_probs[i].get(o, 0.0)
                pj = all_probs[j].get(o, 0.0)
                diff += abs(pi - pj)
            # TV distance: 0 = identical, 1 = opposite
            tv = diff / 2.0
            total_agreement += 1.0 - tv
            pairs += 1

    return total_agreement / pairs if pairs > 0 else 1.0


def fused_probabilities(stats_probs: dict[str, float],
                        ai_probs_list: list[dict[str, float]]) -> dict[str, float]:
    """Compute weighted fusion of stats model and AI models.

    stats_weight and ai_weight from config.
    AI models are averaged first, then fused with stats.
    """
    outcomes = set(stats_probs.keys())
    for p in ai_probs_list:
        outcomes.update(p.keys())

    # Average AI probabilities
    ai_avg = {}
    for o in outcomes:
        vals = [p.get(o, 0.0) for p in ai_probs_list]
        ai_avg[o] = sum(vals) / len(vals) if vals else 0.0

    # Weighted fusion
    fused = {}
    for o in outcomes:
        s = stats_probs.get(o, 0.0)
        a = ai_avg.get(o, 0.0)
        fused[o] = round(config.STATS_WEIGHT * s + config.AI_WEIGHT * a, 4)

    # Normalize
    total = sum(fused.values())
    if total > 0:
        fused = {k: round(v / total, 4) for k, v in fused.items()}

    return fused


def find_value_bets(match_id: int, sport: str,
                    fused_probs: dict[str, float],
                    odds_list: list[dict],
                    all_probs: list[dict[str, float]]) -> list[dict]:
    """Find value bets for a match. Returns list of bet candidates."""
    if not odds_list:
        return []

    # Check model agreement
    agreement = models_agreement(all_probs)
    if agreement < 1.0 - config.DISAGREEMENT_THRESHOLD:
        print(f"[decision] Models disagree too much ({agreement:.2f}), skipping match {match_id}")
        return []

    candidates = []
    for o in odds_list:
        outcome = o["outcome"]
        odds_val = o["avg_odds"]

        if outcome not in fused_probs:
            continue
        if odds_val < config.MIN_ODDS or odds_val > config.MAX_ODDS:
            continue

        prob = fused_probs[outcome]
        value = compute_value(prob, odds_val)

        if value >= config.VALUE_THRESHOLD:
            candidates.append({
                "match_id": match_id,
                "sport": sport,
                "market": "h2h",
                "outcome": outcome,
                "odds": odds_val,
                "probability": prob,
                "value": value,
                "agreement": agreement,
            })

    # Sort by value descending
    candidates.sort(key=lambda x: x["value"], reverse=True)
    return candidates


def select_and_record_bets(candidates: list[dict]) -> list[dict]:
    """Select bets respecting daily cap, record them as virtual bets."""
    bets_today = db.get_bets_count_today()
    remaining = config.MAX_BETS_PER_DAY - bets_today
    if remaining <= 0:
        print(f"[decision] Daily bet cap reached ({config.MAX_BETS_PER_DAY})")
        return []

    # Get current bankroll
    bankroll = db.get_all_bets()
    if bankroll:
        current = config.INITIAL_BANKROLL
        for b in bankroll:
            if b["status"] == "WON":
                current += b["profit"]
            elif b["status"] == "LOST":
                current += b["profit"]  # profit is negative
    else:
        current = config.INITIAL_BANKROLL

    recorded = []
    for cand in candidates[:remaining]:
        # Stake: 1% of bankroll, capped at 5%
        stake = current * config.STAKE_PCT
        stake = min(stake, current * config.MAX_STAKE_PCT)
        stake = round(stake, 2)

        bet_id = db.place_virtual_bet(
            match_id=cand["match_id"],
            sport=cand["sport"],
            market=cand["market"],
            outcome=cand["outcome"],
            odds_taken=cand["odds"],
            stake=stake,
            estimated_prob=cand["probability"],
            value=cand["value"],
            bankroll_before=current,
        )
        cand["bet_id"] = bet_id
        cand["stake"] = stake
        recorded.append(cand)
        current -= stake

    return recorded
