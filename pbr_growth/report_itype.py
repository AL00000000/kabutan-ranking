# -*- coding: utf-8 -*-
"""個人投資家の資金がグロースから抜けたのかを、価格ではなく実際の売買で見る。

itype.json は市場別・週次の投資部門別売買状況。
G は 2022-03 まで東証マザーズ、2022-04 から東証グロース(連続系列として扱う)。

単位は千円で入っているので億円に直す(1億円 = 100,000千円)。
"""
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
OKU = 1e5           # 千円 -> 億円

MARKS = {
    "2022-04": "市場再編",
    "2023-03": "PBR要請",
    "2024-01": "新NISA",
}


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    d = json.load(open(BASE / "itype.json", encoding="utf-8"))

    def year_agg(label):
        out = defaultdict(lambda: [0.0, 0.0, 0.0, 0])   # 差引き, 総代金, 比率和, 週数
        for wk, v in d.get(label, {}).items():
            y = wk[:4]
            if v["個人差引き"] is None:
                continue
            out[y][0] += v["個人差引き"] / OKU
            out[y][1] += (v["総売買代金"] or 0) / OKU
            out[y][2] += v["個人比率"] or 0
            out[y][3] += 1
        return out

    G, P = year_agg("G"), year_agg("P")
    print("■ 個人投資家の売買（年次・億円）")
    print("  グロース系 = 〜2022/3 マザーズ、2022/4〜 グロース\n")
    print(f"{'年':6s}{'週':>4s} | {'G 個人差引き':>13s}{'G 個人比率':>11s}{'G 総売買代金':>13s}"
          f" | {'P 個人差引き':>13s}{'P 個人比率':>11s}")
    for y in sorted(G):
        g, p = G[y], P.get(y, [0, 0, 0, 1])
        note = ""
        for k, v in MARKS.items():
            if k[:4] == y:
                note = f"  <- {v}"
        if g[3] < 30:
            note += f"  (週{g[3]}のみ)"
        print(f"{y:6s}{g[3]:4d} | {g[0]:12,.0f}{g[2]/max(g[3],1):10.1f}%{g[1]:13,.0f}"
              f" | {p[0]:12,.0f}{p[2]/max(p[3],1):10.1f}%{note}")

    # --- 半期。要請(2023-03)とNISA(2024-01)の分離を見る ---
    print("\n\n■ グロース系 個人差引き（半期・億円）と売買代金に対する比率\n")
    half = defaultdict(lambda: [0.0, 0.0, 0])
    for wk, v in d.get("G", {}).items():
        if v["個人差引き"] is None:
            continue
        h = f"{wk[:4]}H{1 if int(wk[5:7]) <= 6 else 2}"
        half[h][0] += v["個人差引き"] / OKU
        half[h][1] += (v["総売買代金"] or 0) / OKU
        half[h][2] += 1
    print(f"{'半期':9s}{'週':>4s}{'個人差引き':>13s}{'総売買代金':>14s}{'差引き/代金':>12s}")
    cum = 0.0
    for h in sorted(half):
        a, t, n = half[h]
        if n < 20:
            continue
        cum += a
        r = a / t * 100 if t else 0
        print(f"{h:9s}{n:4d}{a:13,.0f}{t:14,.0f}{r:11.2f}%")
    print(f"\n{'累計':9s}    {cum:13,.0f}億円")
    return 0


if __name__ == "__main__":
    sys.exit(main())
