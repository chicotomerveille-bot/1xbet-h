"""Check odds and value bets."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
from decision.value_bet import compute_value

db.init_db()
conn = db.get_conn()

# Check odds
odds_count = conn.execute("SELECT COUNT(*) as cnt FROM odds_snapshots").fetchone()
print(f"Odds snapshots: {odds_count['cnt']}")

# Show some odds
odds_rows = conn.execute("SELECT match_id, bookmaker, market, outcome, odds, captured_at FROM odds_snapshots LIMIT 10").fetchall()
print("\nSample odds:")
for r in odds_rows:
    print(f"  match {r['match_id']}: {r['bookmaker']} {r['outcome']} @ {r['odds']:.2f}")

# Check value bets
upcoming = db.get_upcoming_matches(hours_ahead=48)
print(f"\nUpcoming matches: {len(upcoming)}")

all_candidates = []
for m in upcoming:
    preds = db.get_predictions(m["id"], source="fused")
    if not preds:
        continue
    probs = {p["outcome"]: p["probability"] for p in preds}
    
    odds_list = db.get_latest_odds(m["id"], "h2h")
    if not odds_list:
        continue
    
    for o in odds_list:
        outcome = o["outcome"]
        odds_val = o["avg_odds"]
        if outcome not in probs:
            continue
        prob = probs[outcome]
        value = compute_value(prob, odds_val)
        if value > 0:
            all_candidates.append({
                "match": f"{m['home_team']} vs {m['away_team']}",
                "sport": m["sport"],
                "outcome": outcome,
                "prob": prob,
                "odds": odds_val,
                "value": value,
            })

all_candidates.sort(key=lambda x: x["value"], reverse=True)

print(f"\n{'='*60}")
print(f"VALUE BETS FOUND: {len(all_candidates)}")
print(f"{'='*60}")

for vc in all_candidates[:10]:
    print(f"  {vc['match']}: {vc['outcome']} @ {vc['odds']:.2f} "
          f"p={vc['prob']:.1%} value={vc['value']:+.1%}")

if not all_candidates:
    print("  No value bets with current odds.")

conn.close()