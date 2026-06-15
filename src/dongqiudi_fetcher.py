"""
World Cup 2026 — Dongqiudi Schedule Fetcher
============================================
Fetches the complete match schedule from dongqiudi.com (懂球帝),
which provides authoritative Beijing-time kickoff times.

Times are returned as UTC, converted from displayed Beijing time (UTC+8).
"""
import re
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
from contextlib import closing

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BJT_TZ = timezone(timedelta(hours=8))

# ── Status mapping ────────────────────────────────────────────────────────────

STATUS_MAP: Dict[str, str] = {
    "未开始": "upcoming",
    "进行中": "live",
    "已结束": "finished",
    "已推迟": "postponed",
    "已中断": "suspended",
}


@dataclass
class DqMatch:
    """A single match parsed from dongqiudi."""
    match_id: str
    match_time_utc: str
    match_time_bj: str
    status: str
    home_team_zh: str
    away_team_zh: str
    home_score: int
    away_score: int
    group_stage: str
    dongqiudi_url: str
    home_label: str = ""
    away_label: str = ""
    # Filled by _lookup_team_ids
    home_db_id: Optional[int] = None
    away_db_id: Optional[int] = None
    home_name_en: str = ""
    away_name_en: str = ""


def _bj_to_utc(bj_str: str) -> str:
    """Convert '2026-06-16 00:00' (Beijing) → '2026-06-15T16:00:00Z' (UTC)."""
    if not bj_str:
        return ""
    dt_naive = datetime.strptime(bj_str.strip(), "%Y-%m-%d %H:%M")
    dt_bj = dt_naive.replace(tzinfo=BJT_TZ)
    return dt_bj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_flat_text(text: str) -> Optional[tuple]:
    """
    Fallback parser for flat text like:
      '2026-06-12 03:00 已结束 墨西哥 2 - 0 南非'
      '2026-06-16 00:00 未开始 西班牙 - 佛得角'
    """
    text = text.strip()
    # Extract datetime
    m = re.match(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*(.*)', text)
    if not m:
        return None
    dt_str = m.group(1)
    rest = m.group(2).strip()

    # Extract status
    status = "upcoming"
    for zh, en in STATUS_MAP.items():
        if rest.startswith(zh):
            status = en
            rest = rest[len(zh):].strip()
            break

    # Extract teams and optional score
    home_zh, away_zh, home_score, away_score = "", "", 0, 0

    # "墨西哥 2 - 0 南非"
    scored = re.match(r'^(.+?)\s+(\d+)\s*[-–]\s*(\d+)\s+(.+)$', rest)
    if scored:
        home_zh = scored.group(1).strip()
        home_score = int(scored.group(2))
        away_score = int(scored.group(3))
        away_zh = scored.group(4).strip()
    else:
        # "西班牙 - 佛得角"
        noscore = re.match(r'^(.+?)\s*[-–]\s*(.+)$', rest)
        if noscore:
            home_zh = noscore.group(1).strip()
            away_zh = noscore.group(2).strip()

    return (dt_str, status, home_zh, away_zh, home_score, away_score)


def _parse_by_classes(a_tag) -> Optional[tuple]:
    """
    Parse using semantic CSS classes (preferred).
    HTML structure:
      <a class="dp-schedule-row">
        <span class="dp-schedule-row__time">2026-06-16 00:00</span>
        <span class="dp-schedule-row__status ...">未开始</span>
        <div class="dp-schedule-row__teams">
          <span class="dp-schedule-row__team--home">西班牙</span>
          <span class="dp-schedule-row__score">2 - 0</span>   <!-- absent if no score -->
          <span class="dp-schedule-row__team--away">佛得角</span>
        </div>
      </a>
    """
    # Time
    time_span = a_tag.select_one(".dp-schedule-row__time")
    if not time_span:
        return None
    dt_str = time_span.get_text(strip=True)

    # Status
    status_span = a_tag.select_one(".dp-schedule-row__status")
    status_raw = status_span.get_text(strip=True) if status_span else "未开始"
    status = STATUS_MAP.get(status_raw, "upcoming")

    # Teams
    home_span = a_tag.select_one(".dp-schedule-row__team--home")
    away_span = a_tag.select_one(".dp-schedule-row__team--away")
    score_span = a_tag.select_one(".dp-schedule-row__score")

    home_zh = home_span.get_text(strip=True) if home_span else ""
    away_zh = away_span.get_text(strip=True) if away_span else ""
    home_score, away_score = 0, 0

    if score_span:
        score_text = score_span.get_text(strip=True)
        score_match = re.match(r'(\d+)\s*[-–]\s*(\d+)', score_text)
        if score_match:
            home_score = int(score_match.group(1))
            away_score = int(score_match.group(2))

    return (dt_str, status, home_zh, away_zh, home_score, away_score)


def _find_stage(a_tag, soup) -> str:
    """Find the nearest stage title above this match card."""
    # Search for section titles before this match
    for header in soup.find_all(["h2", "h3", "h4", "div"]):
        if header.sourceline and a_tag.sourceline and header.sourceline > a_tag.sourceline:
            break
        text = header.get_text(strip=True)
        for kw in ["小组赛", "1/16决赛", "1/8决赛", "1/4决赛", "半决赛", "季军赛", "决赛"]:
            if kw in text:
                return text
    return ""


def _lookup_team_ids(home_zh: str, away_zh: str, db_path: str) -> tuple:
    """
    Look up team DB IDs by Chinese name.
    For knockout placeholders (A2, B1, 胜者...), uses TBD IDs.
    """
    TBD_HOME_ID = -1
    TBD_AWAY_ID = -2

    with closing(sqlite3.connect(db_path)) as conn:
        cur = conn.cursor()
        # Ensure TBD placeholder teams exist
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
        conn.commit()

        cur.execute("SELECT id, name FROM Teams WHERE name_zh = ?", (home_zh,))
        home_row = cur.fetchone()
        cur.execute("SELECT id, name FROM Teams WHERE name_zh = ?", (away_zh,))
        away_row = cur.fetchone()

    home_id = home_row[0] if home_row else None
    away_id = away_row[0] if away_row else None
    home_en = home_row[1] if home_row else home_zh
    away_en = away_row[1] if away_row else away_zh

    # Is this a knockout placeholder?
    is_placeholder = bool(re.match(r'^[A-K]\d+$', home_zh)) or '胜者' in home_zh or '败者' in home_zh

    if is_placeholder:
        if not home_id:
            home_id = TBD_HOME_ID
            home_en = "TBD_Home"
        if not away_id:
            away_id = TBD_AWAY_ID
            away_en = "TBD_Away"

    return home_id, away_id, home_en, away_en


def fetch_schedule(db_path: str) -> List[DqMatch]:
    """
    Fetch and parse the complete match schedule from dongqiudi.
    """
    url = "https://www.dongqiudi.com/data?cid=61&tab=schedule"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    logger.info("Fetching dongqiudi schedule from %s", url)
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Failed to fetch dongqiudi page: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    matches: List[DqMatch] = []

    # Use DOM structure: each dp-schedule-group contains a title + match cards
    for group_div in soup.find_all("div", class_="dp-schedule-group"):
        title_div = group_div.find("div", class_="dp-schedule-group__title")
        stage_name = title_div.get_text(strip=True) if title_div else ""

        for a_tag in group_div.find_all("a", class_="dp-schedule-row"):
            href = a_tag.get("href", "")
            mid_match = re.search(r"/match/(\d+)", href)
            if not mid_match:
                continue
            match_id = mid_match.group(1)

            # Primary: parse by CSS classes
            parsed = _parse_by_classes(a_tag)
            # Fallback: parse flat text
            if not parsed or not parsed[3]:
                flat_text = a_tag.get_text(separator=" ", strip=True)
                parsed = _parse_flat_text(flat_text)

            if not parsed:
                logger.warning("Could not parse match card: %s", match_id)
                continue

            dt_str_bj, status, home_zh, away_zh, home_score, away_score = parsed

            # For knockout placeholders, store raw text as labels
            is_placeholder = bool(re.match(r'^[A-K]\d+$', home_zh)) or '胜者' in home_zh or '败者' in home_zh
            home_label = home_zh if is_placeholder else ""
            away_label = away_zh if is_placeholder else ""

            match = DqMatch(
                match_id=match_id,
                match_time_utc=_bj_to_utc(dt_str_bj),
                match_time_bj=dt_str_bj,
                status=status,
                home_team_zh=home_zh,
                away_team_zh=away_zh,
                home_score=home_score,
                away_score=away_score,
                group_stage=stage_name,
                dongqiudi_url=f"https://www.dongqiudi.com/match/{match_id}",
                home_label=home_label,
                away_label=away_label,
            )

            # Team lookup
            match.home_db_id, match.away_db_id, match.home_name_en, match.away_name_en = (
                _lookup_team_ids(home_zh, away_zh, db_path)
            )

            if match.home_db_id and match.away_db_id:
                matches.append(match)
            else:
                logger.warning(
                    "Team lookup failed: '%s'(%s) vs '%s'(%s) — match %s",
                    home_zh, match.home_db_id, away_zh, match.away_db_id, match_id,
                )

    logger.info("Fetched %d matches from dongqiudi", len(matches))
    return matches


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import os
    db = os.path.join(os.path.dirname(__file__), "..", "worldcup2026.db")
    results = fetch_schedule(db)
    for m in results[:10]:
        print(f"{m.match_time_bj} BJT | {m.status:8s} | {m.home_team_zh} {m.home_score}-{m.away_score} {m.away_team_zh} | {m.group_stage} | {m.match_time_utc}")
