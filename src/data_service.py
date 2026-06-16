import sqlite3
import logging
import json
import math
import os
from contextlib import closing
from typing import Dict, Any, Tuple, List

logger = logging.getLogger(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'worldcup2026.db')
RANKING_DATA_PATH = os.path.join(os.path.dirname(__file__), 'power_ranking_data.json')

def get_all_data() -> Dict[str, Any]:
    """
    Fetches all core data from SQLite and returns a structured dictionary
    suitable for JSON serialization.
    """
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            with closing(conn.cursor()) as cursor:
                # Teams
                cursor.execute('SELECT * FROM Teams ORDER BY group_name, name')
                teams = {row['id']: dict(row) for row in cursor.fetchall()}
                
                # Players
                cursor.execute('SELECT * FROM Players')
                players = {row['id']: dict(row) for row in cursor.fetchall()}
                
                # Matches
                cursor.execute('''
                    SELECT 
                        m.id, m.match_time_utc, m.status, m.home_score, m.away_score, m.stadium, m.group_stage,
                        m.home_team_id, m.away_team_id, m.home_label, m.away_label,
                        t1.name as home_name, t1.name_zh as home_name_zh, t1.flag_url as home_flag,
                        t2.name as away_name, t2.name_zh as away_name_zh, t2.flag_url as away_flag
                    FROM Matches m
                    JOIN Teams t1 ON m.home_team_id = t1.id
                    JOIN Teams t2 ON m.away_team_id = t2.id
                    ORDER BY m.match_time_utc ASC
                ''')
                matches = [dict(row) for row in cursor.fetchall()]
                
                # Lineups
                cursor.execute('''
                    SELECT l.match_id, l.player_id, p.team_id, m.home_team_id, l.is_starter
                    FROM MatchLineups l
                    JOIN Players p ON l.player_id = p.id
                    JOIN Matches m ON l.match_id = m.id
                ''')
                match_lineups_data = cursor.fetchall()

                # Process matches
                for m in matches:
                    m['home_lineup'] = []
                    m['away_lineup'] = []
                    m['home_squad'] = []
                    m['away_squad'] = []
                    
                    # Squads
                    for p in players.values():
                        if p['team_id'] == m['home_team_id']:
                            m['home_squad'].append(p['id'])
                        elif p['team_id'] == m['away_team_id']:
                            m['away_squad'].append(p['id'])

                # Lineups assignment
                for row in match_lineups_data:
                    mid = row['match_id']
                    pid = row['player_id']
                    is_starter = row['is_starter']
                    match_obj = next((x for x in matches if x['id'] == mid), None)
                    if match_obj:
                        lineup_entry = {"id": pid, "is_starter": is_starter}
                        if row['team_id'] == row['home_team_id']:
                            match_obj['home_lineup'].append(lineup_entry)
                        else:
                            match_obj['away_lineup'].append(lineup_entry)
                
                # Broadcasts
                cursor.execute('SELECT match_id, platform_name, stream_url FROM Broadcasts')
                broadcasts = {}
                for row in cursor.fetchall():
                    mid = row['match_id']
                    if mid not in broadcasts:
                        broadcasts[mid] = []
                    broadcasts[mid].append(dict(row))

        return {
            "teams": teams,
            "players": players,
            "matches": matches,
            "broadcasts": broadcasts
        }
    except sqlite3.Error as e:
        logger.error(f"Database error during get_all_data: {e}")
        raise


# ── Name normalization: JSON key → possible DB names ──────────────────────

_NAME_ALIASES: Dict[str, List[str]] = {
    "Korea Republic": ["Korea Republic", "South Korea"],
    "Cote d'Ivoire": ["Cote d'Ivoire", "Ivory Coast"],
    "United States": ["United States", "USA"],
    "Czech Republic": ["Czech Republic", "Czechia"],
    "DR Congo": ["DR Congo", "Democratic Republic of the Congo"],
    "Bosnia and Herzegovina": ["Bosnia and Herzegovina", "Bosnia"],
    "Cape Verde": ["Cape Verde", "Cabo Verde"],
    "Curacao": ["Curacao", "Cura\u00e7ao"],
}


