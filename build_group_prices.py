# -*- coding: utf-8 -*-
"""「期間騰落率 > グループ別」用の株価ファイルを作る。

期間騰落率タブは **開始日と終了日を自由に選べる** のが売りなので、グループ別も
サーバ側で起点日を決め打ちして書き出すのではなく、**株価をそのまま渡して
ブラウザ側で任意の期間を計算できる形** にする。6/23起点も9/1起点も
「期間プルダウンのプリセット」でしかない、という作りにそろえるため。

docs/data_period/prices.json との違い:
  - 母集団が違う。あちらは売買代金ランキングに載った銘柄(約1,000)だけで、
    グループには載らない小型株(TOPIX除外候補など)が多く含まれる
  - 期間が長い。2024-06-19まで遡る(あちらは直近半年ぶん)

日足の集め方:
  1. cache_bars_5y/<code>.json (新高値バックフィルと共用。Yahooの5年ぶん)
  2. 無ければYahooから取得して同じ場所に保存する
  3. 直近ぶんは cache_period/bars.json(毎日更新されている)で上書きする
     → 5年キャッシュが数週間古くても、最新日までそろう

出力: docs/data_groups/prices.json
"""
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "docs" / "data_groups"
LONG = BASE / "docs" / "data_long"   # 2024年まで遡る過去ぶん(必要時だけ読む)
CACHE5 = BASE / "cache_bars_5y"
START = "2024-06-19"        # これより前は切り捨てる
SLEEP = 0.3

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# ベンチマーク。株探の指数(cache_period側)は約300営業日しか遡れないので、
# それより前はYahooの連動ETF/指数の「日々の騰落率」をつないで伸ばす。
# 直近は公式指数そのもの、古い部分だけ代用という形になる。
BENCH = [
    ("0010", "TOPIX",       "1306.T"),
    ("0000", "日経平均",     "%5EN225"),
    ("0012", "グロース250",  "2516.T"),
]

fp_spec = importlib.util.spec_from_file_location("fp", BASE / "fetch_period.py")
fp = importlib.util.module_from_spec(fp_spec)
fp_spec.loader.exec_module(fp)


def yahoo_5y(sym):
    """[日付, 終値, 出来高] を古い順で返す。fetch_period 側のキャッシュと同じ形。"""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{sym}?range=5y&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    res = (j.get("chart") or {}).get("result") or []
    if not res:
        return []
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    off = (r0.get("meta") or {}).get("gmtoffset", 32400)
    cl, vo = q.get("close") or [], q.get("volume") or []
    from datetime import datetime, timezone
    out = []
    for i, t in enumerate(ts):
        c = cl[i] if i < len(cl) else None
        if c is None:
            continue
        v = vo[i] if i < len(vo) else None
        d = datetime.fromtimestamp(t + off, tz=timezone.utc).date().isoformat()
        out.append([d, float(c), 0.0 if v is None else float(v)])
    return out


def cached_5y(code, fetch=True):
    """cache_bars_5y は [日付, 高値, 終値, 出来高]。ここでは終値だけ使う。"""
    p = CACHE5 / f"{code}.json"
    if p.exists():
        bars = (json.loads(p.read_text(encoding="utf-8")) or {}).get("bars") or []
        return [[b[0], b[1], b[3]] if len(b) == 3 else [b[0], b[2], b[3]] for b in bars]
    if not fetch:
        return []
    try:
        raw = yahoo_5y(f"{code}.T")
    except Exception as e:                       # noqa: BLE001
        print(f"  ! {code}: {e}", file=sys.stderr)
        raw = []
    # 新高値バックフィルと同じ形で保存する(高値は持っていないので終値で埋める)
    CACHE5.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"bars": [[d, c, c, v] for d, c, v in raw]},
                            ensure_ascii=False), encoding="utf-8")
    time.sleep(SLEEP)
    return raw


