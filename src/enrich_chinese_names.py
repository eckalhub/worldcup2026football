"""
从 zh.wikipedia 搜索 API 批量获取球员简体中文名。
支持断点续传 (保存进度到 tempfiles/enrich_progress.json)。
"""

import sqlite3
import requests
import time
import re
import json
import os
import unicodedata
from opencc import OpenCC

T2S = OpenCC("t2s")


def normalize(name):
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return n.lower().strip()


def load_squad_titles():
    """从 26worldcup squads.json 提取所有球员 Wikipedia 标题。"""
    print("[1/4] 加载 Wikipedia 标题...")
    r = requests.get(
        "https://raw.githubusercontent.com/26worldcup/26worldcup.github.io/main/public/data/squads.json",
        timeout=30,
    )
    squads = r.json()

    titles_map = {}
    for code, squad in squads.items():
        for sp in squad.get("players", []):
            wiki_url = sp.get("wiki", "")
            if not wiki_url:
                continue
            match = re.search(r"/wiki/(.+?)(?:#|$)", wiki_url)
            if match:
                title = requests.utils.unquote(match.group(1))
                titles_map[title] = {
                    "team_code": code,
                    "jersey": sp.get("no", 0),
                    "name": sp.get("name", ""),
                }

    print(f"  提取了 {len(titles_map)} 个唯一 Wikipedia 条目")
    return titles_map


def match_to_db(db, squad_titles):
    """将 squad_titles 匹配到数据库球员。"""
    print("[2/4] 匹配数据库球员...")

    teams_raw = requests.get(
        "https://raw.githubusercontent.com/26worldcup/26worldcup.github.io/main/public/data/teams.json",
        timeout=30,
    ).json()
    teams_data = teams_raw.get("teams", teams_raw)
    code_to_cn = {c: i.get("name", {}).get("zh", "") for c, i in teams_data.items()}

    db_teams = db.execute("SELECT id, name_zh FROM Teams WHERE id > 0").fetchall()
    cn_to_db_id = {t["name_zh"]: t["id"] for t in db_teams}

    all_players = db.execute(
        "SELECT id, team_id, name_en, name_zh, jersey_number FROM Players"
    ).fetchall()
    db_by_team = {}
    for p in all_players:
        db_by_team.setdefault(p["team_id"], []).append(p)

    to_enrich = []
    for wiki_title, info in squad_titles.items():
        cn_team = code_to_cn.get(info["team_code"], "")
        if not cn_team or cn_team not in cn_to_db_id:
            continue

        db_team_id = cn_to_db_id[cn_team]
        db_players = db_by_team.get(db_team_id, [])

        matched = None
        jersey_no = info["jersey"]

        for dp in db_players:
            if dp["jersey_number"] == jersey_no and jersey_no > 0:
                matched = dp
                break

        if not matched:
            sp_name = normalize(info["name"])
            for dp in db_players:
                n_db = normalize(dp["name_en"])
                if sp_name == n_db:
                    matched = dp
                    break
                for part in n_db.split(","):
                    if part.strip() == sp_name:
                        matched = dp
                        break
                if matched:
                    break

        if matched:
            to_enrich.append(
                {
                    "db_id": matched["id"],
                    "name_en": matched["name_en"],
                    "name_zh_old": matched["name_zh"],
                    "wiki_title": wiki_title,
                    "jersey": jersey_no,
                    "db_jersey": matched["jersey_number"],
                }
            )

    print(f"  匹配了 {len(to_enrich)} 名球员")
    return to_enrich


