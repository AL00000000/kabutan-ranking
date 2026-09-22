# -*- coding: utf-8 -*-
"""候補コードごとにTDnetを引き直して、TOB対象会社と**初回公表日**を確定する。

日別クロール(raw_tob.json)だけでは初回を取り違える。理由は2つ。
  1. 初回の開示タイトルに「公開買付」が入らない案件がある
     (例: スノーピーク「ＭＢＯの実施及び応募の推奨に関するお知らせ」)
  2. 初回が検証期間より前にある案件が混ざる(ベネッセ、ベネ・ワンなど)

公表日を1日でも後ろにずらすと、その時点の株価はもうTOB価格に張り付いていて
PBRが実態より高く出る。なので会社単位でTDnetを引き直し、いちばん古い当事者開示を
採用する。

  py resolve_targets.py --since 2024-01-01
"""
import argparse
import json
import re
import time
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAW = BASE / "raw_tob.json"
CACHE = BASE / "raw_company"
OUT = BASE / "targets.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) kabutan-ranking/tob-study"
API = "https://webapi.yanoshin.jp/webapi/tdnet/list/{code}.json?limit=150"

# 対象会社(＝買われる側)が出す開示
RE_TARGET = re.compile(
    r"意見表明|賛同の意見|応募(を|することを)?推奨|"
    r"[ＭM][ＢB][ＯO]の実施|マネジメント・バイアウト|非公開化|"
    r"当社株[券式](等)?に対する公開買付")
# 続報・結果のたぐい(初回ではない)
# 「開示事項の経過」「不実施」を外さないと、続報だけが残った会社が
# 180日ルールで新しい案件として二重に立ってしまう(牧野フライスで発覚)
RE_NOT_FIRST = re.compile(
    r"訂正|結果|終了|進捗|延長|条件等の変更|撤回|意見の変更|完了|"
    r"開示事項の経過|不実施|中止|不成立|見送り|延期|見解|申入れ|回答")
# 案件の最初の開示はこの形をしている。クラスタの先頭がこれでなければ案件と見なさない
RE_FIRST = re.compile(
    r"意見表明|賛同|応募(を|することを)?推奨|[ＭM][ＢB][ＯO]の実施|非公開化")
RE_SELF = re.compile(r"自己株式|自己株券")
GAP_DAYS = 180


def http(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def company(code):
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{code}.json"
    if f.exists():
        return json.loads(f.read_text("utf-8")), True
    js = json.loads(http(API.format(code=code)).decode("utf-8"))
    items = []
    for it in js.get("items", []):
        t = it.get("Tdnet", it)
        items.append({
            "date": (t.get("pubdate") or "")[:10],
            "time": (t.get("pubdate") or "")[11:16],
            "name": (t.get("company_name") or "").strip(),
            "title": (t.get("title") or "").strip(),
            "market": (t.get("markets_string") or "").strip(),
            "url": (t.get("document_url") or "").split("rd.php?", 1)[-1],
        })
    f.write_text(json.dumps(items, ensure_ascii=False), "utf-8")
    return items, False


ZEN = str.maketrans("０１２３４５６７８９", "0123456789")


def candidates(rows):
    codes = set()
    for r in rows:
        if r["code"]:
            codes.add(r["code"])
        # 全角で「証券コード：３３７１」と書く会社がある
        title = r["title"].translate(ZEN)
        for m in re.finditer(r"(?:証券コード|コード番号)[：:\s]*([0-9]{4})", title):
            codes.add(m.group(1))
    return sorted(codes)


def kind_of(title):
    if "ＭＢＯ" in title or "MBO" in title or "マネジメント・バイアウト" in title:
        return "MBO"
    if "反対" in title or "留保" in title:
        return "反対/留保"
    return "賛同"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--sleep", type=float, default=0.5)
    a = ap.parse_args()

    rows = json.loads(RAW.read_text("utf-8"))
    codes = candidates(rows)
    print(f"候補コード {len(codes)}件")

    events = []
    for i, code in enumerate(codes, 1):
        try:
            items, cached = company(code)
        except Exception as e:
            print(f"  {code} FAIL {type(e).__name__}", flush=True)
            time.sleep(2)
            continue
        hits = [x for x in items
                if RE_TARGET.search(x["title"])
                and not RE_NOT_FIRST.search(x["title"])
                and not RE_SELF.search(x["title"])]
        hits.sort(key=lambda x: (x["date"], x["time"]))
        if hits:
            clusters = []
            cur = [hits[0]]
            for prev, nxt in zip(hits, hits[1:]):
                if (date.fromisoformat(nxt["date"]) - date.fromisoformat(prev["date"])).days > GAP_DAYS:
                    clusters.append(cur)
                    cur = []
                cur.append(nxt)
            clusters.append(cur)
            for cl in clusters:
                # 案件として認めるのは意見表明/賛同/MBO等が1件でも含まれるとき。
                # ただし公表日はクラスタの先頭(市場が最初に知った日)を使う。
                # 牧野フライスのように、買付者の予告が先で意見表明が後という順もある
                if any(RE_FIRST.search(x["title"]) for x in cl):
                    events.append((code, cl))
        if not cached:
            time.sleep(a.sleep)
        if i % 50 == 0:
            print(f"  {i}/{len(codes)}", flush=True)

    out = []
    for code, ev in events:
        first = ev[0]
        out.append({
            "code": code,
            "name": first["name"],
            "market": first["market"],
            "ann_date": first["date"],
            "ann_time": first["time"],
            "kind": kind_of(first["title"]),
            "title": first["title"],
            "n_disclosures": len(ev),
            "url": first["url"],
        })
    out.sort(key=lambda x: x["ann_date"])
    kept = [x for x in out if x["ann_date"] >= a.since]
    OUT.write_text(json.dumps(kept, ensure_ascii=False, indent=1), "utf-8")
    print(f"当事者開示ベースの案件 {len(out)}件 / {a.since}以降 {len(kept)}件 → {OUT.name}")


if __name__ == "__main__":
    main()
