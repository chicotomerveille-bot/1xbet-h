"""Optional: collect injuries and news context.

This module is a stub. At launch, injuries/news collection is optional.
Fill in with a news API (e.g. NewsAPI.org, GNews) or scraping when ready.
"""

from datetime import datetime


def fetch_injuries(team: str) -> list[dict]:
    """Fetch known injuries for a team. Returns list of {player, position, status, source}.

    TODO: integrate with a news API or sports data provider that covers injuries.
    football-data.org free tier does not include injuries.
    """
    # Placeholder — returns empty list until wired up
    return []


def fetch_news(team: str) -> list[dict]:
    """Fetch recent news headlines for a team. Returns list of {title, source, url, published}.

    TODO: integrate with NewsAPI.org or similar.
    """
    return []


def build_context_summary(team: str) -> str:
    """Build a text summary of injuries + news for a team (for LLM context)."""
    injuries = fetch_injuries(team)
    news = fetch_news(team)
    parts = []
    if injuries:
        inj_lines = [f"- {i['player']} ({i.get('position', '?')}): {i['status']}" for i in injuries]
        parts.append("Injuries:\n" + "\n".join(inj_lines))
    if news:
        news_lines = [f"- {n['title']}" for n in news[:5]]
        parts.append("Recent news:\n" + "\n".join(news_lines))
    return "\n\n".join(parts) if parts else "No injury or news data available."