def stale(c5, short_bars):
    """5年キャッシュが**分割・併合で調整がズレたまま**かを、重なる日の終値で見る。

    Yahooの終値は分割があると過去まで遡って調整し直される。5年キャッシュを取った
    あとに分割があると、古い部分だけ未調整のまま残り、継ぎ目で株価が飛ぶ
    (騰落率が数倍になる)。毎日更新している cache_period と重なる日を突き合わせ、
    食い違っていたら取り直す。
    """
    a = {d: c for d, c, _ in c5}
    both = [d for d, c, _ in short_bars if d in a and c and a[d]]
    if not both:
        return False
    ref = {d: c for d, c, _ in short_bars}
    return any(abs(a[d] / ref[d] - 1) > 0.05 for d in sorted(both)[-5:])


def merge(old, new):
    """日付をキーに new で上書きしたうえで日付順に並べ直す。"""
    m = {b[0]: b for b in old}
    for b in new:
        m[b[0]] = b
    return [m[d] for d in sorted(m)]


def chain_back(recent, proxy):
    """recent(公式指数・短い)の手前を proxy(代用・長い)の日々騰落率で伸ばす。

    recent の最初の日の値を基準に、そこから proxy の変化率を逆向きにかけていく。
    水準は公式指数にそろい、形は proxy のものになる。
    """
    if not recent:
        return {d: c for d, c, _ in proxy}
    out = {d: c for d, c, _ in recent}
    first = min(out)
    px = {d: c for d, c, _ in proxy if c}
    if first not in px:
        return out
    days = sorted(d for d in px if d < first)
    anchor = out[first]
    for d in reversed(days):
        nxt = min((x for x in px if x > d), default=None)
        if nxt is None or nxt not in out or not px[nxt]:
            continue
        out[d] = out[nxt] * px[d] / px[nxt]
    return out


