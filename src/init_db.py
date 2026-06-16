import sqlite3
import logging
import sys
import os
import re
from typing import Optional
from contextlib import closing

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'worldcup2026.db')


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    """Check whether a column already exists in the given table."""
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _safe_add_column(cursor: sqlite3.Cursor, table: str, column: str, type_def: str) -> None:
    """Idempotent ALTER TABLE ADD COLUMN — silently skips if column already present."""
    if _column_exists(cursor, table, column):
        logger.debug("Column %s.%s already present, skipping ADD COLUMN.", table, column)
        return
    logger.info("Migrating schema: adding %s.%s %s", table, column, type_def)
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_def}")


def create_connection(db_file: str) -> Optional[sqlite3.Connection]:
    try:
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except sqlite3.Error as e:
        logger.error("Failed to connect to database %s: %s", db_file, e)
        return None


def init_db() -> bool:
    """
    Idempotent schema initialisation.

    CREATE TABLE IF NOT EXISTS handles fresh installs.
    Follow-up ALTER TABLE blocks safely migrate databases created by older
    versions of this script that did not include every column.
    """
    conn = create_connection(DB_PATH)
    if not conn:
        return False

    try:
        with closing(conn):
            with closing(conn.cursor()) as cursor:
                # ── Teams ──────────────────────────────────────────────────
                logger.info("Initializing Teams table...")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS Teams (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        name_zh TEXT,
                        group_name TEXT,
                        flag_url TEXT,
                        description TEXT,
                        history_stats TEXT,
                        coach TEXT
                    )
                ''')
                _safe_add_column(cursor, "Teams", "history_stats", "TEXT")
                _safe_add_column(cursor, "Teams", "coach", "TEXT")

                # ── Players ────────────────────────────────────────────────
                logger.info("Initializing Players table...")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS Players (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        team_id INTEGER NOT NULL,
                        name_en TEXT NOT NULL,
                        name_zh TEXT NOT NULL,
                        position TEXT,
                        jersey_number INTEGER,
                        profile_url TEXT,
                        history_stats TEXT,
                        description TEXT,
                        tournament_goals INTEGER DEFAULT 0,
                        tournament_assists INTEGER DEFAULT 0,
                        FOREIGN KEY(team_id) REFERENCES Teams(id) ON DELETE CASCADE,
                        UNIQUE(team_id, name_en)
                    )
                ''')
                _safe_add_column(cursor, "Players", "description", "TEXT")
                _safe_add_column(cursor, "Players", "tournament_goals", "INTEGER DEFAULT 0")
                _safe_add_column(cursor, "Players", "tournament_assists", "INTEGER DEFAULT 0")

                # ── Matches ────────────────────────────────────────────────
                logger.info("Initializing Matches table...")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS Matches (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        home_team_id INTEGER NOT NULL,
                        away_team_id INTEGER NOT NULL,
                        match_time_utc TEXT NOT NULL,
                        status TEXT DEFAULT 'upcoming',
                        home_score INTEGER DEFAULT 0,
                        away_score INTEGER DEFAULT 0,
                        stadium TEXT,
                        group_stage TEXT,
                        dongqiudi_url TEXT,
                        FOREIGN KEY(home_team_id) REFERENCES Teams(id) ON DELETE RESTRICT,
                        FOREIGN KEY(away_team_id) REFERENCES Teams(id) ON DELETE RESTRICT
                    )
                ''')
                _safe_add_column(cursor, "Matches", "dongqiudi_url", "TEXT")

                # ── Broadcasts ─────────────────────────────────────────────
                logger.info("Initializing Broadcasts table...")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS Broadcasts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        match_id INTEGER NOT NULL,
                        platform_name TEXT NOT NULL,
                        stream_url TEXT NOT NULL,
                        icon_url TEXT,
                        dongqiudi_url TEXT,
                        FOREIGN KEY(match_id) REFERENCES Matches(id) ON DELETE CASCADE
                    )
                ''')
                _safe_add_column(cursor, "Broadcasts", "dongqiudi_url", "TEXT")

                # ── MatchLineups ───────────────────────────────────────────
                logger.info("Initializing MatchLineups table...")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS MatchLineups (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        match_id INTEGER NOT NULL,
                        player_id INTEGER NOT NULL,
                        is_starter BOOLEAN DEFAULT 1,
                        FOREIGN KEY(match_id) REFERENCES Matches(id) ON DELETE CASCADE,
                        FOREIGN KEY(player_id) REFERENCES Players(id) ON DELETE CASCADE,
                        UNIQUE(match_id, player_id)
                    )
                ''')

                # ── Settings ────────────────────────────────────────────────
                logger.info("Initializing Settings table...")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS Settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    INSERT OR IGNORE INTO Settings (key, value) VALUES ('refresh_interval', '5')
                ''')

            conn.commit()
            logger.info("Database schema verified/initialized successfully at '%s'.", DB_PATH)
            return True

    except sqlite3.Error as e:
        logger.error("Database initialization failed due to SQLite Error: %s", e)
        return False
    except Exception as e:
        logger.error("Unexpected error during database initialization: %s", e)
        return False


if __name__ == '__main__':
    success = init_db()
    if not success:
        sys.exit(1)
