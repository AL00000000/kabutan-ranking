# -*- coding: utf-8 -*-
"""panel.json から、仮説の核心に直接あたる数字を出す。

仮説は「イベント以外で株価が上昇することがかなり少なくなった」。
これは分散比や集中度より、**リターンをイベント日と非イベント日に分けた内訳**
そのもので測るのが素直。aggregate.py が既に両方を持っている。

  ret_ev    … |リターン|上位5日の合計(=イベント日のリターン)
  ret_nonev … それ以外の日の合計(=「間の期間」のリターン)

すべて対数リターン。中央値で集計する(平均は少数の急騰銘柄に引っ張られるため)。
"""
import io
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
SNAPS = ["2016-08", "2020-12", "2023-01", "2025-01", "2026-08"]
NAMES = {"G": "グロース系", "P": "プライム系", "S": "スタンダード系"}


def snap_for(half):
    y, h = int(half[:4]), half[-1]
    start = f"{y}-{'01' if h == '1' else '07'}"
    prev = [s for s in SNAPS if s < start]
    return prev[-1] if prev else SNAPS[0]


def pct(x):
    return (math.exp(x) - 1) * 100


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    panel = json.load(open(BASE / "panel.json", encoding="utf-8"))
    mkt = json.load(open(BASE / "market_hist.json", encoding="utf-8"))
    halves = sorted({h for v in panel.values() for h in v})

    print("■ リターンの内訳（中央値・%換算）")
    print("  ev = |リターン|上位5日の合計 / nonev = それ以外の日の合計\n")
    hdr = "半期      " + "".join(f"{NAMES[g][:4]+'  ev':>12s}{'nonev':>9s}" for g in "GPS")
    print(hdr)
    for half in halves:
        snap = snap_for(half)
        cells = ""
        for g in "GPS":
            ev = [panel[c][half]["ret_ev"] for c in panel
                  if mkt.get(c, {}).get(snap) == g and half in panel[c]]
            nv = [panel[c][half]["ret_nonev"] for c in panel
                  if mkt.get(c, {}).get(snap) == g and half in panel[c]]
            if len(ev) < 20:
                cells += f"{'-':>12s}{'-':>9s}"
            else:
                cells += f"{pct(statistics.median(ev)):11.1f}%{pct(statistics.median(nv)):8.1f}%"
        print(f"{half:9s}{cells}")

    # --- 3年窓で「2倍になった銘柄」の頭数 ---
    print("\n\n■ 3年で株価2倍を達成した銘柄数（期首時点の市場区分で固定）\n")
    windows = [("2017H1", "2019H2", "2017-2019 事前(コロナ前)"),
               ("2020H1", "2022H2", "2020-2022 コロナ〜金利ショック"),
               ("2023H2", "2026H1", "2023H2-2026 事後(要請後)")]
    print(f"{'期間':28s}" + "".join(f"{NAMES[g]:>22s}" for g in "GPS"))
    for a, b, label in windows:
        idx = [h for h in halves if a <= h <= b]
        snap = snap_for(a)
        row = ""
        for g in "GPS":
            codes = [c for c in panel if mkt.get(c, {}).get(snap) == g]
            full = [c for c in codes if all(h in panel[c] for h in idx)]
            dbl = [c for c in full if sum(panel[c][h]["ret"] for h in idx) >= math.log(2)]
            r = f"{len(dbl)}/{len(full)}"
            row += f"{r:>14s} ({len(dbl)/len(full)*100:4.1f}%)" if full else f"{'-':>22s}"
        print(f"{label:28s}{row}")

    # --- 同じ窓で、非イベントリターンの中央値 ---
    print("\n\n■ 3年窓の累積リターン内訳（中央値・%換算）\n")
    print(f"{'期間':28s}" + "".join(f"{NAMES[g][:4]+' 合計':>11s}{'ev':>9s}{'nonev':>9s}" for g in "GPS"))
    for a, b, label in windows:
        idx = [h for h in halves if a <= h <= b]
        snap = snap_for(a)
        row = ""
        for g in "GPS":
            codes = [c for c in panel if mkt.get(c, {}).get(snap) == g
                     and all(h in panel[c] for h in idx)]
            if len(codes) < 20:
                row += f"{'-':>29s}"
                continue
            tot = statistics.median([sum(panel[c][h]["ret"] for h in idx) for c in codes])
            ev = statistics.median([sum(panel[c][h]["ret_ev"] for h in idx) for c in codes])
            nv = statistics.median([sum(panel[c][h]["ret_nonev"] for h in idx) for c in codes])
            row += f"{pct(tot):10.1f}%{pct(ev):8.1f}%{pct(nv):8.1f}%"
        print(f"{label:28s}{row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
