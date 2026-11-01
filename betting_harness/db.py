"""SQLite database schema and access functions for the Sports Betting Harness."""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import config


def get_conn() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        -- API response cache
        CREATE TABLE IF NOT EXISTS api_cache (
            cache_key   TEXT PRIMARY KEY,
            endpoint    TEXT NOT NULL,
            response    TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        -- Matches (fixtures + results)
        CREATE TABLE IF NOT EXISTS matches (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sport        TEXT NOT NULL,
            league       TEXT NOT NULL,
            match_date   TEXT NOT NULL,
            home_team    TEXT NOT NULL,
            away_team    TEXT NOT NULL,
            home_score   INTEGER,
            away_score   INTEGER,
            status       TEXT DEFAULT 'SCHEDULED',  -- SCHEDULED, FINISHED
            source       TEXT,                       -- API source
            source_id    TEXT,                       -- external ID
            created_at   TEXT DEFAULT (datetime('now')),
            updated_at   TEXT DEFAULT (datetime('now')),
            UNIQUE(sport, league, match_date, home_team, away_team)
        );

        -- Odds snapshots (immutable, timestamped)
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id     INTEGER NOT NULL REFERENCES matches(id),
            bookmaker    TEXT NOT NULL,
            market       TEXT NOT NULL,   -- h2h, spreads, totals, etc.
            outcome      TEXT NOT NULL,   -- HOME, DRAW, AWAY
            odds         REAL NOT NULL,
            captured_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_odds_match ON odds_snapshots(match_id, market, captured_at);

        -- Team statistics history
        CREATE TABLE IF NOT EXISTS team_stats (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sport        TEXT NOT NULL,
            team         TEXT NOT NULL,
            stat_date    TEXT NOT NULL,
            played       INTEGER DEFAULT 0,
            won          INTEGER DEFAULT 0,
            drawn        INTEGER DEFAULT 0,
            lost         INTEGER DEFAULT 0,
            goals_for    INTEGER DEFAULT 0,
            goals_against INTEGER DEFAULT 0,
            points       INTEGER DEFAULT 0,
            elo_rating   REAL,
            form         TEXT,            -- e.g. "WWDLW"
            extra        TEXT,            -- JSON blob for sport-specific stats
            UNIQUE(sport, team, stat_date)
        );

        -- AI + stats predictions
        CREATE TABLE IF NOT EXISTS predictions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id     INTEGER NOT NULL REFERENCES matches(id),
            source       TEXT NOT NULL,   -- 'stats', 'deepseek', 'gemini', 'jev', 'fused'
            market       TEXT NOT NULL,
            outcome      TEXT NOT NULL,
            probability  REAL NOT NULL,
            confidence   REAL,
            reasoning    TEXT,
            raw_response TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pred_match ON predictions(match_id, source, market);

        -- Virtual bets (immutable once placed)
        CREATE TABLE IF NOT EXISTS virtual_bets (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id       INTEGER NOT NULL REFERENCES matches(id),
            sport          TEXT NOT NULL,
            market         TEXT NOT NULL,
            outcome        TEXT NOT NULL,
            odds_taken     REAL NOT NULL,
            stake          REAL NOT NULL,
            estimated_prob REAL NOT NULL,
            value          REAL NOT NULL,
            bankroll_before REAL NOT NULL,
            placed_at      TEXT NOT NULL,
            status         TEXT DEFAULT 'PENDING',  -- PENDING, WON, LOST, VOID
            settled_at     TEXT,
            profit         REAL
        );
        CREATE INDEX IF NOT EXISTS idx_bets_status ON virtual_bets(status);

        -- Market odds at close (for CLV)
        CREATE TABLE IF NOT EXISTS closing_odds (
            match_id     INTEGER NOT NULL REFERENCES matches(id),
            market       TEXT NOT NULL,
            outcome      TEXT NOT NULL,
            odds         REAL NOT NULL,
            captured_at  TEXT NOT NULL,
            PRIMARY KEY (match_id, market, outcome)
        );
    """)

    conn.commit()
    conn.close()


# ── API Cache ─────────────────────────────────────────────────────

def cache_get(endpoint: str, key: str, max_age_hours: float) -> Optional[dict]:
    """Return cached API response if fresh enough, else None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT response, created_at FROM api_cache WHERE cache_key=? AND endpoint=?",
        (key, endpoint),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    created = datetime.fromisoformat(row["created_at"])
    if datetime.now() - created > timedelta(hours=max_age_hours):
        return None
    return json.loads(row["response"])


def cache_set(endpoint: str, key: str, response: dict) -> None:
    """Store an API response in cache."""
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO api_cache (cache_key, endpoint, response, created_at) VALUES (?,?,?,?)",
        (key, endpoint, json.dumps(response), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


# ── Matches ───────────────────────────────────────────────────────

def upsert_match(
    sport: str, league: str, match_date: str,
    home_team: str, away_team: str,
    home_score: int = None, away_score: int = None,
    status: str = "SCHEDULED", source: str = None, source_id: str = None,
) -> int:
    """Insert or update a match, return match id."""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO matches (sport, league, match_date, home_team, away_team,
                                home_score, away_score, status, source, source_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(sport, league, match_date, home_team, away_team)
           DO UPDATE SET home_score=excluded.home_score, away_score=excluded.away_score,
                         status=excluded.status, updated_at=datetime('now')""",
        (sport, league, match_date, home_team, away_team,
         home_score, away_score, status, source, source_id),
    )
    if cur.lastrowid:
        match_id = cur.lastrowid
    else:
        row = conn.execute(
            "SELECT id FROM matches WHERE sport=? AND league=? AND match_date=? AND home_team=? AND away_team=?",
            (sport, league, match_date, home_team, away_team),
        ).fetchone()
        match_id = row["id"]
    conn.commit()
    conn.close()
    return match_id


def get_upcoming_matches(hours_ahead: int = 48) -> list[dict]:
    """Return matches in the next N hours that haven't been settled."""
    conn = get_conn()
    now = datetime.now().isoformat()
    horizon = (datetime.now() + timedelta(hours=hours_ahead)).isoformat()
    rows = conn.execute(
        "SELECT * FROM matches WHERE match_date>=? AND match_date<=? AND status='SCHEDULED' ORDER BY match_date",
        (now, horizon),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unsettled_matches() -> list[dict]:
    """Return SCHEDULED matches (for settlement)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM matches WHERE status='SCHEDULED' ORDER BY match_date"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_match_result(match_id: int, home_score: int, away_score: int) -> None:
    """Update match with final score."""
    conn = get_conn()
    conn.execute(
        "UPDATE matches SET home_score=?, away_score=?, status='FINISHED', updated_at=datetime('now') WHERE id=?",
        (home_score, away_score, match_id),
    )
    conn.commit()
    conn.close()


# ── Odds ──────────────────────────────────────────────────────────

def save_odds(match_id: int, bookmaker: str, market: str,
              outcome: str, odds: float, captured_at: str = None) -> None:
    """Store an odds snapshot."""
    if captured_at is None:
        captured_at = datetime.now().isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO odds_snapshots (match_id, bookmaker, market, outcome, odds, captured_at) VALUES (?,?,?,?,?,?)",
        (match_id, bookmaker, market, outcome, odds, captured_at),
    )
    conn.commit()
    conn.close()


def get_latest_odds(match_id: int, market: str = "h2h") -> list[dict]:
    """Return latest average odds per outcome for a match+market."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT outcome, AVG(odds) as avg_odds, COUNT(DISTINCT bookmaker) as n_bookmakers,
                  MAX(captured_at) as last_captured
           FROM odds_snapshots
           WHERE match_id=? AND market=?
           GROUP BY outcome""",
        (match_id, market),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_closing_odds(match_id: int, market: str, outcome: str, odds: float) -> None:
    """Store closing odds for CLV calculation."""
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO closing_odds (match_id, market, outcome, odds, captured_at)
           VALUES (?,?,?,?,?)""",
        (match_id, market, outcome, odds, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


# ── Team Stats ────────────────────────────────────────────────────

def save_team_stats(sport: str, team: str, stat_date: str,
                    **kwargs) -> None:
    """Upsert team statistics."""
    extra = kwargs.pop("extra", None)
    cols = ["sport", "team", "stat_date"]
    vals = [sport, team, stat_date]
    for k, v in kwargs.items():
        cols.append(k)
        vals.append(v)
    if extra is not None:
        cols.append("extra")
        vals.append(json.dumps(extra))
    placeholders = ",".join("?" * len(cols))
    col_names = ",".join(cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in ("sport", "team", "stat_date"))
    conn = get_conn()
    conn.execute(
        f"INSERT INTO team_stats ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT(sport, team, stat_date) DO UPDATE SET {updates}",
        vals,
    )
    conn.commit()
    conn.close()


def get_team_stats(sport: str, team: str, limit: int = 10) -> list[dict]:
    """Return recent stats for a team."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM team_stats WHERE sport=? AND team=? ORDER BY stat_date DESC LIMIT ?",
        (sport, team, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_team_stats(sport: str, team: str) -> Optional[dict]:
    """Return most recent stats for a team."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM team_stats WHERE sport=? AND team=? ORDER BY stat_date DESC LIMIT 1",
        (sport, team),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Predictions ───────────────────────────────────────────────────

def save_prediction(match_id: int, source: str, market: str, outcome: str,
                    probability: float, confidence: float = None,
                    reasoning: str = None, raw_response: str = None) -> None:
    """Store a prediction."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO predictions (match_id, source, market, outcome, probability, confidence, reasoning, raw_response)
           VALUES (?,?,?,?,?,?,?,?)""",
        (match_id, source, market, outcome, probability, confidence, reasoning, raw_response),
    )
    conn.commit()
    conn.close()


def get_predictions(match_id: int, source: str = None) -> list[dict]:
    """Return predictions for a match, optionally filtered by source."""
    conn = get_conn()
    if source:
        rows = conn.execute(
            "SELECT * FROM predictions WHERE match_id=? AND source=? ORDER BY created_at DESC",
            (match_id, source),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM predictions WHERE match_id=? ORDER BY created_at DESC",
            (match_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Virtual Bets ──────────────────────────────────────────────────

def place_virtual_bet(match_id: int, sport: str, market: str, outcome: str,
                      odds_taken: float, stake: float, estimated_prob: float,
                      value: float, bankroll_before: float) -> int:
    """Record a virtual bet (immutable). Returns bet id."""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO virtual_bets (match_id, sport, market, outcome, odds_taken, stake,
                                    estimated_prob, value, bankroll_before, placed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (match_id, sport, market, outcome, odds_taken, stake,
         estimated_prob, value, bankroll_before, datetime.now().isoformat()),
    )
    bet_id = cur.lastrowid
    conn.commit()
    conn.close()
    return bet_id


def get_pending_bets() -> list[dict]:
    """Return bets awaiting settlement."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM virtual_bets WHERE status='PENDING' ORDER BY placed_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def settle_bet(bet_id: int, won: bool, profit: float) -> None:
    """Settle a virtual bet."""
    conn = get_conn()
    conn.execute(
        "UPDATE virtual_bets SET status=?, settled_at=?, profit=? WHERE id=?",
        ("WON" if won else "LOST", datetime.now().isoformat(), profit, bet_id),
    )
    conn.commit()
    conn.close()


def get_all_bets(status: str = None) -> list[dict]:
    """Return all bets, optionally filtered by status."""
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM virtual_bets WHERE status=? ORDER BY placed_at", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM virtual_bets ORDER BY placed_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bets_count_today() -> int:
    """Return number of bets placed today."""
    conn = get_conn()
    today = datetime.now().strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM virtual_bets WHERE placed_at LIKE ?",
        (today + "%",),
    ).fetchone()
    conn.close()
    return row["cnt"]


# ── Initialize ────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {config.DB_PATH}")
