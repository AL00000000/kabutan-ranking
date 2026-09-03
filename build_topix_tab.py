# -*- coding: utf-8 -*-
"""「TOPIX入替確定(推定)」タブのデータを作る。

jpx-5min-archive 側で作った推計結果(rebalance.json)を読み、対象銘柄の日足を株探から
取得して docs/data_topix/ に書き出す。

  py build_topix_tab.py            # 未取得ぶんだけ取る(再開可能)
  py build_topix_tab.py --force    # 日足を取り直す

前提: C:\\Users\\yt\\jpx-5min-archive で fetch_rebalance.py と build_rebalance.py が実行済み。
このタブは更新終了(一度きりの調査データ)なので、通常は再実行しない。
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = Path(r"C:\Users\yt\jpx-5min-archive")
REBALANCE = SRC / "docs" / "data" / "rebalance.json"
OUT = BASE / "docs" / "data_topix"
CODES = OUT / "codes"

BAR_FROM = "20250801"          # チャートは約1年分
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")}


def fetch_bars(code: str, name: str, force: bool = False) -> dict | None:
    """株探の日足を OHLCV で取って docs/data_topix/codes/<code>.json.gz に保存する。

    レスポンス1行目の2列目は市場コード(0=指数, 1=東証, 3=名証, 6=福証, 8=札証)。
    株価の除数は指数のみ100、それ以外は10。7列目は売買代金(百万円)。
    """
    p = CODES / f"{code}.json.gz"
    if p.exists() and not force:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)

    url = f"https://kabutan.jp/stock/read?c={code}&m=1&k=1"
    raw = None
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                raw = r.read().decode("utf-8", errors="replace")
            break
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1.0 + i * 1.5)
    if raw is None:
        return None

    lines = raw.strip().split("\n")
    div = 100.0 if (len(lines[0].split(",")) > 1 and lines[0].split(",")[1] == "0") else 10.0
    rows = []
    for ln in lines[1:]:
        c = ln.split(",")
        if len(c) < 7 or not c[0] or not c[4]:
            continue
        if c[0] < BAR_FROM:
            break
        try:
            rows.append((int(c[0]),
                         int(c[1]) / div if c[1] else None,
                         int(c[2]) / div if c[2] else None,
                         int(c[3]) / div if c[3] else None,
                         int(c[4]) / div,
                         int(c[5]) if c[5] else 0,
                         float(c[6]) * 1e6 if c[6] else 0.0))
        except ValueError:
            continue
    rows.sort()
    if len(rows) < 20:
        return None

    out = {"code": code, "name": name, "updated": rows[-1][0],
           "d": [r[0] for r in rows], "o": [r[1] for r in rows], "h": [r[2] for r in rows],
           "l": [r[3] for r in rows], "c": [r[4] for r in rows], "v": [r[5] for r in rows]}
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    out["_tv"] = [r[6] for r in rows]
    time.sleep(0.3)
    return out


def ret(cl: list[float], back: int) -> float | None:
    if len(cl) <= back or not cl[-back - 1]:
        return None
    return round((cl[-1] / cl[-back - 1] - 1) * 100, 2)


def ytd(days: list[int], cl: list[float]) -> float | None:
    base = next((c for d, c in zip(days, cl) if d >= 20260101), None)
    return round((cl[-1] / base - 1) * 100, 2) if base else None


def main() -> None:
    force = "--force" in sys.argv
    reb = json.loads(REBALANCE.read_text(encoding="utf-8"))
    CODES.mkdir(parents=True, exist_ok=True)

    meta = reb["meta"]
    t96 = meta["t96"]
    NG, NA = meta.get("ineligible", {}), meta.get("no_add", {})

    # 当落線上は「入る側」も「入らない側」も並べて出す。どちらか一方だけ載せると
    # 推計の誤差(浮動株比率は±20%以内が8割)が見えなくなり、断定に見えてしまうため。
    #   near    … 足切りに届かなかった候補のうち、足切りの6割以上 または 上場1年未満
    #             (上場1年未満は8月の日次平均が部分月・大株主が上場前ベースで最も当てにならない)
    #   blocked … サイズは足りているのに母集団外/新規追加見送りで入れない銘柄
    #   keep    … 継続と判定したが足切りからの距離が25%以内の現構成銘柄
    near = [x for x in reb["missed"]
            if x["code"] not in NG and x["code"] not in NA
            and (x["float_mktcap"] >= t96 * 0.6 or (x.get("months") or 12) < 12)]
    blocked = [x for x in reb["missed"]
               if x["code"] in NA or (x["code"] in NG and x["float_mktcap"] >= t96)]
    keepnear = [x for x in reb["kept"] if (x.get("margin") or 9) <= 1.25]

    total = (len(reb["added"]) + len(reb["excluded"])
             + len(near) + len(blocked) + len(keepnear))
    t0, done, miss = time.time(), 0, []

    def pack(rows: list[dict], kind: str, group: str) -> list[dict]:
        nonlocal done
        out = []
        for r in rows:
            bars = fetch_bars(r["code"], r["name"], force)
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{total}  {time.time()-t0:.0f}s", flush=True)
            if bars is None:
                miss.append(r["code"])
                continue
            cl, days = bars["c"], bars["d"]
            drop = ("monthly",) if kind == "add" else ("nonfloat", "monthly")
            row = {k: v for k, v in r.items() if k not in drop}
            row.update({"close": cl[-1], "kind": kind, "group": group,
                        "r1w": ret(cl, 5), "r1m": ret(cl, 20), "r3m": ret(cl, 60),
                        "ytd": ytd(days, cl)})
            out.append(row)
        return out

    added = (pack(reb["added"], "add", "add")
             + pack(near, "add", "near")
             + pack(blocked, "add", "blocked"))
    excluded = pack(reb["excluded"], "out", "out") + pack(keepnear, "out", "keep")

    payload = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "base_date": reb["base_date"],
        "announce_date": reb["announce_date"],
        "effective_date": reb["effective_date"],
        "meta": reb["meta"],
        "added": added,
        "excluded": excluded,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    files = list(CODES.glob("*.json.gz"))
    size = sum(p.stat().st_size for p in files)
    n = lambda rs, g: sum(1 for r in rs if r["group"] == g)
    print(f"新規採用 {n(added,'add')} / 当落線上(圏外) {n(added,'near')} / "
          f"対象外 {n(added,'blocked')}")
    print(f"除外 {n(excluded,'out')} / 当落線上(継続) {n(excluded,'keep')}  取得失敗 {len(miss)}")
    print(f"日足 {len(files)}ファイル {size/1e6:.1f}MB -> {OUT}")


if __name__ == "__main__":
    main()
