# -*- coding: utf-8 -*-
"""出来高が52週の最低を更新した銘柄を集めて docs/data_lowvolume/{日付}.json に保存する。

出来高の枯れは相場の転換点のサインとして見たい、という用途。
売買代金ランキング(fetch_newhigh.py と同じ母集団)に監視銘柄リストを足した集合を走査する。

母集団にランキングだけを使わないのは、出来高が枯れた銘柄は売買代金も落ちて
ランキングから消えるため。監視銘柄はランキング圏外でも必ず見たい。

判定は2種類:
  - 単日  : 当日の出来高が、当日を含まない直近52週のどの日よりも少ない
  - 5日平均: 5日移動平均が、同じく直近52週の5日平均のどれよりも少ない
単日はノイズが乗りやすいので、ならした5日平均のほうが「枯れ」の判断には向く。

日足は fetch_newhigh.py の日足キャッシュ(cache_bars)を共有する。
newhigh-break タスク(16:20)の後に走らせれば、ランキング分はキャッシュが効いて
Yahoo への取得は監視銘柄リストのはみ出し分だけで済む。

使用例:
  py fetch_lowvolume.py
  py fetch_lowvolume.py --codes 7203,6146     # 判定だけ試す(保存しない)
  py fetch_lowvolume.py --pages 4             # 母集団を狭くして軽く試す
"""
import argparse
import json
import sys
import time
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path

from fetch_newhigh import (
    BAR_SLEEP,
    MIN_VALUE,
    PAGES,
    cached_bars,
    fetch_bars,
    fetch_universe,
    load_json,
    save_json,
)

BASE = Path(__file__).parent
DOCS = BASE / "docs" / "data_lowvolume"
WATCHLIST = BASE / "docs" / "data_watch" / "watchlist.json"
NAMES = BASE / "docs" / "data_watch" / "names.json"

WINDOW_DAYS = 365       # 52週
MA_DAYS = 5             # ならし用の移動平均日数
SHORT_HIST = 240        # これ未満の日足しかない銘柄は「上場1年未満」扱いで印を付ける
MIN_BARS = 60           # 判定に必要な最低本数(短すぎる履歴は「52週最低」と呼べない)


# --------------------------------------------------------------- 監視銘柄

def walk_codes(node, path, out):
    for code in node.get("codes", []):
        out.setdefault(code, path)
    for child in node.get("folders", []):
        walk_codes(child, f"{path}/{child['name']}", out)


def watchlist_codes():
    """{コード: リスト内のパス} を返す。"""
    wl = load_json(WATCHLIST, {"lists": []})
    out = {}
    for lst in wl.get("lists", []):
        walk_codes(lst, lst.get("name", "?"), out)
    return out


# --------------------------------------------------------------- 出来高の判定

def valid_series(bars):
    """(日付, 出来高) を、出来高の比較に使える日だけ取り出す。

    落とすのは2種類:
      - 出来高0の日: 終日気配で売買不成立。
      - 高値==安値の日: ストップ高・安の気配で、1本値でしか約定していない日。
        買い気配のストップ高は「誰も買えなかった」ので出来高が極端に小さくなるが、
        これは閑散ではなく過熱であり、拾ってしまうと意味が逆になる。
        さらに厄介なのは、過去に一度でもこの日があると異常に低い出来高が
        52週最小として居座り、本物の閑散日が二度と最低を更新できなくなること。
        そのため当日判定から外すだけでなく、比較の窓からも丸ごと除外する。

    値幅ゼロは売買代金10億円以上の銘柄では気配以外ではまず起きないので、
    この判定で取りこぼす通常の閑散日はないと考えてよい。
    """
    return [(b[0], b[3]) for b in bars
            if b[3] is not None and b[3] > 0
            and not (b[4] is not None and b[1] == b[4])]


