# -*- coding: utf-8 -*-
"""信用需給分析タブ・宇宙銘柄タブ用の analysis.json を生成する。

入力:
  docs/data_jukyu/stocks.json          … 銘柄マスタ(コード/名前/市場/発行済株式数)
  docs/data_jukyu/raw/<code>_<YYYY-MM>.json … 松井証券アプリから読み取った日次の売買内訳(千株)

出力(DATASETS で定義。生データは両方で共有する):
  docs/data_jukyu/analysis.json … 全銘柄 × 2026年6月/7月       → 「信用需給分析」タブ
  docs/data_uchu/analysis.json  … 宇宙5銘柄 × 2026年4月/5月/6月 → 「宇宙銘柄」タブ

使い方:
  python build_jukyu.py            … 検算して両方の analysis.json を書き出す
  python build_jukyu.py --check    … 検算だけして書き出さない

生データを1銘柄追加したら、このスクリプトを実行するだけでサイトの表が更新される。
指標の計算式やサイトの表示ロジックを新しいチャットで作り直さないこと。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT, "docs", "data_jukyu")
RAW_DIR = os.path.join(BASE, "raw")

# months: YYYY-MM → analysis.json 内のキー。codes を None にすると stocks.json の全銘柄。
# total: 全月を足し上げた累計を入れるキー(不要なら None)。
# docs/index.html の JK_VIEWS がこのキーをそのまま参照しているので、
# 月を増やすときは index.html 側の months / diff も合わせて直すこと。
DATASETS = [
    {
        "name": "jukyu",
        "out": os.path.join(BASE, "analysis.json"),
        "months": {"2026-06": "jun", "2026-07": "jul"},
        "codes": None,
        "total": None,
    },
    {
        "name": "uchu",
        "out": os.path.join(ROOT, "docs", "data_uchu", "analysis.json"),
        "months": {"2026-04": "apr", "2026-05": "may", "2026-06": "jun"},
        "codes": ["464A", "290A", "9348", "186A", "402A"],
        "total": "all",
    },
]

FIELDS = ["gb", "kb", "hb", "gs", "ks", "hs", "ur", "vol"]
# gb 現物買 / kb 新規買 / hb 返済買 / gs 現物売 / ks 新規売 / hs 返済売 / ur 空売り / vol 出来高
TOL = 1.0  # 千株。アプリ側の丸めで日次検算が 0.6千株程度ずれることがある
# 単位: 生データと daily は「千株」、月次集計と発行済(shares_man)は「万株」(千株 ÷ 10)


def r1(x):
    return round(x + 0.0, 1)


def r3(x):
    return round(x + 0.0, 3)


def load_master():
    with open(os.path.join(BASE, "stocks.json"), encoding="utf-8") as f:
        m = json.load(f)
    by_code = {s["code"]: s for s in m["stocks"]}
    return m, by_code


def load_raw():
    files = sorted(f for f in os.listdir(RAW_DIR) if f.endswith(".json"))
    out = []
    for fn in files:
        with open(os.path.join(RAW_DIR, fn), encoding="utf-8") as f:
            out.append((fn, json.load(f)))
    return out


def check_day(row):
    """日次検算: 買い合計 = 売り合計 = 出来高"""
    buy = row["gb"] + row["kb"] + row["hb"]
    sell = row["gs"] + row["ks"] + row["hs"] + row["ur"]
    return abs(buy - row["vol"]), abs(sell - row["vol"])


def metrics(tot, days, dates, shares_man, label, errors):
    """千株の累計 tot から万株ベースの指標を作る。丸めるのは最後に一度だけ。"""
    m = {k: v / 10.0 for k, v in tot.items()}   # 千株 → 万株
    gn = m["gb"] - m["gs"]                      # 現物ネット
    kn = m["kb"] - m["hs"]                      # 買い残ネット
    un = m["ur"] + m["ks"] - m["hb"]            # 売り残ネット
    sk = m["kb"]                                # 新規買 累計
    chk = round(gn + kn - un, 2)   # = 買い合計 − 売り合計。理論上は必ず 0
    if abs(chk) > TOL / 10.0:
        errors.append(f"{label}: 累計検算 現物ネット+買残ネット-売残ネット={chk:+.2f}万株")
    return {
        "days": days,
        "gn": r1(gn),
        "kn": r1(kn),
        "un": r1(un),
        "sk": r1(sk),
        "vol": r1(m["vol"]),
        "i1": r1(gn / kn) if kn else None,         # ①現物ネット ÷ 買残ネット(倍)
        "i2": r3(sk / shares_man * 100),           # ②新規買 ÷ 発行済(%)
        "i3": r3(gn / shares_man * 100),           # ③現物ネット ÷ 発行済(%)
        "i4": r3(kn / shares_man * 100),           # ④買残ネット ÷ 発行済(%)
        "i5": r3(un / shares_man * 100),           # ⑤売残ネット ÷ 発行済(%)
        "turn": r1(m["vol"] / shares_man * 100),   # 出来高 ÷ 発行済(%)
        "chk": chk,
        "dates": dates,
    }


def build(ds, master, by_code, raws, errors, warns):
    """1データセットぶんの出力 dict を返す。"""
    months, codes, total = ds["months"], ds["codes"], ds["total"]
    daily = []
    agg = {}          # (code, key) → 月次集計
    tots = {}         # (code, key) → 千株の累計
    spans = {}        # (code, key) → [最初の日, 最後の日, 日数]

    for fn, d in raws:
        code, month = d["code"], d["month"]
        if month not in months:
            continue
        if codes is not None and code not in codes:
            continue
        if code not in by_code:
            errors.append(f"{fn}: stocks.json に銘柄 {code} がありません(発行済株式数を追加すること)")
            continue
        st = by_code[code]
        rows = sorted(d["rows"], key=lambda r: r["date"])
        keys = [months[month]] + ([total] if total else [])
        seen = set()
        for row in rows:
            if row["date"] in seen:
                errors.append(f"{fn}: {row['date']} が重複しています")
            seen.add(row["date"])
            db, dsell = check_day(row)
            if max(db, dsell) > TOL:
                errors.append(
                    f"{fn} {row['date']}: 検算不一致 買い合計-出来高={db:+.1f} 売り合計-出来高={dsell:+.1f} 千株"
                    " → 読み取りミスの可能性。スクショを見直すこと"
                )
            elif max(db, dsell) > 0.05:
                warns.append(f"{fn} {row['date']}: 検算 {max(db, dsell):.1f}千株ずれ(丸め誤差の範囲)")
            for key in keys:
                t = tots.setdefault((code, key), {k: 0.0 for k in FIELDS})
                for k in FIELDS:
                    t[k] += row[k]
            daily.append({
                "date": row["date"], "code": code, "name": st["name"],
                **{k: r1(row[k]) for k in FIELDS},
                "gn": r1(row["gb"] - row["gs"]),
                "kn": r1(row["kb"] - row["hs"]),
                "un": r1(row["ur"] + row["ks"] - row["hb"]),
            })
        for key in keys:
            sp = spans.get((code, key))
            first, last = rows[0]["date"], rows[-1]["date"]
            if sp is None:
                spans[(code, key)] = [first, last, len(rows)]
            else:
                sp[0] = min(sp[0], first)
                sp[1] = max(sp[1], last)
                sp[2] += len(rows)

    for (code, key), tot in tots.items():
        first, last, days = spans[(code, key)]
        shares_man = r1(by_code[code]["shares"] / 10000.0)
        agg[(code, key)] = metrics(tot, days, [first, last], shares_man,
                                   f"{code} {key}", errors)

    # 月ごとの期間文字列(営業日数は同じ群で最大のもの)
    keys = list(months.values()) + ([total] if total else [])
    periods = {}
    for (code, key), a in agg.items():
        cur = periods.get(key)
        if cur is None or a["days"] > cur[2]:
            periods[key] = (a["dates"][0], a["dates"][1], a["days"])

    stocks = []
    for st in master["stocks"]:
        if codes is not None and st["code"] not in codes:
            continue
        e = {"code": st["code"], "name": st["name"], "market": st["market"],
             "shares": st["shares"], "shares_man": r1(st["shares"] / 10000.0)}
        n = 0
        for key in keys:
            a = agg.get((st["code"], key))
            if a:
                e[key] = {k: v for k, v in a.items() if k != "dates"}
                n += 1
        if n:
            stocks.append(e)
        else:
            print(f"NOTE [{ds['name']}] {st['code']} {st['name']} は生データが無いので出力しません")

    out = {}
    for key in keys:
        if key in periods:
            s, e2, n = periods[key]
            out["period_" + key] = f"{s}〜{e2}（{n}営業日）"
    out["source"] = master["source"]
    out["shares_asof"] = master["shares_asof"]
    out["stocks"] = stocks
    out["daily"] = sorted(daily, key=lambda r: (r["date"], r["code"]), reverse=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="検算のみ。ファイルを書き換えない")
    ap.add_argument("--generated", default=None, help="generated に入れる日付(既定: 既存値を維持)")
    args = ap.parse_args()

    master, by_code = load_master()
    raws = load_raw()
    if not raws:
        sys.exit("raw/ に生データがありません")

    errors, warns = [], []
    built = [(ds, build(ds, master, by_code, raws, errors, warns)) for ds in DATASETS]

    for w in sorted(set(warns)):
        print("WARN " + w)
    if errors:
        for e in sorted(set(errors)):
            print("ERROR " + e)
        sys.exit(f"検算エラー {len(set(errors))}件。analysis.json は更新していません")

    for ds, out in built:
        print(f"[{ds['name']}] 銘柄 {len(out['stocks'])} / 日次 {len(out['daily'])}行")
        if args.check:
            continue
        # generated は「新しいデータが入った日」だけ進める(タブの NEW バッジ用)
        generated = args.generated
        if generated is None and os.path.exists(ds["out"]):
            with open(ds["out"], encoding="utf-8") as f:
                generated = json.load(f).get("generated")
        os.makedirs(os.path.dirname(ds["out"]), exist_ok=True)
        with open(ds["out"], "w", encoding="utf-8") as f:
            json.dump({"generated": generated, **out}, f, ensure_ascii=False, separators=(",", ":"))
        print("wrote " + ds["out"])
    if args.check:
        print("--check のため書き出しませんでした")


if __name__ == "__main__":
    main()
