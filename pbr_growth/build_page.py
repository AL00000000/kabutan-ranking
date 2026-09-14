# -*- coding: utf-8 -*-
"""検証結果を docs/kensho_pbr.html (サイトの「仮説検証」タブ) に書き出す。

数値はすべてこのスクリプトの中で再計算する(手で書き写さない)。
配色・組版は docs/kensho.html と同じものを使う。
"""
import io
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
BARS = ROOT / "cache_bars_10y"
DST = ROOT / "docs" / "kensho_pbr.html"
OKU = 1e5
SNAPS = ["2016-08", "2020-12", "2023-01", "2025-01", "2026-08"]
NAME = {"G": "グロース系", "P": "プライム系", "S": "スタンダード系"}
WINDOWS = [("2017-01-01", "2019-12-31", "2016-08", "2017–2019", "コロナ前"),
           ("2020-01-01", "2022-12-31", "2016-08", "2020–2022", "コロナ〜金利上昇"),
           ("2023-07-01", "2026-06-30", "2023-01", "2023H2–2026", "PBR要請後")]


def pct(x):
    return (math.exp(x) - 1) * 100


def daily(bars, a, b):
    r, prev = [], None
    for d, o, h, l, c, v in bars:
        if a <= d <= b:
            if prev and prev > 0 and c > 0:
                r.append(math.log(c / prev))
            prev = c
        elif d < a:
            prev = c
    return r


def collect():
    sys.path.insert(0, str(BASE))
    import aggregate as A
    mkt = json.load(open(BASE / "market_hist.json", encoding="utf-8"))
    itype = json.load(open(BASE / "itype.json", encoding="utf-8"))

    # --- 資金フロー(年次・億円) ---
    flows = {}
    for lbl in ("G", "P"):
        o = defaultdict(lambda: [0.0, 0.0, 0.0, 0])
        for wk, v in itype.get(lbl, {}).items():
            y = int(wk[:4])
            o[y][0] += (v["個人差引き"] or 0) / OKU
            o[y][1] += (v["海外差引き"] or 0) / OKU
            o[y][2] += v["個人比率"] or 0
            o[y][3] += 1
        flows[lbl] = {y: (a, b, c / max(n, 1), n) for y, (a, b, c, n) in o.items()}

    # --- 勝者と集中度 ---
    cache = {p.stem: json.loads(p.read_text(encoding="utf-8"))["bars"]
             for p in BARS.glob("*.json")}
    win = {}
    for a, b, snap, label, _ in WINDOWS:
        for g in "GPS":
            codes = [c for c in cache if mkt.get(c, {}).get(snap) == g]
            n_full = 0
            rows = []
            for c in codes:
                r = daily(cache[c], a, b)
                if len(r) < 500:
                    continue
                n_full += 1
                tot = sum(r)
                if tot < math.log(2):
                    continue
                srt = sorted(r, reverse=True)
                acc = 0.0
                n = 0
                for x in srt:
                    acc += x
                    n += 1
                    if acc >= tot:
                        break
                rows.append({"top5": sum(srt[:5]) / tot, "nd": n,
                             "vr": A.vratio(r, 20), "run": A.runs(r)[1]})
            med = lambda k: statistics.median([x[k] for x in rows if x[k] is not None])
            win[(label, g)] = {
                "n": len(rows), "all": n_full,
                "rate": len(rows) / n_full * 100 if n_full else 0,
                "top5": med("top5") if rows else None, "nd": med("nd") if rows else None,
                "vr": med("vr") if rows else None, "run": med("run") if rows else None,
            }
    return flows, win, mkt


