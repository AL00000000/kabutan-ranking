# -*- coding: utf-8 -*-
"""コード→33業種・市場区分・規模区分 の対応表を作る。

TOBで上場廃止になった会社は現在のJPX一覧に載っていないので、pbr_growth/jpx_hist に
貯めてある過去の東証一覧(data_j)も併せて使い、**公表日にいちばん近い時点の一覧**を
採用する(業種は途中で変わることがある)。

  py build_sectors.py
出力: sectors.json  {"9783": [{"asof":"2024-12-30","sector":"サービス業",...}, ...]}
"""
import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
HIST = BASE.parent / "pbr_growth" / "jpx_hist"
ROWS = BASE.parent / "pbr_growth" / "jpx_rows.json"
OUT = BASE / "sectors.json"


def add(store, df):
    for r in df.to_dict("records"):
        code = str(r["コード"]).strip()
        if len(code) != 4 or str(r["33業種区分"]).strip() in ("-", "nan"):
            continue
        d = str(r["日付"])
        asof = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        store.setdefault(code, {})[asof] = {
            "name": str(r["銘柄名"]).strip(),
            "market": str(r["市場・商品区分"]).strip(),
            "sector": str(r["33業種区分"]).strip(),
            "scale": str(r["規模区分"]).strip(),
        }


def main():
    store = {}
    for f in sorted(HIST.glob("data_j_*.xls")):
        add(store, pd.read_excel(f))
        print("read", f.name)
    if ROWS.exists():
        rows = json.loads(ROWS.read_text("utf-8"))
        df = pd.DataFrame(rows[1:], columns=rows[0])
        add(store, df)
        print("read jpx_rows.json")
    out = {c: [dict(asof=k, **v) for k, v in sorted(d.items())] for c, d in store.items()}
    OUT.write_text(json.dumps(out, ensure_ascii=False), "utf-8")
    print(f"{len(out)}銘柄 → {OUT.name}")


if __name__ == "__main__":
    main()
