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
import csv
import glob
import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
RANK = BASE / "docs" / "data"
OUT = BASE / "docs" / "data_period"
CACHE = BASE / "cache_period" / "bars.json"
GROUPS_CSV = BASE / "groups_623.csv"
OUT623 = BASE / "docs" / "data_623"
START_623 = "2026-06-23"   # 「6.23-」タブの固定開始日

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


def load_groups():
    """groups_623.csv を {グループ名: [(コード, 銘柄名), ...]} で返す(CSVの並び順を保つ)。"""
    if not GROUPS_CSV.exists():
        return {}
    groups = {}
    with GROUPS_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            g = (row.get("グループ") or "").strip()
            code = (row.get("コード") or "").strip()
            if g and code:
                groups.setdefault(g, []).append((code, (row.get("銘柄名") or "").strip()))
    return groups


def period_return(bars, start):
    """start以降の最初の終値から最新終値までの騰落率(%)と、使った日付を返す。"""
    pts = [(d, c) for d, c, _ in bars if d >= start and c]
    if len(pts) < 2:
        return None
    (d0, c0), (d1, c1) = pts[0], pts[-1]
    if not c0:
        return None
    return (c1 / c0 - 1) * 100, d0, d1


def write_623(cache, groups):
    """「6.23-」タブ用。開始日は固定、終了日は取得できた最新営業日まで伸びる。"""
    if not groups:
        return
    # 対TOPIXは銘柄ごとに「その銘柄と同じ起点日」で計算する。
    # 6/23より後に上場した銘柄を6/23起点のTOPIXと比べると意味が壊れるため。
    tpx = {d: c for d, c, _ in (cache.get("1306") or [])}
    tpx_last = max(tpx) if tpx else None

    def excess(ret, d0):
        if not tpx_last or d0 not in tpx or not tpx[d0]:
            return None
        return round(ret - (tpx[tpx_last] / tpx[d0] - 1) * 100, 2)

    out_groups, out_stocks, end = [], [], ""
    for gi, (gname, members) in enumerate(groups.items()):
        rets = []
        for code, name in members:
            r = period_return(cache.get(code) or [], START_623)
            if r is None:
                continue
            ret, d0, d1 = r
            end = max(end, d1)
            bars = cache[code]
            tail = [c * v / 1e6 for d, c, v in bars if d >= START_623][-20:]
            tv = round(sum(tail) / len(tail), 1) if tail else 0.0
            rets.append({"code": code, "name": name, "ret": round(ret, 2),
                         "val": tv, "from": d0})
        if not rets:
            continue
        # 6/23より後に上場した銘柄は起点が自分の上場日になるため、
        # グループの集計からは外す(表には出すが色を変えて区別する)
        base = min(x["from"] for x in rets)
        onbase = [x for x in rets if x["from"] == base]
        vals = [x["ret"] for x in onbase]
        top20 = sorted(onbase, key=lambda x: -x["val"])[:20]
        out_groups.append({
            "name": gname, "n": len(onbase), "late": len(rets) - len(onbase),
            "mean": round(statistics.mean(vals), 1),
            "median": round(statistics.median(vals), 1),
            "top20": round(statistics.mean([x["ret"] for x in top20]), 1),
            "up": sum(1 for v in vals if v > 0),
            "down": sum(1 for v in vals if v < 0),
            "flat": sum(1 for v in vals if v == 0),
        })
        for x in rets:
            out_stocks.append([gi, x["code"], x["name"], x["ret"], x["val"],
                               "" if x["from"] == base else x["from"],
                               excess(x["ret"], x["from"])])

    bench = []
    for code, label in BENCH:
        r = period_return(cache.get(code) or [], START_623)
        if r:
            bench.append({"name": label, "ret": round(r[0], 1)})

    # 全グループ共通の基準起点日(6/23以降で最初に市場が開いた日)
    base_all = min((s[5] or START_623) for s in out_stocks) if out_stocks else START_623
    save_json(OUT623 / "data.json",
              {"start": START_623, "base": base_all, "end": end, "updated": end,
               "benchmarks": bench, "groups": out_groups, "stocks": out_stocks},
              compact=True)
    save_json(OUT623 / "index.json", {"updated": end, "count": len(out_stocks)})
    size = (OUT623 / "data.json").stat().st_size / 1024
    print(f"wrote 6.23- tab: {len(out_groups)} groups / {len(out_stocks)} rows "
          f"({START_623}〜{end}) {size:.0f}KB", flush=True)


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
    groups = load_groups()
    gcodes = sorted({c for members in groups.values() for c, _ in members})
    print(f"universe: {len(codes)} codes / groups: {len(gcodes)} codes "
          f"(union {len(set(codes) | set(gcodes))})", flush=True)

    cache = load_json(CACHE, {}) or {}
    if not args.no_fetch:
        targets = sorted(set(codes) | set(gcodes)) + [c for c, _ in BENCH]
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

    write_623(cache, groups)
    return 0


if __name__ == "__main__":
    sys.exit(main())