def _normalize_name(name: str) -> str:
    """Strip and normalize a team name for cross-source matching."""
    return name.strip().replace('\u00e7', 'c')


def get_power_ranking(
    db_path: str = DB_PATH,
    ranking_path: str = RANKING_DATA_PATH,
) -> List[Dict[str, Any]]:
    """
    Compute the championship probability ranking for all 48 teams.

    Five-layer data fusion:
      1. FIFA ranking (25%)
      2. Market value (25%)
      3. World Cup history (20%)
      4. Qualifying form (30%)
      5. Tournament performance (progressive 0%→65%)

    Returns a list of team ranking dicts sorted by composite_score descending.
    """
    # ── Load static data ─────────────────────────────────────────────────
    if not os.path.exists(ranking_path):
        logger.error("power_ranking_data.json not found at %s", ranking_path)
        return []

    with open(ranking_path, 'r', encoding='utf-8') as f:
        static_data = json.load(f)
    teams_static = static_data.get('teams', {})

    # ── Load DB data ─────────────────────────────────────────────────────
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            with closing(conn.cursor()) as cur:
                cur.execute('SELECT id, name, name_zh, flag_url, group_name FROM Teams')
                db_teams = {row['name']: dict(row) for row in cur.fetchall()}

                cur.execute(
                    "SELECT * FROM Matches WHERE status = 'finished'"
                )
                finished_matches = [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        logger.error("DB error during get_power_ranking: %s", e)
        return []

    # ── Build name lookup (JSON key → DB team) ───────────────────────────
    db_by_normalized = {_normalize_name(k): v for k, v in db_teams.items()}

    def _find_db_team(json_key: str):
        aliases = _NAME_ALIASES.get(json_key, [json_key])
        for alias in aliases:
            norm = _normalize_name(alias)
            if norm in db_by_normalized:
                return db_by_normalized[norm]
        # Fallback: substring match
        norm_key = _normalize_name(json_key).lower()
        for db_name, db_row in db_teams.items():
            if norm_key in _normalize_name(db_name).lower():
                return db_row
        return None

    # ── Pre-compute scalar bounds ────────────────────────────────────────
    all_elos = [t.get('elo', 1500) for t in teams_static.values()]
    max_elo = max(all_elos) if all_elos else 2200
    min_elo = min(all_elos) if all_elos else 1400
    elo_range = max_elo - min_elo if max_elo > min_elo else 1.0

    # Pre-compute market value and FIFA rank bounds
    all_mv = [t.get('market_value_eur_m', 0) for t in teams_static.values()]
    max_mv = max(all_mv) if all_mv else 1200.0
    min_mv = min(all_mv) if all_mv else 0.0
    mv_range = max_mv - min_mv if max_mv > min_mv else 1.0

    all_fifa = [t.get('fifa_rank', 211) for t in teams_static.values()]
    max_fifa = max(all_fifa) if all_fifa else 211

    # ── Historical momentum: last 6 World Cups with time-decay ────────────
    # Half-life = 8 years, exponential decay: e^(-years_since / (half_life / ln(2)))
    REFERENCE_YEAR = 2026
    HALF_LIFE = 8.0
    DECAY_LAMBDA = math.log(2) / HALF_LIFE

    HISTORY_POINTS = {
        2022: dict(champion='Argentina', runner_up='France', third='Croatia', fourth='Morocco'),
        2018: dict(champion='France', runner_up='Croatia', third='Belgium', fourth='England'),
        2014: dict(champion='Germany', runner_up='Argentina', third='Netherlands', fourth='Brazil'),
        2010: dict(champion='Spain', runner_up='Netherlands', third='Germany', fourth='Uruguay'),
        2006: dict(champion='Italy', runner_up='France', third='Germany', fourth='Portugal'),
        2002: dict(champion='Brazil', runner_up='Germany', third='Turkey', fourth='South Korea'),
    }
    FINISH_POINTS = {'champion': 10, 'runner_up': 7, 'third': 5, 'fourth': 3}

    def _compute_hist_momentum(json_key: str) -> float:
        """Time-decayed historical WC performance score (raw, un-normalized)."""
        score = 0.0
        for year, finishers in HISTORY_POINTS.items():
            decay = math.exp(-DECAY_LAMBDA * (REFERENCE_YEAR - year))
            for place, team_name in finishers.items():
                if team_name == json_key:
                    score += FINISH_POINTS[place] * decay
        return score

    # Pre-compute historical momentum for all teams
    hist_scores = {}
    for jk in teams_static:
        hist_scores[jk] = _compute_hist_momentum(jk)
    max_hist = max(hist_scores.values()) if hist_scores else 1.0
    min_hist = min(hist_scores.values()) if hist_scores else 0.0
    hist_range = max_hist - min_hist if max_hist > min_hist else 1.0

    # History tier (display only, NOT in probability calculation)
    def _history_tier(static):
        h = (static['wc_titles'] * 10 + static['wc_finals'] * 6
             + static['wc_semis'] * 4 + static['wc_quarters'] * 2
             + static['wc_appearances'] * 0.5)
        if h >= 100: return '王朝'
        elif h >= 50: return '豪强'
        elif h >= 20: return '劲旅'
        return '新锐'

    # ── Compute tournament stats per team ─────────────────────────────────
    total_games = 104  # 74 group + 32 knockout

    team_tournament: Dict[int, Dict[str, Any]] = {}
    for db_row in db_teams.values():
        tid = db_row['id']
        team_tournament[tid] = {
            'played': 0, 'wins': 0, 'draws': 0, 'losses': 0,
            'goals_for': 0, 'goals_against': 0, 'points': 0,
            'opponent_ranks': [],
        }

    # Build team_id → fifa_rank lookup for opponent quality
    tid_to_fifa: Dict[int, int] = {}
    for json_key, static in teams_static.items():
        db_team = _find_db_team(json_key)
        if db_team:
            tid_to_fifa[db_team['id']] = static['fifa_rank']

    for m in finished_matches:
        hid, aid = m['home_team_id'], m['away_team_id']
        hs, aws = m['home_score'] or 0, m['away_score'] or 0

        if hid in team_tournament:
            t = team_tournament[hid]
            t['played'] += 1
            t['goals_for'] += hs
            t['goals_against'] += aws
            if aid in tid_to_fifa:
                t['opponent_ranks'].append(tid_to_fifa[aid])
            if hs > aws:
                t['wins'] += 1
                t['points'] += 3
            elif hs == aws:
                t['draws'] += 1
                t['points'] += 1
            else:
                t['losses'] += 1

        if aid in team_tournament:
            t = team_tournament[aid]
            t['played'] += 1
            t['goals_for'] += aws
            t['goals_against'] += hs
            if hid in tid_to_fifa:
                t['opponent_ranks'].append(tid_to_fifa[hid])
            if aws > hs:
                t['wins'] += 1
                t['points'] += 3
            elif aws == hs:
                t['draws'] += 1
                t['points'] += 1
            else:
                t['losses'] += 1

    # ── Determine knockout stage for each team ────────────────────────────
    team_stage: Dict[int, str] = {}
    team_eliminated: Dict[int, bool] = {}

    knockout_stages = [
        '1/16决赛', '1/8决赛', '1/4决赛', '半决赛', '季军赛', '决赛'
    ]

    for db_row in db_teams.values():
        tid = db_row['id']
        team_stage[tid] = db_row.get('group_name', '')
        team_eliminated[tid] = False

    # Identify teams that have advanced to knockout & their stage
    for stage in knockout_stages:
        for m in finished_matches:
            if m.get('group_stage') != stage:
                continue
            hid, aid = m['home_team_id'], m['away_team_id']
            if hid in team_stage and hid not in (team_stage.keys()):
                pass
            # Winner advances to next round
            hs, aws = m['home_score'] or 0, m['away_score'] or 0
            if hs > aws:
                team_stage[hid] = stage
            elif aws > hs:
                team_stage[aid] = stage
            # Draw not possible in knockout (penalties)
            else:
                pass

    # ── Per-team computation ─────────────────────────────────────────────
    results: List[Dict[str, Any]] = []

    # Stage-based weight curve (replaces games-played linear weight)
    # Mapping: stage_name → base_weight
    STAGE_WEIGHTS = {
        '1/16决赛': 0.20,
        '1/8决赛': 0.35,
        '1/4决赛': 0.50,
        '半决赛': 0.65,
        '决赛': 0.80,
        '季军赛': 0.65,
    }

    def _get_stage_weight(tid: int) -> float:
        """Per-team weight: how much tournament performance matters."""
        current_stage = team_stage.get(tid, '')
        base = 0.0

        # Scan for the deepest knockout stage this team has reached
        for kw in ['决赛', '季军赛', '半决赛', '1/4决赛', '1/8决赛', '1/16决赛']:
            if kw in current_stage:
                base = STAGE_WEIGHTS[kw]
                break

        # Within-stage performance bonus (0.00 - 0.08)
        tstats = team_tournament.get(tid, {})
        played = tstats.get('played', 0)
        wins = tstats.get('wins', 0)
        if played > 0 and wins == played:
            bonus = 0.08
        elif wins > 0:
            bonus = 0.04
        else:
            bonus = 0.0

        # Cap: don't exceed next stage's base
        next_base = 0.80  # default cap
        for i, kw in enumerate(['决赛', '季军赛', '半决赛', '1/4决赛', '1/8决赛', '1/16决赛']):
            if kw in current_stage:
                # Next higher stage
                if i > 0:
                    next_kw = ['决赛', '季军赛', '半决赛', '1/4决赛', '1/8决赛', '1/16决赛'][i - 1]
                    next_base = STAGE_WEIGHTS[next_kw]
                break

        weight = min(base + bonus, next_base - 0.01)
        return weight

    for json_key, static in teams_static.items():
        db_team = _find_db_team(json_key)
        if not db_team:
            logger.warning("Team %s not found in DB, skipping.", json_key)
            continue

        tid = db_team['id']
        tstats = team_tournament.get(tid, {'played': 0, 'points': 0})

        # -- Multi-factor baseline (0-10) ----------------------------------
        # Factor 1: ELO (30%) — current playing strength
        elo = static.get('elo', 1500)
        elo_score = ((elo - min_elo) / elo_range) * 10.0

        # Factor 2: Historical momentum (35%) — time-decayed WC pedigree
        hist_raw = hist_scores.get(json_key, 0.0)
        hist_score = ((hist_raw - min_hist) / hist_range) * 10.0 if hist_range > 0 else 0.0

        # Factor 3: Market value (20%) — squad depth & talent
        mv = static.get('market_value_eur_m', 0.0)
        mv_score = ((mv - min_mv) / mv_range) * 10.0

        # Factor 4: FIFA rank (15%) — official ranking, inverted
        fifa_rank = static.get('fifa_rank', 211)
        fifa_score = max(0.0, ((max_fifa - fifa_rank) / max((max_fifa - 1), 1.0)) * 10.0)

        # Weighted baseline
        baseline = (0.30 * elo_score + 0.35 * hist_score
                    + 0.20 * mv_score + 0.15 * fifa_score)

        # -- History tier badge (display only, zero impact on probability) -
        hist_tier = _history_tier(static)

        # -- Layer 5: Tournament performance (0-10) ------------------------
        tp = tstats
        played = tp.get('played', 0)
        if played > 0:
            points_rate = tp['points'] / (played * 3.0)         # 0-1
            gd = tp['goals_for'] - tp['goals_against']
            gd_per_game = gd / played
            # Map GD/game to 0-10 (typical range -3 to +3)
            gd_score = max(0.0, min(10.0, (gd_per_game + 3.0) / 6.0 * 10.0))
            gf_per_game = tp['goals_for'] / played
            gf_score = min(10.0, (gf_per_game / 4.0) * 10.0)

            # Opponent quality: avg opponent ELO → 0-10 scale
            opp_ranks = tp.get('opponent_ranks', [])
            if opp_ranks:
                # Convert FIFA ranks to approximated ELO for quality scoring
                # Higher ELO = stronger opponent → higher score
                avg_opp_elo = sum(
                    min_elo + (max_elo - min_elo) * (1.0 - (r - 1.0) / 210.0)
                    for r in opp_ranks
                ) / len(opp_ranks)
                opp_score = max(0.0, min(10.0, (avg_opp_elo - min_elo) / elo_range * 10.0))
            else:
                opp_score = 5.0

            # Weight opponent quality by games played (1 game = 0.05, 3 games = 0.15)
            opp_weight = min(0.20, played * 0.05)
            points_weight = 0.4 - opp_weight * 0.5
            gd_weight = 0.3

            group_perf = (points_weight * points_rate * 10.0
                          + gd_weight * gd_score
                          + 0.2 * gf_score
                          + opp_weight * opp_score)

            # Single-game anti-blowout cap
            if played == 1:
                group_perf = min(group_perf, 6.5)
            elif played == 2:
                group_perf = min(group_perf, 8.0)

            # Knockout bonus
            stage = team_stage.get(tid, '')
            knockout_bonus = 0.0
            if '1/16决赛' in stage:
                knockout_bonus += 0.5
            if '1/8决赛' in stage:
                knockout_bonus += 1.0
            if '1/4决赛' in stage:
                knockout_bonus += 2.0
            if '半决赛' in stage:
                knockout_bonus += 2.0
            if '决赛' in stage:
                knockout_bonus += 3.0

            tournament_perf = min(10.0, group_perf + knockout_bonus)
        else:
            tournament_perf = 0.0

        stage_weight = _get_stage_weight(tid)

        # -- Composite: progressive weighting ------------------------------
        composite = ((1.0 - stage_weight) * baseline
                     + stage_weight * tournament_perf)

        # -- Tier classification -------------------------------------------
        if composite >= 8.0:
            tier = 'Elite'
        elif composite >= 6.5:
            tier = 'Contender'
        elif composite >= 5.0:
            tier = 'Dark Horse'
        else:
            tier = 'Underdog'

        # -- Determine elimination status ----------------------------------
        eliminated = False
        if played >= 3:
            # Check if team played in group stage and didn't qualify
            # A team is eliminated if all 3 group games are done
            # and they're not in any knockout stage
            in_knockout = any(
                k in team_stage.get(tid, '') for k in knockout_stages
            )
            if (tstats.get('losses', 0) >= 3 or
                    (played >= 3 and not in_knockout
                     and not db_team.get('group_name', '').startswith('1/'))):
                # Heuristic: if played 3+ games and not visibly in knockout,
                # may be eliminated.  More precise: check group standings.
                # For now, mark as eliminated only if 3 losses.
                if tstats.get('losses', 0) >= 3:
                    eliminated = True

        # Build result entry
        results.append({
            'team_id': tid,
            'name_zh': db_team['name_zh'],
            'name_en': db_team['name'],
            'flag_url': db_team['flag_url'],
            'group_name': db_team.get('group_name', ''),
            'elo_rating': elo,
            'elo_score': round(elo_score, 2),
            'hist_momentum_score': round(hist_score, 2),
            'market_value_score': round(mv_score, 2),
            'fifa_rank_score': round(fifa_score, 2),
            'tournament_score': round(tournament_perf, 2) if played > 0 else 0,
            'composite_score': round(composite, 2),
            'stage_weight': round(stage_weight, 2),
            'played': played,
            'points': tstats['points'],
            'goals_for': tstats['goals_for'],
            'goals_against': tstats['goals_against'],
            'tier': tier,
            'history_badge': hist_tier,
            'eliminated': eliminated,
            'stage': team_stage.get(tid, ''),
        })

    # ── Sort by composite descending ──────────────────────────────────────
    results.sort(key=lambda x: x['composite_score'], reverse=True)

    # ── Temperature-scaled softmax → championship probability (%) ───────────
    # Tournament uncertainty: in a 48-team knockout, even the best team
    # faces ~25% upset risk per round. T=2.5 flattens the distribution.
    scores = [r['composite_score'] for r in results]
    max_score = max(scores) if scores else 1.0
    temperature = 2.5
    exp_scores = [math.exp((s - max_score) / temperature) for s in scores]
    total_exp = sum(exp_scores) or 1.0

    for i, r in enumerate(results):
        prob = (exp_scores[i] / total_exp) * 100.0
        r['rank'] = i + 1
        r['championship_probability'] = round(prob, 2)
        # Zero out eliminated teams
        if r['eliminated']:
            r['championship_probability'] = 0.0

    return results


# ── Player Rating (0-100) ────────────────────────────────────────────────

def get_player_ratings(db_path: str = DB_PATH) -> Dict[int, int]:
    """
    Compute a 0-100 rating for every player in the database.

    Formula: team_quality_baseline + star_bonus + tournament_form
    - Team quality: scaled from ELO (50-85 range)
    - Star bonus: known world-class players get +5 to +15
    - Tournament form: +goals×3 + assists×1.5 (cap +15)

    Returns dict: {player_id: rating}
    """
    try:
        # Load team ELO from power_ranking_data.json
        elo_data: Dict[str, int] = {}
        if os.path.exists(RANKING_DATA_PATH):
            with open(RANKING_DATA_PATH, 'r', encoding='utf-8') as f:
                static = json.load(f)
            for name, t in static.get('teams', {}).items():
                elo_data[name] = t.get('elo', 1500)

        all_elos = list(elo_data.values())
        min_elo = min(all_elos) if all_elos else 1400
        max_elo = max(all_elos) if all_elos else 2200
        elo_range = max_elo - min_elo if max_elo > min_elo else 1.0

        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            with closing(conn.cursor()) as cur:
                cur.execute(
                    "SELECT p.id, p.team_id, p.name_en, p.name_zh, p.position, "
                    "p.jersey_number, p.profile_url, p.description, "
                    "p.tournament_goals, p.tournament_assists, "
                    "t.name as team_name, t.name_zh as team_name_zh, t.flag_url as team_flag "
                    "FROM Players p JOIN Teams t ON p.team_id = t.id"
                )
                players = [dict(row) for row in cur.fetchall()]

        # Known star players (from STAR_ZH + additional world-class)
        _STARS: Dict[str, int] = {
            # Elite: +15
            'Lionel Messi': 15, 'Kylian Mbappé': 15, 'Erling Haaland': 15,
            'Vinícius Júnior': 15, 'Jude Bellingham': 15, 'Kevin De Bruyne': 15,
            'Mohamed Salah': 15, 'Harry Kane': 15, 'Cristiano Ronaldo': 15,
            'Rodri': 15, 'Jamal Musiala': 15, 'Florian Wirtz': 15,
            # Tier 1: +12
            'Lamine Yamal': 12, 'Bukayo Saka': 12, 'Pedri': 12, 'Gavi': 12,
            'Phil Foden': 12, 'Declan Rice': 12, 'Rúben Dias': 12,
            'Virgil van Dijk': 12, 'Martin Ødegaard': 12, 'Federico Valverde': 12,
            'Lautaro Martínez': 12, 'Julián Álvarez': 12, 'Rafael Leão': 12,
            'Ousmane Dembélé': 12, 'Neymar': 12, 'Bruno Fernandes': 12,
            'Bernardo Silva': 12, 'William Saliba': 12, 'Aurélien Tchouaméni': 12,
            'Antonio Rüdiger': 12, 'Thibaut Courtois': 12, 'Alisson': 12,
            'Manuel Neuer': 12, 'Mike Maignan': 12, 'Emiliano Martínez': 12,
            # Tier 2: +8
            'Son Heungmin': 8, 'Achraf Hakimi': 8, 'Alphonso Davies': 8,
            'Raphinha': 8, 'Gabriel Martinelli': 8, 'Rodrigo De Paul': 8,
            'Enzo Fernández': 8, 'Alexis Mac Allister': 8, 'Cody Gakpo': 8,
            'Memphis Depay': 8, 'Frenkie de Jong': 8, 'Jeremy Doku': 8,
            'Romelu Lukaku': 8, 'Luka Modric': 8, 'Darwin Núñez': 8,
            'Viktor Gyökeres': 8, 'Alexander Isak': 8, 'Luis Díaz': 8,
            'Ronald Araujo': 8, 'Takefusa Kubo': 8, 'Kim Minjae': 8,
            'Kai Havertz': 8, 'Leroy Sané': 8, 'Nico Williams': 8,
            'Dani Olmo': 8, 'João Félix': 8, 'Christian Pulisic': 8,
            "Joshua Kimmich": 8, "James Rodríguez": 8, "N Golo Kanté": 8,
            'Sadio Mané': 8, 'Kalidou Koulibaly': 8,
            # Tier 3: +5
            'Weston McKennie': 5, 'Gio Reyna': 5, 'Ederson': 5,
            'Casemiro': 5, 'Bruno Guimarães': 5, 'Marquinhos': 5,
            'Lisandro Martínez': 5, 'Nicolás Otamendi': 5, 'John Stones': 5,
            'Granit Xhaka': 5, 'Manuel Akanji': 5, 'Mateo Kovacic': 5,
            'Josko Gvardiol': 5, 'Dominik Livakovic': 5, 'Jonathan David': 5,
            'Ismael Saibari': 5, 'Yassine Bounou': 5, 'Brahim Díaz': 5,
        }

        ratings: Dict[int, int] = {}
        ranking: List[Dict[str, Any]] = []
        for p in players:
            pid = p['id']
            name_en = p['name_en'] or ''
            team_name = p['team_name'] or ''
            elo = elo_data.get(team_name, 1500)

            # -- Team quality baseline (50-85) ---------------------------------
            team_score = 50 + ((elo - min_elo) / elo_range) * 35

            # -- Position adjustment (±3) -------------------------------------
            pos = (p['position'] or '').upper()
            pos_adj = {'FW': 3, 'MF': 1, 'DF': -1, 'GK': -3}.get(pos, 0)

            # -- Star bonus (0-15) --------------------------------------------
            star_bonus = _STARS.get(name_en, 0)

            # -- Tournament form (0-15) ---------------------------------------
            goals = p['tournament_goals'] or 0
            assists = p['tournament_assists'] or 0
            tourney_bonus = min(15, goals * 3 + assists * 1.5)

            # -- Composite (0-100) --------------------------------------------
            rating = int(round(team_score + pos_adj + star_bonus + tourney_bonus))
            rating = max(25, min(99, rating))
            ratings[pid] = rating

            ranking.append({
                'player_id': pid,
                'name_en': p['name_en'] or '',
                'name_zh': p['name_zh'] or '',
                'position': pos or '',
                'jersey_number': p['jersey_number'],
                'profile_url': p['profile_url'] or '',
                'team_name': team_name,
                'team_name_zh': p['team_name_zh'] or '',
                'team_flag': p['team_flag'] or '',
                'tournament_goals': goals,
                'tournament_assists': assists,
                'rating': rating,
            })

        # Sort descending by rating
        ranking.sort(key=lambda x: x['rating'], reverse=True)

        return {'ratings': ratings, 'ranking': ranking}

    except sqlite3.Error as e:
        logger.error("Player rating DB error: %s", e)
        return {}
