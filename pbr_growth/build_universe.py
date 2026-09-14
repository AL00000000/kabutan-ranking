# -*- coding: utf-8 -*-
"""市場区分の所属履歴を復元して、検証の母集団を確定させる。

JPXの「東証上場銘柄一覧」は現時点のスナップショットしか配っていない。
そのままだと **グロース→プライムに市場変更した成功組が母集団から抜ける**ため、
「グロースは上がらなくなった」と結論しても同語反復になる。

そこで Wayback から過去のマスタを拾い、各時点の所属を復元する。

  2016-08 / 2020-12 … 旧区分(マザーズ・JASDAQグロース)
  2023-01           … 新区分。PBR要請(2023-03-31)の3か月前 = **事前スナップショット**
  2025-01 / 2026-08 … 事後

母集団の定義は「いずれかの時点でマザーズ/JASDAQグロース/グロースに
属していた内国株」とする(= 上場時の市場で固定することの近似)。
市場変更で抜けた銘柄も残すので、成功組を落とさない。

出力: universe.json
"""
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
HIST = BASE / "jpx_hist"
CUR = BASE / "jpx_rows.json"
OUT = BASE / "universe.json"

# (ラベル, ファイル)。現在ぶんは別途 jpx_rows.json から入れる
SNAPS = [
    ("2016-08", HIST / "data_j_20160804.xls"),
    ("2020-12", HIST / "data_j_20201220.xls"),
    ("2023-01", HIST / "data_j_20230106.xls"),
    ("2025-01", HIST / "data_j_20250109.xls"),
]

GROWTHY = ("マザーズ", "グロース", "JASDAQ(グロース")   # グロース系とみなす区分


def bucket(mkt):
    """市場・商品区分を4分類に畳む。内国株以外は None。"""
    if not mkt or "外国株" in mkt:
        return None
    if "ETF" in mkt or "REIT" in mkt or "PRO" in mkt or "出資証券" in mkt:
        return None
    if "マザーズ" in mkt or "グロース" in mkt:
        return "グロース系"
    if "市場第一部" in mkt or "プライム" in mkt:
        return "プライム系"
    if "市場第二部" in mkt or "スタンダード" in mkt or "JASDAQ" in mkt:
        return "スタンダード系"
    return None


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    hist = defaultdict(dict)        # code -> {label: bucket}
    asof = {}

    for label, path in SNAPS:
        df = pd.read_excel(path, engine="xlrd")
        asof[label] = str(df["日付"].iloc[0])
        for code, mkt in zip(df["コード"].astype(str), df["市場・商品区分"].astype(str)):
            b = bucket(mkt)
            if b:
                hist[code.strip()][label] = b

    cur = json.load(open(CUR, encoding="utf-8"))
    asof["2026-08"] = str(cur[1][0])
    for r in cur[1:]:
        b = bucket(r[3])
        if b:
            hist[str(r[1]).strip()]["2026-08"] = b

    labels = [l for l, _ in SNAPS] + ["2026-08"]
    print("スナップショットの基準日:")
    for l in labels:
        print(f"  {l}  {asof[l]}")

    # --- 母集団: いずれかの時点でグロース系だった銘柄 ---
    universe = {c: h for c, h in hist.items() if "グロース系" in h.values()}
    print(f"\nグロース系に一度でも属した内国株: {len(universe)}銘柄")

    # --- 2023-01(要請前) を起点にした遷移 ---
    g23 = [c for c, h in hist.items() if h.get("2023-01") == "グロース系"]
    trans = Counter(hist[c].get("2026-08", "消滅(上場廃止など)") for c in g23)
    print(f"\n2023-01時点のグロース {len(g23)}銘柄 → 2026-08の所属:")
    for k, v in trans.most_common():
        print(f"  {v:5d}  {k}   ({v/len(g23)*100:.1f}%)")

    # --- 2020-12(再編前・マザーズ) を起点にした遷移 ---
    m20 = [c for c, h in hist.items() if h.get("2020-12") == "グロース系"]
    t20 = Counter(hist[c].get("2026-08", "消滅(上場廃止など)") for c in m20)
    print(f"\n2020-12時点のマザーズ系 {len(m20)}銘柄 → 2026-08の所属:")
    for k, v in t20.most_common():
        print(f"  {v:5d}  {k}   ({v/len(m20)*100:.1f}%)")

    # --- 現在グロースだけを母集団にした場合に何が抜けるか ---
    now_g = {c for c, h in hist.items() if h.get("2026-08") == "グロース系"}
    dropped = [c for c in g23 if c not in now_g]
    print(f"\n『現在のグロース』だけを母集団にすると、2023-01のグロースのうち "
          f"{len(dropped)}銘柄 ({len(dropped)/len(g23)*100:.1f}%) が脱落する。")

    OUT.write_text(json.dumps(
        {"asof": asof, "labels": labels, "universe": universe,
         "growth_2023_01": sorted(g23), "growth_2026_08": sorted(now_g),
         "dropped_if_current_only": sorted(dropped)},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
