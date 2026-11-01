"""Quick DB status check."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
db.init_db()
conn = db.get_conn()
rows = conn.execute("SELECT COUNT(*) as cnt FROM matches").fetchone()
print(f"Matches in DB: {rows['cnt']}")
rows2 = conn.execute("SELECT sport, league, COUNT(*) as cnt FROM matches GROUP BY sport, league").fetchall()
for r in rows2:
    print(f"  {r['sport']} {r['league']}: {r['cnt']}")
bets = conn.execute("SELECT COUNT(*) as cnt FROM virtual_bets").fetchone()
print(f"Virtual bets: {bets['cnt']}")
preds = conn.execute("SELECT source, COUNT(*) as cnt FROM predictions GROUP BY source").fetchall()
print(f"Predictions:")
for p in preds:
    print(f"  {p['source']}: {p['cnt']}")
conn.close()
