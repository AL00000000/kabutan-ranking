# -*- coding: utf-8 -*-
"""主要指数の連騰/連落日数(終値の前日比ベース)を集計し、GitHub Pages 用 JSON に出力する。

連騰日数は符号付きの1つの数で表す:
  +3 … 3日連続で前日比プラス   -2 … 2日連続で前日比マイナス   0 … 直近が前日比ゼロ

データ源は指数ごとに異なる(いずれもブラウザ不要・素のHTTPのみ):
  Yahoo Finance … 米国指数・日経平均・KOSPI・VIX・米10年債利回り(20年分)
  株探          … TOPIX・グロース250(Yahooに無い。約300営業日分しか返らない)
  日経公式CSV   … 日経VI(2023年〜)
  財務省CSV     … 日本10年債利回り(1974年〜。和暦・全期間+当月の2本立て)

日経VIは配布元が転載を明示的に禁じているため、**終値は出力に含めない**。
連騰日数と前日比%(いずれも原データそのものではない派生値)だけを公開する。

出力:
  docs/data_streaks/data.json … 指数ごとの現在の連騰日数と過去統計
"""
import csv
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
OUT_DIR = BASE / "docs" / "data_streaks"
OUT = OUT_DIR / "data.json"
# 株探は約300営業日しか返さないので、TOPIX/グロース250だけ自前で継ぎ足して伸ばす
SERIES_DIR = BASE / "history_index"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SLEEP = 0.4
RETRY = 2

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=20y&interval=1d"
KABUTAN = "https://kabutan.jp/stock/read?c={code}&m=1&k=1"
NKVI_CSV = "https://indexes.nikkei.co.jp/nkave/historical/nikkei_stock_average_vi_daily_jp.csv"
MOF_ALL = "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"
MOF_CUR = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"

# (key, 表示名, グループ, 取得方式, 引数, 単位)
INDICES = [
    ("gspc",    "S&P500",        "米国株",   "yahoo",   "^GSPC", ""),
    ("sox",     "SOX(半導体)",    "米国株",   "yahoo",   "^SOX",  ""),
    ("ixic",    "NASDAQ総合",     "米国株",   "yahoo",   "^IXIC", ""),
    ("dji",     "NYダウ",         "米国株",   "yahoo",   "^DJI",  ""),
    ("rut",     "ラッセル2000",    "米国株",   "yahoo",   "^RUT",  ""),
    ("n225",    "日経平均",       "日本株",   "yahoo",   "^N225", "円"),
    ("topix",   "TOPIX",         "日本株",   "kabutan", "0010",  ""),
    ("growth",  "グロース250",     "日本株",   "kabutan", "0012",  ""),
    ("ks11",    "KOSPI",         "アジア株", "yahoo",   "^KS11", ""),
    ("vix",     "VIX(恐怖指数)",   "変動率",   "yahoo",   "^VIX",  ""),
    ("nkvi",    "日経VI",         "変動率",   "nkvi",    "",      ""),
    ("tnx",     "米10年債利回り",  "金利",     "yahoo",   "^TNX",  "%"),
    ("jgb10",   "日10年債利回り",  "金利",     "mof",     "10年",  "%"),
]
# 配布元が転載を禁じているため終値を公開しない指数
HIDE_CLOSE = {"nkvi"}


