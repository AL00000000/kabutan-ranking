# -*- coding: utf-8 -*-
"""投資部門別売買状況(週次)から、市場別の個人・海外投資家の売買を取り出す。

1ファイルに2週ぶんが横に並んでいる(列4-6が前週、列8-10が当週)。
ファイル名はYYMMW(月内の週番号)なので前後のファイルで週が重複する。
週の日付文字列で重複を除く。

シート名は市場再編で変わる:
  2015-01〜2022-03 … TSE 1st / TSE 2nd / TSE Mothers / TSE JASDAQ
  2022-04〜        … TSE Prime / TSE Standard / TSE Growth

出力: itype.json
  {市場: {"YYYY-MM-DD": {個人買い, 個人売り, 個人差引き, 個人比率,
                         海外差引き, 総売買代金}}}   単位は千円
"""
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
RAW = BASE / "itype_raw"
OUT = BASE / "itype.json"

# シート名 -> 統一ラベル。マザーズはグロースの前身として同じ系列にまとめる
SHEETS = {
    "TSE Prime": "P", "TSE 1st": "P",
    "TSE Standard": "S", "TSE 2nd": "S2", "TSE JASDAQ": "JQ",
    "TSE Growth": "G", "TSE Mothers": "G",
}
COLS = {"w1": (4, 5, 6), "w2": (8, 9, 10)}   # (金額, 比率, 差引き)


def num(x):
    if x is None:
        return None
    s = str(x).replace(",", "").replace("△", "-").strip()
    if s in ("", "nan", "-", "―"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def find_row(df, *needles):
    for i in range(len(df)):
        c0 = str(df.iat[i, 0]).replace("　", "")
        if all(n in c0 for n in needles):
            return i
    return None


def week_dates(df, year, month):
    """行10の 'MM/DD～MM/DD' を (開始日, 終了日) の ISO に直す。"""
    out = {}
    for key, col in (("w1", 3), ("w2", 7)):
        s = None
        for i in range(6, 16):
            v = str(df.iat[i, col])
            if re.match(r"\d{2}/\d{2}", v):
                s = v
                break
        if not s:
            continue
        m = re.findall(r"(\d{2})/(\d{2})", s)
        if len(m) < 2:
            continue
        (m1, d1), (m2, d2) = m[0], m[1]
        # 年またぎ: ヘッダの月より大きい月が出たら前年
        y1 = year - 1 if int(m1) > month + 6 else year
        y2 = year - 1 if int(m2) > month + 6 else year
        out[key] = (f"{y1}-{m1}-{d1}", f"{y2}-{m2}-{d2}")
    return out


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    data = defaultdict(dict)
    files = sorted(RAW.glob("*.xls"))
    print(f"{len(files)}ファイルを解析中...")
    bad = []

    for n, p in enumerate(files, 1):
        try:
            xl = pd.ExcelFile(p, engine="xlrd")
        except Exception as e:
            bad.append([p.name, repr(e)[:70]])
            continue
        for sh in xl.sheet_names:
            label = SHEETS.get(sh.strip())
            if not label:
                continue
            df = xl.parse(sh, header=None)
            hdr = str(df.iat[3, 0])
            m = re.search(r"(\d{4})年(\d{1,2})月", hdr)
            if not m:
                continue
            year, month = int(m.group(1)), int(m.group(2))
            wk = week_dates(df, year, month)
            r_ind = find_row(df, "個", "人")
            r_for = find_row(df, "海外投資家")
            tot = num(df.iat[8, 1])
            if r_ind is None:
                continue
            for key, (cv, cr, cb) in COLS.items():
                if key not in wk:
                    continue
                end = wk[key][1]
                sell = num(df.iat[r_ind, cv])
                buy = num(df.iat[r_ind + 1, cv])
                if sell is None or buy is None:
                    continue
                # 差引きはExcel上、売り側と買い側のどちらか大きいほうの行に書かれる
                # (セル結合の都合)。行を決め打ちすると売り越しの週を取りこぼすので、
                # 買い-売り で計算する。シート記載値は検算にだけ使う。
                fsell = num(df.iat[r_for, cv]) if r_for else None
                fbuy = num(df.iat[r_for + 1, cv]) if r_for else None
                data[label][end] = {
                    "個人売り": sell, "個人買い": buy,
                    "個人差引き": buy - sell,
                    "個人差引き_記載": (num(df.iat[r_ind + 1, cb])
                                  if num(df.iat[r_ind + 1, cb]) is not None
                                  else num(df.iat[r_ind, cb])),
                    "個人比率": num(df.iat[r_ind + 2, cr]),
                    "海外差引き": (fbuy - fsell) if (fbuy is not None and fsell is not None) else None,
                    "総売買代金": tot,
                }
        if n % 100 == 0:
            print(f"  {n}/{len(files)}", flush=True)

    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"\n読めなかったファイル: {len(bad)}")
    for label in ["P", "S", "S2", "JQ", "G"]:
        if label not in data:
            continue
        ks = sorted(data[label])
        print(f"  {label:3s} {len(ks):4d}週  {ks[0]} 〜 {ks[-1]}")
    print(f"-> {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
