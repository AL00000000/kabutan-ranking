# -*- coding: utf-8 -*-
"""引けでストップ安に張り付いた銘柄について、その2営業日後の「後場寄り(12:30始値)」が
どの基準に対して高かった/安かったかを集計し、GitHub Pages 用 JSON に出力する。

比較する3つの基準(いずれも 2営業日後の12:30始値 と比較):
  1. ストップ安日(T)の終値
  2. 2営業日後(T+2)の始値
  3. 2営業日後(T+2)の前場引け値(11:30)

データ源(いずれもブラウザ不要・素のHTTPのみ):
  - ストップ安銘柄の一覧 … Stop-takayasu リポジトリが毎日15:50に保存しているJSON
  - 株価 … Kabutanのチャート裏エンドポイント https://kabutan.jp/stock/read
      m=1 … 日足。1999年まで遡れる → T終値・T+2始値
      m=5 … 5分足。**直近5営業日分しか返らない** → T+2の11:30/12:30

m=5 の保持期間が短いため、11:30/12:30 は後から遡って取得できない。取り逃した行は
intraday_lost=true を立てて二度と再取得を試みない(毎日全銘柄を引き直さないため)。

出力:
  docs/data_stoplow/data.json … 全行(1行 = ストップ安日×銘柄)+ 全体集計
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median

BASE = Path(__file__).parent
DOCS_DATA = BASE / "docs" / "data_stoplow"
OUT = DOCS_DATA / "data.json"
HOLIDAYS = BASE / "docs" / "holidays.json"

# ストップ高安データ(同一マシン上の別リポジトリ)。無ければ公開済みJSONにフォールバック
STOP_LOCAL = Path(r"C:/Users/yt/OneDrive/ドキュメント/VSCodeFolder/Stop-takayasu/docs/data")
STOP_URL = "https://al00000000.github.io/Stop-takayasu/data/"

READ_URL = "https://kabutan.jp/stock/read?c={code}&m={m}&k=1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SLEEP = 0.3      # /stock/read 連続取得の間隔(秒)。503回避のため控えめに
RETRY = 2

OFFSET_DAYS = 2   # ストップ安日から何営業日後を見るか
AM_CLOSE = "11:30"   # 前場引けのバー(この足の終値が前場最後に付いた値)
PM_OPEN = "12:30"    # 後場寄りのバー(この足の始値が後場の寄り値)
DAY_OPEN = "09:00"


# ---------------------------------------------------------------- 営業日計算

def load_holidays():
    j = json.loads(HOLIDAYS.read_text(encoding="utf-8"))
    return set(j["dates"])


def add_trading_days(d, n, holidays):
    """d の n営業日後を返す(土日・JPX休場日をスキップ)。"""
    cur = d
    while n > 0:
        cur += timedelta(days=1)
        if cur.weekday() < 5 and cur.isoformat() not in holidays:
            n -= 1
    return cur


# ------------------------------------------------------------ ストップ安一覧

def stop_low_rows():
    """全保存日から「引けでストップ安張り付き(status=S)」の銘柄を集める。"""
    files = sorted(STOP_LOCAL.glob("????-??-??.json")) if STOP_LOCAL.is_dir() else []
    if files:
        days = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    else:
        print(f"注意: {STOP_LOCAL} が見つからないので公開JSONから取得する", file=sys.stderr)
        idx = json.loads(http_get(STOP_URL + "index.json"))
        days = [json.loads(http_get(f"{STOP_URL}{d}.json")) for d in idx.get("dates", [])]

    rows = []
    for day in days:
        for s in day.get("stocks", []):
            if s.get("group") == "stop_low" and s.get("status") == "S":
                rows.append({
                    "t": day["date"], "code": s["code"],
                    "name": s.get("name", ""), "market": s.get("market", ""),
                })
    return rows


# ------------------------------------------------------------------ 株価取得

def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as res:
        return res.read().decode("utf-8", "replace")


def read_retry(code, m):
    for attempt in range(RETRY + 1):
        try:
            return http_get(READ_URL.format(code=code, m=m))
        except Exception:
            if attempt == RETRY:
                return None
            time.sleep(0.8 * (attempt + 1))


def divisor_of(text):
    """ヘッダー2番目: 0=指数(÷100)、それ以外=個別株/ETF(÷10)。"""
    header = text.split("\n", 1)[0].split(",")
    return 100 if (len(header) > 1 and header[1] == "0") else 10


def daily_bars(code):
    """{"YYYY-MM-DD": {"open":x, "close":y}} を返す。"""
    text = read_retry(code, 1)
    if not text:
        return None
    div = divisor_of(text)
    out = {}
    for line in text.strip().split("\n")[1:]:
        p = line.split(",")
        if len(p) < 5 or not p[0]:
            continue
        ymd = p[0].split("#")[0]           # 当日行は "20260729#13:25" 形式
        if len(ymd) != 8 or not ymd.isdigit():
            continue
        try:
            o, c = float(p[1]) / div, float(p[4]) / div
        except ValueError:
            continue
        out[f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"] = {"open": o, "close": c}
    return out


def min5_bars(code, year):
    """{"MM-DD": {"HH:MM": {"open":x, "close":y, "vol":n}}} を返す。

    5分足のタイムスタンプは "07.28/12:30" 形式で年を持たないため、年は呼び出し側が渡す。
    直近5営業日しか返らないので、年をまたぐのは年末年始のみ。

    出来高は必ず持ち帰ること。売り気配で売買が成立していない間もKabutanは直前の
    約定値を出来高0のまま持ち越すので、出来高を見ないと「実際に付いた値」と
    「気配のまま据え置かれた値」を区別できない。
    """
    text = read_retry(code, 5)
    if not text:
        return None
    div = divisor_of(text)
    out = {}
    for line in text.strip().split("\n")[1:]:
        p = line.split(",")
        if len(p) < 6 or "/" not in p[0]:
            continue
        mmdd, hhmm = p[0].split("/", 1)
        try:
            o, c, v = float(p[1]) / div, float(p[4]) / div, int(float(p[5]))
        except ValueError:
            continue
        out.setdefault(mmdd.replace(".", "-"), {})[hhmm] = {"open": o, "close": c, "vol": v}
    # 実データの日付(p[6])が使えないので、年は暦から補う
    return {f"{year}-{k}": v for k, v in out.items()}


# -------------------------------------------------------------------- 集計

def pct(base, target):
    if base in (None, 0) or target is None:
        return None
    return round((target - base) / base * 100, 4)


def agg(values):
    if not values:
        return {"count": 0, "mean": None, "median": None, "up": 0, "down": 0, "flat": 0}
    return {
        "count": len(values),
        "mean": round(mean(values), 4),
        "median": round(median(values), 4),
        "up": sum(1 for v in values if v > 0),
        "down": sum(1 for v in values if v < 0),
        "flat": sum(1 for v in values if v == 0),
    }


# ---------------------------------------------------------------------- 本体

def main():
    today = date.today()
    holidays = load_holidays()
    DOCS_DATA.mkdir(parents=True, exist_ok=True)

    prev = {}
    if OUT.is_file():
        for r in json.loads(OUT.read_text(encoding="utf-8")).get("rows", []):
            prev[(r["t"], r["code"])] = r

    rows = []
    for base in stop_low_rows():
        key = (base["t"], base["code"])
        r = dict(prev.get(key, {}))
        r.update(base)
        t2 = add_trading_days(date.fromisoformat(base["t"]), OFFSET_DAYS, holidays)
        r["t2"] = t2.isoformat()
        rows.append(r)
    rows.sort(key=lambda r: (r["t"], r["code"]), reverse=True)

    # 取得が必要な行だけ引く。日足は消えないので一度埋めれば再取得不要。
    # 5分足は取り逃すと二度と取れないので、期間外と判明した時点で打ち切る。
    fetched = 0
    for r in rows:
        if r["t2"] > today.isoformat():
            r["status"] = "pending"          # 2営業日後がまだ来ていない
            continue

        need_daily = r.get("close_t") is None or r.get("open_t2") is None
        need_min5 = (not r.get("intraday_lost")) and (
            r.get("pm_open") is None or r.get("pm_open_vol") is None)

        if need_daily:
            bars = daily_bars(r["code"])
            fetched += 1
            time.sleep(SLEEP)
            if bars:
                r["close_t"] = (bars.get(r["t"]) or {}).get("close")
                r["open_t2"] = (bars.get(r["t2"]) or {}).get("open")

        if need_min5:
            bars = min5_bars(r["code"], r["t2"][:4])
            fetched += 1
            time.sleep(SLEEP)
            if bars is not None:
                day = bars.get(r["t2"])
                if day is None:
                    # 5分足の保持期間(直近5営業日)を過ぎている。以後は諦める
                    r["intraday_lost"] = True
                else:
                    am, pm = day.get(AM_CLOSE) or {}, day.get(PM_OPEN) or {}
                    r["am_close"], r["am_close_vol"] = am.get("close"), am.get("vol")
                    r["pm_open"], r["pm_open_vol"] = pm.get("open"), pm.get("vol")
                    if r.get("open_t2") is None:
                        r["open_t2"] = (day.get(DAY_OPEN) or {}).get("open")

        # 後場寄りに1株も出来ていない = 売り気配のまま。表示している値は直前の約定値が
        # 持ち越されただけで実際には付いていないので、集計から外す。
        r["no_trade"] = r.get("pm_open_vol") == 0
        r["pct_close_t"] = pct(r.get("close_t"), r.get("pm_open"))
        r["pct_open_t2"] = pct(r.get("open_t2"), r.get("pm_open"))
        r["pct_am_close"] = pct(r.get("am_close"), r.get("pm_open"))
        r["status"] = ("kehai" if r["no_trade"]
                       else "done" if r.get("pct_am_close") is not None else "partial")

    def vals(key, need_am=False):
        out = []
        for r in rows:
            if r.get(key) is None or r.get("no_trade"):
                continue
            if need_am and not r.get("am_close_vol"):   # 前場引けも出来ていない行は除く
                continue
            out.append(r[key])
        return out

    summary = {
        "close_t": agg(vals("pct_close_t")),
        "open_t2": agg(vals("pct_open_t2")),
        "am_close": agg(vals("pct_am_close", need_am=True)),
        "excluded_no_trade": sum(1 for r in rows if r.get("no_trade")),
    }

    done = [r["t2"] for r in rows if r.get("pm_open") is not None or r.get("close_t") is not None]
    payload = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "updated": max(done) if done else None,   # データが揃っている最新の2営業日後
        "offset_days": OFFSET_DAYS,
        "total": len(rows),
        "summary": summary,
        "rows": [
            {k: r.get(k) for k in (
                "t", "t2", "code", "name", "market", "close_t", "open_t2",
                "am_close", "pm_open", "am_close_vol", "pm_open_vol",
                "pct_close_t", "pct_open_t2", "pct_am_close",
                "status", "intraday_lost", "no_trade")}
            for r in rows
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")

    print(str(OUT))
    print(f"行数: {len(rows)} / 今回の取得: {fetched}件 / "
          f"11:30比較の有効数: {summary['am_close']['count']}", file=sys.stderr)


if __name__ == "__main__":
    main()
