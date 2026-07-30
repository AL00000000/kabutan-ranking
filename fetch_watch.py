# -*- coding: utf-8 -*-
"""監視銘柄(docs/data_watch/watchlist.json)の日足データを取得する。

Yahoo Finance のチャートエンドポイント
    https://query1.finance.yahoo.com/v8/finance/chart/{code}.T?range=1y&interval=1d
から日足の始値・高値・安値・終値・出来高を取得し、銘柄ごとの JSON に追記する。

出力:
  docs/data_watch/codes/{code}.json … 銘柄ごとの日足(約1年分)
  docs/data_watch/summary.json      … 全銘柄の最新値・騰落率(騰落率タブはこれだけで動く)
  docs/data_watch/names.json        … 銘柄コード -> 銘柄名

■ 自己修復について
毎日必ず成功させる必要はない。保存済みデータの最終日と今日の差を見て取得レンジを
自動で広げるため、PCを数日つけていなくても次回実行時に穴が埋まる。
また --full を付けると全銘柄を1年分取り直すので、株式分割・併合による過去値の
ズレもそこで是正される(daily_watch.py が土曜に自動で付ける)。

使用例:
  py fetch_watch.py              … 差分更新(通常の日次実行)
  py fetch_watch.py --full       … 全銘柄1年分を取り直す(初回/週次)
  py fetch_watch.py --codes 6146,7735
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "docs" / "data_watch"
CODES_DIR = DATA / "codes"
WATCHLIST = DATA / "watchlist.json"
NAMES = DATA / "names.json"
SUMMARY = DATA / "summary.json"
RANKING_DATA = BASE / "docs" / "data"

CHART_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
             "?range={rng}&interval=1d")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SLEEP = 0.4      # 銘柄間の間隔(秒)。429回避のため控えめに
RETRY = 3        # 1銘柄あたりの再試行回数
KEEP_BARS = 300  # 保存する日足の本数(1年=約245本 + 余裕)


# ---------------------------------------------------------------- 小物

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


def dint(d):
    return d.year * 10000 + d.month * 100 + d.day


def to_date(n):
    return date(n // 10000, n // 100 % 100, n % 100)


def collect_codes(node, out):
    for code in node.get("codes", []):
        if code not in out:
            out.append(code)
    for child in node.get("folders", []):
        collect_codes(child, out)


def watchlist_codes():
    wl = load_json(WATCHLIST, {"lists": []})
    codes = []
    for lst in wl.get("lists", []):
        collect_codes(lst, codes)
    return codes


# ------------------------------------------------- Firestore からの取り込み
#
# ブラウザ(docs/watch.html)側はGoogleログインして Firestore の
# watchlists/main を編集する。ここではそれを読んで watchlist.json に
# 書き戻し、以降の取得対象に反映させる。読み取り専用・鍵不要。

FS_PROJECT = "margin-call-visualizer"
FS_DOC = "watchlists/main"
FS_KEY = "AIzaSyCItdy5OI11Qc51K92Eh-BdnKf8x9wbVN8"
FS_URL = (f"https://firestore.googleapis.com/v1/projects/{FS_PROJECT}"
          f"/databases/(default)/documents/{FS_DOC}?key={FS_KEY}")


def fs_decode(v):
    """Firestore REST の型付きJSONを素のPythonの値に戻す。"""
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return v["booleanValue"]
    if "nullValue" in v:
        return None
    if "timestampValue" in v:
        return v["timestampValue"]
    if "arrayValue" in v:
        return [fs_decode(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return {k: fs_decode(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return None


def valid_node(n):
    if not isinstance(n, dict):
        return False
    if not all(isinstance(c, str) for c in n.get("codes", []) or []):
        return False
    return all(valid_node(f) for f in n.get("folders", []) or [])


def sync_from_firestore():
    """クラウド側のリストを watchlist.json に取り込む。失敗しても処理は止めない。"""
    try:
        req = urllib.request.Request(FS_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            doc = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("クラウドにまだ保存がありません: ローカルの watchlist.json を使います")
        elif e.code in (401, 403):
            print("クラウドの読み取りが許可されていません(Firestoreルール未設定): "
                  "ローカルの watchlist.json を使います")
        else:
            print(f"クラウド取得に失敗 (HTTP {e.code}): ローカルの watchlist.json を使います")
        return False
    except Exception as e:
        print(f"クラウド取得に失敗 ({e}): ローカルの watchlist.json を使います")
        return False

    data = {k: fs_decode(v) for k, v in (doc.get("fields") or {}).items()}
    lists = data.get("lists")
    if not isinstance(lists, list) or not lists or not all(valid_node(l) for l in lists):
        print("クラウドの内容が不正: ローカルの watchlist.json を使います")
        return False

    new = {"version": data.get("version") or 1, "lists": lists}
    if load_json(WATCHLIST) == new:
        print(f"クラウドと一致 (更新 {data.get('updated', '-')})")
        return True
    save_json(WATCHLIST, new)
    print(f"クラウドから取り込みました (更新 {data.get('updated', '-')})")
    return True


# ---------------------------------------------------------------- 取得

def fetch_chart(code, rng):
    """Yahoo から日足を取得して JSON(dict) を返す。失敗時は例外。"""
    url = CHART_URL.format(sym=f"{code}.T", rng=rng)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last_err = None
    for attempt in range(RETRY):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            last_err = e
            if attempt < RETRY - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"取得失敗: {code} ({last_err})")


def parse_chart(payload):
    """チャートJSONを [(日付int, o, h, l, c, v), ...] と meta に変換する。"""
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise RuntimeError("結果が空です")
    r = results[0]
    meta = r.get("meta") or {}
    stamps = r.get("timestamp") or []
    quote = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    offset = meta.get("gmtoffset", 32400)

    bars = []
    for i, ts in enumerate(stamps):
        c = quote.get("close", [None] * len(stamps))[i]
        if c is None:
            continue  # 休場・気配のみの日は捨てる
        d = datetime.fromtimestamp(ts + offset, tz=timezone.utc)
        bars.append((
            dint(d.date()),
            _round(quote.get("open", [None] * len(stamps))[i]),
            _round(quote.get("high", [None] * len(stamps))[i]),
            _round(quote.get("low", [None] * len(stamps))[i]),
            _round(c),
            int(quote.get("volume", [0] * len(stamps))[i] or 0),
        ))
    return bars, meta


def _round(v):
    return None if v is None else round(float(v), 1)


def pick_range(existing, today, full):
    """保存済みデータの最終日から、取得すべきレンジを決める(自己修復)。"""
    if full or not existing or not existing.get("d"):
        return "1y"
    gap = (today - to_date(existing["d"][-1])).days
    if gap <= 7:
        return "1mo"
    if gap <= 60:
        return "6mo"
    return "1y"


def merge_bars(existing, new_bars):
    """既存の日足に新しい日足をマージする(日付をキーに上書き)。"""
    table = {}
    if existing and existing.get("d"):
        for i, d in enumerate(existing["d"]):
            table[d] = (d, existing["o"][i], existing["h"][i],
                        existing["l"][i], existing["c"][i], existing["v"][i])
    for bar in new_bars:
        table[bar[0]] = bar
    merged = [table[k] for k in sorted(table)]
    return merged[-KEEP_BARS:]


def dump_code_file(path, code, name, bars):
    """日足ファイルを書き出す。配列は1行にして差分を追いやすくする。"""
    def j(x):
        return json.dumps(x, ensure_ascii=False, separators=(",", ":"))

    body = "\n".join([
        "{",
        f'"code":{j(code)},',
        f'"name":{j(name)},',
        f'"updated":{j(bars[-1][0] if bars else None)},',
        f'"d":{j([b[0] for b in bars])},',
        f'"o":{j([b[1] for b in bars])},',
        f'"h":{j([b[2] for b in bars])},',
        f'"l":{j([b[3] for b in bars])},',
        f'"c":{j([b[4] for b in bars])},',
        f'"v":{j([b[5] for b in bars])}',
        "}",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(body + "\n")


# ---------------------------------------------------------------- 銘柄名

def ranking_lookup(limit=10):
    """直近のランキングデータから コード -> (銘柄名, 最新順位) を作る。"""
    names, ranks = {}, {}
    index = load_json(RANKING_DATA / "index.json", {"dates": []})
    for i, d in enumerate(index.get("dates", [])[:limit]):
        day = load_json(RANKING_DATA / f"{d}.json")
        if not day:
            continue
        for s in day.get("stocks", []):
            names.setdefault(s["code"], s["name"])
            if i == 0:
                ranks[s["code"]] = s["rank"]
    return names, ranks


# ---------------------------------------------------------------- 集計

def close_at_or_before(bars, target):
    """target(日付int)以前で最も新しい終値を返す。"""
    for d, _o, _h, _l, c, _v in reversed(bars):
        if d <= target and c is not None:
            return c
    return None


def pct(now, before):
    if now is None or before in (None, 0):
        return None
    return round((now / before - 1) * 100, 2)


def summarize(code, name, bars, rank):
    if not bars:
        return None
    last = bars[-1]
    last_date = to_date(last[0])
    close = last[4]
    prev = bars[-2][4] if len(bars) >= 2 else None
    recent = bars[-250:]

    def back(days):
        return pct(close, close_at_or_before(bars, dint(last_date - timedelta(days=days))))

    # 25日移動平均線(直近25本の終値の単純平均)。カードの色分けに使う
    closes25 = [b[4] for b in bars[-25:] if b[4] is not None]
    ma25 = round(sum(closes25) / len(closes25), 1) if len(closes25) == 25 else None

    ytd_base = close_at_or_before(bars, dint(date(last_date.year, 1, 1) - timedelta(days=1)))
    highs = [b[2] for b in recent if b[2] is not None]
    lows = [b[3] for b in recent if b[3] is not None]

    return {
        "name": name,
        "date": last_date.isoformat(),
        "close": close,
        "prev": prev,
        "chg": None if prev is None else round(close - prev, 1),
        "pct": pct(close, prev),
        "r1w": back(7),
        "ma25": ma25,
        "vs25": pct(close, ma25),      # 25日線からの乖離率(+なら線の上)
        "r1m": back(30),
        "r3m": back(91),
        "r6m": back(182),
        "r1y": back(365),
        "rytd": pct(close, ytd_base),
        "high1y": max(highs) if highs else None,
        "low1y": min(lows) if lows else None,
        "vol": last[5],
        "bars": len(bars),
        "rank": rank,
    }


# ---------------------------------------------------------------- 本体

def main(argv=None):
    args = build_parser().parse_args(argv)

    if not args.no_sync:
        sync_from_firestore()
    all_codes = watchlist_codes()
    if args.codes:
        targets = [c.strip().upper() for c in args.codes.replace(",", " ").split() if c.strip()]
    else:
        targets = all_codes
    if not targets:
        print("監視銘柄が登録されていません (docs/data_watch/watchlist.json)")
        return 0

    names = load_json(NAMES, {})
    rank_names, ranks = ranking_lookup()
    today = date.today()

    if args.summary_only:
        # 保存済みの日足から summary.json を作り直すだけ(通信しない)。
        # 集計項目を増やしたときに、取得し直さず反映させるために使う。
        build_summary(all_codes, names, ranks)
        return 0

    print(f"対象 {len(targets)}銘柄 ({'全期間取り直し' if args.full else '差分更新'})")
    ok, failed = 0, []
    for i, code in enumerate(targets, start=1):
        path = CODES_DIR / f"{code}.json"
        existing = load_json(path)
        rng = pick_range(existing, today, args.full)
        try:
            payload = fetch_chart(code, rng)
            bars, meta = parse_chart(payload)
        except Exception as e:
            failed.append(code)
            print(f"  [{i}/{len(targets)}] {code} 失敗: {e}")
            time.sleep(SLEEP)
            continue

        merged = merge_bars(existing, bars)
        name = (names.get(code) or rank_names.get(code)
                or meta.get("longName") or meta.get("shortName") or code)
        names[code] = name
        dump_code_file(path, code, name, merged)
        ok += 1
        added = len(merged) - (len(existing["d"]) if existing and existing.get("d") else 0)
        print(f"  [{i}/{len(targets)}] {code} {name} {rng} "
              f"{len(merged)}本 (+{max(added, 0)})")
        time.sleep(SLEEP)

    save_json(NAMES, dict(sorted(names.items())))
    build_summary(all_codes, names, ranks)

    print(f"完了: 成功 {ok} / 失敗 {len(failed)}")
    if failed:
        print(f"失敗した銘柄: {', '.join(failed)}")
    return 0 if ok else 1


def build_summary(codes, names, ranks):
    """全監視銘柄の最新値・騰落率をまとめた summary.json を作る。"""
    stocks = {}
    latest = None
    for code in codes:
        data = load_json(CODES_DIR / f"{code}.json")
        if not data or not data.get("d"):
            continue
        bars = list(zip(data["d"], data["o"], data["h"],
                        data["l"], data["c"], data["v"]))
        s = summarize(code, names.get(code, data.get("name", code)), bars, ranks.get(code))
        if s:
            stocks[code] = s
            latest = max(latest or s["date"], s["date"])
    save_json(SUMMARY, {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "date": latest,
        "count": len(stocks),
        "stocks": stocks,
    })
    print(f"summary.json: {len(stocks)}銘柄 (最新 {latest})")


def build_parser():
    p = argparse.ArgumentParser(description="監視銘柄の日足データ取得")
    p.add_argument("--full", "--init", action="store_true", dest="full",
                   help="全銘柄を1年分取り直す(初回および週次のメンテナンス)")
    p.add_argument("--codes", help="対象銘柄を限定する (例: 6146,7735)")
    p.add_argument("--no-sync", action="store_true", dest="no_sync",
                   help="Firestoreからの取り込みを行わず、ローカルの watchlist.json をそのまま使う")
    p.add_argument("--summary-only", action="store_true", dest="summary_only",
                   help="株価を取得せず、保存済みの日足から summary.json だけ作り直す")
    return p


if __name__ == "__main__":
    sys.exit(main())
