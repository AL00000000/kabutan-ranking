# -*- coding: utf-8 -*-
"""TOB対象会社の公表直前PBRを集計する。

素の平均は外れ値(グロースの高PBR銘柄)に引っ張られるので、次の4通りを並べる。
  1. 素の平均・中央値
  2. トリム平均(上下10%を落とす)
  3. 高PBR業種を除いた平均・中央値
  4. 業種相対PBR = 各社のPBR ÷ 同じ月・同じ市場・同じ33業種の平均PBR(JPX)
     → 「その業種の中で安かったのか」だけを見る。1.0未満なら業種平均より割安。

  py analyze.py            表示
  py analyze.py --json     集計結果をJSONで吐く
"""
import argparse
import json
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
PBR = BASE / "pbr.json"
SECTORS = BASE / "sectors.json"
JPX = BASE / "jpx_perpbr.json"
OUT = BASE / "summary.json"

# JPXの業種名(「7 化学」形式)とdata_jの33業種区分を突き合わせる
JPX_PREFIX = None


def nearest_sector(entries, ann_date):
    d = date.fromisoformat(ann_date)
    best = min(entries, key=lambda e: abs((date.fromisoformat(e["asof"]) - d).days))
    return best


def market_key(market):
    if market.startswith("プライム"):
        return "プライム市場"
    if market.startswith("スタンダード"):
        return "スタンダード市場"
    if market.startswith("グロース"):
        return "グロース市場"
    return None


def prev_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y}-{m:02d}"


def sector_pbr(jpx, ym, mkt, sector):
    """JPXの月次から、その市場・その33業種の単純平均PBR"""
    for key in (prev_month(ym), ym):
        blk = jpx.get(key, {}).get(mkt)
        if not blk:
            continue
        for name, v in blk.items():
            if name.split(" ", 1)[-1] == sector and v.get("pbr"):
                return v["pbr"], key
    return None, None


