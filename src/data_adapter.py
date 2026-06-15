"""
World Cup 2026 — Real Data Adapter
====================================
Fetches live match data from worldcup26.ir (free REST API),
maps it to the existing SQLite schema, and upserts teams,
matches, stadiums, and group standings.

JWT tokens are cached in a local file so the adapter runs
without re-registration across invocations.

Usage:
    python data_adapter.py              # full sync
    python data_adapter.py --update     # match scores only
"""

import sqlite3
import logging
import sys
import os
import json
import time
import re
import base64
import argparse
from typing import Dict, List, Optional, Any
from contextlib import closing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = "https://worldcup26.ir"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "worldcup2026.db")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", ".wc2026_token.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Chinese team-name mapping (FIFA code → Chinese) ──────────────────────────

TEAM_ZH: Dict[str, str] = {
    "MEX": "墨西哥",
    "RSA": "南非",
    "KOR": "韩国",
    "CZE": "捷克",
    "CAN": "加拿大",
    "BIH": "波黑",
    "QAT": "卡塔尔",
    "SUI": "瑞士",
    "BRA": "巴西",
    "MAR": "摩洛哥",
    "HAI": "海地",
    "SCO": "苏格兰",
    "USA": "美国",
    "PAR": "巴拉圭",
    "AUS": "澳大利亚",
    "TUR": "土耳其",
    "GER": "德国",
    "CUW": "库拉索",
    "CIV": "科特迪瓦",
    "ECU": "厄瓜多尔",
    "NED": "荷兰",
    "JPN": "日本",
    "SWE": "瑞典",
    "TUN": "突尼斯",
    "BEL": "比利时",
    "EGY": "埃及",
    "IRN": "伊朗",
    "NZL": "新西兰",
    "ESP": "西班牙",
    "CPV": "佛得角",
    "KSA": "沙特阿拉伯",
    "URU": "乌拉圭",
    "FRA": "法国",
    "SEN": "塞内加尔",
    "IRQ": "伊拉克",
    "NOR": "挪威",
    "ARG": "阿根廷",
    "ALG": "阿尔及利亚",
    "AUT": "奥地利",
    "JOR": "约旦",
    "POR": "葡萄牙",
    "COD": "刚果民主共和国",
    "UZB": "乌兹别克斯坦",
    "COL": "哥伦比亚",
    "ENG": "英格兰",
    "CRO": "克罗地亚",
    "GHA": "加纳",
    "PAN": "巴拿马",
}

# ── Scorer Chinese-name mapping (API name → Chinese) ─────────────────────────

SCORER_ZH: Dict[str, str] = {
    # Group A
    "J. Quiñones": "J. 基尼奥内斯",
    "R. Jiménez": "R. 希门尼斯",
    "I.B. Hwang": "黄喜灿",
    "H.G. Oh": "吴贤揆",
    "L. Krejčí": "L. 克雷伊奇",
    # Group B
    "C. Larin": "C. 拉林",
    "Jovo Lukić": "约沃·卢基奇",
    "B. Khoukhi": "B. 胡赫",
    "Breel Embolo": "布雷尔·恩博洛",
    # Group C
    "V. Júnior": "维尼修斯",
    "I. Saibari": "I. 赛巴里",
    "J. McGinn": "J. 麦金",
    # Group D
    "F. Balogun": "F. 巴洛贡",
    "G. Reyna": "G. 雷纳",
    "Maurício": "毛里西奥",
    "Nestory Irankunda": "内斯托里·伊兰昆达",
    "C. Metcalfe": "C. 梅特卡夫",
}

# ── Knockout stage name mapping (API → Chinese) ──────────────────────────────

STAGE_ZH = {
    "R32": "1/16决赛",
    "R16": "1/8决赛",
    "QF": "1/4决赛",
    "SF": "半决赛",
    "3RD": "季军赛",
    "FINAL": "决赛",
}

# TBD team placeholders used for knockout rounds when teams are undecided.
TBD_HOME_ID = -1
TBD_AWAY_ID = -2


# ── Token management ─────────────────────────────────────────────────────────