def rolling_prev_min(series):
    """各日について「その日を含まない直近52週の最小値」を返す(単調デックでO(n))。"""
    n = len(series)
    out = [None] * n
    dq = deque()      # 値が単調増加するインデックス列。先頭が窓内の最小
    for i in range(n):
        if i > 0:
            k = i - 1
            while dq and series[dq[-1]][1] >= series[k][1]:
                dq.pop()
            dq.append(k)
        left = series[i][0] - timedelta(days=WINDOW_DAYS)
        while dq and series[dq[0]][0] < left:
            dq.popleft()
        if dq:
            out[i] = series[dq[0]][1]
    return out


def moving_average(series, days):
    """(日付, n日平均) を返す。最初の n-1 日は平均が出せないので落とす。"""
    out, total = [], 0.0
    for i, (d, v) in enumerate(series):
        total += v
        if i >= days:
            total -= series[i - days][1]
        if i >= days - 1:
            out.append((d, total / days))
    return out


def analyze(bars):
    """当日が出来高52週最低を更新したかを、単日と5日平均の両方で判定する。

    判定できないときは None。当日が気配で valid_series に落とされた場合も
    None を返す(前日を「当日」として判定してしまわないため)。
    """
    series = valid_series(bars)
    if len(series) < MIN_BARS:
        return None
    if not bars or series[-1][0] != bars[-1][0]:
        return None

    prev_min = rolling_prev_min(series)
    last = len(series) - 1
    today_vol = series[last][1]
    is_low = prev_min[last] is not None and today_vol < prev_min[last]

    # 前回いつ最低を更新したか(単日ベース)
    flags = [prev_min[i] is not None and series[i][1] < prev_min[i] for i in range(len(series))]
    prev_idx = next((i for i in range(last - 1, -1, -1) if flags[i]), None)

    ma = moving_average(series, MA_DAYS)
    ma_low, ma_value, ma_prev = False, None, None
    if len(ma) >= MIN_BARS - MA_DAYS:
        ma_prev_min = rolling_prev_min(ma)
        ma_value = ma[-1][1]
        ma_prev = ma_prev_min[-1]
        ma_low = ma_prev is not None and ma_value < ma_prev

    window = [v for d, v in series if d >= series[last][0] - timedelta(days=WINDOW_DAYS)]
    avg52 = sum(window) / len(window) if window else None

    return {
        "is_low": is_low,
        "ma_low": ma_low,
        "volume": today_vol,
        "prev_min": prev_min[last],
        "ma": ma_value,
        "ma_prev_min": ma_prev,
        "avg52": avg52,
        "vs_avg_pct": round(today_vol / avg52 * 100, 1) if avg52 else None,
        "prev_date": series[prev_idx][0].isoformat() if prev_idx is not None else None,
        "gap": (last - prev_idx) if prev_idx is not None else None,
        "hist_days": len(series),
        # 上場して1年経ったかは「気配日を除く前」の本数で見る。
        # hist_days は気配日を落とした後なので、ストップ高安の多い銘柄だと
        # 上場1年以上でも240本を割り、誤って「1年未満」と表示されてしまう。
        "raw_days": len(bars),
    }


