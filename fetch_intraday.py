# -*- coding: utf-8 -*-
"""売買代金上位N銘柄について、当日の 15:24 終値 → 15:30 終値(大引け)の
変化率を集計し、GitHub Pages 用 JSON に出力する。

ブラウザ不要・素のHTTPリクエストのみ。Kabutanのチャート裏エンドポイント
    https://kabutan.jp/stock/read?c={code}&m=4&k=1
が始値・高値・安値・終値・出来高の実数値を返す(時刻降順)。

出力:
  docs/data_intraday/YYYY-MM-DD.json … 当日の集計+銘柄一覧
  docs/data_intraday/index.json      … 日付一覧(新しい順)
"""
import json
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path
from statistics import mean, median

import fetch_ranking as fr  # 同ディレクトリのランキング取得・パースロジックを再利用

BASE = Path(__file__).parent
DOCS_DATA = BASE / "docs" / "data_intraday"

TOP_N = 200                      # 取得する売買代金上位銘柄数
CUTOFFS = [10, 50, 75, 100, 200]  # カットオフ別集計
READ_URL = "https://kabutan.jp/stock/read?c={code}&m=4&k=1"
SLEEP = 0.3                       # /stock/read 連続取得の間隔(秒)。503回避のため控えめに
RETRY = 2                        # 各銘柄の再試行回数


def fetch_read(code):
    """1銘柄の分足を取得し、{"HH:MM": 終値} と取引日を返す。"""
    url = READ_URL.format(code=code)
    req = urllib.request.Request(url, headers={"User-Agent": fr.UA})
    with urllib.request.urlopen(req, timeout=20) as res:
        text = res.read().decode("utf-8", "replace")
    lines = text.strip().split("\n")
    header = lines[0].split(",")
    # ヘッダー2番目: 0=指数(÷100), 1=個別株/ETF(÷10)
    divisor = 100 if (len(header) > 1 and header[1] == "0") else 10
    closes = {}
    trade_date = None
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 7 or not parts[0] or "/" not in parts[0]:
            continue
        try:
            c = float(parts[4]) / divisor
        except ValueError:
            continue
        hhmm = parts[0].split("/")[1]
        closes[hhmm] = c
        if trade_date is None:
            trade_date = parts[6].replace(".", "-")
    return trade_date, closes


def fetch_read_retry(code):
    for attempt in range(RETRY + 1):
        try:
            return fetch_read(code)
        except Exception:
            if attempt == RETRY:
                return None, {}
            time.sleep(0.8 * (attempt + 1))


def num_or_none(v):
    """数値文字列をfloatに。「－」や空欄はNone。"""
    if v is None:
        return None
    t = str(v).replace(",", "").replace("+", "").strip()
    if t in ("", "－", "-", "―"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def agg(subset):
    ps = [s["pct"] for s in subset]
    pos = [p for p in ps if p > 0]
    neg = [p for p in ps if p < 0]
    zero = sum(1 for p in ps if p == 0)
    return {
        "count": len(ps),
        "mean": round(mean(ps), 4) if ps else None,
        "median": round(median(ps), 4) if ps else None,
        "up": len(pos),
        "down": len(neg),
        "flat": zero,
    }


def main():
    today = date.today().isoformat()

    # 1) 売買代金ランキング上位 TOP_N 銘柄(50件/頁)
    stocks = []
    for page in range(1, (TOP_N // 50) + 1):
        html = fr.fetch(page)
        rows = fr.parse(html)
        if not rows:
            print(f"ERROR: ranking page {page} の解析に失敗(ページ構造変更の可能性)",
                  file=sys.stderr)
            sys.exit(1)
        stocks.extend(rows)
        time.sleep(1.0)
    seen = set()
    stocks = [s for s in stocks if not (s["code"] in seen or seen.add(s["code"]))][:TOP_N]
    for i, s in enumerate(stocks, 1):
        s["rank"] = i

    # 2) 各銘柄の 15:24 / 15:30 終値
    trade_date = None
    for s in stocks:
        td, closes = fetch_read_retry(s["code"])
        if td and trade_date is None:
            trade_date = td
        p1530 = closes.get("15:30")
        p1524 = closes.get("15:24")
        s["p1530"] = p1530
        s["p1524"] = p1524
        if p1530 is not None and p1524 not in (None, 0):
            diff = p1530 - p1524
            s["diff"] = round(diff, 2)
            s["pct"] = round(diff / p1524 * 100, 4)
        else:
            s["diff"] = None
            s["pct"] = None
        time.sleep(SLEEP)

    # 3) 集計(正・負・ゼロすべて込みの単純平均/中央値)
    valid = [s for s in stocks if s["pct"] is not None]
    overall = agg(valid)
    cutoffs = []
    for n in CUTOFFS:
        if n > len(stocks):
            continue
        sub = [s for s in valid if s["rank"] <= n]
        st = agg(sub)
        st["n"] = n
        border = next((s for s in stocks if s["rank"] == n), None)
        if border:
            st["border_code"] = border["code"]
            st["border_name"] = border["name"]
            st["border_value"] = fr.parse_number(border["value"])  # 百万円
        cutoffs.append(st)

    # 4) 出力
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": today,
        "trade_date": trade_date,
        "count": len(stocks),
        "valid": len(valid),
        "overall": overall,
        "cutoffs": cutoffs,
        "stocks": [
            {
                "rank": s["rank"], "code": s["code"], "name": s["name"],
                "market": s["market"], "value": fr.parse_number(s["value"]),
                "change_pct": num_or_none(s.get("change_pct")),
                "p1524": s["p1524"], "p1530": s["p1530"],
                "diff": s["diff"], "pct": s["pct"],
            }
            for s in stocks
        ],
    }
    (DOCS_DATA / f"{today}.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    dates = sorted((p.stem for p in DOCS_DATA.glob("????-??-??.json")), reverse=True)
    (DOCS_DATA / "index.json").write_text(
        json.dumps({"dates": dates}, ensure_ascii=False), encoding="utf-8")

    print(str(DOCS_DATA / f"{today}.json"))
    print(f"銘柄数: {len(stocks)}, 有効: {len(valid)}, 全体平均: {overall['mean']}%",
          file=sys.stderr)


if __name__ == "__main__":
    main()
