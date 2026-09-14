# -*- coding: utf-8 -*-
"""Phase 0: 決算発表日を使わずに「値動きの質」が変わったかを測る。

仮説は「PBR要請以降、グロース株は決算のたびに振れるだけで、
間の期間に継続的な買いが入らなくなった」。決算日データの構築は重いので、
まず決算日なしで兆候が出るかを見て、Phase 1に進む価値を判定する。

銘柄 × 半期 で以下を出す:

  ret      … 半期リターン(対数)
  conc5    … |日次リターン|の上位5日が、|リターン|合計に占める割合
             高いほど「一部の日にリターンが集中」= イベント偏重
  vr5/vr20 … 分散比 Var(k日リターン)/(k×Var(1日リターン))
             >1 トレンド(継続的な買い) / <1 往復(買いが続かない)
  vr*_nj   … 上位5日のリターンを0に置いた系列で同じものを計算。
             ジャンプを除いた「間の期間」のトレンド性。これが仮説の核心。
  maxrun   … 連騰の最大日数 / meanrun … 平均
  tvalue   … 日次売買代金の中央値(百万円)

**分散比の注意**: 重複するk日和を使っている。銘柄間・期間間の比較には使えるが、
水準そのものを理論値1と厳密に比べる用途には向かない(重複窓のぶん自由度が落ちる)。

母集団は期首時点の市場区分で固定する(market_hist.json)。
市場変更した銘柄も追い続けるので、成功組を落とさない。

出力: panel.json (銘柄×半期の生の指標) と標準出力のサマリ
"""
import io
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
BARS = BASE.parent / "cache_bars_10y"
MKT = BASE / "market_hist.json"
OUT = BASE / "panel.json"

MIN_DAYS = 80           # 半期の最低営業日数
TOPN = 5                # 「イベント」とみなすジャンプ日数
SNAPS = ["2016-08", "2020-12", "2023-01", "2025-01", "2026-08"]


def half_of(d):
    y, m = int(d[:4]), int(d[5:7])
    return f"{y}H{1 if m <= 6 else 2}"


def snap_for(half):
    """その半期の期首より前の、最も近いスナップショットを返す(先読み防止)。"""
    y = int(half[:4]); h = half[-1]
    start = f"{y}-{'01' if h == '1' else '07'}"
    prev = [s for s in SNAPS if s < start]
    return prev[-1] if prev else SNAPS[0]


def var(xs):
    return statistics.pvariance(xs) if len(xs) > 1 else 0.0


def vratio(r, k):
    """Var(重複k日和)/(k*Var(1日))。"""
    if len(r) < k * 3:
        return None
    v1 = var(r)
    if v1 <= 0:
        return None
    sums = [sum(r[i:i + k]) for i in range(len(r) - k + 1)]
    return var(sums) / (k * v1)


def runs(r):
    best = cur = 0
    lens = []
    for x in r:
        if x > 0:
            cur += 1
            best = max(best, cur)
        else:
            if cur:
                lens.append(cur)
            cur = 0
    if cur:
        lens.append(cur)
    return best, (statistics.mean(lens) if lens else 0.0)


def metrics(bars):
    """bars: [日付, 始値, 高値, 安値, 終値, 出来高] -> {半期: 指標}"""
    out = {}
    byh = defaultdict(list)
    prev = None
    for d, o, h, l, c, v in bars:
        if prev is not None and prev > 0 and c > 0:
            byh[half_of(d)].append((math.log(c / prev), c * v / 1e6))
        prev = c
    for half, rows in byh.items():
        if len(rows) < MIN_DAYS:
            continue
        r = [x[0] for x in rows]
        tv = [x[1] for x in rows]
        absr = sorted(range(len(r)), key=lambda i: -abs(r[i]))
        top = set(absr[:TOPN])
        sa = sum(abs(x) for x in r)
        nj = [0.0 if i in top else x for i, x in enumerate(r)]
        mx, mn = runs(r)
        out[half] = {
            "n": len(r),
            "ret": round(sum(r), 5),
            "conc5": round(sum(abs(r[i]) for i in top) / sa, 4) if sa else None,
            "ret_ev": round(sum(r[i] for i in top), 5),
            "ret_nonev": round(sum(nj), 5),
            "vr5": vratio(r, 5), "vr20": vratio(r, 20),
            "vr5_nj": vratio(nj, 5), "vr20_nj": vratio(nj, 20),
            "maxrun": mx, "meanrun": round(mn, 3),
            "tvalue": round(statistics.median(tv), 1),
        }
    return out


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    mkt = json.load(open(MKT, encoding="utf-8"))
    files = sorted(BARS.glob("*.json"))
    print(f"日足ファイル {len(files)}件を読み込み中...")

    panel = {}
    for i, p in enumerate(files, 1):
        code = p.stem
        try:
            bars = json.loads(p.read_text(encoding="utf-8"))["bars"]
        except Exception:
            continue
        m = metrics(bars)
        if m:
            panel[code] = m
        if i % 800 == 0:
            print(f"  {i}/{len(files)}", flush=True)

    OUT.write_text(json.dumps(panel, ensure_ascii=False), encoding="utf-8")
    print(f"銘柄 {len(panel)}件 -> {OUT.name}\n")

    halves = sorted({h for v in panel.values() for h in v})
    keys = ["conc5", "vr5_nj", "vr20_nj", "meanrun", "ret"]
    for grp in ["G", "P", "S"]:
        print(f"===== {grp} (期首時点の市場区分で固定) =====")
        print(f"{'半期':8s} {'銘柄数':>5s} " + " ".join(f"{k:>9s}" for k in keys))
        for half in halves:
            snap = snap_for(half)
            vals = defaultdict(list)
            n = 0
            for code, hs in panel.items():
                if mkt.get(code, {}).get(snap) != grp or half not in hs:
                    continue
                n += 1
                for k in keys:
                    x = hs[half].get(k)
                    if x is not None:
                        vals[k].append(x)
            if n < 20:
                continue
            cells = " ".join(
                f"{statistics.median(vals[k]):9.3f}" if vals[k] else f"{'-':>9s}"
                for k in keys)
            print(f"{half:8s} {n:5d} {cells}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
