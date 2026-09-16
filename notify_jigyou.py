# -*- coding: utf-8 -*-
"""その日の「事業整理」開示をDiscordに通知する。

確度「低」(タイトルが『特別損失の計上』だけで、本文にも事業整理を示す語が無かったもの)は
既定では送らない。ノイズで埋まると見なくなるため。--all で全部送れる。

webhookのURLはこのリポジトリが**公開**されているためリポジトリ内に置かない。
C:\\Users\\yt\\automation\\webhooks.json (git管理外) の "jigyou_seiri" から読む。
環境変数 JIGYOU_SEIRI_WEBHOOK があればそちらを優先する。

同じ日に二重投稿しないよう state_jigyou.json に投稿済みの日付を残す。

  py notify_jigyou.py
  py notify_jigyou.py --dry-run     投稿せず内容だけ表示
  py notify_jigyou.py --force       投稿済みの日でも送る
  py notify_jigyou.py --date 2026-09-15
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

from webhook_config import get_webhook

BASE = Path(__file__).parent
DATA = BASE / "docs" / "data_jigyou"
STATE = BASE / "state_jigyou.json"
WEBHOOK_KEY = "jigyou_seiri"      # 実体は automation/webhooks.json(git管理外)
SITE = "https://al00000000.github.io/kabutan-ranking/#jigyou"
ORANGE = 0xd08b3a
MAX_FIELDS = 20                   # Discordの埋め込みは25個まで

CAT_MARK = {
    "子会社整理": "🏢", "事業譲渡・撤退": "🚪", "分割・再編": "🔀",
    "構造改革": "🛠", "人員削減": "👥", "拠点整理": "📍", "損失計上": "📉",
}


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def latest_date():
    idx = load(DATA / "index.json", {}) or {}
    dates = idx.get("dates") or []
    return dates[0] if dates else None


def build(day, include_weak):
    data = load(DATA / f"{day}.json")
    if not data:
        return None, f"{day} のデータがありません"

    items = [i for i in data["items"] if include_weak or i.get("conf") != "低"]
    if not items:
        return None, f"{day}: 通知対象なし(全{data['counts']['all']}件中、該当0件)"

    # 確度が高いもの、過去1年の回数が多いものを上に
    rank = {"高": 0, "中": 1, "保留": 2, "低": 3}
    items.sort(key=lambda i: (rank.get(i.get("conf"), 9), -i.get("repeat", 1)))

    fields = []
    for it in items[:MAX_FIELDS]:
        pdf = it.get("pdf") or {}
        bits = []
        for a in pdf.get("amounts", [])[:3]:
            bits.append(f"{a['k']} **{a['v']}**")
        if pdf.get("impact"):
            bits.append(f"業績影響: {pdf['impact']}")
        if it.get("repeat", 1) > 1:
            bits.append(f"⚠ 過去1年で{it['repeat']}回目")
        mark = "".join(CAT_MARK.get(c, "") for c in it["cats"])
        name = f"{mark} {it['code']} {it['name']}"
        if it.get("conf") in ("中", "低"):
            name += f"（確度{it['conf']}）"
        body = f"[{it['title'][:90]}]({it['url']})"
        if bits:
            body += "\n" + " / ".join(bits)
        if pdf.get("excerpt"):
            body += f"\n> {pdf['excerpt'][:110]}"
        fields.append({"name": name[:256], "value": body[:1024], "inline": False})

    c = data["counts"]
    more = f"（ほか{len(items) - MAX_FIELDS}件）" if len(items) > MAX_FIELDS else ""
    embed = {
        "title": f"事業整理の開示 {day}　{len(items)}件{more}",
        "url": SITE,
        "color": ORANGE,
        "description": (f"適時開示 全{c['all']}件から抽出"
                        + (f" / 確度低のため非表示 {c.get('weak', 0)}件" if not include_weak and c.get("weak") else "")),
        "fields": fields,
        "footer": {"text": "TDnet適時開示 / タイトルと本文の語句マッチによる機械判定"},
    }
    return {"embeds": [embed]}, f"{day}: {len(items)}件"


def post(payload, url):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--all", action="store_true", help="確度『低』も送る")
    a = ap.parse_args()

    day = a.date or latest_date()
    if not day:
        print("データがありません")
        return 0

    state = load(STATE, {}) or {}
    if not a.force and not a.dry_run and state.get("posted") == day:
        print(f"{day} は投稿済み。--force で再送できます")
        return 0

    payload, msg = build(day, a.all)
    print(msg)
    if not payload:
        return 0

    if a.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    try:
        url = get_webhook(WEBHOOK_KEY)
    except RuntimeError as e:
        # webhook未設定でタスク全体を失敗させない(データの取得と公開は済んでいるため)
        print(f"webhook未設定のため通知をスキップ: {e}")
        return 0
    post(payload, url)
    state["posted"] = day
    with STATE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    print("posted")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
