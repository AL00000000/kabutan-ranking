# -*- coding: utf-8 -*-
"""raw_tob.json から「TOBされた側(対象会社)」と初回公表日を取り出す。

対象会社は自分で「意見表明」の開示を出す。ここを拾うのが一番素直で、買付者が
非上場(ファンド/SPC)でも取れる。自己株TOB(自社株買い)は買収ではないので落とす。

**初回の公表日を取り違えると株価が汚染される**(公表後の株価はTOB価格に張り付く)。
なので raw は検証したい期間より前から貯めておき、同じ会社の意見表明が180日以内に
続く場合は同じ案件の続報として扱い、いちばん古い日付を採用する。

  py extract_targets.py --since 2024-01-01
  py extract_targets.py --since 2024-01-01 --show
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAW = BASE / "raw_tob.json"
OUT = BASE / "targets.json"

RE_OPINION = re.compile(r"意見表明|賛同の意見|応募(を)?推奨|応募することを推奨")
RE_NOT_FIRST = re.compile(r"訂正|結果|終了|進捗|期間の延長|買付条件等の変更|撤回")
RE_SELF = re.compile(r"自己株式|自己株券")
GAP_DAYS = 180


def kind_of(title):
    if "ＭＢＯ" in title or "MBO" in title or "マネジメント・バイアウト" in title:
        return "MBO"
    if "反対" in title or "留保" in title:
        return "反対/留保"
    return "賛同"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()

    rows = json.loads(RAW.read_text("utf-8"))
    by_code = defaultdict(list)
    mentioned = defaultdict(list)
    other = []
    for r in rows:
        t = r["title"]
        if RE_SELF.search(t):
            other.append(("自己株TOB", r))
            continue
        if RE_OPINION.search(t) and not RE_NOT_FIRST.search(t):
            by_code[r["code"]].append(r)
        else:
            other.append(("その他", r))
            for m in re.finditer(r"(?:証券コード|コード番号)[：:\s]*(\d{4})", t):
                mentioned[m.group(1)].append(r)

    events = []
    for code, rs in by_code.items():
        rs.sort(key=lambda r: (r["date"], r["time"]))
        cur = [rs[0]]
        for prev, nxt in zip(rs, rs[1:]):
            gap = (date.fromisoformat(nxt["date"]) - date.fromisoformat(prev["date"])).days
            if gap > GAP_DAYS:
                events.append(cur)
                cur = []
            cur.append(nxt)
        events.append(cur)

    out = []
    for ev in events:
        first = ev[0]
        out.append({
            "code": first["code"],
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
    print(f"意見表明ベースの案件 {len(out)}件 / うち {a.since} 以降 {len(kept)}件 → {OUT.name}")

    miss = sorted(c for c in mentioned
                  if c not in by_code and min(r["date"] for r in mentioned[c]) >= a.since)
    print(f"意見表明を拾えていないが買付者開示に出るコード: {len(miss)}件")
    if a.show:
        print("種別:", Counter(x["kind"] for x in kept).most_common())
        print("除外:", Counter(k for k, _ in other).most_common())
        for c in miss:
            r = sorted(mentioned[c], key=lambda r: r["date"])[0]
            print(f"  {c} {r['date']} {r['name']} | {r['title'][:70]}")


if __name__ == "__main__":
    main()
