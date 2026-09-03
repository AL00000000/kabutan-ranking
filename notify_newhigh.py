# -*- coding: utf-8 -*-
"""その日の**上場来新高値**銘柄をDiscordに通知する。52週だけの更新は通知しない。

webhookのURLはこのリポジトリが公開されているため**リポジトリ内に置かない**。
C:\\Users\\yt\\automation\\webhooks.json (git管理外) の "newhigh_ath" から読む。
環境変数 NEWHIGH_WEBHOOK があればそちらを優先する。

同じ日に二重投稿しないよう state_newhigh.json に投稿済みの日付を残す(gitignore済み)。

使用例:
  py notify_newhigh.py
  py notify_newhigh.py --dry-run    … 投稿せず内容だけ表示
  py notify_newhigh.py --force      … 投稿済みの日でも送る
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "docs" / "data_newhigh"
STATE = BASE / "state_newhigh.json"
WEBHOOK_FILE = Path(r"C:\Users\yt\automation\webhooks.json")
WEBHOOK_KEY = "newhigh_ath"
SITE = "https://al00000000.github.io/kabutan-ranking/"
CYAN = 0x39c5cf
MAX_FIELDS = 20          # Discordの埋め込みは25個まで


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def webhook_url():
    env = os.environ.get("NEWHIGH_WEBHOOK")
    if env:
        return env
    cfg = load(WEBHOOK_FILE, {}) or {}
    url = cfg.get(WEBHOOK_KEY)
    if not url:
        raise RuntimeError(
            f"webhookが見つかりません。{WEBHOOK_FILE} の \"{WEBHOOK_KEY}\" に設定してください")
    return url


def fmt_oku(hyakuman):
    if hyakuman is None:
        return "-"
    oku = hyakuman / 100
    if oku < 1:
        return f"{hyakuman:,.0f}百万円"
    if oku < 10:
        return f"{oku:.1f}億円"
    return f"{oku:,.0f}億円"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    idx = load(DATA / "index.json")
    if not idx or not idx.get("dates"):
        print("データがありません", file=sys.stderr)
        return 1
    day = idx["dates"][0]
    data = load(DATA / f"{day}.json")
    if not data:
        print(f"{day} のデータを読めません", file=sys.stderr)
        return 1

    state = load(STATE, {}) or {}
    if state.get("last") == day and not args.force and not args.dry_run:
        print(f"skip: {day} は通知済み")
        return 0

    ath = [s for s in data.get("stocks", []) if s.get("ath")]
    ath.sort(key=lambda s: -(s.get("value") or 0))
    if not ath:
        print(f"{day}: 上場来新高値なし。通知しない")
        if not args.dry_run:
            state["last"] = day
            STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return 0

    fields = []
    for s in ath[:MAX_FIELDS]:
        sub = [f"終値 {s['close']:,.1f}（{s['change_pct']:+.2f}%）",
               f"売買代金 {fmt_oku(s.get('value'))}"]
        if s.get("ath_break_pct") is not None:
            sub.append(f"前の上場来高値 {s['prev_ath']:,.1f} を {s['ath_break_pct']:+.2f}%更新")
        if s.get("ath_since"):
            sub.append(f"遡れる範囲 {s['ath_since']}〜")
        if s.get("close_break"):
            sub.append("終値ベースでも更新")
        fields.append({
            "name": f"{s['name']}（{s['code']}・{s['market']}）",
            "value": " / ".join(sub),
            "inline": False,
        })

    more = len(ath) - len(fields)
    embed = {
        "title": f"上場来新高値 {len(ath)}銘柄（{day}）",
        "url": SITE,
        "color": CYAN,
        "fields": fields,
        "footer": {"text": ("売買代金10億円以上・東証3市場が母集団"
                            + (f" / ほか{more}銘柄" if more > 0 else ""))},
    }
    payload = {"embeds": [embed]}

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    # Discord は User-Agent の無いリクエストを403で弾くので必ず付ける
    req = urllib.request.Request(
        webhook_url(), data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": "kabutan-ranking-bot/1.0 "
                               "(+https://al00000000.github.io/kabutan-ranking/)"},
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        code = r.status
    state["last"] = day
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"通知しました（HTTP {code}）: {day} 上場来新高値 {len(ath)}銘柄")
    return 0


if __name__ == "__main__":
    sys.exit(main())
