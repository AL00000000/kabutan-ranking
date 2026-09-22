# -*- coding: utf-8 -*-
"""対照群: ふつうの上場企業のPBR分布を、同じ物差し(IRBANK)で取る。

TOB対象のPBRが低いかどうかは、**同じ時期の市場全体と比べて**はじめて言える。
全銘柄を取ると4000リクエストになるので、2023年1月時点の東証一覧から乱数で
300社だけ抜き、同じ日付のPBRを拾う。母集団を2023年1月にするのは、その後
上場廃止になった会社を落とさない(生存バイアスを避ける)ため。

  py fetch_control.py --n 300 --dates 2024-06-28,2025-06-30,2026-06-30
出力: control.json
"""
import argparse
import json
import random
import time
from pathlib import Path

import pandas as pd

from fetch_pbr import get_html, parse_rows

BASE = Path(__file__).resolve().parent
MASTER = BASE.parent / "pbr_growth" / "jpx_hist" / "data_j_20230106.xls"
OUT = BASE / "control.json"


def universe():
    df = pd.read_excel(MASTER)
    out = []
    for r in df.to_dict("records"):
        code = str(r["コード"]).strip()
        mkt = str(r["市場・商品区分"]).strip()
        if len(code) == 4 and mkt.endswith("（内国株式）") or mkt.startswith(("プライム", "スタンダード", "グロース")):
            if str(r["33業種区分"]).strip() not in ("-", "nan"):
                out.append({"code": code, "name": str(r["銘柄名"]).strip(),
                            "market": mkt, "sector": str(r["33業種区分"]).strip()})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--dates", default="2024-06-28,2025-06-30,2026-06-30")
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=20260923)
    a = ap.parse_args()

    uni = universe()
    random.seed(a.seed)
    sample = random.sample(uni, min(a.n, len(uni)))
    dates = a.dates.split(",")
    res = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}

    for d in dates:
        res.setdefault(d, {})
        for i, c in enumerate(sample, 1):
            if c["code"] in res[d]:
                continue
            try:
                html, cached = get_html(c["code"], d)
                rows = [r for r in parse_rows(html) if r["date"] <= d]
                rec = {"pbr": rows[0]["pbr"], "date": rows[0]["date"],
                       "sector": c["sector"], "market": c["market"]} if rows else {"pbr": None}
            except Exception as e:
                rec, cached = {"pbr": None, "err": type(e).__name__}, True
            res[d][c["code"]] = rec
            if i % 25 == 0:
                print(f"{d} {i}/{len(sample)}", flush=True)
                OUT.write_text(json.dumps(res, ensure_ascii=False), "utf-8")
            if not cached:
                time.sleep(a.sleep)
        OUT.write_text(json.dumps(res, ensure_ascii=False), "utf-8")
        got = [v["pbr"] for v in res[d].values() if v.get("pbr")]
        print(f"{d}: PBRが取れた {len(got)}/{len(sample)}社", flush=True)


if __name__ == "__main__":
    main()
