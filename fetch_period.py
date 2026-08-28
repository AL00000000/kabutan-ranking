# -*- coding: utf-8 -*-
"""売買代金ランキングに登場した全銘柄の日足終値(分割調整済み)を集めて
「期間騰落率」タブ用の1ファイルにまとめる。

対象銘柄 = docs/data/*.json(保存済みの売買代金ランキング全日分)に一度でも
登場したコードの和集合。ランキングは上位500位までなので、日によって顔ぶれが
入れ替わる。和集合を使うことで「期間の途中まで上位だったが今は圏外」という
銘柄も拾える。

出力:
  docs/data_period/prices.json … {updated, dates[], stocks{code:{n,m,r,tv,c[]}}, bench{}}
  docs/data_period/index.json  … {"updated": "YYYY-MM-DD"}(NEWバッジ/最終更新日の判定用。
                                  prices.json は1MB近いのでタブ見出しの判定では読まない)

Yahoo は分割調整済み終値(adjclose)を返すため、期間中に分割があった銘柄も
騰落率が壊れない。毎回6か月ぶんを取り直すのは、過去分の調整値が後から
変わる(分割・併合)のを自動で取り込むため。

使用例:
  py fetch_period.py             … 取得して書き出し(日次実行)
  py fetch_period.py --no-fetch  … キャッシュのまま prices.json を作り直す
"""
import argparse
import glob
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
RANK = BASE / "docs" / "data"
OUT = BASE / "docs" / "data_period"
CACHE = BASE / "cache_period" / "bars.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
       "?range=6mo&interval=1d")
JST = timezone(timedelta(hours=9))
SLEEP = 0.35
RETRY = 3

# 横断比較用のベンチマーク(指数現物は取りにくいので流動性のあるETFで代理)
BENCH = [("1306", "TOPIX"), ("1321", "日経225"), ("2516", "グロース250")]


def compact_price(v):
    """JSONを軽くするため、終値は小数1桁に丸め、整数なら整数で書く。
    全銘柄×半年ぶんを1ファイルで配るので、1数値あたり数文字の差がMB単位で効く。"""
    r = round(v, 1)
    return int(r) if r == int(r) else r


def load_json(path, default=None):
    if not Path(path).exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def universe():
    """ランキング保存分の和集合。あわせて最新日の売買代金順位も返す。"""
    meta, rank = {}, {}
    files = sorted(glob.glob(str(RANK / "*.json")))
    for p in files:
        if Path(p).name == "index.json":
            continue
        d = load_json(p, {})
        for r in d.get("stocks", []):
            meta[r["code"]] = {"name": r["name"], "market": r.get("market", "")}
    latest = [p for p in files if Path(p).name != "index.json"]
    if latest:
        for r in load_json(latest[-1], {}).get("stocks", []):
            rank[r["code"]] = r.get("rank")
    return meta, rank


def fetch_bars(sym):
    """[[YYYY-MM-DD, 調整後終値, 出来高], ...] を返す。"""
    req = urllib.request.Request(URL.format(sym=sym), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        j = json.load(r)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] is not None else c
        bars.append([datetime.fromtimestamp(t, JST).strftime("%Y-%m-%d"),
                     round(a, 2), q["volume"][i] or 0])
    return bars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true",
                    help="取得せずキャッシュから prices.json を作り直す")
    args = ap.parse_args()

    meta, rank = universe()
    codes = sorted(meta)
    print(f"universe: {len(codes)} codes", flush=True)

    cache = load_json(CACHE, {}) or {}
    if not args.no_fetch:
        targets = codes + [c for c, _ in BENCH]
        for i, code in enumerate(targets, 1):
            for attempt in range(RETRY):
                try:
                    cache[code] = fetch_bars(f"{code}.T")
                    break
                except Exception as e:
                    if attempt == RETRY - 1:
                        print(f"FAIL {code}: {e}", flush=True)
                    else:
                        time.sleep(2)
            time.sleep(SLEEP)
            if i % 100 == 0:
                save_json(CACHE, cache, compact=True)
                print(f"{i}/{len(targets)}", flush=True)
        save_json(CACHE, cache, compact=True)

    # 全銘柄の営業日を統合(ETFしか動かない日などは無いが、念のため和集合)
    dates = sorted({b[0] for code in codes for b in cache.get(code, [])})
    if not dates:
        print("no data", file=sys.stderr)
        return 1
    idx = {d: i for i, d in enumerate(dates)}

    stocks = {}
    for code in codes:
        bars = cache.get(code) or []
        if not bars:
            continue
        closes = [None] * len(dates)
        turn = []          # 直近20営業日の売買代金(百万円)
        for d, c, v in bars:
            if d in idx:
                closes[idx[d]] = compact_price(c)
                turn.append(c * v / 1e6)
        row = {"n": meta[code]["name"], "m": meta[code]["market"], "c": closes}
        if rank.get(code):
            row["r"] = rank[code]
        if turn:
            row["tv"] = round(sum(turn[-20:]) / len(turn[-20:]), 1)
        stocks[code] = row

    bench = {}
    for code, label in BENCH:
        bars = cache.get(code) or []
        if not bars:
            continue
        closes = [None] * len(dates)
        for d, c, _ in bars:
            if d in idx:
                closes[idx[d]] = compact_price(c)
        bench[code] = {"n": label, "c": closes}

    updated = dates[-1]
    save_json(OUT / "prices.json",
              {"updated": updated, "dates": dates, "stocks": stocks, "bench": bench},
              compact=True)
    save_json(OUT / "index.json", {"updated": updated, "count": len(stocks)})
    size = (OUT / "prices.json").stat().st_size / 1e6
    print(f"wrote {len(stocks)} stocks / {len(dates)} days "
          f"({dates[0]}〜{dates[-1]}) {size:.2f}MB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
