# -*- coding: utf-8 -*-
"""過去の新高値を日足から再現し、「その後の騰落率」の標本を増やす。

実記録(docs/data_newhigh/*.json)は2026-07-30開始でまだ24営業日ぶんしかない。
そこで日足5年ぶんを取り直し、**過去の各営業日について新高値だったかを計算し直して**
標本を数千件régime に増やす。

  1. 母集団: cache_bars にある銘柄(=株探の売買代金ランキングに載ったことがある銘柄)。
     各日について「終値×出来高 ≧ 10億円」の日だけを対象にする(実運用の条件に合わせる)。
  2. 52週新高値: 当日高値 ≧ その日を含まない直近365日の最高値。
  3. 上場来新高値: さらに月足(上場来)+それまでの日足の最高値も超えたもの。
  4. 5営業日後/20営業日後の終値騰落率と、TOPIX(1306)を引いた超過リターンを出す。

**この再現には偏りがある。**母集団は「直近で売買代金ランキングに載った銘柄」なので、
昔は流動性があったが今は無い銘柄が入っていない(生存バイアス)。実運用の母集団は
その日の株探ランキング上位800銘柄なので、完全には一致しない。参考値として扱うこと。

出力: docs/data_newhigh/backfill.json

使用例:
  py backfill_newhigh.py --fetch     … 5年ぶんの日足を取得(初回・約10分)
  py backfill_newhigh.py             … 取得済みキャッシュから集計だけやり直す
"""
import argparse
import json
import statistics
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
DOCS = BASE / "docs" / "data_newhigh"
CACHE = BASE / "cache_bars"
CACHE5 = BASE / "cache_bars_5y"
CACHE_MO = BASE / "cache_bars_mo"
PERIOD_CACHE = BASE / "cache_period" / "bars.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}.T"
       "?range=5y&interval=1d")
MIN_VALUE = 1000        # 売買代金の下限(百万円) = 10億円
WINDOW = 365            # 52週
HORIZONS = [(5, "1週間"), (20, "1か月")]
BENCH = "1306"
SLEEP = 0.35

