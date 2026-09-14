# -*- coding: utf-8 -*-
"""日足10年ぶんを取り直す(PBR要請→グロース検証用)。

既存の cache_bars_5y は 2021-09 開始で、PBR要請(2023-03-31)の事前期間が
19か月しか取れない。しかも2022年の世界的なグロース暴落と丸かぶりなので
比較期間として使えない。Yahoo は range=10y&interval=1d なら10年返すので
(7203で2463本・2016-09〜を確認済み)、そちらで取り直す。

  * cache_bars_5y は本番スクリプトが参照しているので上書きしない。別ディレクトリに取る。
  * 保存形式は [日付, 始値, 高値, 安値, 終値, 出来高]。
    5y版は[日付,高値,終値,出来高]で始値が無く、ギャップ分析ができないため。
  * 上場廃止銘柄は404で取れない(4485で確認)。生存バイアスは消せないので
    失敗コードは failed.json に残して、集計時に母集団の偏りとして扱う。
  * レジューム可。既に取得済みのコードは飛ばす。

使用例:
  py fetch_10y.py            … 未取得ぶんを取得
  py fetch_10y.py --force    … 全部取り直す
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "cache_bars_5y"
OUT = BASE / "cache_bars_10y"
FAILED = Path(__file__).resolve().parent / "failed.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
       "?range=10y&interval=1d")
SLEEP = 0.35
# 指数。グロース250は Yahoo に無いので株探側で別途対応する(memoに既出)。
INDEXES = ["^N225", "^TPX", "1306.T", "2516.T"]


def jst_date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().strftime("%Y-%m-%d")


def fetch(sym):
    req = urllib.request.Request(URL.format(sym=sym), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    res = (j.get("chart") or {}).get("result") or []
    if not res:
        return []
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, l, c = (q.get(k) or [] for k in ("open", "high", "low", "close"))
    v = q.get("volume") or []
    bars = []
    for i, t in enumerate(ts):
        row = [o[i], h[i], l[i], c[i], v[i]]
        if any(x is None for x in row):
            continue        # 気配のみの日は Yahoo が null を返す
        bars.append([jst_date(t), row[0], row[1], row[2], row[3], row[4]])
    return bars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    codes = sorted(p.stem for p in SRC.glob("*.json"))
    targets = [f"{c}.T" for c in codes if not c.startswith("^")] + INDEXES

    failed, done, skipped = {}, 0, 0
    for i, sym in enumerate(targets, 1):
        name = sym.replace(".T", "").lstrip("^")
        dst = OUT / f"{name}.json"
        if dst.exists() and not args.force:
            skipped += 1
            continue
        try:
            bars = fetch(sym)
            if not bars:
                failed[name] = "empty"
            else:
                dst.write_text(json.dumps({"sym": sym, "bars": bars},
                                          ensure_ascii=False), encoding="utf-8")
                done += 1
        except urllib.error.HTTPError as e:
            failed[name] = f"HTTP {e.code}"
        except Exception as e:
            failed[name] = repr(e)[:120]
        if i % 200 == 0:
            print(f"{i}/{len(targets)} done={done} skip={skipped} fail={len(failed)}",
                  flush=True)
        time.sleep(SLEEP)

    FAILED.write_text(json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完了 取得={done} スキップ={skipped} 失敗={len(failed)} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
