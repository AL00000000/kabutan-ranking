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
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
RANK = BASE / "docs" / "data"
OUT = BASE / "docs" / "data_period"
CACHE = BASE / "cache_period" / "bars.json"
GROUPS_CSV = BASE / "groups_623.csv"
SHARES = BASE / "cache_period" / "shares.json"        # 発行済株式数(株探)
RAWCLOSE = BASE / "cache_period" / "raw_close.json"   # 未調整の最新終値
OUT623 = BASE / "docs" / "data_623"
START_623 = "2026-06-23"   # 「6.23-」タブの固定開始日

OUT0901 = BASE / "docs" / "data_0901"
TOPIX_SUMMARY = BASE / "docs" / "data_topix" / "summary.json"
START_0901 = "2026-08-31"  # 「9/1-」タブの起点。この日の終値を基準にするので9/1当日の値動きから乗る
PASSIVE_0901 = 0.12        # パッシブ保有 ÷ 浮動株時価総額(TOPIXのウエイトは浮動株基準なので全銘柄共通)

# 知名度で選んだ銘柄(2026-09-01時点、主観)。タブの任意フィルタに使うだけで母集団は絞らない
FAMOUS_0901 = set("""
9413 9405 4839 7860 4337 7844 3668 3632 3656 3932 6238
2211 2288 2908 2209 2804 2819 2933 2594 2266 250A 1375
7522 3561 3196 3053 3395 3193 7554 9979
9946 2698 9278 2674 3028 8281 8185 3333 2792 8244 8165
4951 4218 4574 7962 7955 6718 7952 7990
2305 6571 7823 4331 2378 4801 9470 4718 4668 4714 9795
2440 2193 2120 3660 6027 3665 3922 9474
9046 9052 9081 9726 9534 9535
6310 6445 7238 7222 6986 6222 7102
""".split())

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
       "?range=6mo&interval=1d")
JST = timezone(timedelta(hours=9))
SLEEP = 0.35
RETRY = 3

# 横断比較用のベンチマーク(指数現物は取りにくいので流動性のあるETFで代理)
BENCH = [("1306", "TOPIX"), ("1321", "日経225"), ("2516", "グロース250")]

# 時価総額 = 未調整の最新終値 × 発行済株式数。
# 株式数は株探の銘柄ページから取る。めったに変わらないので取り直しは間引く。
KABUTAN_URL = "https://kabutan.jp/stock/?code={code}"
KABUTAN_SLEEP = 0.9
SHARES_RE = re.compile(r"発行済株式数</th>\s*<td>([\d,]+)")
SHARES_MAX_AGE = 30        # 何日たったら取り直すか
SHARES_DEFAULT_LIMIT = 150 # 1回の実行で取り直す上限(日次実行を長引かせないため)

# 未調整の最新終値。fetch_bars が埋める(時価総額の計算にだけ使う)
RAW_CLOSE = {}


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


def write_0901(cache):
    """「9/1-」タブ用。2026年10月のTOPIX入替で確定除外(margin<0.80)となる銘柄の、
    8/31終値を起点とした騰落率。母集団は data_topix/summary.json が正。

    売日数(パッシブ売却総額 ÷ 60日平均売買代金)も併記する。除外は8段階に分かれるので
    1回あたりはこの1/8。指標の定義は notes の 投資/需給指標の考え方 を参照。
    """
    summary = load_json(TOPIX_SUMMARY, {})
    members = [x for x in summary.get("excluded", []) if x.get("risk") == "low"]
    if not members:
        print("skip 9/1- tab: TOPIX除外リストが読めない", flush=True)
        return

    tpx = {d: c for d, c, _ in (cache.get("1306") or [])}
    tpx_last = max(tpx) if tpx else None

    out, end = [], ""
    for x in members:
        code = x["code"]
        bars = cache.get(code) or []
        r = period_return(bars, START_0901)
        if r is None:
            continue
        ret, d0, d1 = r
        end = max(end, d1)

        # 売日数: 浮動株時価総額は8月平均ベースなので、現値との比で今の水準に直す
        recent = [(c, v) for d, c, v in bars][-60:]
        adv = sum(c * v for c, v in recent) / len(recent) if recent else 0
        aug = [c for d, c, _ in bars if d[:7] == "2026-08"]
        days = None
        if adv > 0 and aug and x.get("float_mktcap"):
            now = bars[-1][1]
            fmc = x["float_mktcap"] * now / (sum(aug) / len(aug))
            days = round(fmc * PASSIVE_0901 / adv, 1)

        ex = None
        if tpx_last and d0 in tpx and tpx[d0]:
            ex = round(ret - (tpx[tpx_last] / tpx[d0] - 1) * 100, 2)

        out.append([code, x["name"], x.get("sector", ""), round(ret, 2),
                    x.get("margin"), days, round(adv / 1e6, 1), ex,
                    1 if code in FAMOUS_0901 else 0])

    out.sort(key=lambda r: r[3])          # 昇順(下落が大きい順)
    bench = []
    for code, label in BENCH:
        r = period_return(cache.get(code) or [], START_0901)
        if r:
            bench.append({"name": label, "ret": round(r[0], 2)})

    base_day = START_0901
    save_json(OUT0901 / "data.json",
              {"start": START_0901, "base": base_day, "end": end, "updated": end,
               "count": len(out), "famous": sum(r[8] for r in out),
               "benchmarks": bench, "stocks": out}, compact=True)
    save_json(OUT0901 / "index.json", {"updated": end, "count": len(out)})
    size = (OUT0901 / "data.json").stat().st_size / 1024
    print(f"wrote 9/1- tab: {len(out)} rows ({START_0901}〜{end}) {size:.0f}KB", flush=True)