def _load_token() -> Optional[str]:
    """Read cached JWT from disk, verify it hasn't expired."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        token = data.get("token")
        expires = data.get("expires_at", 0)
        if token and time.time() < expires - 3600:  # 1h buffer
            return token
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return None


def _save_token(token: str, expires_at: float) -> None:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({"token": token, "expires_at": expires_at}, f)


def _obtain_token() -> str:
    """Authenticate with worldcup26.ir, return a valid JWT."""
    cached = _load_token()
    if cached:
        logger.info("Using cached JWT token.")
        return cached

    # Use environment variables if available, otherwise fall back to defaults.
    email = os.environ.get("WC2026_EMAIL")
    password = os.environ.get("WC2026_PASSWORD")

    # Try loading from .env file if vars not set
    if not email or not password:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        if key == "WC2026_EMAIL" and not email:
                            email = val.strip()
                        elif key == "WC2026_PASSWORD" and not password:
                            password = val.strip()

    if not email or not password:
        raise RuntimeError(
            "WC2026_EMAIL and WC2026_PASSWORD environment variables must be set. "
            "Copy .env.example to .env and fill in your worldcup26.ir credentials."
        )

    login = requests.post(
        f"{BASE_URL}/auth/authenticate",
        json={"email": email, "password": password},
        timeout=15,
    )
    if login.status_code == 200:
        body = login.json()
        token = body["token"]
        # Parse expiry from JWT payload (base64url, second segment)
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = payload.get("exp", time.time() + 86400)
        except Exception:
            exp = time.time() + 86400
        _save_token(token, exp)
        logger.info("Logged in to worldcup26.ir, token saved.")
        return token

    # Register fresh
    logger.info("Account not found, registering...")
    reg = requests.post(
        f"{BASE_URL}/auth/register",
        json={"name": "WC2026Aggregator", "email": email, "password": password},
        timeout=15,
    )
    if reg.status_code not in (200, 201):
        raise RuntimeError(f"Registration failed: {reg.status_code} {reg.text}")

    body = reg.json()
    token = body["token"]
    _save_token(token, time.time() + 84 * 86400)
    logger.info("Registered and logged in to worldcup26.ir.")
    return token


# ── API client ────────────────────────────────────────────────────────────────

class WorldCupAPI:
    """Thin wrapper around worldcup26.ir REST endpoints."""

    def __init__(self, token: str):
        self._headers = {"Authorization": f"Bearer {token}"}

    def _get(self, path: str) -> dict:
        resp = requests.get(f"{BASE_URL}{path}", headers=self._headers, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def fetch_teams(self) -> List[dict]:
        data = self._get("/get/teams")
        return data.get("teams", [])

    def fetch_games(self) -> List[dict]:
        data = self._get("/get/games")
        return data.get("games", [])

    def fetch_groups(self) -> List[dict]:
        data = self._get("/get/groups")
        return data.get("groups", [])

    def fetch_stadiums(self) -> List[dict]:
        data = self._get("/get/stadiums")
        return data.get("stadiums", [])


# ── Date helpers ──────────────────────────────────────────────────────────────

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

def _parse_local_date(raw: str) -> str:
    """Convert '06/11/2026 13:00' (Tehran local time) → '2026-06-11T08:30:00Z' (UTC)"""
    if not raw:
        return ""
    try:
        naive_dt = datetime.strptime(raw.strip(), "%m/%d/%Y %H:%M")
        # Attach Tehran timezone and convert to UTC
        tehran_dt = naive_dt.replace(tzinfo=TEHRAN_TZ)
        utc_dt = tehran_dt.astimezone(timezone.utc)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        logger.warning("Could not parse date: %s", raw)
        return raw


def _compute_status(api_finished: str, api_elapsed: str, match_utc: str) -> str:
    """
    Determine match status.  System UTC is authoritative — API status
    fields from worldcup26.ir are only trusted when consistent with time.
    """
    # Parse match kickoff time
    try:
        match_dt = datetime.strptime(match_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "upcoming"

    now = datetime.now(timezone.utc)
    diff_minutes = (now - match_dt).total_seconds() / 60

    # Time-based status using system UTC (authoritative)
    if diff_minutes > 150:          # > 2.5 hours after kickoff → finished
        time_status = "finished"
    elif diff_minutes > -30:        # within 30 min of kickoff, or during match → live
        time_status = "live"
    else:
        time_status = "upcoming"

    # API status: only trusted when consistent with time
    if api_finished == "TRUE" and diff_minutes > 0:
        return "finished"
    if (api_elapsed not in (None, "notstarted", "", "finished")
            and diff_minutes > -30):
        return "live"

    return time_status


def _parse_scorers(raw: Optional[str]) -> str:
    """Normalise scorer strings from the API (may contain curly quotes)."""
    if raw is None or raw in ("null", "NULL", ""):
        return ""
    text = str(raw)
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    return text


def _parse_scorer_entries(raw: Optional[str]) -> List[str]:
    """
    Extract player names from an API scorer string, skipping own goals.

    Input:  '{"F. Balogun 31\'","D. Bobadilla 7\'(OG)","G. Reyna 90\'+8\'"}'
    Output: ['F. Balogun', 'F. Balogun', 'G. Reyna']
             (Balogun appears twice = 2 goals, OG excluded)
    """
    text = _parse_scorers(raw)
    if not text:
        return []

    # The API embeds a JSON array of strings; try to parse it.
    try:
        entries = json.loads(text)
    except json.JSONDecodeError:
        # Heuristic fallback: split on commas outside quotes
        entries = re.split(r'",\s*"', text.strip('{}"'))
        entries = [e.strip('"') for e in entries]

    names: List[str] = []
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        # Skip own goals
        if "(OG)" in entry or "(og)" in entry:
            continue
        # Extract name: strip trailing minute info like " 31'", " 45'+5'", " 17' (p)"
        entry = re.sub(r"\s+\d+\+?\d*\'\s*(\+?\d+\+?\d*\'?)?(\s*\(.*?\))?$", "", entry)
        name = entry.strip().rstrip("'")
        if name:
            names.append(name)

    return names


# ── Database sync ─────────────────────────────────────────────────────────────

class DataAdapter:
    """Reads from the live API, writes to the local SQLite database."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ── Full sync ────────────────────────────────────────────────────────

    def sync_all(self, api: WorldCupAPI) -> bool:
        """One-shot: pull teams, matches, stadiums from the API and upsert."""
        try:
            teams = api.fetch_teams()
            games = api.fetch_games()
            stadiums = api.fetch_stadiums()

            logger.info(
                "Fetched %d teams, %d games, %d stadiums.",
                len(teams), len(games), len(stadiums),
            )

            with closing(self._conn()) as conn:
                with closing(conn.cursor()) as cur:
                    stadium_map = self._upsert_stadiums(cur, stadiums)
                    team_id_map = self._upsert_teams(cur, teams)
                    self._upsert_matches(cur, games, team_id_map, stadium_map)
                conn.commit()

            logger.info("Full sync completed successfully.")

            # Populate real goal-scorer data, broadcast links, player images, wiki bios
            self.sync_scorers(api)
            self.sync_broadcasts()
            self.enrich_player_images()
            self.enrich_wikipedia()

            return True
        except requests.RequestException as e:
            logger.error("API request failed: %s", e)
            return False
        except sqlite3.Error as e:
            logger.error("Database error during sync: %s", e)
            return False

    # ── Match-only update ────────────────────────────────────────────────

    def sync_matches(self, api: WorldCupAPI) -> bool:
        """Update match scores / status only — does not touch teams."""
        try:
            games = api.fetch_games()
            stadiums = api.fetch_stadiums()
            stadium_lookup = {s["id"]: s.get("name_en", "") for s in stadiums}

            with closing(self._conn()) as conn:
                with closing(conn.cursor()) as cur:
                    # Load team map from DB
                    cur.execute("SELECT id, name FROM Teams")
                    db_team_map = {row[1]: row[0] for row in cur.fetchall()}

                    # Load team map from API
                    teams = api.fetch_teams()
                    api_team_map = {t["id"]: t for t in teams}

                    update_count = 0
                    for g in games:
                        ht = api_team_map.get(g["home_team_id"])
                        at = api_team_map.get(g["away_team_id"])
                        if not ht or not at:
                            continue

                        home_db_id = db_team_map.get(ht["name_en"])
                        away_db_id = db_team_map.get(at["name_en"])
                        if not home_db_id or not away_db_id:
                            continue

                        match_utc = _parse_local_date(g.get("local_date", ""))

                        # Status: API fields + time-based correction
                        api_finished = g.get("finished", "FALSE")
                        api_elapsed = g.get("time_elapsed", "")
                        # Initial status using API time — will be overridden
                        # with DB's correct time if match exists
                        status = _compute_status(api_finished, api_elapsed, match_utc)

                        home_score = int(g.get("home_score", 0) or 0)
                        away_score = int(g.get("away_score", 0) or 0)
                        group_stage = g.get("group", "")
                        # Normalize: "Group A" → "A", "Group C" → "C"
                        if group_stage.startswith("Group "):
                            group_stage = group_stage[6:]
                        if group_stage in STAGE_ZH:
                            group_stage = STAGE_ZH[group_stage]
                        stadium_name = stadium_lookup.get(g.get("stadium_id", ""), "")

                        # Look up existing match by team pair (time-agnostic),
                        # so that dongqiudi-set correct UTC times are preserved.
                        cur.execute(
                            """SELECT id, match_time_utc FROM Matches
                               WHERE ((home_team_id = ? AND away_team_id = ?)
                                  OR  (home_team_id = ? AND away_team_id = ?))
                               LIMIT 1""",
                            (home_db_id, away_db_id, away_db_id, home_db_id),
                        )
                        row = cur.fetchone()
                        if row:
                            # Re-compute status using DB's correct UTC time
                            db_match_utc = row[1]
                            status = _compute_status(api_finished, api_elapsed, db_match_utc)
                            cur.execute(
                                """UPDATE Matches
                                   SET status = ?, home_score = ?,
                                       away_score = ?, stadium = ?,
                                       group_stage = ?
                                   WHERE id = ?""",
                                (status, home_score, away_score,
                                 stadium_name, group_stage, row[0]),
                            )
                            update_count += 1

                conn.commit()

            logger.info(
                "Match update completed: %d match(es) refreshed.", update_count
            )
            return True
        except (requests.RequestException, sqlite3.Error) as e:
            logger.error("Match sync failed: %s", e)
            return False

    # ── Scorer sync ──────────────────────────────────────────────────────

    def sync_scorers(self, api: WorldCupAPI) -> bool:
        """
        Parse real goal-scorer names from the API's finished matches and
        upsert Player records with tournament_goals counts.

        Only processes finished matches so re-running is idempotent.
        Previously stored tournament_goals are zeroed first to remove
        stale simulated data.
        """
        try:
            games = api.fetch_games()
            teams_data = api.fetch_teams()
            team_id_map = {t["id"]: t.get("name_en", "") for t in teams_data}

            with closing(self._conn()) as conn:
                with closing(conn.cursor()) as cur:
                    # Reset old simulated goal tallies
                    cur.execute("UPDATE Players SET tournament_goals = 0")
                    cur.execute("SELECT id, name FROM Teams")
                    db_teams = {row[1]: row[0] for row in cur.fetchall()}

                    scorer_counts: Dict[tuple, int] = {}  # (db_team_id, name_en) → count

                    for g in games:
                        if g.get("finished") != "TRUE":
                            continue
                        ht_name = team_id_map.get(g["home_team_id"])
                        at_name = team_id_map.get(g["away_team_id"])
                        if not ht_name or not at_name:
                            continue

                        # Home scorers
                        for name in _parse_scorer_entries(g.get("home_scorers")):
                            tid = db_teams.get(ht_name)
                            if tid:
                                key = (tid, name)
                                scorer_counts[key] = scorer_counts.get(key, 0) + 1

                        # Away scorers
                        for name in _parse_scorer_entries(g.get("away_scorers")):
                            tid = db_teams.get(at_name)
                            if tid:
                                key = (tid, name)
                                scorer_counts[key] = scorer_counts.get(key, 0) + 1

                    new_players = 0
                    updated_players = 0
                    for (team_id, name_en), goals in scorer_counts.items():
                        cur.execute(
                            "SELECT id, tournament_goals FROM Players "
                            "WHERE team_id = ? AND name_en = ?",
                            (team_id, name_en),
                        )
                        row = cur.fetchone()
                        name_zh_val = SCORER_ZH.get(name_en, name_en)
                        if row:
                            cur.execute(
                                "UPDATE Players SET tournament_goals = ?, name_zh = ? WHERE id = ?",
                                (goals, name_zh_val, row[0]),
                            )
                            updated_players += 1
                        else:
                            name_zh_val = SCORER_ZH.get(name_en, name_en)
                            cur.execute(
                                "INSERT INTO Players "
                                "(team_id, name_en, name_zh, position, jersey_number, "
                                " profile_url, history_stats, tournament_goals, tournament_assists) "
                                "VALUES (?, ?, ?, 'FW', 0, '#', '{}', ?, 0)",
                                (team_id, name_en, name_zh_val, goals),
                            )
                            new_players += 1

                conn.commit()

            logger.info(
                "Scorer sync: %d new player(s), %d updated, %d unique scorers.",
                new_players, updated_players, len(scorer_counts),
            )
            return True
        except (requests.RequestException, sqlite3.Error) as e:
            logger.error("Scorer sync failed: %s", e)
            return False

    # ── Player image enrichment (TheSportsDB) ────────────────────────────
    TSD_BASE = "https://www.thesportsdb.com/api/v1/json/3"

    @staticmethod
    def _map_tsd_position(tsd_pos: str) -> str:
        """Map TheSportsDB position string to short DB code (FW/MF/DF/GK)."""
        pos = tsd_pos.lower()
        if any(k in pos for k in ('goalkeeper', 'keeper', 'gk')):
            return 'GK'
        if any(k in pos for k in ('defender', 'back', 'df', 'sweeper',
                                    'centre back', 'left back', 'right back',
                                    'wing back')):
            return 'DF'
        if any(k in pos for k in ('midfielder', 'midfield', 'mf', 'winger')):
            return 'MF'
        if any(k in pos for k in ('forward', 'striker', 'fw', 'attacker')):
            return 'FW'
        return 'FW'

    def enrich_player_images(self) -> bool:
        """
        Fetch player thumbnails, cutouts, biographies and fanart from
        TheSportsDB for every player without a profile image.  Also syncs
        position and jersey number from TSD data.  Falls back to
        ui-avatars.com when TSD has no matching record.
        """
        import urllib.parse
        import time as time_mod

        players_sql = (
            "SELECT id, name_en FROM Players "
            "WHERE (profile_url = '#' OR profile_url = '' OR profile_url IS NULL)"
        )
        try:
            with closing(self._conn()) as conn:
                with closing(conn.cursor()) as cur:
                    cur.execute(players_sql)
                    candidates = cur.fetchall()

            enriched = 0
            skipped = 0
            for player_id, name_en in candidates:
                try:
                    resp = requests.get(
                        f"{self.TSD_BASE}/searchplayers.php",
                        params={"p": name_en},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    # Respect API rate limits
                    time_mod.sleep(0.5)
                    players = data.get("player")
                    if not players:
                        # TSD has no record — set ui-avatars fallback
                        encoded_name = urllib.parse.quote(name_en)
                        fallback_avatar = (
                            f"https://ui-avatars.com/api/"
                            f"?name={encoded_name}&background=11151c&color=00ff87&size=128"
                        )
                        with closing(self._conn()) as conn:
                            conn.execute(
                                "UPDATE Players SET profile_url = ? WHERE id = ?",
                                (fallback_avatar, player_id),
                            )
                            conn.commit()
                        skipped += 1
                        continue

                    # Pick the best match (first result)
                    p = players[0]

                    thumb = p.get("strCutout") or p.get("strThumb") or ""
                    fanart = p.get("strPoster") or ""
                    banner = p.get("strBanner") or ""
                    fanart1 = p.get("strFanart1") or ""
                    fanart2 = p.get("strFanart2") or ""

                    # Map TSD position to short code, extract jersey number
                    tsd_position = self._map_tsd_position(p.get("strPosition", ""))
                    jersey_num = int(p.get("strNumber", 0) or 0)

                    # Build a JSON blob for large images and metadata
                    extra = json.dumps({
                        "fanart": fanart,
                        "banner": banner,
                        "fanart1": fanart1,
                        "fanart2": fanart2,
                        "full_name": p.get("strPlayerAlternate", ""),
                        "birth": p.get("dateBorn", ""),
                        "birth_place": p.get("strBirthLocation", ""),
                        "height": p.get("strHeight", ""),
                        "weight": p.get("strWeight", ""),
                        "nationality": p.get("strNationality", ""),
                        "position": p.get("strPosition", ""),
                        "team": p.get("strTeam", ""),
                        "instagram": p.get("strInstagram", ""),
                        "facebook": p.get("strFacebook", ""),
                        "bio": p.get("strDescriptionEN", ""),
                    }, ensure_ascii=False)

                    with closing(self._conn()) as conn:
                        conn.execute(
                            "UPDATE Players SET profile_url = ?, description = ?, "
                            "position = ?, jersey_number = ? WHERE id = ?",
                            (thumb, extra, tsd_position, jersey_num, player_id),
                        )
                        conn.commit()

                    enriched += 1
                    logger.debug(
                        "Enriched %s: thumb=%s fanart=%s",
                        name_en, bool(thumb), bool(fanart),
                    )
                except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
                    logger.warning("TheSportsDB lookup failed for %s: %s", name_en, e)
                    # Set fallback avatar on error too
                    try:
                        encoded_name = urllib.parse.quote(name_en)
                        fallback_avatar = (
                            f"https://ui-avatars.com/api/"
                            f"?name={encoded_name}&background=11151c&color=00ff87&size=128"
                        )
                        with closing(self._conn()) as conn:
                            conn.execute(
                                "UPDATE Players SET profile_url = ? WHERE id = ?",
                                (fallback_avatar, player_id),
                            )
                            conn.commit()
                    except Exception:
                        pass
                    skipped += 1
                    continue

            logger.info(
                "Player image enrichment: %d enriched, %d skipped.",
                enriched, skipped,
            )
            return True
        except sqlite3.Error as e:
            logger.error("Image enrichment failed: %s", e)
            return False

    # ── Wikipedia enrichment ─────────────────────────────────────────────
    WIKI_UA = "WorldCup2026Aggregator/2.0"

    def enrich_wikipedia(self) -> bool:
        """
        Fetch player bios and large thumbnails from Wikipedia's REST API.
        Updates the description JSON for every scorer who doesn't yet
        have a Wikipedia extract.
        """
        WIKI_BASE = "https://en.wikipedia.org/api/rest_v1/page/summary"

        try:
            with closing(self._conn()) as conn:
                with closing(conn.cursor()) as cur:
                    cur.execute(
                        "SELECT id, name_en, description FROM Players "
                        "WHERE tournament_goals > 0"
                    )
                    candidates = cur.fetchall()

            enriched = 0
            for pid, name_en, desc_raw in candidates:
                # Check if already has Wikipedia data
                try:
                    existing = json.loads(desc_raw or "{}")
                    if existing.get("wiki_extract"):
                        continue
                except json.JSONDecodeError:
                    existing = {}

                # Use full name from TheSportsDB if available, else fall back to API name
                search_name = existing.get("full_name", "") or name_en

                try:
                    # Step 1: Search Wikipedia for the correct page title
                    search_resp = requests.get(
                        "https://en.wikipedia.org/w/api.php",
                        params={
                            "action": "query", "list": "search",
                            "srsearch": search_name, "format": "json",
                        },
                        headers={"User-Agent": self.WIKI_UA},
                        timeout=10,
                    )
                    search_data = search_resp.json()
                    results = search_data.get("query", {}).get("search", [])
                    if not results:
                        continue

                    wiki_title = results[0]["title"]
                    wiki_name = wiki_title.replace(" ", "_")

                    # Step 2: Fetch summary for the found page
                    resp = requests.get(
                        f"{WIKI_BASE}/{wiki_name}",
                        headers={"User-Agent": self.WIKI_UA},
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                    extract = data.get("extract", "")
                    thumb_src = (
                        data.get("thumbnail", {}).get("source", "")
                    )
                    page_url = (
                        data.get("content_urls", {})
                        .get("desktop", {})
                        .get("page", "")
                    )
                    title = data.get("title", "")

                    if not extract and not thumb_src:
                        continue

                    existing["wiki_extract"] = extract[:800]
                    existing["wiki_title"] = title
                    existing["wiki_url"] = page_url
                    existing["wiki_thumb"] = thumb_src

                    with closing(self._conn()) as conn:
                        conn.execute(
                            "UPDATE Players SET description = ? WHERE id = ?",
                            (json.dumps(existing, ensure_ascii=False), pid),
                        )
                        conn.commit()
                    enriched += 1
                except (requests.RequestException, KeyError, json.JSONDecodeError):
                    continue

            logger.info("Wikipedia enrichment: %d player(s) updated.", enriched)
            return True
        except sqlite3.Error as e:
            logger.error("Wikipedia enrichment failed: %s", e)
            return False

    # ── Broadcast sync ───────────────────────────────────────────────────

    # Known 2026 World Cup broadcast platforms (URLs, icons).
    BROADCAST_PLATFORMS = [
        {
            "name": "CCTV-5",
            "url": "https://tv.cctv.com/live/cctv5/",
            "icon": (
                "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                "8/87/CCTV-5_logo.svg/120px-CCTV-5_logo.svg.png"
            ),
        },
        {
            "name": "央视频",
            "url": "https://www.yangshipin.cn/",
            "icon": (
                "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                "e/e5/Yangshipin_logo.svg/120px-Yangshipin_logo.svg.png"
            ),
        },
        {
            "name": "咪咕视频",
            "url": "https://www.miguvideo.com/",
            "icon": (
                "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                "8/8e/Migu_Video_logo.svg/120px-Migu_Video_logo.svg.png"
            ),
        },
        {
            "name": "FIFA+",
            "url": "https://www.fifa.com/fifaplus/en/",
            "icon": (
                "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                "1/1b/FIFA_logo_without_slogan.svg/120px-FIFA_logo_without_slogan.svg.png"
            ),
        },
        {
            "name": "FOX Sports",
            "url": "https://www.foxsports.com/soccer/world-cup",
            "icon": (
                "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                "2/29/Fox_Sports_logo.svg/120px-Fox_Sports_logo.svg.png"
            ),
        },
        {
            "name": "懂球帝",
            "url": "https://www.dongqiudi.com/data/worldcup/2026",
            "icon": (
                "https://upload.wikimedia.org/wikipedia/commons/thumb/"
                "a/a5/Dongqiudi_logo.svg/120px-Dongqiudi_logo.svg.png"
            ),
        },
    ]

    def sync_broadcasts(self) -> bool:
        """
        Ensure every match in the database has a full set of broadcast
        platform links.  Idempotent — existing entries are left untouched.
        """
        try:
            with closing(self._conn()) as conn:
                with closing(conn.cursor()) as cur:
                    # Clean orphaned broadcast entries (match deleted)
                    cur.execute(
                        "DELETE FROM Broadcasts WHERE match_id NOT IN "
                        "(SELECT id FROM Matches)"
                    )
                    orphaned = cur.rowcount
                    if orphaned:
                        logger.info("Removed %d orphaned broadcast(s).", orphaned)

                    # Get all match IDs
                    cur.execute("SELECT id FROM Matches")
                    match_ids = [row[0] for row in cur.fetchall()]

                    added = 0
                    for mid in match_ids:
                        for plat in self.BROADCAST_PLATFORMS:
                            cur.execute(
                                "SELECT id FROM Broadcasts "
                                "WHERE match_id = ? AND platform_name = ?",
                                (mid, plat["name"]),
                            )
                            if cur.fetchone():
                                continue  # already exists
                            cur.execute(
                                "INSERT INTO Broadcasts "
                                "(match_id, platform_name, stream_url, icon_url) "
                                "VALUES (?, ?, ?, ?)",
                                (mid, plat["name"], plat["url"], plat["icon"]),
                            )
                            added += 1

                conn.commit()

            logger.info(
                "Broadcast sync: %d new entries across %d match(es) × %d platform(s).",
                added, len(match_ids), len(self.BROADCAST_PLATFORMS),
            )
            return True
        except sqlite3.Error as e:
            logger.error("Broadcast sync failed: %s", e)
            return False

    # ── Cleanup ──────────────────────────────────────────────────────────

    def clean_old_data(self, api: WorldCupAPI) -> int:
        """Remove simulated data: delete teams/matches not in the API."""
        api_teams = api.fetch_teams()
        api_names = {t["name_en"] for t in api_teams}

        with closing(self._conn()) as conn:
            with closing(conn.cursor()) as cur:
                # Find stale team IDs
                cur.execute("SELECT id, name, group_name FROM Teams")
                stale_ids = []
                for row in cur.fetchall():
                    # Skip TBD placeholder teams used for knockout bracket
                    if row[1] in ("TBD_Home", "TBD_Away"):
                        continue
                    if row[1] not in api_names:
                        stale_ids.append(row[0])
                        logger.info("Marking stale team for removal: %s (%s)", row[1], row[2])

                if stale_ids:
                    placeholders = ",".join("?" * len(stale_ids))
                    cur.execute(
                        f"DELETE FROM Matches WHERE home_team_id IN ({placeholders}) OR away_team_id IN ({placeholders})",
                        stale_ids + stale_ids,
                    )
                    cur.execute(
                        f"DELETE FROM Teams WHERE id IN ({placeholders})",
                        stale_ids,
                    )
                    removed = len(stale_ids)
                    logger.info("Removed %d stale team(s) and their matches.", removed)
                else:
                    removed = 0

                # Also delete old simulated matches
                cur.execute("DELETE FROM Matches WHERE stadium = 'Mock Stadium'")
                mock_removed = cur.rowcount

                conn.commit()
                return removed + mock_removed

    @staticmethod
    def _upsert_stadiums(cur, stadiums: List[dict]) -> Dict[str, str]:
        """Store stadium names; return {api_id: name}."""
        stadium_map: Dict[str, str] = {}
        for s in stadiums:
            stadium_map[s["id"]] = s.get("name_en", "")
        return stadium_map

    @staticmethod
    def _upsert_teams(cur, teams: List[dict]) -> Dict[str, int]:
        """Insert/update teams; return {api_team_id: db_team_id}."""
        team_id_map: Dict[str, int] = {}
        for t in teams:
            name_en = t["name_en"]
            name_zh = TEAM_ZH.get(t.get("fifa_code", ""), name_en)
            group_name = t.get("groups", "")
            flag_url = t.get("flag", "")

            # Try update existing team by English name
            cur.execute("SELECT id FROM Teams WHERE name = ?", (name_en,))
            row = cur.fetchone()
            if row:
                db_id = row[0]
                cur.execute(
                    """UPDATE Teams
                       SET name_zh = ?, group_name = ?, flag_url = ?
                       WHERE id = ?""",
                    (name_zh, group_name, flag_url, db_id),
                )
            else:
                cur.execute(
                    """INSERT INTO Teams (name, name_zh, group_name, flag_url)
                       VALUES (?, ?, ?, ?)""",
                    (name_en, name_zh, group_name, flag_url),
                )
                db_id = cur.lastrowid

            team_id_map[t["id"]] = db_id

        return team_id_map

    @staticmethod
    def _upsert_matches(
        cur,
        games: List[dict],
        team_id_map: Dict[str, int],
        stadium_map: Dict[str, str],
    ) -> None:
        # Ensure TBD placeholder teams exist for knockout rounds
        cur.execute(
            "INSERT OR IGNORE INTO Teams (id, name, name_zh, group_name) "
            "VALUES (?, 'TBD_Home', '待定', '')",
            (TBD_HOME_ID,),
        )
        cur.execute(
            "INSERT OR IGNORE INTO Teams (id, name, name_zh, group_name) "
            "VALUES (?, 'TBD_Away', '待定', '')",
            (TBD_AWAY_ID,),
        )

        for g in games:
            home_db_id = team_id_map.get(g["home_team_id"])
            away_db_id = team_id_map.get(g["away_team_id"])

            # Knockout rounds with TBD teams: use placeholder IDs
            is_knockout = g.get("type", "group") != "group"
            if is_knockout and (not home_db_id or not away_db_id):
                home_db_id = home_db_id or TBD_HOME_ID
                away_db_id = away_db_id or TBD_AWAY_ID

            if not home_db_id or not away_db_id:
                continue

            match_utc = _parse_local_date(g.get("local_date", ""))
            if not match_utc:
                continue

            # Status will be recomputed using DB's correct UTC after lookup
            api_finished_flag = g.get("finished", "FALSE")
            api_elapsed_flag = g.get("time_elapsed", "")
            status = _compute_status(api_finished_flag, api_elapsed_flag, match_utc)

            home_score = int(g.get("home_score", 0) or 0)
            away_score = int(g.get("away_score", 0) or 0)
            group_stage = g.get("group", "")
            # Normalize: "Group A" → "A", "Group C" → "C"
            if group_stage.startswith("Group "):
                group_stage = group_stage[6:]
            # Map API knockout codes to Chinese display names
            if group_stage in STAGE_ZH:
                group_stage = STAGE_ZH[group_stage]
            stadium_name = stadium_map.get(g.get("stadium_id", ""), "")

            home_label = g.get("home_team_label", "")
            away_label = g.get("away_team_label", "")

            cur.execute(
                """SELECT id, match_time_utc FROM Matches
                   WHERE ((home_team_id = ? AND away_team_id = ?)
                      OR  (home_team_id = ? AND away_team_id = ?))
                   LIMIT 1""",
                (home_db_id, away_db_id, away_db_id, home_db_id),
            )
            row = cur.fetchone()

            if row:
                # Re-compute status using DB's correct UTC time
                db_match_utc = row[1]
                status = _compute_status(
                    g.get("finished", "FALSE"),
                    g.get("time_elapsed", ""),
                    db_match_utc,
                )
                cur.execute(
                    """UPDATE Matches
                       SET status = ?, home_score = ?, away_score = ?,
                           stadium = ?, group_stage = ?,
                           home_label = ?, away_label = ?
                       WHERE id = ?""",
                    (status, home_score, away_score, stadium_name,
                     group_stage, home_label, away_label, row[0]),
                )
            else:
                cur.execute(
                    """INSERT INTO Matches
                       (home_team_id, away_team_id, match_time_utc, status,
                        home_score, away_score, stadium, group_stage,
                        home_label, away_label)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        home_db_id, away_db_id, match_utc, status,
                        home_score, away_score, stadium_name, group_stage,
                        home_label, away_label,
                    ),
                )


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="World Cup 2026 real-data adapter (worldcup26.ir)"
    )
    p.add_argument(
        "--update",
        action="store_true",
        help="Match-scores-only update (skips team/stadium sync)",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="Remove stale simulated teams/matches before sync",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    try:
        token = _obtain_token()
    except RuntimeError as e:
        logger.error("Authentication failed: %s", e)
        sys.exit(1)

    api = WorldCupAPI(token)
    adapter = DataAdapter(DB_PATH)

    if args.clean:
        removed = adapter.clean_old_data(api)
        logger.info("Cleaned %d stale record(s).", removed)

    if args.update:
        ok = adapter.sync_matches(api)
    else:
        ok = adapter.sync_all(api)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