def load_progress():
    """加载已保存的进度。"""
    try:
        with open("tempfiles/enrich_progress.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_progress(progress):
    """保存进度到文件。"""
    os.makedirs("tempfiles", exist_ok=True)
    with open("tempfiles/enrich_progress.json", "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def search_chinese_names(to_enrich):
    """用 zh.wikipedia search API 获取中文名。"""
    print(f"[3/4] zh.wikipedia 搜索中文名...")

    progress = load_progress()
    chinese_names = progress.get("chinese_names", {})
    last_idx = progress.get("last_idx", 0)

    total = len(to_enrich)
    found_start = len([v for v in chinese_names.values() if v])
    print(f"  总: {total}, 上次进度: {last_idx}, 已有: {found_start}")

    for idx in range(last_idx, total):
        item = to_enrich[idx]
        wiki_title = item["wiki_title"]

        if wiki_title in chinese_names:
            continue

        time.sleep(0.8)

        try:
            resp = requests.get(
                "https://zh.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": wiki_title.replace("_", " "),
                    "srlimit": 1,
                    "format": "json",
                },
                headers={"User-Agent": "WorldCup2026/1.0"},
                timeout=15,
            )

            if resp.status_code == 200:
                data = resp.json()
                results = data.get("query", {}).get("search", [])
                if results:
                    cn_title = results[0]["title"]
                    if any("\u4e00" <= c <= "\u9fff" for c in cn_title):
                        chinese_names[wiki_title] = T2S.convert(cn_title)
                    else:
                        chinese_names[wiki_title] = None
                else:
                    chinese_names[wiki_title] = None
            else:
                chinese_names[wiki_title] = None
        except Exception:
            chinese_names[wiki_title] = None

        if (idx + 1) % 50 == 0:
            found = len([v for v in chinese_names.values() if v])
            progress["chinese_names"] = chinese_names
            progress["last_idx"] = idx + 1
            save_progress(progress)
            print(f"  进度: {idx+1}/{total}, 已获取 {found} 个")

    progress["chinese_names"] = chinese_names
    progress["last_idx"] = total
    save_progress(progress)

    found_end = len([v for v in chinese_names.values() if v])
    print(f"  完成: {found_end}/{total}")
    return chinese_names


def update_db(db, to_enrich, chinese_names):
    """更新数据库。"""
    print("[4/4] 更新数据库...")
    updated_zh = 0
    updated_jersey = 0

    for item in to_enrich:
        zh_name = chinese_names.get(item["wiki_title"])
        if zh_name and zh_name != item["name_zh_old"]:
            db.execute(
                "UPDATE Players SET name_zh = ? WHERE id = ?",
                (zh_name, item["db_id"]),
            )
            updated_zh += 1

        if item.get("jersey", 0) > 0 and item.get("db_jersey", 0) == 0:
            db.execute(
                "UPDATE Players SET jersey_number = ? WHERE id = ?",
                (item["jersey"], item["db_id"]),
            )
            updated_jersey += 1

    db.commit()
    print(f"  中文名: +{updated_zh}, 球衣号: +{updated_jersey}")
    return updated_zh


def main():
    db = sqlite3.connect("worldcup2026.db")
    db.row_factory = sqlite3.Row

    try:
        total = db.execute("SELECT COUNT(*) FROM Players").fetchone()[0]
        need_zh = db.execute(
            "SELECT COUNT(*) FROM Players WHERE name_zh = name_en"
        ).fetchone()[0]
        print(f"更新前: {need_zh}/{total} 球员中文名缺失\n")

        squad_titles = load_squad_titles()
        to_enrich = match_to_db(db, squad_titles)
        chinese_names = search_chinese_names(to_enrich)
        updated = update_db(db, to_enrich, chinese_names)

        still_need = db.execute(
            "SELECT COUNT(*) FROM Players WHERE name_zh = name_en"
        ).fetchone()[0]
        print(f"\n更新后: {still_need}/{total} 中文名缺失, 改善了 {need_zh - still_need}")

        if need_zh - still_need > 0:
            samples = db.execute(
                "SELECT name_en, name_zh FROM Players WHERE name_zh != name_en LIMIT 15"
            ).fetchall()
            print("\n=== 更新样例 ===")
            for s in samples:
                print(f"  {s['name_en']:30s} -> {s['name_zh']}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