def main():
    fetch = "--no-fetch" not in sys.argv
    groups = fp.load_groups()
    groups.update(fp.topix_groups())
    gnames = list(groups)
    gi = {}
    names = {}
    for i, (g, members) in enumerate(groups.items()):
        for code, name in members:
            gi.setdefault(code, []).append(i)
            names.setdefault(code, name)
    codes = sorted(gi)
    print(f"グループ {len(gnames)} / 銘柄 {len(codes)}", flush=True)

    short = fp.load_json(fp.CACHE, {}) or {}
    caps = fp.market_caps(fp.load_json(fp.SHARES, {}) or {},
                          fp.load_json(fp.RAWCLOSE, {}) or {})

    series, missing, refreshed = {}, 0, []
    for i, code in enumerate(codes, 1):
        c5, sh = cached_5y(code, fetch), short.get(code) or []
        if fetch and stale(c5, sh):
            (CACHE5 / f"{code}.json").unlink(missing_ok=True)
            c5 = cached_5y(code, True)
            refreshed.append(code)
        bars = merge(c5, sh)
        bars = [b for b in bars if b[0] >= START and b[1]]
        if len(bars) < 2:
            missing += 1
            continue
        series[code] = bars
        if i % 200 == 0:
            print(f"  {i}/{len(codes)}", flush=True)
    print(f"株価あり {len(series)} / 無し {missing}", flush=True)
    if refreshed:
        print(f"  分割で調整がズレていたため取り直し {len(refreshed)}銘柄: "
              f"{','.join(refreshed[:20])}", flush=True)

    dates = sorted({b[0] for bars in series.values() for b in bars})
    idx = {d: i for i, d in enumerate(dates)}
    print(f"日付 {len(dates)}日 ({dates[0]} 〜 {dates[-1]})", flush=True)

    stocks = {}
    for code, bars in series.items():
        cl = [None] * len(dates)
        turn = []
        for d, c, v in bars:
            cl[idx[d]] = fp.compact_price(c)
            turn.append(c * v / 1e6)            # 百万円
        tail = turn[-20:]
        stocks[code] = {"n": names.get(code, ""), "g": gi[code], "c": cl,
                        "tv": round(sum(tail) / len(tail), 1) if tail else 0.0,
                        "mc": caps.get(code)}

    bench = {}
    for code, label, proxy_sym in BENCH:
        recent = [b for b in (short.get(code) or []) if b[0] >= START]
        try:
            proxy = yahoo_5y(proxy_sym)
        except Exception as e:                   # noqa: BLE001
            print(f"  ! ベンチ {label}: {e}", file=sys.stderr)
            proxy = []
        s = chain_back(recent, [b for b in proxy if b[0] >= START])
        bench[code] = {"n": label,
                       "c": [fp.compact_price(s[d]) if d in s else None for d in dates],
                       "spliced": min(recent)[0] if recent else None}

    # ---- 直近ぶんと過去ぶんに割って出す ----
    # 「タブを分けないと重い」を避けるための分割。期間騰落率タブが最初に読むのは
    # 直近ぶんだけで、2024年まで遡る過去ぶんは **古い起点日を選んだときにだけ** 読む。
    # 割る位置は期間騰落率タブ(data_period/prices.json)の最初の日にそろえる。
    pdd = fp.load_json(BASE / "docs" / "data_period" / "prices.json", {}).get("dates") or []
    split = pdd[0] if pdd else dates[0]
    cut = next((i for i, d in enumerate(dates) if d >= split), len(dates))

    OUT.mkdir(parents=True, exist_ok=True)
    LONG.mkdir(parents=True, exist_ok=True)
    fp.save_json(OUT / "prices.json",
                 {"updated": dates[-1], "start": split, "dates": dates[cut:],
                  "groups": gnames,
                  "bench": {k: {"n": v["n"], "c": v["c"][cut:]} for k, v in bench.items()},
                  "stocks": {c: {**s, "c": s["c"][cut:]} for c, s in stocks.items()}},
                 compact=True)
    fp.save_json(OUT / "index.json", {"updated": dates[-1], "count": len(stocks)})
    fp.save_json(LONG / "groups.json",
                 {"dates": dates[:cut],
                  "bench": {k: {"c": v["c"][:cut]} for k, v in bench.items()},
                  "stocks": {c: s["c"][:cut] for c, s in stocks.items()}},
                 compact=True)

    # 期間騰落率(全銘柄)の過去ぶんも同じ日割りで作る。母集団が違うだけで作りは同じ。
    # 5年キャッシュに無い銘柄はここでは取りに行かない(グループ銘柄ほど重要ではないため)。
    pd_stocks = fp.load_json(BASE / "docs" / "data_period" / "prices.json", {}).get("stocks") or {}
    old, nodata = {}, 0
    for code in pd_stocks:
        bars = [b for b in cached_5y(code, fetch=False) if START <= b[0] < split and b[1]]
        if not bars:
            nodata += 1
            continue
        cl = [None] * cut
        for d, c, _ in bars:
            if d in idx and idx[d] < cut:
                cl[idx[d]] = fp.compact_price(c)
        old[code] = cl
    fp.save_json(LONG / "period.json",
                 {"dates": dates[:cut],
                  "bench": {k: {"c": v["c"][:cut]} for k, v in bench.items()},
                  "stocks": old},
                 compact=True)
    fp.save_json(LONG / "index.json", {"dates": dates[:cut], "start": START, "split": split})

    mb = lambda p: p.stat().st_size / 1e6                  # noqa: E731
    print(f"wrote group prices: {len(stocks)} stocks / {len(dates)} days "
          f"({dates[0]}〜{dates[-1]})", flush=True)
    print(f"  data_groups/prices.json {mb(OUT / 'prices.json'):.2f}MB "
          f"({split}〜 / グループ別を開いたとき)", flush=True)
    print(f"  data_long/groups.json   {mb(LONG / 'groups.json'):.2f}MB "
          f"({START}〜{split} / 古い起点日を選んだときだけ)", flush=True)
    print(f"  data_long/period.json   {mb(LONG / 'period.json'):.2f}MB "
          f"(全銘柄 {len(old)}銘柄 / 5年キャッシュ無し {nodata}銘柄は過去を出せない)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
