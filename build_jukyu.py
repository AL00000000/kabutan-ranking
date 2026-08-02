# -*- coding: utf-8 -*-
"""信用需給分析タブ用 docs/data_jukyu/analysis.json を生成する。

入力:
  docs/data_jukyu/stocks.json          … 銘柄マスタ(コード/名前/市場/発行済株式数)
  docs/data_jukyu/raw/<code>_<YYYY-MM>.json … 松井証券アプリから読み取った日次の売買内訳(千株)

使い方:
  python build_jukyu.py            … 検算して analysis.json を書き出す
  python build_jukyu.py --check    … 検算だけして書き出さない

生データを1銘柄追加したら、このスクリプトを実行するだけでサイトの表が更新される。
指標の計算式やサイトの表示ロジックを新しいチャットで作り直さないこと。
"""
import argparse
import json
import os
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data_jukyu")
RAW_DIR = os.path.join(BASE, "raw")
OUT = os.path.join(BASE, "analysis.json")

# YYYY-MM → analysis.json 内のキー。docs/index.html の jkGroupSel(データ群のプルダウン)と
# jkRenderCards の "diff"(= 2つ目 − 1つ目)がこのキーを直接参照しているため、
# 月を増やすときは index.html 側も合わせて直すこと。
MONTH_KEYS = {
    "2026-06": "jun",
    "2026-07": "jul",
}

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
    daily = []
    # (code, month_key) → 月次集計
    agg = {}

    for fn, d in raws:
        code, month = d["code"], d["month"]
        if code not in by_code:
            errors.append(f"{fn}: stocks.json に銘柄 {code} がありません(発行済株式数を追加すること)")
            continue
        if month not in MONTH_KEYS:
            errors.append(
                f"{fn}: 月 {month} が MONTH_KEYS にありません。"
                f"build_jukyu.py と docs/index.html の jkGroupSel/diff を両方直すこと"
            )
            continue
        st = by_code[code]
        rows = sorted(d["rows"], key=lambda r: r["date"])
        seen = set()
        tot = {k: 0.0 for k in FIELDS}
        for row in rows:
            if row["date"] in seen:
                errors.append(f"{fn}: {row['date']} が重複しています")
            seen.add(row["date"])
            db, ds = check_day(row)
            if max(db, ds) > TOL:
                errors.append(
                    f"{fn} {row['date']}: 検算不一致 買い合計-出来高={db:+.1f} 売り合計-出来高={ds:+.1f} 千株"
                    " → 読み取りミスの可能性。スクショを見直すこと"
                )
            elif max(db, ds) > 0.05:
                warns.append(f"{fn} {row['date']}: 検算 {max(db, ds):.1f}千株ずれ(丸め誤差の範囲)")
            for k in FIELDS:
                tot[k] += row[k]
            gn = r1(row["gb"] - row["gs"])          # 現物ネット
            kn = r1(row["kb"] - row["hs"])          # 買い残ネット
            un = r1(row["ur"] + row["ks"] - row["hb"])  # 売り残ネット
            daily.append({
                "date": row["date"], "code": code, "name": st["name"],
                **{k: r1(row[k]) for k in FIELDS},
                "gn": gn, "kn": kn, "un": un,
            })

        # 指標は丸める前の累計から計算し、最後に一度だけ丸める
        shares_man = r1(st["shares"] / 10000.0)              # 万株
        m = {k: v / 10.0 for k, v in tot.items()}            # 千株 → 万株
        gn = m["gb"] - m["gs"]                               # 現物ネット
        kn = m["kb"] - m["hs"]                               # 買い残ネット
        un = m["ur"] + m["ks"] - m["hb"]                     # 売り残ネット
        sk = m["kb"]                                         # 新規買 累計
        chk = round(gn + kn - un, 2)   # = 買い合計 − 売り合計。理論上は必ず 0
        if abs(chk) > TOL / 10.0:
            errors.append(f"{fn}: 累計検算 現物ネット+買残ネット-売残ネット={chk:+.2f}万株")
        agg[(code, MONTH_KEYS[month])] = {
            "days": len(rows),
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
            "dates": [rows[0]["date"], rows[-1]["date"]],
        }

    for w in warns:
        print("WARN " + w)
    if errors:
        for e in errors:
            print("ERROR " + e)
        sys.exit(f"検算エラー {len(errors)}件。analysis.json は更新していません")

    # 月ごとの期間文字列(営業日数は同月の最大日数)
    periods = {}
    for (code, key), a in agg.items():
        cur = periods.get(key)
        if cur is None or a["days"] > cur[2]:
            periods[key] = (a["dates"][0], a["dates"][1], a["days"])

    stocks = []
    for st in master["stocks"]:
        e = {"code": st["code"], "name": st["name"], "market": st["market"],
             "shares": st["shares"], "shares_man": r1(st["shares"] / 10000.0)}
        n = 0
        for key in MONTH_KEYS.values():
            a = agg.get((st["code"], key))
            if a:
                e[key] = {k: v for k, v in a.items() if k != "dates"}
                n += 1
        if n:
            stocks.append(e)
        else:
            print(f"NOTE {st['code']} {st['name']} は生データが無いので出力しません")

    generated = args.generated
    if generated is None and os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            generated = json.load(f).get("generated")

    out = {"generated": generated}
    for key in MONTH_KEYS.values():
        if key in periods:
            s, e, n = periods[key]
            out["period_" + key] = f"{s}〜{e}（{n}営業日）"
    out["source"] = master["source"]
    out["shares_asof"] = master["shares_asof"]
    out["stocks"] = stocks
    out["daily"] = sorted(daily, key=lambda r: (r["date"], r["code"]), reverse=True)

    print(f"銘柄 {len(stocks)} / 生データ {len(raws)}ファイル / 日次 {len(out['daily'])}行")
    if args.check:
        print("--check のため書き出しませんでした")
        return
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote " + OUT)


if __name__ == "__main__":
    main()
