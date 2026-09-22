# -*- coding: utf-8 -*-
"""TDnetの適時開示から「公開買付け(TOB)」に関する開示を全部拾って貯める。

yanoshin の TDnet API は過去に遡れる(本家は31日まで)。1日ずつ取り、タイトルに
「公開買付」を含むものだけ raw_tob.json に貯める。再実行しても取得済みの日は飛ばす。

  py fetch_tob_list.py --from 2024-01-01 --to 2026-09-22
"""
import argparse
import datetime as dt
import json
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAW = BASE / "raw_tob.json"
DONE = BASE / "raw_tob_days.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) kabutan-ranking/tob-study"
API = "https://webapi.yanoshin.jp/webapi/tdnet/list/{ymd}.json?limit=5000"


def http(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch_day(day):
    js = json.loads(http(API.format(ymd=day.strftime("%Y%m%d"))).decode("utf-8"))
    out = []
    for it in js.get("items", []):
        # 同じAPIでも {"Tdnet": {...}} で来る日とフラットで来る日がある
        t = it.get("Tdnet", it)
        title = (t.get("title") or "").strip()
        if "公開買付" not in title:
            continue
        url = t.get("document_url") or ""
        if "rd.php?" in url:
            url = url.split("rd.php?", 1)[1]
        out.append({
            "date": (t.get("pubdate") or "")[:10],
            "time": (t.get("pubdate") or "")[11:16],
            "code": (t.get("company_code") or "")[:4],
            "name": (t.get("company_name") or "").strip(),
            "title": title,
            "url": url,
            "market": (t.get("markets_string") or "").strip(),
        })
    return out, len(js.get("items", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--sleep", type=float, default=0.7)
    a = ap.parse_args()

    rows = json.loads(RAW.read_text("utf-8")) if RAW.exists() else []
    done = set(json.loads(DONE.read_text("utf-8"))) if DONE.exists() else set()

    d = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end)
    n_new = 0
    while d <= end:
        key = d.isoformat()
        if d.weekday() >= 5 or key in done:
            d += dt.timedelta(days=1)
            continue
        try:
            got, total = fetch_day(d)
        except Exception as e:
            print(f"{key} FAIL {type(e).__name__} {e}", flush=True)
            time.sleep(3)
            d += dt.timedelta(days=1)
            continue
        if total >= 5000:
            print(f"{key} !! 上限5000に達した(取りこぼしの可能性)", flush=True)
        # 同じ日を取り直しても重複しないようにする
        seen = {(r["date"], r["time"], r["code"], r["title"]) for r in rows}
        rows.extend(r for r in got
                    if (r["date"], r["time"], r["code"], r["title"]) not in seen)
        done.add(key)
        n_new += len(got)
        if got:
            print(f"{key} 全{total}件 → 公開買付 {len(got)}件", flush=True)
        RAW.write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
        DONE.write_text(json.dumps(sorted(done), ensure_ascii=False), "utf-8")
        time.sleep(a.sleep)
        d += dt.timedelta(days=1)

    print(f"done. 新規 {n_new}件 / 累計 {len(rows)}件")


if __name__ == "__main__":
    main()
