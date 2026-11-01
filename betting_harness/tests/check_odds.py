"""Check odds and bets status."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
db.init_db()
conn = db.get_conn()

odds = conn.execute("SELECT COUNT(*) as cnt FROM odds_snapshots").fetchone()
print(f"Odds snapshots: {odds['cnt']}")

bets = conn.execute("SELECT COUNT(*) as cnt FROM virtual_bets").fetchone()
print(f"Virtual bets: {bets['cnt']}")

# Show upcoming matches with their predictions
rows = conn.execute("""
    SELECT m.id, m.home_team, m.away_team, m.match_date,
           GROUP_CONCAT(DISTINCT p.source) as sources
    FROM matches m
    LEFT JOIN predictions p ON m.id = p.match_id
    WHERE m.status = 'SCHEDULED'
    GROUP BY m.id
    ORDER BY m.match_date
    LIMIT 5
""").fetchall()
print(f"\nUpcoming matches with predictions:")
for r in rows:
    print(f"  {r['home_team']} vs {r['away_team']} ({r['match_date'][:10]}) — sources: {r['sources']}")

# Check if any value bets candidates exist
from decision.value_bet import compute_value
from db import get_latest_odds, get_predictions
upcoming = db.get_upcoming_matches(hours_ahead=48)
print(f"\nValue bet analysis for {len(upcoming)} upcoming matches:")
for m in upcoming[:5]:
    preds = db.get_predictions(m["id"], source="fused")
    if not preds:
        continue
    probs = {p["outcome"]: p["probability"] for p in preds}
    odds_list = db.get_latest_odds(m["id"], "h2h")
    if not odds_list:
        continue
    for o in odds_list:
        outcome = o["outcome"]
        if outcome in probs:
            v = compute_value(probs[outcome], o["avg_odds"])
            if v > 0:
                print(f"  {m['home_team']} vs {m['away_team']}: {outcome} @ {o['avg_odds']:.2f} "
                      f"p={probs[outcome]:.1%} value={v:+.1%}")

conn.close()
