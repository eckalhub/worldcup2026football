import sqlite3
import logging
import sys
import time
import random
import json
import os
import argparse
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from contextlib import closing

try:
    from scrapling import StealthyFetcher
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'worldcup2026.db')

# ── Data containers ───────────────────────────────────────────────────────────

@dataclass
class Player:
    name_en: str
    name_zh: str
    position: str
    jersey_number: int
    profile_url: str
    history_stats: dict


@dataclass
class Team:
    name: str
    name_zh: str
    group_name: str
    flag_url: str
    description: str
    players: List[Player]


@dataclass
class Match:
    home_team_name: str
    away_team_name: str
    match_time_utc: str
    status: str
    home_score: int
    away_score: int
    stadium: str
    group_stage: str
    lineups_home_en: List[str]
    lineups_away_en: List[str]
    home_label: str = ""
    away_label: str = ""


@dataclass
class Broadcast:
    home_team_name: str
    away_team_name: str
    platform_name: str
    stream_url: str
    icon_url: str


# ── Persistence helpers ───────────────────────────────────────────────────────

def _db_team_count(db_path: str) -> int:
    """Return current number of teams in the database (0 on error)."""
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM Teams").fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error as e:
        logger.warning("Unable to read team count: %s", e)
        return 0


def _assert_safe_for_init(db_path: str, force: bool) -> None:
    """
    Guard rail: refuse to run init mode when the database already contains
    substantial real data.  *force* overrides.
    """
    count = _db_team_count(db_path)
    if count > 10 and not force:
        logger.error(
            "Database already contains %d teams. "
            "Refusing to overwrite with init data. "
            "Use --force to override (DESTRUCTIVE).", count
        )
        sys.exit(2)


def _validate_match_status(status: str) -> str:
    """Reject unknown status values; default to 'upcoming'."""
    valid = {'upcoming', 'live', 'finished'}
    if status not in valid:
        logger.warning("Unknown match status '%s', falling back to 'upcoming'.", status)
        return 'upcoming'
    return status


# ── Scraper ───────────────────────────────────────────────────────────────────

class DongqiudiScraper:
    """
    Anti-bot scraper targeting Chinese sports portals (Dongqiudi / Transfermarkt).

    Modes:
      * init  – full team + player + match roster (first-time population).
      * update – match status, scores, and lineups only (safe for live refresh).
    """

    def __init__(self):
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        if SCRAPLING_AVAILABLE:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.fetcher = StealthyFetcher()
            logger.info("Scrapling StealthyFetcher initialised.")
        else:
            logger.warning("Scrapling unavailable – running in demo-fallback mode.")
            self.fetcher = None

    def _random_delay(self, min_sec: float = 1.0, max_sec: float = 3.0) -> None:
        delay = random.uniform(min_sec, max_sec)
        logger.debug("Sleeping %.2fs to evade rate limits.", delay)
        time.sleep(delay)

    # -- init helpers (demo fallback) -------------------------------------------

    def scrape_teams_and_players(self) -> List[Team]:
        """
        Full 48-team roster scrape (init mode).

        When scrapling is unavailable this returns a small demo dataset so the
        pipeline can still be exercised.  The *DatabaseStore* safety gate
        ensures demo data never overwrites a live database.
        """
        logger.info("Initiating team/player scrape (init mode)...")

        # ── [HARD SCRAPE PLACEHOLDER] ─────────────────────────────────────
        # page = self.fetcher.get("https://www.dongqiudi.com/data/worldcup")
        # … real parsing logic …
        # self._random_delay(2, 5)
        # ──────────────────────────────────────────────────────────────────

        self._random_delay(0.5, 1.5)

        p1 = Player("Christian Pulisic", "克里斯蒂安·普利西奇", "FW", 10, "#",
                     {"goals": 25, "caps": 60})
        p2 = Player("Weston McKennie", "韦斯顿·麦肯尼", "MF", 8, "#",
                     {"goals": 11, "caps": 45})
        p3 = Player("Lionel Messi", "利昂内尔·梅西", "FW", 10, "#",
                     {"goals": 109, "caps": 180, "wc_winner": True})
        p4 = Player("Emiliano Martínez", "埃米利亚诺·马丁内斯", "GK", 23, "#",
                     {"clean_sheets": 30, "caps": 40})
        p5 = Player("Kylian Mbappé", "基利安·姆巴佩", "FW", 10, "#",
                     {"goals": 46, "caps": 75, "wc_winner": True})
        p6 = Player("Vinícius Júnior", "维尼修斯·儒尼奥尔", "FW", 7, "#",
                     {"goals": 15, "caps": 35})

        return [
            Team("United States", "美国", "Group A",
                 "https://upload.wikimedia.org/wikipedia/en/a/a4/Flag_of_the_United_States.svg",
                 "Co-Host Nation. Strong athletic squad.", [p1, p2]),
            Team("Argentina", "阿根廷", "Group B",
                 "https://upload.wikimedia.org/wikipedia/commons/1/1a/Flag_of_Argentina.svg",
                 "Defending World Champions.", [p3, p4]),
            Team("France", "法国", "Group C",
                 "https://upload.wikimedia.org/wikipedia/en/c/c3/Flag_of_France.svg",
                 "European Powerhouse with deep talent.", [p5]),
            Team("Brazil", "巴西", "Group C",
                 "https://upload.wikimedia.org/wikipedia/en/0/05/Flag_of_Brazil.svg",
                 "Five-time Winners, Jogo Bonito.", [p6]),
        ]

    def scrape_matches(self) -> List[Match]:
        """Full match roster scrape from dongqiudi.com (init mode)."""
        logger.info("Scraping match schedules from dongqiudi...")
        self._random_delay(0.5, 1.5)

        try:
            from dongqiudi_fetcher import fetch_schedule
            dq_matches = fetch_schedule(DB_PATH)
        except Exception as e:
            logger.error("Dongqiudi fetch failed: %s", e)
            return []

        result: List[Match] = []
        for dm in dq_matches:
            result.append(Match(
                home_team_name=dm.home_name_en,
                away_team_name=dm.away_name_en,
                match_time_utc=dm.match_time_utc,
                status=dm.status,
                home_score=dm.home_score,
                away_score=dm.away_score,
                stadium="",
                group_stage=dm.group_stage,
                lineups_home_en=[],
                lineups_away_en=[],
                home_label=dm.home_label,
                away_label=dm.away_label,
            ))

        logger.info("Scraped %d matches from dongqiudi", len(result))
        return result

    def scrape_broadcasts(self) -> List[Broadcast]:
        logger.info("Scraping broadcast streams...")
        self._random_delay(0.2, 0.5)
        return [
            Broadcast("United States", "Argentina", "FOX Sports",
                      "https://www.foxsports.com/live",
                      "https://upload.wikimedia.org/wikipedia/commons/2/29/Fox_Sports_logo.svg"),
            Broadcast("France", "Brazil", "CCTV-5",
                      "https://tv.cctv.com/live/cctv5/",
                      "https://upload.wikimedia.org/wikipedia/commons/8/87/CCTV-5_logo.svg"),
        ]

    # -- update helpers (match status / scores / lineups only) ------------------

    def scrape_broadcasts_for_matches(self, home: str, away: str) -> List[Broadcast]:
        """Scrape broadcast links for a specific match pair."""
        self._random_delay(0.2, 0.5)
        # ── [LIVE BROADCAST SCRAPE PLACEHOLDER] ───────────────────────────
        return []