def http_get(url, encoding=None):
    for attempt in range(RETRY + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as res:
                raw = res.read()
            return raw.decode(encoding, "replace") if encoding else raw
        except Exception:
            if attempt == RETRY:
                raise
            time.sleep(1.0 * (attempt + 1))


# ------------------------------------------------------------------ 取得

def from_yahoo(ticker):
    j = json.loads(http_get(YAHOO.format(t=urllib.parse.quote(ticker))))
    r = j["chart"]["result"][0]
    off = r["meta"].get("gmtoffset", 0)
    closes = r["indicators"]["quote"][0]["close"]
    out = []
    for ts, c in zip(r["timestamp"], closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts + off, timezone.utc).date().isoformat()
        out.append((d, float(c)))
    return out


def from_kabutan(code):
    text = http_get(KABUTAN.format(code=code), "utf-8")
    lines = text.strip().split("\n")
    header = lines[0].split(",")
    div = 100 if (len(header) > 1 and header[1] == "0") else 10
    out = []
    for line in lines[1:]:
        p = line.split(",")
        if len(p) < 5 or not p[0] or not p[4]:
            continue
        ymd = p[0].split("#")[0]          # 当日行は "20260729#15:22" 形式
        if len(ymd) != 8 or not ymd.isdigit():
            continue
        try:
            c = float(p[4]) / div
        except ValueError:
            continue
        out.append((f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}", c))
    out.sort()
    return out


def from_nkvi(_):
    text = http_get(NKVI_CSV, "cp932")
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        d, c = row[0].strip(), row[1].strip()
        if not d or "/" not in d:
            continue                       # ヘッダー行・末尾の著作権表示行
        try:
            out.append((d.replace("/", "-"), float(c)))
        except ValueError:
            continue
    out.sort()
    return out


ERA_START = {"M": 1868, "T": 1912, "S": 1926, "H": 1989, "R": 2019}


def wareki(s):
    """'R8.7.1' → '2026-07-01'。変換できなければ None。"""
    try:
        era, rest = s[0], s[1:]
        y, m, d = (int(x) for x in rest.split("."))
        return f"{ERA_START[era] + y - 1:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None


def from_mof(col_label):
    """全期間ファイル(前月末まで)と当月ファイルを結合して返す。"""
    out = {}
    for url in (MOF_ALL, MOF_CUR):
        text = http_get(url, "cp932")
        idx = None
        for row in csv.reader(io.StringIO(text)):
            if not row or not row[0].strip():
                continue
            if row[0].strip() == "基準日":
                idx = row.index(col_label) if col_label in row else None
                continue
            if idx is None or len(row) <= idx:
                continue
            d = wareki(row[0].strip())
            try:
                v = float(row[idx])
            except (ValueError, TypeError):
                continue                   # 休場日は "-"
            if d:
                out[d] = v
        time.sleep(SLEEP)
    return sorted(out.items())


FETCHERS = {"yahoo": from_yahoo, "kabutan": from_kabutan, "nkvi": from_nkvi, "mof": from_mof}


# -------------------------------------------------- 株探ぶんの自前ヒストリ

def merge_series(key, series):
    """株探は直近300営業日しか返さないので、取得済みぶんと合成して保存する。"""
    SERIES_DIR.mkdir(exist_ok=True)
    path = SERIES_DIR / f"{key}.json"
    merged = {}
    if path.is_file():
        merged.update(json.loads(path.read_text(encoding="utf-8")))
    merged.update({d: c for d, c in series})
    path.write_text(json.dumps(merged, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")), encoding="utf-8")
    return sorted(merged.items())


# ------------------------------------------------------------------ 集計

def runs_of(series):
    """連続同方向の区間を [(方向, 日数)] で返す。最後の要素が進行中の連騰/連落。"""
    runs = []
    cur_dir = cur_len = 0
    for i in range(1, len(series)):
        diff = series[i][1] - series[i - 1][1]
        sign = 1 if diff > 0 else -1 if diff < 0 else 0
        if sign == 0:
            if cur_len:
                runs.append((cur_dir, cur_len))
            cur_dir = cur_len = 0
        elif sign == cur_dir:
            cur_len += 1
        else:
            if cur_len:
                runs.append((cur_dir, cur_len))
            cur_dir, cur_len = sign, 1
    runs.append((cur_dir, cur_len))        # 進行中(0日ならcur_dir=0)
    return runs


def summarize(series):
    if len(series) < 2:
        return None
    runs = runs_of(series)
    cur_dir, cur_len = runs[-1]
    past = runs[:-1]
    cur = cur_dir * cur_len

    ups = [n for d, n in runs if d > 0]
    downs = [n for d, n in runs if d < 0]
    same = [n for d, n in past if d == cur_dir and n >= cur_len] if cur_len else []

    prev_close, last_close = series[-2][1], series[-1][1]
    return {
        "last_date": series[-1][0],
        "close": round(last_close, 2),
        "change_pct": round((last_close - prev_close) / prev_close * 100, 2) if prev_close else None,
        "cur": cur,
        "max_up": max(ups) if ups else 0,
        "max_down": max(downs) if downs else 0,
        "same_or_longer": len(same),
        "is_record": bool(cur_len) and cur_len >= max(ups if cur_dir > 0 else downs, default=0),
        "hist_from": series[0][0],
        "hist_to": series[-1][0],
        "hist_days": len(series),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []

    for key, name, group, kind, arg, unit in INDICES:
        try:
            series = FETCHERS[kind](arg)
            if kind == "kabutan":
                series = merge_series(key, series)
            s = summarize(series)
            if s is None:
                raise ValueError("データが不足しています")
        except Exception as e:
            failed.append(f"{name}: {type(e).__name__}: {e}")
            print(f"WARN {name}: {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(SLEEP)
            continue

        if key in HIDE_CLOSE:
            s["close"] = None              # 配布元が転載を禁じているため公開しない
        s.update(key=key, name=name, group=group, unit=unit)
        rows.append(s)
        time.sleep(SLEEP)

    payload = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "updated": max((r["last_date"] for r in rows), default=None),
        "count": len(rows),
        "failed": failed,
        "indices": rows,
    }

    # 休場日に走っても中身が同じなら書かない(generated だけ動く空コミットを防ぐ)
    if OUT.is_file():
        old = json.loads(OUT.read_text(encoding="utf-8"))
        if {k: v for k, v in old.items() if k != "generated"} == \
           {k: v for k, v in payload.items() if k != "generated"}:
            print("skip: 前回から変化なし", file=sys.stderr)
            print(str(OUT))
            return

    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(str(OUT))
    print(f"指数: {len(rows)}/{len(INDICES)}" + (f" / 失敗 {len(failed)}件" if failed else ""),
          file=sys.stderr)


if __name__ == "__main__":
    main()
