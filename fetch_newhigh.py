# -*- coding: utf-8 -*-
"""52週新高値を更新した銘柄のうち、売買代金が10億円以上のものを抽出する。

「久々のブレイク」を拾うのが目的なので、直近5営業日以内にも新高値を付けていた
銘柄(=上昇トレンド継続中で毎日新高値の銘柄)は前回新高値からの営業日数(gap)で
区別できるようにしておき、閲覧側の既定表示から外す。

処理:
  1. Kabutan 売買代金ランキングを16ページ(=800銘柄)取得し、
     売買代金10億円以上・東証3市場(東P/東S/東G)の銘柄を母集団にする。
     ETF(東E)・ETN・REIT(東R)は対象外。
     ランキングページは16:00現在で確定値になるため、16:10以降に実行する想定。
  2. 母集団の各銘柄について Yahoo Finance から日足1年分を取得し、
     「当日高値 >= それ以前52週(365日)の最高値」で新高値を判定する(高値ベース)。
     同じ計算を過去の各日にも行い、前回新高値の日付と営業日数を出す。

出力:
  docs/data_newhigh/YYYY-MM-DD.json … 当日の新高値銘柄
  docs/data_newhigh/index.json      … 日付一覧(新しい順)
  cache_bars/{code}.json            … 日足キャッシュ(再実行を速くするだけ。gitignore)

使用例:
  py fetch_newhigh.py
  py fetch_newhigh.py --pages 20      … 母集団をさらに深く取る
  py fetch_newhigh.py --codes 4722,2767
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
DOCS = BASE / "docs" / "data_newhigh"
CACHE = BASE / "cache_bars"
CACHE_MO = BASE / "cache_bars_mo"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
COOKIE = "shared_perpage=50"          # 1ページ50件表示
RANK_URL = ("https://kabutan.jp/warning/trading_value_ranking"
            "?market=0&capitalization=-1&dispmode=normal&stc=&stm=0&page={page}")
CHART_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}.T"
             "?range=1y&interval=1d")
# 上場来高値の判定用。月足なら30年ぶんでも300本程度で済むので軽い。
# quote.high は分割調整済み(トヨタの2021年1:5分割で段差が出ないことを確認済み)。
MO_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}.T"
          "?range=max&interval=1mo")

PAGES = 16                # 50件 x 16 = 800銘柄(10億円のボーダーは700位台)
MIN_VALUE = 1000          # 売買代金の下限(百万円) = 10億円
MARKETS = ("東Ｐ", "東Ｓ", "東Ｇ")   # ETF/ETN/REIT・地方単独上場を除く
WINDOW_DAYS = 365         # 52週
FRESH_DAYS = 5            # 「直近n営業日以内にも新高値」を継続扱いにする境界
SHORT_HIST = 240          # これ未満の日足しかない銘柄は「上場1年未満」扱いで印を付ける
RANK_SLEEP = 1.5          # Kabutanのページ間隔(既存 fetch_ranking.py と同じ)
BAR_SLEEP = 0.35          # Yahooの銘柄間隔
RETRY = 3

AS_OF_RE = re.compile(r'(\d{4})年(\d{2})月(\d{2})日</li>\s*<li>(\d{2}:\d{2})現在')


# --------------------------------------------------------------- 小物

def load_json(path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj, indent=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.write("\n")


def num(s):
    """"1,234" / "+2.1" / "－" を float に。数値でなければ None"""
    try:
        return float(str(s).replace(",", "").replace("+", "").replace("%", ""))
    except (ValueError, AttributeError):
        return None


def get(url, cookie=None):
    headers = {"User-Agent": UA, "Accept-Language": "ja"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    last = None
    for attempt in range(RETRY):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.read()
        except (urllib.error.URLError, OSError) as e:
            last = e
            if attempt < RETRY - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"取得失敗: {url} ({last})")


# ------------------------------------------------- Kabutan 売買代金ランキング

def parse_rank_page(html):
    """ランキング表から (コード, 銘柄名, 市場, 株価, 前日比%, 売買代金) を取り出す。

    列の並びに依存せず <td>/<th> を順番に拾う。列位置は
    0:コード 1:銘柄名 2:市場 3,4:アイコン 5:株価 6:前日終値 7:前日比 8:前日比% 9:売買代金
    """
    m = re.search(r'<table class="stock_table st_market">(.*?)</table>', html, re.S)
    if not m:
        return []
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S):
        if not re.search(r'<a href="/stock/\?code=([0-9A-Z]+)"', tr):
            continue
        code = re.search(r'<a href="/stock/\?code=([0-9A-Z]+)"', tr).group(1)
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) < 10:
            continue
        rows.append({
            "code": code,
            "name": cells[1],
            "market": cells[2],
            "close": num(cells[5]),
            "change_pct": num(cells[8]),
            "value": num(cells[9]),
        })
    return rows


def fetch_universe(pages):
    """売買代金10億円以上・東証3市場の銘柄を上位から集める。"""
    stocks, as_of, seen = [], None, set()
    for page in range(1, pages + 1):
        html = get(RANK_URL.format(page=page), cookie=COOKIE).decode("utf-8", "replace")
        if as_of is None:
            m = AS_OF_RE.search(html)
            if m:
                as_of = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}"
        rows = parse_rank_page(html)
        if not rows:
            print(f"ERROR: ランキング {page} ページ目から行を抽出できませんでした"
                  f"(ページ構造の変更の可能性)", file=sys.stderr)
            sys.exit(1)
        below = False
        for r in rows:
            if r["code"] in seen:
                continue
            seen.add(r["code"])
            if r["value"] is None:
                continue
            if r["value"] < MIN_VALUE:
                below = True          # ここより下は全て10億円未満
                continue
            r["rank"] = len(seen)
            if r["market"] in MARKETS:
                stocks.append(r)
        if below:
            break
        if page < pages:
            time.sleep(RANK_SLEEP)
    else:
        print(f"注意: {pages}ページ目でも売買代金が{MIN_VALUE}百万円以上でした。"
              f"--pages を増やすと母集団が広がります", file=sys.stderr)
    return stocks, as_of, len(seen)


# ------------------------------------------------------- Yahoo 日足

def fetch_bars(code):
    """[(date, high, close, volume, low), ...] を古い順に返す。

    先頭3つ(日付・高値・終値)がこのスクリプトの新高値判定で使う本体。
    出来高と安値は fetch_lowvolume.py が使う(安値は「高値==安値」で
    ストップ高・安の気配日を見分けるため)。取れない日は None のまま残す。
    """
    payload = json.loads(get(CHART_URL.format(sym=code)).decode("utf-8", "replace"))
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise RuntimeError("結果が空です")
    r = results[0]
    meta = r.get("meta") or {}
    stamps = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    offset = meta.get("gmtoffset", 32400)
    highs, closes = q.get("high") or [], q.get("close") or []
    volumes, lows = q.get("volume") or [], q.get("low") or []
    bars = []
    for i, ts in enumerate(stamps):
        h = highs[i] if i < len(highs) else None
        c = closes[i] if i < len(closes) else None
        v = volumes[i] if i < len(volumes) else None
        lo = lows[i] if i < len(lows) else None
        if h is None or c is None:
            continue      # 休場・気配のみの日
        d = datetime.fromtimestamp(ts + offset, tz=timezone.utc).date()
        bars.append((d, float(h), float(c),
                     None if v is None else float(v),
                     None if lo is None else float(lo)))
    return bars


def fetch_monthly(code):
    """[(月初日, その月の高値), ...] を古い順に返す(上場来)。"""
    payload = json.loads(get(MO_URL.format(sym=code)).decode("utf-8", "replace"))
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise RuntimeError("結果が空です")
    r = results[0]
    meta = r.get("meta") or {}
    stamps = r.get("timestamp") or []
    highs = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("high") or []
    offset = meta.get("gmtoffset", 32400)
    out = []
    for i, ts in enumerate(stamps):
        h = highs[i] if i < len(highs) else None
        if h is None:
            continue
        d = datetime.fromtimestamp(ts + offset, tz=timezone.utc).date()
        out.append((d, float(h)))
    return out


def cached_monthly(code, want_month, use_cache=True):
    """月足は当月ぶんを判定に使わないので、月が変わるまでキャッシュを使い回せる。"""
    path = CACHE_MO / f"{code}.json"
    if use_cache:
        c = load_json(path)
        if c and c.get("month") == want_month:
            return [(date.fromisoformat(d), h) for d, h in c["bars"]], True
    bars = fetch_monthly(code)
    if bars:
        save_json(path, {"month": want_month,
                         "bars": [[d.isoformat(), h] for d, h in bars]}, indent=None)
    return bars, False


def all_time_high_before(monthly, daily):
    """「当日より前」の上場来最高値。

    当月ぶんは月足だと当日を含んでしまうので使わず、
    当月の当日より前は日足(直近1年)側でカバーする。
    """
    if not daily:
        return None, None
    today = daily[-1][0]
    cur = today.strftime("%Y-%m")
    mvals = [h for d, h in monthly if d.strftime("%Y-%m") < cur]
    dvals = [b[1] for b in daily[:-1]]
    vals = mvals + dvals
    if not vals:
        return None, None
    since = monthly[0][0] if monthly else daily[0][0]
    return max(vals), since


CACHE_VERSION = 3      # 1=出来高なし 2=安値なし。上げると次回実行で全銘柄を取り直す


def cached_bars(code, want_date, use_cache=True):
    """(日足, キャッシュから読んだか) を返す。同日中の再実行を速くするためだけの仕組み。"""
    path = CACHE / f"{code}.json"
    if use_cache:
        c = load_json(path)
        if c and c.get("last") == want_date.isoformat() and c.get("v") == CACHE_VERSION:
            return [(date.fromisoformat(b[0]), b[1], b[2], b[3], b[4]) for b in c["bars"]], True
    bars = fetch_bars(code)
    if bars:
        save_json(path, {"last": bars[-1][0].isoformat(), "v": CACHE_VERSION,
                         "bars": [[d.isoformat(), h, c, v, lo] for d, h, c, v, lo in bars]},
                  indent=None)
    return bars, False


# ------------------------------------------------------- 新高値の判定

def rolling_prev_max(bars, idx):
    """各日について「その日を含まない直近52週の最高値」を返す(単調デックでO(n))。

    idx=1 なら高値、idx=2 なら終値を対象にする。
    """
    n = len(bars)
    out = [None] * n
    dq = deque()      # 値が単調減少するインデックス列。先頭が窓内の最大
    for i in range(n):
        if i > 0:
            k = i - 1
            while dq and bars[dq[-1]][idx] <= bars[k][idx]:
                dq.pop()
            dq.append(k)
        left = bars[i][0] - timedelta(days=WINDOW_DAYS)
        while dq and bars[dq[0]][0] < left:
            dq.popleft()
        if dq:
            out[i] = bars[dq[0]][idx]
    return out


def analyze(bars):
    """当日が新高値か、前回新高値はいつかを求める。

    「更新」= 前の高値を超えること。前日と同値で並んだだけの日は更新に数えない
    (株探の年初来高値更新リストと同じ扱い)。
    """
    prev_high = rolling_prev_max(bars, 1)   # 高値ベース
    prev_close = rolling_prev_max(bars, 2)  # 終値ベース(参考列)
    flags = [prev_high[i] is not None and bars[i][1] > prev_high[i]
             for i in range(len(bars))]
    last = len(bars) - 1
    prev_idx = next((i for i in range(last - 1, -1, -1) if flags[i]), None)
    return {
        "is_new_high": flags[last],
        "prev52": prev_high[last],
        "close_break": (prev_close[last] is not None
                        and bars[last][2] > prev_close[last]),
        "prev_date": bars[prev_idx][0].isoformat() if prev_idx is not None else None,
        "gap": (last - prev_idx) if prev_idx is not None else None,
        "hist_days": len(bars),
    }


# ------------------------------------------------------- メイン

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=PAGES, help="ランキングの取得ページ数")
    ap.add_argument("--codes", help="この銘柄だけ判定してみる(カンマ区切り・保存しない)")
    ap.add_argument("--no-cache", action="store_true", help="日足キャッシュを使わない")
    args = ap.parse_args()

    if args.codes:
        for code in args.codes.split(","):
            bars = fetch_bars(code.strip())
            print(code.strip(), analyze(bars), sep=": ")
        return

    universe, as_of, scanned = fetch_universe(args.pages)
    if not as_of:
        print("ERROR: ランキングページからデータ時点を読めませんでした", file=sys.stderr)
        sys.exit(1)
    data_date = as_of[:10]
    print(f"母集団: {scanned}銘柄を走査し、売買代金{MIN_VALUE}百万円以上かつ"
          f"東証3市場の {len(universe)}銘柄 (データ時点 {as_of})")

    # 休場日に走ると前営業日の内容がそのまま返るため、実行日ではなくページの日付で保存する
    if (DOCS / f"{data_date}.json").is_file():
        print(f"skip: {data_date} は取得済み")
        return

    want = date.fromisoformat(data_date)
    stocks, failed, stale = [], [], []
    for i, s in enumerate(universe, 1):
        try:
            bars, from_cache = cached_bars(s["code"], want, use_cache=not args.no_cache)
        except Exception as e:                     # noqa: BLE001 - 1銘柄の失敗で全体を止めない
            failed.append(s["code"])
            print(f"  ! {s['code']} {s['name']}: {e}", file=sys.stderr)
            continue
        if not from_cache:
            time.sleep(BAR_SLEEP)                  # 取得したときだけ間隔をあける
        if len(bars) < 30:
            stale.append(s["code"])
            continue
        if bars[-1][0] != want:
            # Yahoo側に当日の足がまだ無い/日付がずれている
            stale.append(s["code"])
            continue
        a = analyze(bars)
        if not a["is_new_high"]:
            continue
        high = bars[-1][1]
        stocks.append({
            "rank": s["rank"], "code": s["code"], "name": s["name"],
            "market": s["market"], "close": bars[-1][2], "change_pct": s["change_pct"],
            "value": s["value"], "high": high, "prev52": a["prev52"],
            "break_pct": round((high / a["prev52"] - 1) * 100, 2) if a["prev52"] else None,
            "close_break": a["close_break"], "prev_date": a["prev_date"], "gap": a["gap"],
            "hist_days": a["hist_days"], "short_hist": a["hist_days"] < SHORT_HIST,
            "_bars": bars,     # 上場来判定で使い、保存前に落とす
        })
        if i % 100 == 0:
            print(f"  {i}/{len(universe)} 銘柄 … 新高値 {len(stocks)}件")

    # 上場来新高値の判定。52週新高値を付けた銘柄だけ月足を追加取得すれば足りる
    # (52週高値を超えていない銘柄が上場来高値を超えることはない)。
    want_month = want.strftime("%Y-%m")
    ath_failed = []
    for st in stocks:
        try:
            monthly, from_cache = cached_monthly(st["code"], want_month,
                                                 use_cache=not args.no_cache)
        except Exception as e:                     # noqa: BLE001
            ath_failed.append(st["code"])
            print(f"  ! 月足 {st['code']} {st['name']}: {e}", file=sys.stderr)
            st["ath"] = None
            continue
        if not from_cache:
            time.sleep(BAR_SLEEP)
        daily = st.pop("_bars")
        prev, since = all_time_high_before(monthly, daily)
        st["prev_ath"] = round(prev, 1) if prev else None
        st["ath_since"] = since.isoformat() if since else None
        st["ath"] = bool(prev and st["high"] >= prev)
        st["ath_break_pct"] = (round((st["high"] / prev - 1) * 100, 2)
                               if prev and st["ath"] else None)
    for st in stocks:
        st.pop("_bars", None)

    if stale:
        print(f"注意: 日足が当日({data_date})まで揃っていない銘柄 {len(stale)}件 "
              f"(実行が早すぎるか上場直後): {stale[:10]}", file=sys.stderr)
    if len(failed) + len(stale) > len(universe) // 3:
        print("ERROR: 判定できなかった銘柄が多すぎます。保存を中止します", file=sys.stderr)
        sys.exit(1)

    stocks.sort(key=lambda s: -(s["value"] or 0))
    fresh = [s for s in stocks if s["gap"] is None or s["gap"] > FRESH_DAYS]
    payload = {
        "date": data_date,
        "as_of": as_of,
        "updated": data_date,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "min_value": MIN_VALUE,
        "fresh_days": FRESH_DAYS,
        "window_days": WINDOW_DAYS,
        "counts": {
            "scanned": scanned, "universe": len(universe), "new_high": len(stocks),
            "fresh": len(fresh), "close_break": sum(1 for s in stocks if s["close_break"]),
            "ath": sum(1 for s in stocks if s.get("ath")),
            "failed": len(failed), "stale": len(stale), "ath_failed": len(ath_failed),
        },
        "failed": failed,
        "stocks": stocks,
    }
    save_json(DOCS / f"{data_date}.json", payload)

    dates = sorted((p.stem for p in DOCS.glob("*.json") if p.stem != "index"), reverse=True)
    save_json(DOCS / "index.json", {"dates": dates, "updated": dates[0] if dates else None})

    print(f"52週新高値(高値ベース) {len(stocks)}銘柄 / うち直近{FRESH_DAYS}営業日以内に"
          f"新高値なし {len(fresh)}銘柄 / 終値も更新 {payload['counts']['close_break']}銘柄"
          f" / 上場来新高値 {payload['counts']['ath']}銘柄")
    print(DOCS / f"{data_date}.json")


if __name__ == "__main__":
    main()
