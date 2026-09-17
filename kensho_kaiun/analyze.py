"""海運株の予想PER(会社予想ベース)の推移を作る.

入力: forecasts_raw.csv (parse_docs.py), Yahoo日足(分割調整済み), IRBANKの実績EPS
出力: result.json (docs/kensho_kaiun.html の埋め込みデータ)

予想PER(日次) = 終値(分割調整後) / その日の引けまでに開示された最新の会社予想EPS(分割調整後)
  - 予想の対象期は「開示済みの予想のうち最も新しい期」。期が終わっても本決算までは旧期の予想を使う
  - EPSの基準(分割前後)は 予想純利益÷予想EPS=株数 から判定する(併合・分割の直前は新基準で書く会社がある)
  - 赤字予想・未定の日は予想PERを出さない
"""
import csv, json, math, os, re, statistics, time
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup

from stocks import STOCKS, BIG3

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
JST = timezone(timedelta(hours=9))
START = "2005-01-01"


def yahoo(code):
    path = os.path.join(CACHE, f"yahoo_{code}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        return json.load(open(path, encoding="utf-8"))
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.T"
         f"?period1=1104537600&period2={int(time.time())}&interval=1d&events=split,div")
    j = requests.get(u, headers=UA, timeout=60).json()["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    adj = j["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, ts in enumerate(j["timestamp"]):
        c = q["close"][i]
        if c is None or not q["volume"][i]:
            continue
        d = datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d")
        bars.append([d, round(c, 3), round(adj[i], 3)])
    splits = sorted((datetime.fromtimestamp(int(k), JST).strftime("%Y-%m-%d"), v["numerator"] / v["denominator"])
                    for k, v in j.get("events", {}).get("splits", {}).items())
    out = {"bars": bars, "splits": splits}
    json.dump(out, open(path, "w", encoding="utf-8"))
    time.sleep(0.5)
    return out


def num(s):
    s = s.replace(",", "").strip()
    if s in ("", "-"):
        return None
    m = re.fullmatch(r"(-?[\d.]+)(兆|億|万)?", s)
    if not m:
        return None
    return float(m.group(1)) * {"兆": 1e12, "億": 1e8, "万": 1e4, None: 1}[m.group(2)]


def jp_num(s):
    """'1兆1347億' '-1394億7800万' '52億690万' -> 円."""
    s = s.strip().replace(",", "")
    neg = s.startswith("-")
    v, rest = 0.0, s.lstrip("-")
    for unit, mul in (("兆", 1e12), ("億", 1e8), ("万", 1e4)):
        if unit in rest:
            a, rest = rest.split(unit, 1)
            v += float(a) * mul
    if rest:
        v += float(rest)
    return -v if neg else v


def actual_ni(code):
    """IRBANK 決算まとめの「当期利益」の年次実績(円). {'2022-03': 6.4e11}.

    IRBANKの実績EPSは分割調整が一部しか反映されていない年があるので使わない
    (例: 川崎汽船の2022年3月期は2022年と2024年の分割のうち1回分だけ調整)。
    """
    path = os.path.join(CACHE, f"irbank_results_{code}.html")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 86400 * 7:
        r = requests.get(f"https://irbank.net/{code}/results", headers=UA, timeout=60)
        open(path, "w", encoding="utf-8").write(r.text)
        time.sleep(1)
    t = BeautifulSoup(open(path, encoding="utf-8").read(), "html.parser").get_text("\n")
    t = re.sub(r"\n\s*\n+", "\n", t)
    lines = [l.strip() for l in t.split("\n")]
    lists, cur, prev = [], None, None
    for k, l in enumerate(lines):
        m = re.fullmatch(r"(\d{4})/(\d{2})", l)
        if not m:
            continue
        nxt = lines[k + 1:k + 4]
        yo = bool(nxt) and nxt[0] == "予"
        v = next((x for x in nxt if re.fullmatch(r"-?[\d.]+(?:兆|億|万)[\d.兆億万]*", x)), None)
        if not v:
            continue
        if cur is None or m.group(1) < prev:
            cur = {"label": " ".join(lines[max(0, k - 3):k]), "rows": []}
            lists.append(cur)
        cur["rows"].append((f"{m.group(1)}-{m.group(2)}", yo, v))
        prev = m.group(1)
    # 明細(「○億○万」の精度)のうち、経常利益の次の系列が当期利益
    detail = [x for x in lists if any("万" in v for _, _, v in x["rows"])]
    for n, x in enumerate(detail[:-1]):
        if "経常利益" in x["label"]:
            return {k: jp_num(v) for k, yo, v in detail[n + 1]["rows"] if not yo}
    return {}


def load_forecasts():
    rows = list(csv.DictReader(open(os.path.join(HERE, "forecasts_raw.csv"), encoding="utf-8")))
    by = {}
    for r in rows:
        if not r["fy_end"]:
            continue
        # 短信で通期行はあるがEPSが無い(経常利益だけ等) → 純利益予想なしとして扱う
        if r["eps"] == "" and not (r["note"] == "undisclosed" or (r["kind"] == "tanshin" and r["note"] == "noeps" and not r["tid"].startswith("wb"))):
            continue
        by.setdefault(r["code"], []).append({
            "pub": r["pub"], "fy": r["fy_end"], "kind": r["kind"],
            "eps": float(r["eps"]) if r["eps"] else None,
            "ni": float(r["ni"]) if r["ni"] else None,
            "src": "wb" if r["tid"].startswith("wb") else "tdnet",
        })
    for v in by.values():
        v.sort(key=lambda d: d["pub"])
    return by


def adjust(docs, splits):
    """EPSを現在の株数基準に直す。基準は予想純利益/予想EPS(=株数)が前後の開示と揃う方を採る."""
    def factor_after(k):          # 基準 k(=k本目の分割まで反映済み) → 現在基準 の株数倍率
        f = 1.0
        for _, r in splits[k:]:
            f *= r
        return f

    def k_at(date):
        return sum(1 for d, _ in splits if d <= date)

    for d in docs:
        k0 = k_at(d["pub"][:10])
        d["cands"] = [k0]
        nxt = splits[k0][0] if k0 < len(splits) else None
        if nxt and (datetime.strptime(nxt, "%Y-%m-%d") - datetime.strptime(d["pub"][:10], "%Y-%m-%d")).days < 200:
            d["cands"].append(k0 + 1)
        d["shares"] = None
        if d["eps"] and d["ni"] and abs(d["eps"]) >= 1 and abs(d["ni"]) >= 100:
            d["shares"] = d["ni"] * 1e6 / d["eps"]
    sure = [(d["pub"], d["shares"] * factor_after(d["cands"][0])) for d in docs
            if d["shares"] and len(d["cands"]) == 1 and d["shares"] > 0]
    for d in docs:
        k = d["cands"][0]
        if len(d["cands"]) > 1 and d["shares"] and d["shares"] > 0:
            t = datetime.strptime(d["pub"][:10], "%Y-%m-%d")
            ref = [s for p, s in sure if abs((datetime.strptime(p[:10], "%Y-%m-%d") - t).days) < 800]
            if ref:
                med = statistics.median(ref)
                k = min(d["cands"], key=lambda c: abs(math.log(d["shares"] * factor_after(c) / med)))
        d["basis"] = k
        f = factor_after(k)
        d["eps_adj"] = None if d["eps"] is None else d["eps"] / f
        d["shares_adj"] = d["shares"] * f if d["shares"] and d["shares"] > 0 else None
        del d["cands"]
    return docs


def effective_date(pub):
    """開示が株価に反映される最初の立会日(引け前の開示は当日)."""
    day, hm = pub[:10], pub[11:16]
    close = "15:30" if day >= "2024-11-05" else "15:00"
    return day if hm < close else (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def daily(code, docs, bars):
    """各営業日の (日付, 終値, 調整後終値, 予想EPS, 対象期, 株数, 状態)."""
    eff = [effective_date(d["pub"]) for d in docs]
    out = []
    for date, close, adj in bars:
        n = bisect_right(eff, date)
        if n == 0:
            out.append([date, close, adj, None, None, None, "nodata"])
            continue
        seen = docs[:n]
        fy = max(d["fy"] for d in seen)
        cur = [d for d in seen if d["fy"] == fy][-1]
        shares = next((d["shares_adj"] for d in reversed(seen) if d.get("shares_adj")), None)
        if cur["eps_adj"] is None:
            st = "undisclosed"
        elif cur["eps_adj"] <= 0:
            st = "loss"
        else:
            st = "ok"
        # 1年以上前の予想しか無い(資料の欠落)なら使わない
        if (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(cur["pub"][:10], "%Y-%m-%d")).days > 400:
            st = "stale"
        # 対象期の末日から80日過ぎても翌期の予想が無い = 本決算短信が手元に無い(資料の欠落)
        if (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(fy + "-28", "%Y-%m-%d")).days > 80:
            st = "stale"
        out.append([date, close, adj, cur["eps_adj"], fy, shares, st])
    return out


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = (len(xs) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def main():
    fc = load_forecasts()
    res = {"generated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "stocks": {}, "big3": [],
           "fy_table": [], "buckets": []}
    dd = {}
    for code, name in STOCKS.items():
        y = yahoo(code)
        docs = adjust(fc.get(code, []), y["splits"])
        bars = [b for b in y["bars"] if b[0] >= START]
        rows = daily(code, docs, bars)
        dd[code] = rows
        act_ni = actual_ni(code)
        ok = [r for r in rows if r[6] == "ok"]
        pers = [r[1] / r[3] for r in ok]
        weekly = []
        last_week = None
        for i, r in enumerate(rows):
            wk = datetime.strptime(r[0], "%Y-%m-%d").isocalendar()[:2]
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            if nxt and datetime.strptime(nxt[0], "%Y-%m-%d").isocalendar()[:2] == wk:
                continue
            per = round(r[1] / r[3], 2) if r[6] == "ok" else None
            weekly.append([r[0], round(r[1], 1), per, None if r[3] is None else round(r[3], 2), r[4], r[6]])
        cover = [r for r in rows if r[6] != "nodata"]
        res["stocks"][code] = {
            "name": name,
            "splits": y["splits"],
            "first": cover[0][0] if cover else None,
            "weekly": weekly,
            "docs": [{k: d[k] for k in ("pub", "fy", "kind", "eps", "eps_adj", "src")} for d in docs],
            "actual_ni": act_ni,
            "stats": {
                "n_days": len(cover),
                "ok": len(ok), "loss": sum(r[6] == "loss" for r in cover),
                "undisclosed": sum(r[6] == "undisclosed" for r in cover),
                "stale": sum(r[6] == "stale" for r in cover),
                "median": pct(pers, .5), "p10": pct(pers, .1), "p90": pct(pers, .9),
                "min": min(pers) if pers else None, "max": max(pers) if pers else None,
                "last": weekly[-1],
            },
        }
        # 予想の当たり外れ: 期初予想(本決算短信の翌期予想) / 期中最後の予想 / 実績
        # 実績EPS = IRBANKの実績純利益 ÷ その期の予想から逆算した株数(現在の株数基準)
        for fy in sorted({d["fy"] for d in docs}):
            fd = [d for d in docs if d["fy"] == fy and (d["eps_adj"] is not None or d["kind"] == "tanshin")]
            if not fd or fy not in act_ni:
                continue
            first, last = fd[0], [d for d in fd if d["eps_adj"] is not None][-1:] or [None]
            last = last[0]
            y0 = int(fy[:4]) - 1
            if not (f"{y0}-04-01" <= first["pub"][:10] <= f"{y0}-06-30"):
                continue  # 期初の本決算短信が手元に無い期は比べない
            sh = [d["shares_adj"] for d in fd if d.get("shares_adj")]
            if not sh:
                continue
            act_eps = act_ni[fy] / statistics.median(sh)
            b = [r for r in rows if r[0] >= effective_date(first["pub"])]
            px = b[0][1] if b else None
            fe = first["eps_adj"]
            res["fy_table"].append({
                "code": code, "fy": fy, "first_pub": first["pub"][:10],
                "first": None if fe is None else round(fe, 2),
                "last": None if last is None else round(last["eps_adj"], 2),
                "actual": round(act_eps, 2), "src": first["src"], "px": px,
                "per_first": round(px / fe, 2) if px and fe and fe > 0 else None,
                "per_actual": round(px / act_eps, 2) if px and act_eps > 0 else None,
            })

    # 大手3社合算: Σ時価総額 / Σ予想純利益 (株数は開示の 予想純利益÷予想EPS)
    idx = {c: {r[0]: r for r in dd[c]} for c in BIG3}
    dates = [r[0] for r in dd[BIG3[0]]]
    agg_rows = []
    for d in dates:
        rs = [idx[c].get(d) for c in BIG3]
        if any(r is None or r[6] not in ("ok", "loss") or not r[5] for r in rs):
            agg_rows.append([d, None, "na"])
            continue
        cap = sum(r[1] * r[5] for r in rs)
        ni = sum(r[3] * r[5] for r in rs)
        agg_rows.append([d, cap / ni if ni > 0 else None, "ok" if ni > 0 else "loss", cap])
    wk = []
    for i, r in enumerate(agg_rows):
        w = datetime.strptime(r[0], "%Y-%m-%d").isocalendar()[:2]
        if i + 1 < len(agg_rows) and datetime.strptime(agg_rows[i + 1][0], "%Y-%m-%d").isocalendar()[:2] == w:
            continue
        wk.append([r[0], None if r[1] is None else round(r[1], 2), r[2],
                   None if len(r) < 4 else round(r[3] / 1e8)])
    res["big3"] = wk

    # 予想PERの水準別 その後1年(250営業日)の配当込みリターン (大手3社, 日次観測)
    obs = []
    for c in BIG3:
        rows = dd[c]
        for i, r in enumerate(rows):
            if i + 250 >= len(rows) or r[6] not in ("ok", "loss"):
                continue
            ret = rows[i + 250][2] / r[2] - 1
            per = r[1] / r[3] if r[6] == "ok" else None
            obs.append((c, r[0], per, ret))
    edges = [("赤字予想", None, None), ("5倍未満", 0, 5), ("5〜10倍", 5, 10), ("10〜15倍", 10, 15),
             ("15〜25倍", 15, 25), ("25倍以上", 25, 1e9)]
    for label, lo, hi in edges:
        xs = [o for o in obs if (o[2] is None if lo is None else (o[2] is not None and lo <= o[2] < hi))]
        rets = [o[3] for o in xs]
        if not rets:
            continue
        res["buckets"].append({
            "label": label, "n": len(rets), "years": len({o[1][:4] for o in xs}),
            "median": pct(rets, .5), "mean": sum(rets) / len(rets),
            "win": sum(x > 0 for x in rets) / len(rets),
            "by": {c: len([o for o in xs if o[0] == c]) for c in BIG3},
        })
    json.dump(res, open(os.path.join(HERE, "result.json"), "w", encoding="utf-8"), ensure_ascii=False)
    for c, s in res["stocks"].items():
        st = s["stats"]
        print(c, s["name"], "from", s["first"], "ok", st["ok"], "loss", st["loss"], "und", st["undisclosed"],
              "stale", st["stale"], "med", st["median"] and round(st["median"], 1),
              "p10-90", st["p10"] and round(st["p10"], 1), st["p90"] and round(st["p90"], 1), "last", st["last"])
    for b in res["buckets"]:
        print(b)


if __name__ == "__main__":
    main()
