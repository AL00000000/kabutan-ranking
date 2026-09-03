# -*- coding: utf-8 -*-
"""「9/1-」タブ(TOPIX確定除外銘柄の騰落率)のワーストTOP10をDiscordに通知する。

fetch_period.py が書いた docs/data_0901/data.json を読むだけで、取得はしない。
そのため必ず fetch_period.py の後に実行する(tasks.json の period-returns に相乗り)。

同じ日のデータで二重に鳴らさないよう、最後に通知した end 日を state に持つ。
--force で無視して送る。

使用例:
  py notify_0901.py
  py notify_0901.py --dry-run
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

from webhook_config import get_webhook

BASE = Path(__file__).parent
DATA = BASE / "docs" / "data_0901" / "data.json"
STATE = BASE / "state_0901.json"
WEBHOOK_KEY = "d0901"      # 実体は automation/webhooks.json(git管理外)
SITE = "https://al00000000.github.io/kabutan-ranking/"
TOP_N = 10
RED, BLUE, GRAY = 0xff5b6a, 0x4da3ff, 0x99aab5


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def post(payload, dry):
    if dry:
        print("--- DRY RUN (未送信) ---")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    # Discord は User-Agent の無いリクエストを403で弾くので必ず付ける
    req = urllib.request.Request(
        get_webhook(WEBHOOK_KEY), data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": "kabutan-ranking-bot/1.0 (+https://al00000000.github.io/kabutan-ranking/)"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status >= 300:
            raise RuntimeError(f"HTTP {r.status}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="同じ日でも再送する")
    args = ap.parse_args()

    d = load(DATA)
    if not d or not d.get("stocks"):
        print("data_0901/data.json が無いか空。fetch_period.py を先に実行する", file=sys.stderr)
        return 1

    end = d.get("end", "")
    state = load(STATE, {}) or {}
    if not args.force and not args.dry_run and state.get("last") == end:
        print(f"skip: {end} は通知済み")
        return 0

    # data.json は既に騰落率の昇順。null は末尾に寄せてある
    rows = [r for r in d["stocks"] if r[3] is not None][:TOP_N]
    lines = []
    for i, r in enumerate(rows, 1):
        code, name, sec, ret, margin, days = r[0], r[1], r[2], r[3], r[4], r[5]
        tail = []
        if days is not None:
            tail.append(f"売日数{days:.0f}日")
        if margin is not None:
            tail.append(f"margin{margin:.2f}")
        lines.append(
            f"**{i}. {ret:+.2f}%**　[{code} {name}](https://kabutan.jp/stock/?code={code})"
            + (f"\n　　{sec}　" + " / ".join(tail) if tail else ""))

    def stats(xs):
        if not xs:
            return None, None
        s = sorted(xs)
        n = len(s)
        med = s[(n - 1) // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
        return med, sum(s) / n

    med, avg = stats([r[3] for r in d["stocks"] if r[3] is not None])
    emed, eavg = stats([r[7] for r in d["stocks"] if r[7] is not None])
    # ベンチマークは連動ETF1本の騰落率。単一系列なので中央値/平均の区別は無い
    bench = "　".join(f"{b['name']}連動ETF({b.get('code', '')}) {b['ret']:+.2f}%"
                      for b in (d.get("benchmarks") or []))
    worst = rows[0][3] if rows else 0.0

    payload = {
        # スマホのプッシュは先頭しか出ないので、要点を1行だけ短く置く
        "content": f"TOPIX除外 下落TOP10: 1位 {rows[0][1]} {worst:+.1f}%" if rows else "TOPIX除外",
        "embeds": [{
            "title": f"📉 TOPIX確定除外 値下がりTOP{len(rows)}（{d['start']}〜{end}）",
            "url": SITE,
            "description": "\n".join(lines),
            "color": RED if worst < 0 else BLUE,
            "fields": [
                {"name": f"騰落率（対象{d.get('count')}銘柄）", "inline": True,
                 "value": f"中央値 **{med:+.2f}%**\n平均値 **{avg:+.2f}%**"},
                {"name": "対TOPIX（超過リターン）", "inline": True,
                 "value": f"中央値 **{emed:+.2f}%**\n平均値 **{eavg:+.2f}%**"},
            ],
            "footer": {"text": f"比較対象は連動ETFの騰落率（ETF1本なので中央値/平均の区別なし）"
                               f"　|　{bench}"},
        }],
    }
    post(payload, args.dry_run)
    if not args.dry_run:
        state["last"] = end
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        print(f"sent ({end}) worst={rows[0][0]} {worst:+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
