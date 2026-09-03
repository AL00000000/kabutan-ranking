# -*- coding: utf-8 -*-
"""新高値に載った銘柄の「その後」を集計する。

docs/data_newhigh/*.json に貯まっている過去の新高値記録それぞれについて、
記録日の終値を起点に **5営業日後(≒1週間)** と **20営業日後(≒1か月)** の騰落率を出し、
平均・中央値・勝率をまとめる。TOPIX(1306)の同期間の騰落率を引いた超過リターンも併記する
(「1週間で+2%」だけでは地合いなのか銘柄の力なのか分からないため)。

上場来かどうかの区別は過去ぶんの記録に入っていないので、月足を使って**遡って判定し直す**。

出力: docs/data_newhigh/followup.json

使用例:
  py build_newhigh_followup.py
  py build_newhigh_followup.py --no-fetch   … 月足を取りに行かず、キャッシュ済みだけで集計
"""
import argparse
import json
import statistics
import sys
import time
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
DOCS = BASE / "docs" / "data_newhigh"
CACHE = BASE / "cache_bars"
CACHE_MO = BASE / "cache_bars_mo"
PERIOD_CACHE = BASE / "cache_period" / "bars.json"

HORIZONS = [(5, "1週間"), (20, "1か月")]
BENCH = "1306"          # TOPIX連動ETF


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def daily(code):
    """cache_bars の [[日付, 高値, 終値, 出来高, 安値], ...] を返す。"""
    c = load(CACHE / f"{code}.json")
    return c["bars"] if c and c.get("bars") else []


def monthly(code, fetch_ok):
    c = load(CACHE_MO / f"{code}.json")
    if c and c.get("bars"):
        return c["bars"]
    if not fetch_ok:
        return []
    import importlib.util
    spec = importlib.util.spec_from_file_location("fn", BASE / "fetch_newhigh.py")
    fn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fn)
    bars = fn.fetch_monthly(code)
    out = [[d.isoformat(), h] for d, h in bars]
    CACHE_MO.mkdir(parents=True, exist_ok=True)
    (CACHE_MO / f"{code}.json").write_text(
        json.dumps({"month": date.today().strftime("%Y-%m"), "bars": out},
                   ensure_ascii=False), encoding="utf-8")
    time.sleep(0.35)
    return out


def bench_closes():
    """TOPIX(1306)の {日付: 終値}。期間騰落率タブのキャッシュを使い回す。"""
    c = load(PERIOD_CACHE, {}) or {}
    bars = c.get(BENCH) or []
    return {b[0]: b[1] for b in bars}


def stats(vals):
    if not vals:
        return None
    return {
        "n": len(vals),
        "mean": round(statistics.mean(vals), 2),
        "median": round(statistics.median(vals), 2),
        "win": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
        "max": round(max(vals), 2),
        "min": round(min(vals), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()

    files = sorted(p for p in DOCS.glob("????-??-??.json"))
    if not files:
        print("記録がありません", file=sys.stderr)
        return 1

    records = []
    for p in files:
        d = load(p) or {}
        for s in d.get("stocks", []):
            records.append({"date": p.stem, "code": s["code"], "name": s["name"],
                            "close": s.get("close"), "high": s.get("high")})
    codes = sorted({r["code"] for r in records})
    print(f"記録 {len(records)}件 / {len(files)}営業日 / {len(codes)}銘柄", flush=True)

    bench = bench_closes()
    if not bench:
        print("注意: TOPIXの終値が読めないため、超過リターンは出しません", file=sys.stderr)

    # 銘柄ごとに日足・月足を用意
    dmap, mmap = {}, {}
    for i, c in enumerate(codes, 1):
        dmap[c] = daily(c)
        mmap[c] = monthly(c, not args.no_fetch)
        if i % 50 == 0:
            print(f"  {i}/{len(codes)}", flush=True)

    rows, skipped = [], 0
    for r in records:
        bars = dmap.get(r["code"]) or []
        idx = {b[0]: i for i, b in enumerate(bars)}
        i = idx.get(r["date"])
        if i is None or bars[i][2] is None:
            skipped += 1
            continue
        base = bars[i][2]

        # 上場来かどうかを遡って判定(当月は月足に当日が含まれるので日足側で見る)
        cur = r["date"][:7]
        mv = [h for d, h in (mmap.get(r["code"]) or []) if d[:7] < cur]
        dv = [b[1] for b in bars[:i] if b[1] is not None]
        prev_ath = max(mv + dv) if (mv or dv) else None
        is_ath = bool(prev_ath and r["high"] and r["high"] >= prev_ath)

        row = {"date": r["date"], "code": r["code"], "ath": is_ath}
        for n, _ in HORIZONS:
            j = i + n
            if j < len(bars) and bars[j][2] is not None:
                ret = (bars[j][2] / base - 1) * 100
                row[f"r{n}"] = round(ret, 2)
                b0, b1 = bench.get(bars[i][0]), bench.get(bars[j][0])
                if b0 and b1:
                    row[f"e{n}"] = round(ret - (b1 / b0 - 1) * 100, 2)
        rows.append(row)

    def agg(sel):
        out = {}
        for n, label in HORIZONS:
            vals = [x[f"r{n}"] for x in rows if sel(x) and f"r{n}" in x]
            ex = [x[f"e{n}"] for x in rows if sel(x) and f"e{n}" in x]
            out[str(n)] = {"label": label, "raw": stats(vals), "excess": stats(ex)}
        return out

    payload = {
        "generated": date.today().isoformat(),
        "from": files[0].stem, "to": files[-1].stem,
        "days": len(files), "records": len(rows), "skipped": skipped,
        "horizons": [{"n": n, "label": l} for n, l in HORIZONS],
        "all": agg(lambda x: True),
        "ath": agg(lambda x: x["ath"]),
        "w52": agg(lambda x: not x["ath"]),
        "counts": {"all": len(rows), "ath": sum(1 for x in rows if x["ath"]),
                   "w52": sum(1 for x in rows if not x["ath"])},
    }
    (DOCS / "followup.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"\n集計 {len(rows)}件(除外 {skipped}件) / "
          f"上場来 {payload['counts']['ath']} ・ 52週のみ {payload['counts']['w52']}")
    for key, jp in (("all", "全体"), ("ath", "上場来"), ("w52", "52週のみ")):
        print(f"\n[{jp}]")
        for n, label in HORIZONS:
            a = payload[key][str(n)]
            if not a["raw"]:
                print(f"  {label}後: データ不足")
                continue
            r, e = a["raw"], a["excess"]
            print(f"  {label}後(n={r['n']:>3}): 平均 {r['mean']:+.2f}% / 中央値 {r['median']:+.2f}% "
                  f"/ 勝率 {r['win']:.0f}%" +
                  (f"  ｜対TOPIX 平均 {e['mean']:+.2f}% / 中央値 {e['median']:+.2f}%" if e else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