# ---------- SVG ----------
def svg_flow(flows, lbl, title, W=880, H=250):
    ys = [y for y in sorted(flows[lbl]) if flows[lbl][y][3] >= 40]
    ind = [flows[lbl][y][0] for y in ys]
    fgn = [flows[lbl][y][1] for y in ys]
    lo = min(0, min(ind + fgn)) * 1.1
    hi = max(0, max(ind + fgn)) * 1.1
    # 値は億円。1万億円=1兆円なので、桁が大きい市場だけ兆円表記に切り替える
    tril = max(abs(lo), abs(hi)) >= 20000
    fmt = (lambda v: "{0:+.1f}兆".format(v / 10000)) if tril         else (lambda v: "{0:+,.0f}".format(v))
    pad = {"l": 62, "r": 12, "t": 16, "b": 30}
    pw, ph = W - pad["l"] - pad["r"], H - pad["t"] - pad["b"]
    Y = lambda v: pad["t"] + ph * (hi - v) / (hi - lo)
    bw = pw / len(ys) / 2.6
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{title}">']
    for gv in range(5):
        v = lo + (hi - lo) * gv / 4
        y = Y(v)
        p.append(f'<line x1="{pad["l"]}" x2="{W-pad["r"]}" y1="{y:.1f}" y2="{y:.1f}" '
                 f'stroke="var(--line-soft)" stroke-width="1"/>')
        p.append(f'<text x="{pad["l"]-8}" y="{y+4:.1f}" text-anchor="end" font-size="10.5" '
                 f'fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">'
                 f'{fmt(v)}</text>')
    p.append(f'<line x1="{pad["l"]}" x2="{W-pad["r"]}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" '
             f'stroke="var(--ink-3)" stroke-width="1.2"/>')
    for i, y in enumerate(ys):
        cx = pad["l"] + pw * (i + .5) / len(ys)
        for val, col, off in ((ind[i], "var(--slate)", -bw * 0.55),
                              (fgn[i], "var(--nikkei)", bw * 0.55)):
            y0, y1 = Y(0), Y(val)
            p.append(f'<rect x="{cx+off-bw/2:.1f}" y="{min(y0,y1):.1f}" width="{bw:.1f}" '
                     f'height="{abs(y1-y0):.1f}" fill="{col}" rx="1"/>')
        p.append(f'<text x="{cx:.1f}" y="{H-10}" text-anchor="middle" font-size="10.5" '
                 f'fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">{y%100:02d}</text>')
    p.append("</svg>")
    return "\n".join(p)


def svg_rate(win, W=880, H=230):
    labels = [w[3] for w in WINDOWS]
    hi = max(win[(l, g)]["rate"] for l in labels for g in "GPS") * 1.18
    pad = {"l": 52, "r": 12, "t": 14, "b": 42}
    pw, ph = W - pad["l"] - pad["r"], H - pad["t"] - pad["b"]
    Y = lambda v: pad["t"] + ph * (1 - v / hi)
    cols = {"G": "var(--brass)", "P": "var(--slate)", "S": "var(--teal)"}
    gw = pw / len(labels)
    bw = gw / 4.6
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="3年で2倍になった割合">']
    for gv in range(5):
        v = hi * gv / 4
        y = Y(v)
        p.append(f'<line x1="{pad["l"]}" x2="{W-pad["r"]}" y1="{y:.1f}" y2="{y:.1f}" '
                 f'stroke="var(--line-soft)"/>')
        p.append(f'<text x="{pad["l"]-8}" y="{y+4:.1f}" text-anchor="end" font-size="10.5" '
                 f'fill="var(--ink-3)" font-family="IBM Plex Mono,monospace">{v:.0f}%</text>')
    for i, lab in enumerate(labels):
        base = pad["l"] + gw * i + gw / 2
        for j, g in enumerate("GPS"):
            v = win[(lab, g)]["rate"]
            x = base + (j - 1) * bw * 1.15 - bw / 2
            y = Y(v)
            p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                     f'height="{Y(0)-y:.1f}" fill="{cols[g]}" rx="1"/>')
            p.append(f'<text x="{x+bw/2:.1f}" y="{y-5:.1f}" text-anchor="middle" '
                     f'font-size="10.5" fill="var(--ink-2)" '
                     f'font-family="IBM Plex Mono,monospace">{v:.1f}</text>')
        p.append(f'<text x="{base:.1f}" y="{H-22}" text-anchor="middle" font-size="11.5" '
                 f'fill="var(--ink-2)">{lab}</text>')
        p.append(f'<text x="{base:.1f}" y="{H-8}" text-anchor="middle" font-size="10" '
                 f'fill="var(--ink-3)">{WINDOWS[i][4]}</text>')
    p.append("</svg>")
    return "\n".join(p)