def describe(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return {}
    n = len(vals)
    k = int(n * 0.1)
    trimmed = vals[k:n - k] if n - 2 * k >= 3 else vals
    return {
        "n": n,
        "mean": round(st.mean(vals), 3),
        "median": round(st.median(vals), 3),
        "trim10": round(st.mean(trimmed), 3),
        "p25": round(vals[int(n * 0.25)], 3),
        "p75": round(vals[int(n * 0.75)], 3),
        "min": vals[0],
        "max": vals[-1],
        "under1": round(sum(v < 1 for v in vals) / n * 100, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows = json.loads(PBR.read_text("utf-8"))
    sectors = json.loads(SECTORS.read_text("utf-8"))
    jpx = json.loads(JPX.read_text("utf-8")) if JPX.exists() else {}

    for r in rows:
        ent = sectors.get(r["code"])
        if ent:
            s = nearest_sector(ent, r["ann_date"])
            r["sector"] = s["sector"]
            r["scale"] = s["scale"]
            r["mkt"] = market_key(s["market"])
        else:
            r["sector"] = r["scale"] = r["mkt"] = None
        r["sector_pbr"] = r["rel_pbr"] = None
        if r.get("pbr") and r["sector"] and r["mkt"]:
            sp, used = sector_pbr(jpx, r["ann_date"][:7], r["mkt"], r["sector"])
            if sp:
                r["sector_pbr"] = sp
                r["rel_pbr"] = round(r["pbr"] / sp, 3)

    have = [r for r in rows if r.get("pbr")]
    print(f"対象会社 {len(rows)}社 / PBRが取れた {len(have)}社")
    print()
    print("■ 公表直前PBR（全件）")
    d = describe([r["pbr"] for r in have])
    print(f"  n={d['n']}  平均 {d['mean']}倍  中央値 {d['median']}倍  "
          f"トリム平均(上下10%除外) {d['trim10']}倍")
    print(f"  四分位 {d['p25']}〜{d['p75']}倍  最小 {d['min']}  最大 {d['max']}  "
          f"1倍割れ {d['under1']}%")

    print()
    print("■ 分布")
    buckets = [(0, .5), (.5, .8), (.8, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 99)]
    for lo, hi in buckets:
        c = sum(1 for r in have if lo <= r["pbr"] < hi)
        bar = "█" * round(c / max(1, len(have)) * 60)
        print(f"  {lo:>4.1f}〜{hi:<4.1f} {c:4d}社 {c/len(have)*100:5.1f}% {bar}")

    print()
    print("■ 業種相対PBR（各社PBR ÷ 同月・同市場・同業種の平均PBR）")
    rel = [r["rel_pbr"] for r in have if r["rel_pbr"]]
    d2 = describe(rel)
    if d2:
        print(f"  n={d2['n']}  平均 {d2['mean']}  中央値 {d2['median']}  "
              f"トリム平均 {d2['trim10']}  1.0未満(業種平均より割安) {d2['under1']}%")

    print()
    print("■ 業種別（3社以上）")
    by = defaultdict(list)
    for r in have:
        by[r["sector"] or "不明"].append(r["pbr"])
    for sec, vs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if len(vs) < 3:
            continue
        print(f"  {sec:<12} n={len(vs):3d}  中央値 {st.median(vs):5.2f}  平均 {st.mean(vs):5.2f}")

    print()
    print("■ 年別")
    byy = defaultdict(list)
    for r in have:
        byy[r["ann_date"][:4]].append(r["pbr"])
    for y, vs in sorted(byy.items()):
        print(f"  {y} n={len(vs):3d}  中央値 {st.median(vs):5.2f}  平均 {st.mean(vs):5.2f}  "
              f"1倍割れ {sum(v<1 for v in vs)/len(vs)*100:4.1f}%")

    print()
    print("■ 種別")
    byk = defaultdict(list)
    for r in have:
        byk[r["kind"]].append(r["pbr"])
    for k, vs in sorted(byk.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k:<8} n={len(vs):3d}  中央値 {st.median(vs):5.2f}  平均 {st.mean(vs):5.2f}")

    print()
    print("■ 市場別")
    bym = defaultdict(list)
    for r in have:
        bym[r["mkt"] or "不明"].append(r["pbr"])
    for k, vs in sorted(bym.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k:<10} n={len(vs):3d}  中央値 {st.median(vs):5.2f}  平均 {st.mean(vs):5.2f}")

    print()
    print("■ 高PBRになりやすい業種を除いた場合")
    # JPXの月次で、市場全体(プライム)の平均PBRが高い業種を落とす
    HIGH = {"情報・通信業", "サービス業", "医薬品", "精密機器", "電気機器", "その他製品"}
    kept = [r["pbr"] for r in have if r["sector"] not in HIGH]
    d3 = describe(kept)
    print(f"  除外業種: {'、'.join(sorted(HIGH))}")
    print(f"  n={d3['n']}  平均 {d3['mean']}倍  中央値 {d3['median']}倍  "
          f"トリム平均 {d3['trim10']}倍  1倍割れ {d3['under1']}%")

    ctrl_path = BASE / "control.json"
    if ctrl_path.exists():
        ctrl = json.loads(ctrl_path.read_text("utf-8"))

        def fresh(d):
            """上場廃止済みの会社は古い日付の値が返ってくるので落とす"""
            out = []
            for v in ctrl[d].values():
                if not v.get("pbr") or not v.get("date"):
                    continue
                if (date.fromisoformat(d) - date.fromisoformat(v["date"])).days > 30:
                    continue
                out.append(v)
            return out

        print()
        print("■ 対照群（2023年1月時点の東証一覧から乱数抽出した普通の上場企業）")
        for d in sorted(ctrl):
            rowsv = fresh(d)
            vals = [v["pbr"] for v in rowsv]
            stale = len([1 for v in ctrl[d].values() if v.get("pbr")]) - len(vals)
            if not vals:
                continue
            print(f"  （その時点で上場廃止済み等で除外 {stale}社）")
            c = describe(vals)
            print(f"  {d} n={c['n']:3d}  中央値 {c['median']:5.2f}  平均 {c['mean']:5.2f}  "
                  f"トリム平均 {c['trim10']:5.2f}  1倍割れ {c['under1']:4.1f}%")
        # TOB群と同じ年の対照群を並べる
        print()
        print("■ 同じ年で並べる（TOB群 vs 対照群の中央値）")
        for d in sorted(ctrl):
            y = d[:4]
            t = [r["pbr"] for r in have if r["ann_date"][:4] == y]
            c = [v["pbr"] for v in fresh(d)]
            if t and c:
                print(f"  {y}  TOB群 n={len(t):3d} 中央値 {st.median(t):5.2f} / "
                      f"対照群 n={len(c):3d} 中央値 {st.median(c):5.2f}  "
                      f"1倍割れ {sum(v<1 for v in t)/len(t)*100:4.1f}% vs "
                      f"{sum(v<1 for v in c)/len(c)*100:4.1f}%")
        # 市場区分をそろえて比べる(構成の違いで見かけの差が出るのを防ぐ)
        print()
        print("■ 市場区分をそろえた比較（中央値／1倍割れ率）")
        mk = {"プライム": "プライム市場", "スタンダード": "スタンダード市場", "グロース": "グロース市場"}
        for d in sorted(ctrl):
            y = d[:4]
            print(f"  {y}")
            for pre, name in mk.items():
                t = [r["pbr"] for r in have
                     if r["ann_date"][:4] == y and r["mkt"] == name]
                c = [v["pbr"] for v in fresh(d) if v["market"].startswith(pre)]
                if len(t) >= 3 and len(c) >= 10:
                    print(f"    {name:<10} TOB群 n={len(t):3d} {st.median(t):5.2f} "
                          f"({sum(v<1 for v in t)/len(t)*100:4.1f}%) / "
                          f"対照群 n={len(c):3d} {st.median(c):5.2f} "
                          f"({sum(v<1 for v in c)/len(c)*100:4.1f}%)")

        # 1倍割れ企業がTOBされる年率(概算)
        print()
        print("■ 「PBR1倍割れを持っていたらTOBに当たる確率」の概算")
        n_listed = 3800
        for d in sorted(ctrl):
            y = d[:4]
            c = [v["pbr"] for v in fresh(d)]
            t = [r["pbr"] for r in have if r["ann_date"][:4] == y]
            if not c or not t:
                continue
            share = sum(v < 1 for v in c) / len(c)
            pool = n_listed * share
            hits = sum(v < 1 for v in t)
            print(f"  {y}  1倍割れの母集団 概算{pool:.0f}社 / その年のTOB(1倍割れ) {hits}社 "
                  f"→ 年率 {hits/pool*100:.2f}%")

    if a.json:
        OUT.write_text(json.dumps({"rows": rows, "all": d, "rel": d2},
                                  ensure_ascii=False, indent=1), "utf-8")
        print(f"\n→ {OUT.name}")


if __name__ == "__main__":
    main()