# --------------------------------------------------------------- メイン

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=PAGES, help="ランキングの取得ページ数")
    ap.add_argument("--codes", help="この銘柄だけ判定してみる(カンマ区切り・保存しない)")
    ap.add_argument("--no-cache", action="store_true", help="日足キャッシュを使わない")
    args = ap.parse_args()

    if args.codes:
        for code in args.codes.split(","):
            print(code.strip(), analyze(fetch_bars(code.strip())), sep=": ")
        return

    universe, as_of, scanned = fetch_universe(args.pages)
    if not as_of:
        print("ERROR: ランキングページからデータ時点を読めませんでした", file=sys.stderr)
        sys.exit(1)
    data_date = as_of[:10]

    # ランキング圏外の監視銘柄を母集団に足す
    watch = watchlist_codes()
    names = load_json(NAMES, {})
    known = {s["code"] for s in universe}
    for code, path in sorted(watch.items()):
        if code not in known:
            universe.append({"code": code, "name": names.get(code, code), "market": "",
                             "close": None, "change_pct": None, "value": None,
                             "rank": None, "watch": path})
    for s in universe:
        s.setdefault("watch", watch.get(s["code"]))

    extra = len(universe) - len(known)
    print(f"母集団: 売買代金{MIN_VALUE}百万円以上 {len(known)}銘柄 "
          f"+ ランキング圏外の監視銘柄 {extra}銘柄 = {len(universe)}銘柄 "
          f"(データ時点 {as_of})")

    if (DOCS / f"{data_date}.json").is_file():
        print(f"skip: {data_date} は取得済み")
        return

    want = date.fromisoformat(data_date)
    stocks, failed, stale, skipped = [], [], [], []
    for i, s in enumerate(universe, 1):
        try:
            bars, from_cache = cached_bars(s["code"], want, use_cache=not args.no_cache)
        except Exception as e:                     # noqa: BLE001 - 1銘柄の失敗で全体を止めない
            failed.append(s["code"])
            print(f"  ! {s['code']} {s['name']}: {e}", file=sys.stderr)
            continue
        if not from_cache:
            time.sleep(BAR_SLEEP)                  # 取得したときだけ間隔をあける
        if not bars or bars[-1][0] != want:
            stale.append(s["code"])                # 当日の足がまだ無い/日付がずれている
            continue
        a = analyze(bars)
        if a is None:
            skipped.append(s["code"])   # 履歴が短い or 当日が気配
            continue
        if not (a["is_low"] or a["ma_low"]):
            continue
        stocks.append({
            "rank": s["rank"], "code": s["code"], "name": s["name"], "market": s["market"],
            "close": bars[-1][2], "change_pct": s["change_pct"], "value": s["value"],
            "watch": s.get("watch"),
            "volume": a["volume"], "prev_min": a["prev_min"],
            "ma": round(a["ma"]) if a["ma"] else None,
            "ma_prev_min": round(a["ma_prev_min"]) if a["ma_prev_min"] else None,
            "is_low": a["is_low"], "ma_low": a["ma_low"],
            "avg52": round(a["avg52"]) if a["avg52"] else None,
            "vs_avg_pct": a["vs_avg_pct"],
            "prev_date": a["prev_date"], "gap": a["gap"],
            "hist_days": a["hist_days"], "short_hist": a["raw_days"] < SHORT_HIST,
        })
        if i % 100 == 0:
            print(f"  {i}/{len(universe)} 銘柄 … 該当 {len(stocks)}件")

    if stale:
        print(f"注意: 日足が当日({data_date})まで揃っていない銘柄 {len(stale)}件 "
              f"(実行が早すぎるか上場直後): {stale[:10]}", file=sys.stderr)
    if len(failed) + len(stale) > len(universe) // 3:
        print("ERROR: 判定できなかった銘柄が多すぎます。保存を中止します", file=sys.stderr)
        sys.exit(1)

    # 枯れ具合(52週平均に対する当日出来高の低さ)が強い順
    stocks.sort(key=lambda s: (s["vs_avg_pct"] is None, s["vs_avg_pct"]))
    payload = {
        "date": data_date,
        "as_of": as_of,
        "updated": data_date,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "min_value": MIN_VALUE,
        "window_days": WINDOW_DAYS,
        "ma_days": MA_DAYS,
        "counts": {
            "scanned": scanned, "universe": len(universe), "hit": len(stocks),
            "day_low": sum(1 for s in stocks if s["is_low"]),
            "ma_low": sum(1 for s in stocks if s["ma_low"]),
            "watch": sum(1 for s in stocks if s["watch"]),
            "failed": len(failed), "stale": len(stale), "skipped": len(skipped),
        },
        "failed": failed,
        "stocks": stocks,
    }
    save_json(DOCS / f"{data_date}.json", payload)

    dates = sorted((p.stem for p in DOCS.glob("*.json") if p.stem != "index"), reverse=True)
    save_json(DOCS / "index.json", {"dates": dates, "updated": dates[0] if dates else None})

    c = payload["counts"]
    print(f"52週の出来高最低を更新 {c['hit']}銘柄 "
          f"(単日 {c['day_low']} / {MA_DAYS}日平均 {c['ma_low']} / うち監視銘柄 {c['watch']})")
    print(DOCS / f"{data_date}.json")


if __name__ == "__main__":
    main()
