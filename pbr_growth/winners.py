# -*- coding: utf-8 -*-
"""Q2: 実際に上がった銘柄について、リターンがどこに乗っていたかを見る。

中央値では2017-2019の時点でグロースは「数日で稼いで残りはジリ貧」だった。
だが当初の問いは勝者についてのものなので、勝者だけを取り出して比べる。

選抜は**期間ごとに独立**に行う(現時点から振り返って勝者を選ぶと後知恵になる)。
各3年窓で、その窓の間に2倍以上になった銘柄をその窓の勝者とする。

指標:
  top5_share  … 上位5日の上昇が、期間トータルの上昇に占める割合
  n_for_total … 上位から何日ぶんを足すと期間リターンに届くか
                「3年間の上昇は実質何日で起きたか」。小さいほどイベント偏重
  vr20        … 分散比(順序に依存する = タイミングの情報を持つ)
  meanrun     … 連騰の平均日数

**注意**: top5_share と n_for_total は日次リターンの順序を入れ替えても
値が変わらない。「決算日に集中していたか」は測れない。測れるのは
「上昇が少数の日に偏っていたか」まで。トレード可能性の話としては
それで十分だが、イベントとの結びつきはPhase 1(決算日)を待つ。
"""
import io
import json
import math
import statistics
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
BARS = BASE.parent / "cache_bars_10y"
SNAPS = ["2016-08", "2020-12", "2023-01", "2025-01", "2026-08"]
WINDOWS = [("2017-01-01", "2019-12-31", "2016-08", "2017-2019 事前(コロナ前)"),
           ("2020-01-01", "2022-12-31", "2016-08", "2020-2022 コロナ〜金利"),
           ("2023-07-01", "2026-06-30", "2023-01", "2023H2-2026 要請後")]


def daily(bars, a, b):
    r, prev = [], None
    for d, o, h, l, c, v in bars:
        if a <= d <= b:
            if prev and prev > 0 and c > 0:
                r.append(math.log(c / prev))
            prev = c
        elif d < a:
            prev = c
    return r


def stats(r):
    tot = sum(r)
    srt = sorted(r, reverse=True)
    top5 = sum(srt[:5])
    n = 0
    acc = 0.0
    for x in srt:
        acc += x
        n += 1
        if acc >= tot:
            break
    import importlib
    A = importlib.import_module("aggregate")
    return {"tot": tot, "top5_share": top5 / tot if tot > 0 else None,
            "n_for_total": n, "vr20": A.vratio(r, 20), "meanrun": A.runs(r)[1]}


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.path.insert(0, str(BASE))
    mkt = json.load(open(BASE / "market_hist.json", encoding="utf-8"))
    cache = {}
    for p in BARS.glob("*.json"):
        cache[p.stem] = json.loads(p.read_text(encoding="utf-8"))["bars"]
    print(f"日足 {len(cache)}銘柄\n")

    print("■ 各3年窓で2倍以上になった銘柄（勝者）の、上昇の集中度")
    print("  top5_share = 上位5日の上昇 ÷ 期間リターン")
    print("  n_for_total = 上位から何日ぶんで期間リターンに届くか\n")
    print(f"{'期間':26s}{'市場':6s}{'勝者数':>6s}{'top5_share':>12s}"
          f"{'n_for_total':>13s}{'vr20':>8s}{'meanrun':>9s}{'営業日':>7s}")
    for a, b, snap, label in WINDOWS:
        for g in "GPS":
            codes = [c for c in cache if mkt.get(c, {}).get(snap) == g]
            rows = []
            nd = []
            for c in codes:
                r = daily(cache[c], a, b)
                if len(r) < 500:
                    continue
                if sum(r) < math.log(2):
                    continue
                s = stats(r)
                if s["top5_share"] is None:
                    continue
                rows.append(s)
                nd.append(len(r))
            if len(rows) < 10:
                print(f"{label:26s}{g:6s}{len(rows):6d}{'(少数)':>12s}")
                continue
            med = lambda k: statistics.median([x[k] for x in rows if x[k] is not None])
            print(f"{label:26s}{g:6s}{len(rows):6d}{med('top5_share'):12.3f}"
                  f"{med('n_for_total'):13.0f}{med('vr20'):8.3f}"
                  f"{med('meanrun'):9.3f}{statistics.median(nd):7.0f}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
