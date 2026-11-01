"""Streamlit interface for the Sports Betting Harness.

Pages:
1. Paris du jour — today's bets with model probabilities, odds, value, AI reasoning
2. Historique — virtual bet history + bankroll curve
3. Comparaison des modèles — Brier, ROI, CLV by model
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

import config
import db

# Page config
st.set_page_config(
    page_title="Betting Harness IA",
    page_icon="🎰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Init DB
db.init_db()

# ── Sidebar ───────────────────────────────────────────────────────
st.sidebar.title("🎰 Betting Harness")
st.sidebar.markdown("---")

nav = st.sidebar.radio(
    "Navigation",
    ["📋 Paris du jour", "📈 Historique", "🔬 Comparaison modèles"],
    index=0,
)

st.sidebar.markdown("---")
from tracking.metrics import overall_metrics
metrics = overall_metrics()
st.sidebar.metric("💰 Bankroll", f"{metrics['bankroll']:.0f} u",
                  delta=f"{metrics['bankroll'] - metrics.get('initial_bankroll', config.INITIAL_BANKROLL):+.1f}")
st.sidebar.metric("📊 ROI", f"{metrics['roi']:.2%}")
st.sidebar.metric("🎯 Win Rate", f"{metrics['win_rate']:.1%}")
st.sidebar.metric("📝 Paris", f"{metrics['total_bets']}")

st.sidebar.markdown("---")
st.sidebar.caption(f"Phase de test: 2 semaines\nDémarrage: début du tracking")


# ── Page 1: Paris du jour ─────────────────────────────────────────
if nav == "📋 Paris du jour":
    st.title("📋 Paris du jour")

    daily = db.get_bets_count_today()
    st.info(f"Paris placés aujourd'hui : {daily} / {config.MAX_BETS_PER_DAY}")

    # Upcoming matches with analysis
    upcoming = db.get_upcoming_matches(hours_ahead=48)

    if not upcoming:
        st.warning("Aucun match à venir dans les 48 prochaines heures.")
    else:
        for match in upcoming:
            match_id = match["id"]

            # Get predictions
            all_preds = db.get_predictions(match_id)
            if not all_preds:
                continue

            # Get odds
            odds_list = db.get_latest_odds(match_id, "h2h")

            # Get pending bet if exists
            conn = db.get_conn()
            bet = conn.execute(
                "SELECT * FROM virtual_bets WHERE match_id=? AND status='PENDING'",
                (match_id,),
            ).fetchone()
            conn.close()

            # Format header
            sport_emoji = "⚽" if match["sport"] == "football" else "🏀"
            is_pinned = bet is not None
            header = f"{sport_emoji} {match['home_team']} vs {match['away_team']}"
            if is_pinned:
                header += " 🎯"

            with st.expander(header, expanded=is_pinned):
                col1, col2, col3 = st.columns([2, 1, 1])

                with col1:
                    st.caption(f"{match['league']} · {match['match_date'][:16]}")

                    # Model probabilities table
                    sources = {}
                    for p in all_preds:
                        src = p["source"]
                        if src not in sources:
                            sources[src] = {}
                        sources[src][p["outcome"]] = p["probability"]

                    if sources:
                        df = pd.DataFrame(sources).T
                        st.dataframe(df, use_container_width=True)

                with col2:
                    if odds_list:
                        st.markdown("**Cotes (moy. marché)**")
                        for o in odds_list:
                            st.write(f"{o['outcome']}: **{o['avg_odds']:.2f}** ({o['n_bookmakers']} bk)")

                with col3:
                    if bet:
                        st.markdown("**🎯 Pari virtuel**")
                        st.write(f"Outcome: **{bet['outcome']}**")
                        st.write(f"Cote: **{bet['odds_taken']:.2f}**")
                        st.write(f"Mise: **{bet['stake']:.1f} u**")
                        st.write(f"Value: **{bet['value']:.1%}**")
                        st.write(f"Proba: **{bet['estimated_prob']:.1%}**")

                    # Show AI reasoning
                    ai_preds = [p for p in all_preds if p["source"] in ("deepseek", "gemini", "jev") and p.get("reasoning")]
                    if ai_preds:
                        with st.popover("🧠 Raisonnement IA"):
                            for p in ai_preds[:3]:
                                st.caption(f"**{p['source']}** ({p['outcome']}: {p['probability']:.1%})")
                                st.write(p["reasoning"])


# ── Page 2: Historique ───────────────────────────────────────────
elif nav == "📈 Historique":
    st.title("📈 Historique des paris virtuels")

    bets = db.get_all_bets()

    if not bets:
        st.warning("Aucun pari enregistré pour l'instant.")
    else:
        # Bankroll curve
        st.subheader("Courbe de bankroll")
        from decision.bankroll import bankroll_history
        history = bankroll_history()

        if len(history) > 1:
            df_hist = pd.DataFrame(history)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=list(range(len(df_hist))),
                y=df_hist["bankroll"],
                mode="lines+markers",
                name="Bankroll",
                line=dict(color="#4CAF50", width=2),
            ))
            fig.add_hline(y=config.INITIAL_BANKROLL, line_dash="dash",
                          annotation_text="Départ")
            fig.update_layout(
                height=400,
                xaxis_title="Paris",
                yaxis_title="Unités",
                template="plotly_white",
            )
            st.plotly_chart(fig, use_container_width=True)

        # Bets table
        st.subheader("Tous les paris")
        df = pd.DataFrame(bets)
        display_cols = ["id", "sport", "outcome", "odds_taken", "stake",
                        "estimated_prob", "value", "status", "profit", "placed_at"]
        df_display = df[[c for c in display_cols if c in df.columns]].copy()
        df_display.columns = ["ID", "Sport", "Outcome", "Cote", "Mise",
                              "Proba", "Value", "Statut", "Profit", "Date"]
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Summary stats
        col1, col2, col3, col4 = st.columns(4)
        settled = [b for b in bets if b["status"] in ("WON", "LOST")]
        wins = [b for b in settled if b["status"] == "WON"]
        col1.metric("Total paris", len(bets))
        col2.metric("Résolus", len(settled))
        col3.metric("Gagnés", len(wins))
        col4.metric("Profit total", f"{sum(b['profit'] or 0 for b in settled):+.1f} u")


# ── Page 3: Comparaison des modèles ──────────────────────────────
elif nav == "🔬 Comparaison modèles":
    st.title("🔬 Comparaison des modèles")

    from tracking.metrics import model_comparison, clv_metrics, overall_metrics

    # Model comparison (Brier)
    st.subheader("Score de Brier par modèle")
    st.caption("Plus bas = mieux calibré. ~0.33 = aléatoire (3 classes), ~0.25 (2 classes).")
    comparison = model_comparison()

    if comparison:
        df_comp = pd.DataFrame(comparison).T
        df_comp.columns = ["Brier moyen", "Matchs évalués"]
        st.dataframe(df_comp, use_container_width=True)

        # Bar chart
        fig = go.Figure()
        valid = {k: v["avg_brier"] for k, v in comparison.items() if v["avg_brier"] is not None}
        if valid:
            fig.add_trace(go.Bar(
                x=list(valid.keys()),
                y=list(valid.values()),
                marker_color=["#4CAF50" if "stats" in k else "#2196F3" if "deep" in k else "#FF9800" if "gem" in k else "#9C27B0" for k in valid.keys()],
            ))
            fig.update_layout(height=350, yaxis_title="Brier Score", template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Pas encore assez de données pour comparer les modèles.")

    # CLV
    st.subheader("Closing Line Value (CLV)")
    st.caption("Compare la cote prise à la cote de clôture. Indicateur le plus fiable sur petit échantillon.")
    clv = clv_metrics()
    if clv["n_with_clv"] > 0:
        col1, col2, col3 = st.columns(3)
        col1.metric("CLV moyen", f"{clv['clv_avg']:+.3f}")
        col2.metric("CLV positif", f"{clv['clv_positive_pct']:.1%}")
        col3.metric("Paris avec CLV", clv["n_with_clv"])
    else:
        st.info("Pas encore de données CLV (nécessite des cotes de clôture).")

    # Overall
    st.subheader("Performance globale")
    metrics = overall_metrics()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ROI", f"{metrics['roi']:.2%}")
    col2.metric("Profit", f"{metrics['profit']:+.1f} u")
    col3.metric("Win Rate", f"{metrics['win_rate']:.1%}")
    col4.metric("Bankroll", f"{metrics['bankroll']:.0f} u")

    if metrics["settled"] < 100:
        st.warning(f"⚠️ Échantillon petit ({metrics['settled']} paris résolus). "
                   f"Ne pas tirer de conclusion définitive sous 100 paris.")


# ── Export CSV ────────────────────────────────────────────────────
st.sidebar.markdown("---")
if st.sidebar.button("📥 Export CSV"):
    bets = db.get_all_bets()
    if bets:
        df = pd.DataFrame(bets)
        csv = df.to_csv(index=False)
        st.sidebar.download_button(
            label="Télécharger les paris",
            data=csv,
            file_name=f"virtual_bets_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
    else:
        st.sidebar.info("Aucun pari à exporter")