# 相場環境で切った期間。良し悪しは日経平均の実績で決めている
# (2021-09〜2022-12 は -12.0%、2025-04-07〜2026-03-02 は +86.5%、
#  2026-04-01〜2026-06-23 は +29.9%)。
REGIMES = [
    ("bad2122",  "2021-09〜2022-12（悪:日経-12%）", "2021-09-06", "2022-12-30"),
    ("good2503", "2025-04〜2026-03（良:日経+87%）", "2025-04-07", "2026-03-02"),
    ("good2606", "2026-04〜2026-06（良:日経+30%）", "2026-04-01", "2026-06-23"),
]
N225 = "N225"          # cache_bars_5y/N225.json (^N225 を保存したもの)
MA_DAYS = 200


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def fetch5(code):
    req = urllib.request.Request(URL.format(sym=code), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    res = (j.get("chart") or {}).get("result") or []
    if not res:
        return []
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    off = (r0.get("meta") or {}).get("gmtoffset", 32400)
    hi, cl, vo = q.get("high") or [], q.get("close") or [], q.get("volume") or []
    out = []
    for i, t in enumerate(ts):
        h = hi[i] if i < len(hi) else None
        c = cl[i] if i < len(cl) else None
        v = vo[i] if i < len(vo) else None
        if h is None or c is None:
            continue
        d = datetime.fromtimestamp(t + off, tz=timezone.utc).date().isoformat()
        out.append([d, float(h), float(c), 0.0 if v is None else float(v)])
    return out


def clean_bars(bars):
    """Yahooの日足に混ざる明らかな異常値を落とす。

    実際に見つかった例:
      - 8303: 終値が 55,319,998,464 の行が12本(桁が壊れている)
      - 1306: 2026-03-30 と 03-31 の **2日連続** で終値が約1/10(383 -> 37)。翌日には戻る

    2種類で弾く:
      1. 系列の中央値から20倍以上/20分の1以下に外れている行(桁壊れ)
      2. **前5本の中央値と後5本の中央値の両方から50%以上外れ、かつその2つの中央値どうしは
         30%以内**に収まっている行。行って戻る=ノイズと判断する。
         単純に隣と比べる方式だと、上の1306のように異常が2日続いたときに
         「隣も異常」なので見逃す。中央値を使うと数日続く不良も拾える。
         本物の急騰・急落は水準が切り替わるので前後の中央値が乖離し、これには当たらない。
    """
    vals = sorted(b[2] for b in bars if b[2])
    if not vals:
        return bars, 0
    med = vals[len(vals) // 2]
    ok = [b for b in bars if b[2] and med / 20 <= b[2] <= med * 20]
    dropped = len(bars) - len(ok)

    def mid(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else None

    out = []
    for i, b in enumerate(ok):
        pre = mid([x[2] for x in ok[max(0, i - 5):i] if x[2]])
        post = mid([x[2] for x in ok[i + 1:i + 6] if x[2]])
        if pre and post and b[2]:
            odd = abs(b[2] / pre - 1) > 0.5 and abs(b[2] / post - 1) > 0.5
            stable = abs(post / pre - 1) < 0.3
            if odd and stable:
                dropped += 1
                continue
        out.append(b)
    return out, dropped


def prev_max(bars, idx=1):
    """各日について「その日を含まない直近365日の最高値」(単調デックでO(n))。"""
    n = len(bars)
    out = [None] * n
    dq = deque()
    for i in range(n):
        if i > 0:
            k = i - 1
            while dq and bars[dq[-1]][idx] <= bars[k][idx]:
                dq.pop()
            dq.append(k)
        di = datetime.fromisoformat(bars[i][0]).date()
        while dq:
            dj = datetime.fromisoformat(bars[dq[0]][0]).date()
            if (di - dj).days > WINDOW:
                dq.popleft()
            else:
                break
        out[i] = bars[dq[0]][idx] if dq else None
    return out


def tail_mean(v, frac, top):
    """上位/下位 frac 割の平均。標本が少ないときは None を返す。"""
    if len(v) < 10:
        return None
    k = max(1, int(round(len(v) * frac)))
    sv = sorted(v, reverse=top)
    return round(sum(sv[:k]) / k, 2)


def stats(v):
    if not v:
        return None
    return {
        "n": len(v),
        "mean": round(statistics.mean(v), 2),
        "median": round(statistics.median(v), 2),
        "win": round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
        "top20": tail_mean(v, 0.2, True),      # 上位2割の平均
        "bot20": tail_mean(v, 0.2, False),     # 下位2割の平均
    }



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="5年ぶんの日足を取得し直す")
    ap.add_argument("--limit", type=int, help="銘柄数を絞ってお試し")
    args = ap.parse_args()

    codes = sorted(p.stem for p in CACHE.glob("*.json"))
    if args.limit:
        codes = codes[:args.limit]
    print(f"対象 {len(codes)} 銘柄", flush=True)

    CACHE5.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        got = 0
        for i, c in enumerate(codes, 1):
            p = CACHE5 / f"{c}.json"
            if p.exists():
                continue
            try:
                bars = fetch5(c)
            except Exception as e:                 # noqa: BLE001
                print(f"  ! {c}: {e}", file=sys.stderr)
                bars = []
            p.write_text(json.dumps({"bars": bars}, ensure_ascii=False),
                         encoding="utf-8")
            got += 1
            time.sleep(SLEEP)
            if i % 100 == 0:
                print(f"  {i}/{len(codes)} (新規取得 {got})", flush=True)
        print(f"日足5年 取得完了(新規 {got}銘柄)", flush=True)

        # 上場来判定に月足が要る。無い銘柄だけ取る
        import importlib.util
        spec = importlib.util.spec_from_file_location("fn", BASE / "fetch_newhigh.py")
        fn = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fn)
        CACHE_MO.mkdir(parents=True, exist_ok=True)
        need = [c for c in codes if not (CACHE_MO / f"{c}.json").exists()]
        print(f"月足の未取得 {len(need)}銘柄", flush=True)
        for i, c in enumerate(need, 1):
            try:
                bars = fn.fetch_monthly(c)
            except Exception as e:                 # noqa: BLE001
                print(f"  ! 月足 {c}: {e}", file=sys.stderr)
                bars = []
            (CACHE_MO / f"{c}.json").write_text(
                json.dumps({"month": datetime.now().strftime("%Y-%m"),
                            "bars": [[d.isoformat(), h] for d, h in bars]},
                           ensure_ascii=False), encoding="utf-8")
            time.sleep(SLEEP)
            if i % 100 == 0:
                print(f"  月足 {i}/{len(need)}", flush=True)
        print("月足 取得完了", flush=True)

    # 期間騰落率タブのキャッシュは6か月ぶんしか無いので、ベンチマークも5年ぶん取る
    bpath = CACHE5 / f"{BENCH}.json"
    if not bpath.exists():
        bpath.write_text(json.dumps({"bars": fetch5(BENCH)}, ensure_ascii=False),
                         encoding="utf-8")
    bbars, bdrop = clean_bars(((load(bpath, {}) or {}).get("bars") or []))
    if bdrop:
        print(f"ベンチマーク(1306)の異常値を {bdrop}本 除外", file=sys.stderr)
    bench = {b[0]: b[2] for b in bbars}
    if len(bench) < 300:
        print(f"注意: ベンチマーク(1306)が{len(bench)}本しかありません", file=sys.stderr)
    rows, no5y, no_mo, n_dropped = [], 0, [], 0
    # 比較対象: 同じ母集団・同じ流動性条件で「新高値ではない日」。
    # 新高値の数字が高いのか低いのかは、これと比べないと判断できない。
    base_rows = []      # (日付, r5, e5, r20, e20)。レジーム別に切るため日付が要る
    for n, c in enumerate(codes, 1):
        bars = (load(CACHE5 / f"{c}.json", {}) or {}).get("bars") or []
        bars, dr = clean_bars(bars)
        n_dropped += dr
        if len(bars) < 300:
            no5y += 1
            continue
        pm = prev_max(bars, 1)
        mo = (load(CACHE_MO / f"{c}.json", {}) or {}).get("bars") or []
        if not mo:
            no_mo.append(c)                         # 月足が無い銘柄は上場来を判定しない
        run_ath = None                              # それまでの高値の累積(日足側)
        for i, b in enumerate(bars):
            d, h, cl, v = b
            if i + max(x[0] for x in HORIZONS) >= len(bars):
                break
            # 「その日を含まない」累積最高値にする(初日は比較対象が無いのでNone)
            if i > 0:
                run_ath = bars[i - 1][1] if run_ath is None else max(run_ath, bars[i - 1][1])
            if cl * v / 1e6 < MIN_VALUE:            # その日の売買代金が10億円未満
                continue
            is_high = pm[i] is not None and h >= pm[i]
            if not is_high:                          # 新高値でない日は比較対象へ
                rec = [d]
                for k, _ in HORIZONS:
                    j = i + k
                    if j < len(bars):
                        ret = (bars[j][2] / cl - 1) * 100
                        b0, b1 = bench.get(d), bench.get(bars[j][0])
                        rec.append(round(ret, 3))
                        rec.append(round(ret - (b1 / b0 - 1) * 100, 3)
                                   if (b0 and b1) else None)
                    else:
                        rec += [None, None]
                base_rows.append(tuple(rec))
                continue
            if mo and run_ath is not None:
                mv = [x[1] for x in mo if x[0][:7] < d[:7]]
                prev_all = max(mv + [run_ath]) if mv else run_ath
                is_ath = bool(prev_all and h >= prev_all)
            else:
                is_ath = None                       # 月足が無く判定できない
            row = {"d": d, "c": c, "ath": is_ath}
            for k, _ in HORIZONS:
                j = i + k
                if j < len(bars):
                    ret = (bars[j][2] / cl - 1) * 100
                    row[f"r{k}"] = round(ret, 3)
                    b0, b1 = bench.get(d), bench.get(bars[j][0])
                    if b0 and b1:
                        row[f"e{k}"] = round(ret - (b1 / b0 - 1) * 100, 3)
            rows.append(row)
        if n % 200 == 0:
            print(f"  集計 {n}/{len(codes)} … {len(rows)}件", flush=True)

    if not rows:
        print("再現できた記録がありません(--fetch を先に実行してください)", file=sys.stderr)
        return 1

    def agg(sel, within=None):
        out = {}
        for k, label in HORIZONS:
            sub = [x for x in rows if sel(x) and f"r{k}" in x
                   and (within is None or within(x["d"]))]
            out[str(k)] = {
                "label": label,
                "raw": stats([x[f"r{k}"] for x in sub]),
                "excess": stats([x[f"e{k}"] for x in sub if f"e{k}" in x]),
            }
        return out

    def agg_base(within=None):
        """比較対象(新高値でない日)。rec = (日付, r5, e5, r20, e20)"""
        out = {}
        for idx, (k, label) in enumerate(HORIZONS):
            ri, ei = 1 + idx * 2, 2 + idx * 2
            sub = [x for x in base_rows
                   if x[ri] is not None and (within is None or within(x[0]))]
            out[str(k)] = {
                "label": label,
                "raw": stats([x[ri] for x in sub]),
                "excess": stats([x[ei] for x in sub if x[ei] is not None]),
            }
        return out

    # 日経平均の200日移動平均で機械的にも切る(手で選んだ期間だけだと
    # 結論が期間の選び方に依存してしまうため)
    n225 = (load(CACHE5 / f"{N225}.json", {}) or {}).get("bars") or []
    n225, _ = clean_bars(n225)
    above = {}
    closes = [x[2] for x in n225]
    for i in range(MA_DAYS, len(n225)):
        above[n225[i][0]] = closes[i] > sum(closes[i - MA_DAYS:i]) / MA_DAYS

    regimes = {}
    for key, label, a, z in REGIMES:
        w = (lambda d, a=a, z=z: a <= d <= z)
        regimes[key] = {
            "label": label, "from": a, "to": z,
            "all": agg(lambda x: True, w),
            "ath": agg(lambda x: x["ath"] is True, w),
            "w52": agg(lambda x: x["ath"] is False, w),
            "base": agg_base(w),
        }
    for key, lab, want in (("ma_above", f"日経が{MA_DAYS}日線より上", True),
                           ("ma_below", f"日経が{MA_DAYS}日線より下", False)):
        w = (lambda d, want=want: above.get(d) is want)
        regimes[key] = {
            "label": lab, "from": None, "to": None,
            "all": agg(lambda x: True, w),
            "ath": agg(lambda x: x["ath"] is True, w),
            "w52": agg(lambda x: x["ath"] is False, w),
            "base": agg_base(w),
        }

    ds = sorted(x["d"] for x in rows)
    payload = {
        "generated": datetime.now().date().isoformat(),
        "from": ds[0], "to": ds[-1], "records": len(rows),
        "codes": len({x["c"] for x in rows}), "no_history": no5y,
        "horizons": [{"n": k, "label": l} for k, l in HORIZONS],
        "base": agg_base(),
        "regimes": regimes,
        "all": agg(lambda x: True),
        "ath": agg(lambda x: x["ath"] is True),
        "w52": agg(lambda x: x["ath"] is False),
        "counts": {"all": len(rows),
                   "ath": sum(1 for x in rows if x["ath"] is True),
                   "w52": sum(1 for x in rows if x["ath"] is False),
                   "unknown": sum(1 for x in rows if x["ath"] is None),
                   "base": len(base_rows)},
        "no_monthly": len(no_mo), "dropped_bars": n_dropped,
    }
    (DOCS / "backfill.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"\n再現 {len(rows)}件 / {payload['codes']}銘柄 / {ds[0]}〜{ds[-1]}"
          f"(異常値 {n_dropped}本を除外 / 5年足が無く除外 {no5y}銘柄 / "
          f"月足が無く上場来を判定できない "
          f"{len(no_mo)}銘柄・{payload['counts']['unknown']}件)")
    for key, jp in (("all", "全体"), ("ath", "上場来"), ("w52", "52週のみ"),
                    ("base", "比較対象(新高値でない日)")):
        print(f"\n[{jp}] n={payload['counts'][key]}")
        for k, label in HORIZONS:
            a = payload[key][str(k)]
            if not a["raw"]:
                continue
            r, e = a["raw"], a["excess"]
            print(f"  {label}後(n={r['n']:>5}): 平均 {r['mean']:+.2f}% / 中央値 {r['median']:+.2f}%"
                  f" / 勝率 {r['win']:.0f}%"
                  + (f"  ｜対TOPIX(n={e['n']}) 平均 {e['mean']:+.2f}% / "
                     f"中央値 {e['median']:+.2f}%" if e else ""))
    print("\n========== 相場環境別 ==========")
    for key, r in regimes.items():
        n_all = (r["all"]["20"]["raw"] or {}).get("n", 0)
        n_base = (r["base"]["20"]["raw"] or {}).get("n", 0)
        if not n_all:
            continue
        print(f"\n[{r['label']}]  新高値 {n_all:,}件 / 比較対象 {n_base:,}件")
        for k, lab in HORIZONS:
            line = f"  {lab}後  "
            for seg, nm in (("all", "新高値"), ("ath", "上場来"),
                            ("w52", "52週のみ"), ("base", "比較対象")):
                a = r[seg][str(k)]["raw"]
                line += (f"{nm} 平均{a['mean']:+6.2f}/中央{a['median']:+6.2f}  "
                         if a else f"{nm} -  ")
            print(line)
            a, b = r["all"][str(k)]["raw"], r["base"][str(k)]["raw"]
            if a and b:
                print(f"           → 新高値 − 比較対象 = 平均 {a['mean']-b['mean']:+.2f}pt "
                      f"/ 中央値 {a['median']-b['median']:+.2f}pt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
