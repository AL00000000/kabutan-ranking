"""引け確定値ベースの売買代金ランキングを保存する(平日16:15)。

既存の `fetch_ranking.py` は **15:40** に走る。株探の売買代金ランキングはその時刻だと
まだ「15:24現在」を返すので、`docs/data/` に貯まっているのはザラ場中のスナップショット。
「15:24→引け 分析」タブがその15:24の値を必要としているため、あちらの取得時刻は動かせない。

一方、同じページを **16:00以降**に見ると「16:00現在」に変わり、そちらはJPXの確定値と
一致する(2026-08-28のキオクシアで 1,590,240 に対しJPX 1,590,239)。そこで引け後にもう一度
取り、確定値として `docs/data_close/` に別途貯める。

  python fetch_ranking_close.py            取得して保存
  python fetch_ranking_close.py --dry-run  保存せず内容だけ表示
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

import fetch_ranking as fr

BASE = Path(__file__).resolve().parent
DOCS_DATA = BASE / "docs" / "data_close"

TOP_N = 500
# これより前の時点表記なら、まだ確定値になっていないとみなして保存しない。
# ここを緩めると15:24のザラ場値が「確定値」として混ざる。
MIN_AS_OF = "15:30"


def main():
    dry = "--dry-run" in sys.argv
    stocks, as_of_date, as_of_time = [], None, None

    for page in range(1, (TOP_N // 50) + 1):
        html = fr.fetch(page)
        if as_of_date is None:
            m = fr.AS_OF_RE.search(html)
            if m:
                as_of_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                as_of_time = m.group(4)
        rows = fr.parse(html)
        if not rows:
            print(f"ERROR: ranking page {page} の解析に失敗(ページ構造変更の可能性)", file=sys.stderr)
            return 1
        stocks.extend(rows)
        time.sleep(1.0)

    if not as_of_date or not as_of_time:
        print("ERROR: ページの時点表記が読めない", file=sys.stderr)
        return 1
    if as_of_time < MIN_AS_OF:
        print(f"skip: {as_of_date} {as_of_time}現在 はまだ確定値ではない({MIN_AS_OF}以降を待つ)")
        return 0

    seen = set()
    stocks = [s for s in stocks if not (s["code"] in seen or seen.add(s["code"]))][:TOP_N]
    for i, s in enumerate(stocks, 1):
        s["rank"] = i

    out = {
        "date": as_of_date,
        "as_of": f"{as_of_date} {as_of_time}",
        "count": len(stocks),
        "stocks": stocks,
    }
    top = " / ".join(f"{s['rank']}位 {s['name']} {s['value']}" for s in stocks[:3])
    print(f"{as_of_date} {as_of_time}現在  {len(stocks)}銘柄  {top}")

    if dry:
        print("(dry-run) 保存しない")
        return 0
    if as_of_date != date.today().isoformat():
        print(f"note: 実行日({date.today().isoformat()})と取得日({as_of_date})が違う(休場日など)")

    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    (DOCS_DATA / f"{as_of_date}.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    dates = sorted((p.stem for p in DOCS_DATA.glob("????-??-??.json")), reverse=True)
    (DOCS_DATA / "index.json").write_text(
        json.dumps({"dates": dates}, ensure_ascii=False), encoding="utf-8")
    print(f"saved {DOCS_DATA / (as_of_date + '.json')} ({len(dates)}日ぶん)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