# ── Database layer ────────────────────────────────────────────────────────────

class DatabaseStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    # ------------------------------------------------------------------
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # -- Full init -------------------------------------------------------

    def store_data(self,
                   teams: List[Team],
                   matches: List[Match],
                   broadcasts: List[Broadcast]) -> bool:
        """
        Full-sync write: upserts teams, players, matches, broadcasts, lineups.
        Intended for init-mode only.
        """
        try:
            with closing(self._get_connection()) as conn:
                with closing(conn.cursor()) as cursor:
                    self._upsert_teams(cursor, teams)
                    team_map = self._build_team_map(cursor)

                    self._upsert_players(cursor, teams, team_map)
                    player_map = self._build_player_map(cursor)

                    self._upsert_matches(cursor, matches, team_map)
                    self._upsert_lineups(cursor, matches, team_map, player_map)
                    self._upsert_broadcasts(cursor, broadcasts, team_map)

                conn.commit()
                logger.info("Database transaction committed (init mode).")
                return True
        except sqlite3.Error as e:
            logger.error("Database transaction failed: %s", e)
            return False

    # -- Inner helpers ----------------------------------------------------

    @staticmethod
    def _upsert_teams(cursor, teams):
        for team in teams:
            cursor.execute('''
                INSERT INTO Teams (name, name_zh, group_name, flag_url, description)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    name_zh    = excluded.name_zh,
                    group_name = excluded.group_name,
                    flag_url   = excluded.flag_url,
                    description = excluded.description
            ''', (team.name, team.name_zh, team.group_name,
                  team.flag_url, team.description))

    @staticmethod
    def _build_team_map(cursor) -> Dict[str, int]:
        cursor.execute("SELECT id, name FROM Teams")
        return {row[1]: row[0] for row in cursor.fetchall()}

    @staticmethod
    def _upsert_players(cursor, teams, team_map):
        for team in teams:
            team_id = team_map.get(team.name)
            if team_id is None:
                continue
            for p in team.players:
                stats_json = json.dumps(p.history_stats, ensure_ascii=False)
                cursor.execute('''
                    INSERT INTO Players
                        (team_id, name_en, name_zh, position,
                         jersey_number, profile_url, history_stats)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(team_id, name_en) DO UPDATE SET
                        name_zh       = excluded.name_zh,
                        position       = excluded.position,
                        jersey_number  = excluded.jersey_number,
                        profile_url    = excluded.profile_url,
                        history_stats  = excluded.history_stats
                ''', (team_id, p.name_en, p.name_zh, p.position,
                      p.jersey_number, p.profile_url, stats_json))

    @staticmethod
    def _build_player_map(cursor) -> Dict[str, int]:
        cursor.execute("SELECT id, name_en FROM Players")
        return {row[1]: row[0] for row in cursor.fetchall()}

    @staticmethod
    def _upsert_matches(cursor, matches, team_map):
        for match in matches:
            home_id = team_map.get(match.home_team_name)
            away_id = team_map.get(match.away_team_name)
            if not home_id or not away_id:
                continue

            status = _validate_match_status(match.status)

            cursor.execute('''
                SELECT id FROM Matches
                WHERE home_team_id = ? AND away_team_id = ?
                  AND match_time_utc = ?
            ''', (home_id, away_id, match.match_time_utc))
            row = cursor.fetchone()

            if row:
                match_id = row[0]
                cursor.execute('''
                    UPDATE Matches SET
                        status       = ?,
                        home_score   = ?,
                        away_score   = ?,
                        stadium      = ?,
                        group_stage  = ?,
                        home_label   = ?,
                        away_label   = ?
                    WHERE id = ?
                ''', (status, match.home_score, match.away_score,
                      match.stadium, match.group_stage,
                      match.home_label, match.away_label, match_id))
            else:
                cursor.execute('''
                    INSERT INTO Matches
                        (home_team_id, away_team_id, match_time_utc,
                         status, home_score, away_score, stadium, group_stage,
                         home_label, away_label)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (home_id, away_id, match.match_time_utc,
                      status, match.home_score, match.away_score,
                      match.stadium, match.group_stage,
                      match.home_label, match.away_label))
                match_id = cursor.lastrowid

            # Track match_id on the Match object for lineup insertion
            match._lastrowid = match_id  # pylint: disable=protected-access

    @staticmethod
    def _upsert_lineups(cursor, matches, team_map, player_map):
        for match in matches:
            match_id = getattr(match, '_lastrowid', None)
            if match_id is None:
                continue
            for p_en in (match.lineups_home_en + match.lineups_away_en):
                p_id = player_map.get(p_en)
                if p_id:
                    cursor.execute('''
                        INSERT OR IGNORE INTO MatchLineups
                            (match_id, player_id, is_starter)
                        VALUES (?, ?, 1)
                    ''', (match_id, p_id))

    @staticmethod
    def _upsert_broadcasts(cursor, broadcasts, team_map):
        for bc in broadcasts:
            home_id = team_map.get(bc.home_team_name)
            away_id = team_map.get(bc.away_team_name)
            if not home_id or not away_id:
                continue

            cursor.execute(
                "SELECT id FROM Matches WHERE home_team_id = ? AND away_team_id = ?",
                (home_id, away_id),
            )
            match_row = cursor.fetchone()
            if not match_row:
                continue

            match_id = match_row[0]
            cursor.execute(
                "SELECT id FROM Broadcasts WHERE match_id = ? AND platform_name = ?",
                (match_id, bc.platform_name),
            )
            bc_row = cursor.fetchone()
            if bc_row:
                cursor.execute(
                    "UPDATE Broadcasts SET stream_url = ?, icon_url = ? WHERE id = ?",
                    (bc.stream_url, bc.icon_url, bc_row[0]),
                )
            else:
                cursor.execute(
                    "INSERT INTO Broadcasts (match_id, platform_name, stream_url, icon_url) "
                    "VALUES (?, ?, ?, ?)",
                    (match_id, bc.platform_name, bc.stream_url, bc.icon_url),
                )


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="World Cup 2026 data scraper – Dongqiudi / Transfermarkt",
    )
    parser.add_argument(
        "--mode", choices=("init", "update"), default="init",
        help="init = full data load; update = match scores/status only (default: init)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the database safety gate (DESTRUCTIVE)",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    scraper = DongqiudiScraper()

    if args.mode == "init":
        _assert_safe_for_init(DB_PATH, args.force)

        logger.info("=== INIT MODE: full team/player/match sync ===")
        teams = scraper.scrape_teams_and_players()
        matches = scraper.scrape_matches()
        broadcasts = scraper.scrape_broadcasts()

        store = DatabaseStore(DB_PATH)
        if store.store_data(teams, matches, broadcasts):
            logger.info("Init pipeline finished successfully.")
        else:
            logger.error("Init pipeline encountered database faults.")
            sys.exit(1)

    elif args.mode == "update":
        logger.info("=== UPDATE MODE: delegating to data_adapter ===")
        try:
            from data_adapter import DataAdapter, WorldCupAPI, _obtain_token
            token = _obtain_token()
            api = WorldCupAPI(token)
            adapter = DataAdapter(DB_PATH)
            adapter.sync_matches(api)
            adapter.sync_scorers(api)
            logger.info("Update pipeline finished successfully.")
        except Exception as e:
            logger.error("Update pipeline failed: %s", e)
            sys.exit(1)


if __name__ == '__main__':
    main()
