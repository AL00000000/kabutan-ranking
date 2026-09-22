# -*- coding: utf-8 -*-
"""TOB対象会社の「公表直前のPBR」をIRBANKから取る。

IRBANKの /{code}/chart?y=YYYY-MM-DD は、その日を末尾とする約100営業日分の
日足(終値・時価総額・PER・PBR)を返す。上場廃止後も残るので、TOBで消えた会社も
取れる(株探やYahooは消える)。

公表が15:00以降なら当日終値がニュース前の値、場中ならその日の終値は既に
ニュースを織り込んでいるので前営業日の終値を使う。

  py fetch_pbr.py              targets.json 全件
  py fetch_pbr.py --limit 5    先頭5件だけ(動作確認)
"""
import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
TARGETS = BASE / "targets.json"
CACHE = BASE / "raw_irbank"
OUT = BASE / "pbr.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) kabutan-ranking/tob-study"
URL = "https://irbank.net/{code}/chart?y={date}"


def http(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def get_html(code, date):
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{code}_{date}.html"
    if f.exists():
        return f.read_text("utf-8"), True
    h = http(URL.format(code=code, date=date))
    f.write_text(h, "utf-8")
    return h, False


def parse_rows(html):
    """[(YYYY-MM-DD, 終値, 時価総額文字列, PER, PBR), ...] 新しい順"""
    t = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    out = []
    year = None
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, flags=re.S):
        cells = [re.sub(r"\s+", "", re.sub("<[^>]+>", "", c)) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S)]
        if len(cells) == 1 and re.fullmatch(r"20\d\d", cells[0]):
            year = cells[0]
            continue
        if len(cells) < 11 or not re.fullmatch(r"\d\d/\d\d", cells[0]):
            continue
        if year is None:
            continue
        mm, dd = cells[0].split("/")
        def num(s):
            s = s.replace(",", "")
            try:
                return float(s)
            except ValueError:
                return None
        out.append({
            "date": f"{year}-{mm}-{dd}",
            "close": num(cells[4]),
            "mcap": cells[7],
            "per": num(cells[9]),
            "pbr": num(cells[10]),
        })
    return out


def close_time(day):
    """東証の取引終了時刻。2024年11月5日から15:30に延びた。"""
    return "15:30" if day >= "2024-11-05" else "15:00"


def pick(rows, ann_date, ann_time):
    """ニュース前の最後の終値の行を返す"""
    rows = [r for r in rows if r["date"] <= ann_date]
    if not rows:
        return None, "期間外"
    after_close = (ann_time or "00:00") >= close_time(ann_date)
    if rows[0]["date"] == ann_date and not after_close:
        rows = rows[1:]          # 場中の公表 → 当日終値は使えない
        if not rows:
            return None, "期間外"
    return rows[0], ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()

    targets = json.loads(TARGETS.read_text("utf-8"))
    if a.limit:
        targets = targets[:a.limit]

    out = []
    for i, t in enumerate(targets, 1):
        try:
            html, cached = get_html(t["code"], t["ann_date"])
            rows = parse_rows(html)
            row, err = pick(rows, t["ann_date"], t["ann_time"])
        except Exception as e:
            row, err, cached = None, f"{type(e).__name__}", True
        rec = dict(t)
        if row:
            rec.update({"ref_date": row["date"], "close": row["close"],
                        "pbr": row["pbr"], "per": row["per"], "mcap": row["mcap"]})
        else:
            rec.update({"ref_date": None, "pbr": None, "error": err or "行なし"})
        out.append(rec)
        print(f"{i:4d}/{len(targets)} {t['code']} {t['name'][:12]:<12} "
              f"{rec.get('ref_date') or '-'} PBR={rec.get('pbr')} {rec.get('error','')}", flush=True)
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
        if not cached:
            time.sleep(a.sleep)

    ok = [r for r in out if r.get("pbr") is not None]
    print(f"PBRが取れた: {len(ok)}/{len(out)}")


if __name__ == "__main__":
    main()
