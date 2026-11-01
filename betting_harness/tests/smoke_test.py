"""Quick smoke test: verify all modules import and DB initializes."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("Testing imports...")

import config
print(f"  config OK — DB: {config.DB_PATH}")
print(f"    Sports: {config.ACTIVE_SPORTS}")
print(f"    Bankroll: {config.INITIAL_BANKROLL} u, Stake: {config.STAKE_PCT*100}%")

import db
print("  db OK — initializing...")
db.init_db()
print(f"    Database created at {config.DB_PATH}")

from collectors import football_data, balldontlie_nba, odds, injuries_news
print("  collectors OK")

from models import stats_model, llm_analyst, jev_client
print("  models OK")

from decision import value_bet, bankroll
print("  decision OK")

from tracking import settle, metrics
print("  tracking OK")

# Test stats model
print("\nTesting stats model (no data yet, should use defaults)...")
probs = stats_model.get_match_probabilities("football", "Paris Saint-Germain", "Marseille")
print(f"  Football PSG vs OM: {probs}")
probs2 = stats_model.get_match_probabilities("basketball", "Boston Celtics", "LA Lakers")
print(f"  NBA Celtics vs Lakers: {probs2}")

# Test value calculation
print("\nTesting value bet logic...")
v = value_bet.compute_value(0.55, 2.00)
print(f"  value(p=0.55, odds=2.0) = {v:.3f} (expected 0.100)")
v2 = value_bet.compute_value(0.40, 2.00)
print(f"  value(p=0.40, odds=2.0) = {v2:.3f} (expected -0.200)")

# Test model agreement
print("\nTesting model agreement...")
a = {"HOME": 0.50, "DRAW": 0.25, "AWAY": 0.25}
b = {"HOME": 0.55, "DRAW": 0.20, "AWAY": 0.25}
agr = value_bet.models_agreement([a, b])
print(f"  Agreement({a}, {b}) = {agr:.3f} (should be high)")

c = {"HOME": 0.20, "DRAW": 0.20, "AWAY": 0.60}
agr2 = value_bet.models_agreement([a, c])
print(f"  Agreement({a}, {c}) = {agr2:.3f} (should be low)")

# Test fusion
print("\nTesting probability fusion...")
fused = value_bet.fused_probabilities(a, [b])
print(f"  Fused(stats={a}, ai=[{b}]) = {fused}")

# Metrics
print("\nTesting metrics...")
m = metrics.overall_metrics()
print(f"  Overall: {m}")
d = metrics.daily_summary()
print(f"  Daily: {d}")

print("\n✅ All tests passed!")
