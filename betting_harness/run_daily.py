"""Daily pipeline orchestrator.

Runs the full chain each day:
1. Collect matches, odds, stats
2. Run statistical model
3. Run AI analysis (DeepSeek + Gemini, optional Jev)
4. Fuse probabilities
5. Find value bets and record virtual bets
6. Settle yesterday's bets
"""

import sys
from datetime import datetime

import config
import db


def run_daily():
    """Execute the full daily pipeline."""
    print(f"\n{'='*60}")
    print(f"  Daily Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # Init DB
    db.init_db()

    # ── Step 0: Settle previous bets ──────────────────────────
    print("[0] Settling pending bets...")
    from tracking.settle import settle_pending_bets
    settled = settle_pending_bets()
    print(f"    Settled {settled} bets")

    # Record closing odds for upcoming matches (for CLV)
    from tracking.settle import record_closing_odds
    n_closing = record_closing_odds()
    print(f"    Recorded {n_closing} closing odds entries")

    # ── Step 1: Collect data ──────────────────────────────────
    print("\n[1] Collecting data...")

    # Football (Ligue 1)
    from collectors.football_data import store_upcoming as fd_store_upcoming
    from collectors.football_data import store_results as fd_store_results

    for league_code in config.LEAGUES["football"]:
        ids = fd_store_upcoming(league_code)
        print(f"    Football {league_code}: {len(ids)} upcoming matches")
        n = fd_store_results(league_code, days_back=7)
        print(f"    Football {league_code}: {n} results stored")

    # NBA
    from collectors.balldontlie_nba import store_upcoming as nba_store_upcoming
    from collectors.balldontlie_nba import store_results as nba_store_results

    ids = nba_store_upcoming()
    print(f"    NBA: {len(ids)} upcoming games")
    n = nba_store_results(days_back=7)
    print(f"    NBA: {n} results stored")

    # Odds
    from collectors.odds import store_odds
    for league_code in config.LEAGUES["football"]:
        n = store_odds(league_code)
        print(f"    Odds {league_code}: {n} snapshots")
    n = store_odds("NBA")
    print(f"    Odds NBA: {n} snapshots")

    # ── Step 2: Get upcoming matches to analyze ───────────────
    print("\n[2] Analyzing upcoming matches...")
    upcoming = db.get_upcoming_matches(hours_ahead=48)
    print(f"    {len(upcoming)} matches in next 48h")

    if not upcoming:
        print("    No matches to analyze. Done.")
        return

    # ── Steps 3-5: Model → AI → Fuse → Decide ────────────────
    from models.stats_model import get_match_probabilities
    from models.llm_analyst import analyze_match
    from models.jev_client import analyze_match_jev, is_available
    from decision.value_bet import fused_probabilities, find_value_bets, select_and_record_bets

    all_candidates = []

    for match in upcoming:
        print(f"\n  Match: {match['home_team']} vs {match['away_team']} ({match['league']})")
        match_id = match["id"]
        sport = match["sport"]

        # Stats model
        stats_probs = get_match_probabilities(sport, match["home_team"], match["away_team"])
        print(f"    Stats model: {stats_probs}")

        # Save stats prediction
        for outcome, prob in stats_probs.items():
            db.save_prediction(match_id, "stats", "h2h", outcome, prob)

        # Get team stats for context
        from db import get_latest_team_stats
        home_stats = get_latest_team_stats(sport, match["home_team"])
        away_stats = get_latest_team_stats(sport, match["away_team"])

        # Get odds
        from collectors.odds import get_average_odds
        odds_list = get_average_odds(match_id, "h2h")

        # AI analysis via FreeLLMAPI (multiple models)
        ai_results = analyze_match(match, stats_probs, home_stats, away_stats, odds_list)
        for source, probs in ai_results.items():
            print(f"    {source}: {probs}")
            for outcome, prob in probs.items():
                db.save_prediction(match_id, source, "h2h", outcome, prob,
                                   reasoning=f"AI analysis via {source} (FreeLLMAPI)")

        # Jev (optional)
        jev_probs = None
        if is_available():
            jev_probs = analyze_match_jev(match, stats_probs)
            if jev_probs:
                print(f"    jev: {jev_probs}")
                for outcome, prob in jev_probs.items():
                    db.save_prediction(match_id, "jev", "h2h", outcome, prob)

        # Build list of all probability sources for agreement check
        all_probs_list = [stats_probs] + list(ai_results.values())
        if jev_probs:
            all_probs_list.append(jev_probs)

        # Fuse
        ai_only = list(ai_results.values())
        if jev_probs:
            ai_only.append(jev_probs)

        if ai_only:
            final_probs = fused_probabilities(stats_probs, ai_only)
        else:
            final_probs = stats_probs

        print(f"    Fused: {final_probs}")
        # Save fused prediction
        for outcome, prob in final_probs.items():
            db.save_prediction(match_id, "fused", "h2h", outcome, prob)

        # Find value bets
        candidates = find_value_bets(match_id, sport, final_probs, odds_list, all_probs_list)
        if candidates:
            for c in candidates:
                print(f"    VALUE: {c['outcome']} @ {c['odds']:.2f} "
                      f"(p={c['probability']:.1%}, value={c['value']:.1%})")
            all_candidates.extend(candidates)
        else:
            print(f"    No value bets")

    # ── Step 6: Record virtual bets ───────────────────────────
    print(f"\n[6] Recording virtual bets...")
    if all_candidates:
        recorded = select_and_record_bets(all_candidates)
        print(f"    Recorded {len(recorded)} virtual bets")
        for r in recorded:
            print(f"      Bet #{r['bet_id']}: {r['outcome']} @ {r['odds']:.2f} "
                  f"stake={r['stake']} value={r['value']:.1%}")
    else:
        print("    No bets to record")

    # ── Step 7: Summary ───────────────────────────────────────
    print(f"\n{'='*60}")
    from tracking.metrics import overall_metrics, daily_summary
    metrics = overall_metrics()
    daily = daily_summary()
    print(f"  Bankroll: {metrics['bankroll']} / {metrics['initial_bankroll']}")
    print(f"  Total bets: {metrics['total_bets']} (settled: {metrics['settled']}, "
          f"pending: {metrics['pending']})")
    print(f"  ROI: {metrics['roi']:.2%}")
    print(f"  Win rate: {metrics['win_rate']:.2%}")
    print(f"  Today: {daily['bets_placed']} bets, profit {daily['profit_today']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run_daily()