def write_623(cache, groups, caps):
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
                               excess(x["ret"], x["from"]), caps.get(x["code"])])

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
    bars, last_raw = [], None
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] is not None else c
        bars.append([datetime.fromtimestamp(t, JST).strftime("%Y-%m-%d"),
                     round(a, 2), q["volume"][i] or 0])
        last_raw = c
    if bars and last_raw:
        # 調整後終値は配当ぶん割り引かれているので、時価総額には未調整終値を使う
        RAW_CLOSE[sym.split(".")[0]] = [bars[-1][0], round(last_raw, 2)]
    return bars


KEEP_BARS = 140   # キャッシュに残す日足の本数(6か月=約123本+余裕)


def merge_bars(old, new):
    """取得できた日足で上書きしつつ、今回返ってこなかった日は消さない。

    データ提供側が直近の1日を一時的に落とすことがある(2026-08-29にYahooで発生し、
    8/28の日足が全銘柄から消えた)。単純に置き換えると、その日を永久に失って
    公開済みの数字まで巻き戻ってしまうため、日付をキーにマージする。
    分割・併合で過去の調整値が変わったときは新しい値が勝つ。"""
    if not old:
        return new[-KEEP_BARS:]
    m = {d: [d, c, v] for d, c, v in old}
    for d, c, v in new:
        m[d] = [d, c, v]
    return [m[d] for d in sorted(m)][-KEEP_BARS:]


def fetch_shares(code):
    """株探の銘柄ページから発行済株式数を取る。取れなければ None。"""
    req = urllib.request.Request(KABUTAN_URL.format(code=code),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        html = r.read().decode("utf-8", "replace")
    m = SHARES_RE.search(html)
    return int(m.group(1).replace(",", "")) if m else None


def update_shares(codes, limit):
    """発行済株式数のキャッシュを更新する。未取得の銘柄を優先し、
    古いものは limit 件までしか取り直さない(日次実行を長引かせないため)。"""
    shares = load_json(SHARES, {}) or {}
    today = datetime.now(JST).date()
    stale = []
    for code in codes:
        rec = shares.get(code)
        if not rec:
            stale.append((0, code))            # 未取得は最優先
        else:
            age = (today - to_date(rec["d"])).days
            if age >= SHARES_MAX_AGE:
                stale.append((1, code))
    stale.sort()
    todo = [c for _, c in stale][:limit]
    if not todo:
        return shares
    print(f"shares: {len(todo)} 銘柄を取得(未取得 "
          f"{sum(1 for k, _ in stale if k == 0)} / 期限切れ "
          f"{sum(1 for k, _ in stale if k == 1)})", flush=True)
    for i, code in enumerate(todo, 1):
        n = None
        for attempt in range(RETRY):
            try:
                n = fetch_shares(code)
                break
            except Exception as e:
                if attempt == RETRY - 1:
                    print(f"  FAIL shares {code}: {e}", flush=True)
                else:
                    time.sleep(2)
        # 取れなかった銘柄も日付だけ記録して、毎回叩き直さないようにする
        shares[code] = {"n": n, "d": today.isoformat()}
        time.sleep(KABUTAN_SLEEP)
        if i % 100 == 0:
            save_json(SHARES, shares, compact=True)
            print(f"  shares {i}/{len(todo)}", flush=True)
    save_json(SHARES, shares, compact=True)
    return shares


def to_date(ymd):
    y, m, d = (int(x) for x in ymd.split("-"))
    return date(y, m, d)


def market_caps(shares, raw):
    """時価総額(億円)。株式数・終値のどちらかが無ければ入れない。"""
    out = {}
    for code, rec in shares.items():
        n, r = rec.get("n"), raw.get(code)
        if n and r and r[1]:
            out[code] = round(r[1] * n / 1e8, 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true",
                    help="取得せずキャッシュから prices.json を作り直す")
    ap.add_argument("--shares-limit", type=int, default=SHARES_DEFAULT_LIMIT,
                    help="発行済株式数を取り直す上限件数(0で取得しない)")
    args = ap.parse_args()

    meta, rank = universe()
    codes = sorted(meta)
    groups = load_groups()
    gcodes = sorted({c for members in groups.values() for c, _ in members})
    # 「9/1-」タブの母集団(TOPIX確定除外)も取得対象に含める
    xcodes = sorted({x["code"] for x in (load_json(TOPIX_SUMMARY, {}).get("excluded") or [])
                     if x.get("risk") == "low"})
    print(f"universe: {len(codes)} codes / groups: {len(gcodes)} / TOPIX除外: {len(xcodes)} "
          f"(union {len(set(codes) | set(gcodes) | set(xcodes))})", flush=True)

    cache = load_json(CACHE, {}) or {}
    if not args.no_fetch:
        targets = sorted(set(codes) | set(gcodes) | set(xcodes)) + [c for c, _ in BENCH]
        for i, code in enumerate(targets, 1):
            for attempt in range(RETRY):
                try:
                    cache[code] = merge_bars(cache.get(code), fetch_bars(f"{code}.T"))
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

    # 時価総額は「6.23-」タブでしか使わないので、対象はグループ銘柄だけでよい
    shares = update_shares(gcodes, args.shares_limit) if args.shares_limit else         (load_json(SHARES, {}) or {})
    raw = load_json(RAWCLOSE, {}) or {}
    raw.update(RAW_CLOSE)
    if RAW_CLOSE:
        save_json(RAWCLOSE, raw, compact=True)
    caps = market_caps(shares, raw)
    print(f"時価総額: {len(caps)}/{len(gcodes)} 銘柄", flush=True)

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

    write_623(cache, groups, caps)
    write_0901(cache)
    return 0


if __name__ == "__main__":
    sys.exit(main())
