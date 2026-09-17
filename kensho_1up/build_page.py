"""result.json -> docs/kensho_1up.html (サイトの「仮説検証」タブに埋め込むレポート)."""
import html, json, math, os, statistics as st
from math import comb

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
data = json.load(open(os.path.join(HERE, "result.json"), encoding="utf-8"))
ALL = data["rows"]
OK = [r for r in ALL if r["status"] == "ok"]
FRI = [r for r in OK if r["wd"] == "金"]
FRI_X = [r for r in FRI if not r["stop_high"]]

# 既存レポートと同じスタイルを流用する
pbr = open(os.path.join(DOCS, "kensho_pbr.html"), encoding="utf-8").read()
STYLE = pbr[pbr.index("<style>"):pbr.index("</head>")]


def esc(s):
    return html.escape(str(s))


def f(x, d=2, sign=True):
    if x is None:
        return "—"
    s = f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
    return s


def cls(x):
    return "" if x is None or abs(x) < 1e-9 else ("pos" if x > 0 else "neg")


def sign_p(v):
    k = sum(x > 0 for x in v)
    n = sum(x != 0 for x in v)
    return min(1.0, sum(comb(n, i) for i in range(max(k, n - k), n + 1)) / 2 ** n * 2), k, n


def tstat(v):
    return st.mean(v) / (st.stdev(v) / math.sqrt(len(v)))


def stats(rs, key):
    v = [r[key] for r in rs if r.get(key) is not None]
    return {"n": len(v), "mean": st.mean(v), "med": st.median(v),
            "win": sum(x > 0 for x in v) / len(v) * 100}


def diff(rs, key, ref):
    """ref='g' グロース250比 / ref='self' 同銘柄の平常時比."""
    if ref == "g":
        v = [r[key] - r[f"g_{key}"] for r in rs if r.get(key) is not None and r.get(f"g_{key}") is not None]
    else:
        v = [r[key] - r["ctrl"][key] for r in rs if r.get("ctrl") and key in r["ctrl"]]
    return v


METRICS = [("gap", "始値（寄り付き）"), ("high", "高値"), ("low", "安値"),
           ("close", "終値"), ("oc", "寄り→引け"), ("d5", "5営業日後の終値"),
           ("d20", "20営業日後の終値")]


def summary_table(rs):
    out = []
    for k, lab in METRICS:
        s = stats(rs, k)
        g = diff(rs, k, "g") if k in ("gap", "close", "d5", "d20") else None
        c = diff(rs, k, "self") if k in ("gap", "high", "close") else None
        hl = ' class="hl"' if k in ("gap", "close") else ""
        gtxt = (f'<td class="n {cls(st.mean(g))}">{f(st.mean(g))}</td>'
                f'<td class="n">{sum(x > 0 for x in g)}/{len(g)}</td>') if g else '<td class="n">—</td><td class="n">—</td>'
        ctxt = (f'<td class="n {cls(st.mean(c))}">{f(st.mean(c))}</td>'
                f'<td class="n">{sum(x > 0 for x in c)}/{len(c)}</td>') if c else '<td class="n">—</td><td class="n">—</td>'
        out.append(f'<tr{hl}><td>{lab}</td><td class="n">{s["n"]}</td>'
                   f'<td class="n {cls(s["mean"])}">{f(s["mean"])}%</td>'
                   f'<td class="n {cls(s["med"])}">{f(s["med"])}%</td>'
                   f'<td class="n">{s["win"]:.0f}%</td>{gtxt}{ctxt}</tr>')
    return "\n".join(out)


def sig_rows():
    out = []
    for lab, rs in (("金曜公開 全件", FRI), ("ストップ高2件を除く", FRI_X)):
        for k, kl in (("gap", "始値"), ("close", "終値"), ("high", "高値")):
            v = diff(rs, k, "self")
            p, pos, n = sign_p(v)
            out.append(f'<tr><td>{lab} ／ {kl}</td><td class="n">{len(v)}</td>'
                       f'<td class="n {cls(st.mean(v))}">{f(st.mean(v))}pt</td>'
                       f'<td class="n {cls(st.median(v))}">{f(st.median(v))}pt</td>'
                       f'<td class="n">{pos}/{n}</td><td class="n">{p:.4f}</td>'
                       f'<td class="n">{tstat(v):.2f}</td></tr>')
        v = [r["oc"] for r in rs]
        p, pos, n = sign_p(v)
        out.append(f'<tr><td>{lab} ／ 寄り→引け</td><td class="n">{len(v)}</td>'
                   f'<td class="n {cls(st.mean(v))}">{f(st.mean(v))}%</td>'
                   f'<td class="n {cls(st.median(v))}">{f(st.median(v))}%</td>'
                   f'<td class="n">{pos}/{n}</td><td class="n">{p:.4f}</td>'
                   f'<td class="n">{tstat(v):.2f}</td></tr>')
    return "\n".join(out)


def year_rows():
    out = []
    for y in sorted({r["pub"][:4] for r in FRI}):
        rs = [r for r in FRI if r["pub"][:4] == y]
        c = diff(rs, "close", "self")
        out.append(f'<tr><td>{y}年</td><td class="n">{len(rs)}</td>'
                   f'<td class="n {cls(st.mean(r["gap"] for r in rs))}">{f(st.mean(r["gap"] for r in rs))}%</td>'
                   f'<td class="n {cls(st.mean(r["close"] for r in rs))}">{f(st.mean(r["close"] for r in rs))}%</td>'
                   f'<td class="n {cls(st.median(r["close"] for r in rs))}">{f(st.median(r["close"] for r in rs))}%</td>'
                   f'<td class="n">{sum(r["close"] > 0 for r in rs)}/{len(rs)}</td>'
                   f'<td class="n {cls(st.mean(c)) if c else ""}">{f(st.mean(c)) + "pt" if c else "—"}</td></tr>')
    return "\n".join(out)


def timeline_svg():
    """各回の翌営業日終値騰落率(棒)を公開順に並べる."""
    rs = sorted(OK, key=lambda r: r["pub"])
    W, H, L, T, B = 900, 300, 44, 14, 40
    lo, hi = -24, 30
    bw = (W - L - 8) / len(rs)
    y = lambda v: T + (hi - max(lo, min(hi, v))) / (hi - lo) * (H - T - B)
    parts = []
    for g in (-20, -10, 0, 10, 20, 30):
        parts.append(f'<line x1="{L}" x2="{W}" y1="{y(g):.1f}" y2="{y(g):.1f}" stroke="var(--line)" stroke-width="{1.2 if g == 0 else .6}"/>'
                     f'<text x="{L - 6}" y="{y(g) + 4:.1f}" text-anchor="end" font-size="11" fill="var(--ink-3)" class="num">{g:+d}%</text>')
    prev_year, last_x = None, -99
    for i, r in enumerate(rs):
        x = L + i * bw
        v = r["close"]
        col = "var(--pos)" if v > 0 else "var(--neg)"
        op = "1" if r["wd"] == "金" else ".35"
        y0, y1 = sorted((y(0), y(v)))
        tip = f'{r["pub"][:10]}（{r["wd"]}） {r["name"]}  翌営業日終値 {v:+.2f}%'
        parts.append(f'<rect x="{x + bw * .15:.1f}" y="{y0:.1f}" width="{bw * .7:.1f}" height="{max(1, y1 - y0):.1f}" fill="{col}" opacity="{op}"><title>{esc(tip)}</title></rect>')
        yr = r["pub"][:4]
        if yr != prev_year:
            parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{T}" y2="{H - B + 6}" stroke="var(--ink-3)" stroke-dasharray="2 3" stroke-width=".7"/>')
            if x - last_x > 40:
                parts.append(f'<text x="{x + 3:.1f}" y="{H - B + 20}" font-size="11" fill="var(--ink-2)" class="num">{yr}</text>')
                last_x = x
            prev_year = yr
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="各回の翌営業日終値騰落率">{"".join(parts)}</svg>'


def hist_svg():
    """翌営業日終値騰落率の分布: 動画の翌日 vs 同じ銘柄の平常時の金曜→翌日(平均値の分布ではなく各回の値)."""
    edges = list(range(-8, 11, 1))
    def counts(v):
        c = [0] * (len(edges) + 1)
        for x in v:
            i = 0
            while i < len(edges) and x >= edges[i]:
                i += 1
            c[i] += 1
        return [n / len(v) * 100 for n in c]
    ev = counts([r["close"] for r in FRI])
    W, H, L, T, B = 900, 240, 44, 10, 36
    n = len(ev)
    bw = (W - L - 8) / n
    mx = max(ev) * 1.1
    y = lambda v: T + (1 - v / mx) * (H - T - B)
    parts = []
    for g in (0, 10, 20, 30):
        if g <= mx:
            parts.append(f'<line x1="{L}" x2="{W}" y1="{y(g):.1f}" y2="{y(g):.1f}" stroke="var(--line)" stroke-width=".6"/>'
                         f'<text x="{L - 6}" y="{y(g) + 4:.1f}" text-anchor="end" font-size="11" fill="var(--ink-3)" class="num">{g}%</text>')
    for i, v in enumerate(ev):
        x = L + i * bw
        lo_e = "−∞" if i == 0 else f"{edges[i - 1]:+d}"
        hi_e = "+∞" if i == n - 1 else f"{edges[i]:+d}"
        mid = (edges[i - 1] if i else -9) + .5
        col = "var(--pos)" if mid > 0 else "var(--neg)"
        parts.append(f'<rect x="{x + 2:.1f}" y="{y(v):.1f}" width="{bw - 4:.1f}" height="{H - B - y(v):.1f}" fill="{col}" opacity=".85"><title>{lo_e}%〜{hi_e}%: {v:.1f}%</title></rect>')
        if i % 2 == 1 or i == n - 1:
            lab = f"{edges[i - 1]:+d}" if i else ""
            parts.append(f'<text x="{x:.1f}" y="{H - B + 16}" text-anchor="middle" font-size="11" fill="var(--ink-3)" class="num">{lab}</text>')
    parts.append(f'<text x="{W - 4}" y="{H - 4}" text-anchor="end" font-size="11" fill="var(--ink-3)">翌営業日終値の騰落率（%、1%刻み・両端は±∞まで）</text>')
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="翌営業日終値騰落率の分布">{"".join(parts)}</svg>'


def list_rows():
    out = []
    for r in sorted(ALL, key=lambda r: r["pub"], reverse=True):
        url = f'https://www.youtube.com/watch?v={r["vid"]}'
        badges = ""
        if r["wd"] != "金":
            badges += '<span class="badge">金曜以外</span>'
        if r.get("stop_high"):
            badges += '<span class="badge i">S高</span>'
        if r.get("news"):
            t = " / ".join(f'{n[0][5:]} {n[1]}' for n in r["news"])
            badges += f'<span class="badge m" title="{esc(t)}">開示あり</span>'
        if r["status"] != "ok":
            out.append(f'<tr class="dim"><td class="n">{r["pub"][:10]}</td><td class="n">{r["wd"]}</td>'
                       f'<td><a href="{url}" target="_blank" rel="noopener" title="{esc(r["title"])}">{esc(r["name"])}</a> <span class="badge">除外</span></td>'
                       f'<td class="n">{r["code"]}</td><td colspan="9" style="text-align:left">{esc(r["status"])}</td></tr>')
            continue
        c = r.get("ctrl")
        cd = r["close"] - c["close"] if c else None
        cells = [r["gap"], r["high"], r["low"], r["close"], r["oc"]]
        tds = "".join(f'<td class="n {cls(x)}" data-v="{x}">{f(x)}</td>' for x in cells)
        tds += f'<td class="n {cls(cd)}" data-v="{cd if cd is not None else -999}">{f(cd)}</td>'
        tds += "".join(f'<td class="n {cls(r.get(k))}" data-v="{r.get(k) if r.get(k) is not None else -999}">{f(r.get(k))}</td>' for k in ("d5", "d20"))
        tds += f'<td class="n" data-v="{r["vol_x"]}">{f(r["vol_x"], 2, False)}</td>'
        dim = ' class="dim"' if r["wd"] != "金" else ""
        out.append(f'<tr{dim} data-fri="{1 if r["wd"] == "金" else 0}"><td class="n" data-v="{r["pub"]}">{r["pub"][:10]}</td><td class="n">{r["wd"]} {r["pub"][11:]}</td>'
                   f'<td><a href="{url}" target="_blank" rel="noopener" title="{esc(r["title"])}">{esc(r["name"])}</a> {badges}'
                   f'<div class="small">{r["base_d"]} 終値 → {r["next_d"]}</div></td>'
                   f'<td class="n"><a href="https://kabutan.jp/stock/chart?code={r["code"]}" target="_blank" rel="noopener">{r["code"]}</a></td>{tds}</tr>')
    return "\n".join(out)


# 見出しカード用の数字
s_close = stats(FRI, "close")
s_gap = stats(FRI, "gap")
s_oc = stats(FRI, "oc")
c_close = diff(FRI, "close", "self")
p_close, k_close, n_close = sign_p(c_close)
g_close = diff(FRI, "close", "g")
recent = [r for r in FRI if r["pub"] >= "2025"]
c_recent = diff(recent, "close", "self")
companies = len({r["code"] for r in OK})
first = min(r["pub"] for r in OK)[:10]
last = max(r["pub"] for r in OK)[:10]
excluded = [r for r in ALL if r["status"] != "ok"]
dal = sum(1 for r in FRI if r["code"] == "3848")
FRI_NODAL = [r for r in FRI if r["code"] != "3848"]
c_nodal = diff(FRI_NODAL, "close", "self")
pre5 = [r["pre5"] for r in FRI if r.get("pre5") is not None]
volx = [r["vol_x"] for r in FRI]

page = f"""<!doctype html>
<html lang="ja" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>1UP企業インタビュー効果</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Shippori+Mincho+B1:wght@600;700&family=Zen+Kaku+Gothic+New:wght@400;500;700&family=IBM+Plex+Mono:wght@400;600&display=swap">
{STYLE}
<style>
tr.dim td{{opacity:.55}}
#list th{{cursor:pointer;user-select:none}}
#list th:hover{{color:var(--ink)}}
#list td:first-child,#list th:first-child{{min-width:0}}
#list td:nth-child(3){{text-align:left;white-space:normal;min-width:200px}}
#list .small{{font-size:11px}}
.ctl{{display:flex;gap:16px;align-items:center;font-size:13px;color:var(--ink-2);margin-top:14px}}
</style>
</head>
<body>
<div class="wrap">

<header class="top">
  <div class="eyebrow">仮説検証 / YouTube 1UP投資部屋</div>
  <h1>金曜夜の企業インタビュー動画で、<br>翌営業日に株価は上がるのか</h1>
  <p class="sub">YouTubeチャンネル「1UP投資部屋」（@1up794）は、ほぼ毎週金曜20:00に上場企業の社長インタビュー
  （【銘柄勉強会】）を公開している。取引時間外に公開されるので、影響が出るなら翌営業日の寄り付きからになる。
  遡れる最初の回（{first}）から{last}までの<b>{len(OK)}本・{companies}社</b>で、翌営業日の値動きを調べた。
  結論は<b>翌営業日は上がりやすい。ただし上昇はほぼ寄り付きの時点で出ていて、寄ってから買っても平均的には取れない</b>。</p>

  <div class="cards">
    <div class="card" style="--c:var(--pos)">
      <div class="lbl">金曜公開 {s_close['n']}本の翌営業日の終値<br>（金曜終値比・平均）</div>
      <div class="big">{f(s_close['mean'])}%</div>
      <div class="foot">中央値 {f(s_close['med'])}% ／ 上昇 {s_close['win']:.0f}%</div>
    </div>
    <div class="card" style="--c:var(--brass)">
      <div class="lbl">同じ銘柄の「動画なしの金曜→翌営業日」との差（終値）</div>
      <div class="big">{f(st.mean(c_close))}pt</div>
      <div class="foot">上回った回 {k_close}/{n_close}（符号検定 p={p_close:.4f}）</div>
    </div>
    <div class="card" style="--c:var(--teal)">
      <div class="lbl">翌営業日の始値<br>（金曜終値比・平均）</div>
      <div class="big">{f(s_gap['mean'])}%</div>
      <div class="foot">中央値 {f(s_gap['med'])}% ／ 上昇 {s_gap['win']:.0f}%</div>
    </div>
    <div class="card" style="--c:var(--ink-2)">
      <div class="lbl">寄り付きで買って大引けで売った場合<br>（寄り→引け・平均）</div>
      <div class="big">{f(s_oc['mean'])}%</div>
      <div class="foot">中央値 {f(s_oc['med'])}% ／ 上昇 {s_oc['win']:.0f}%（偶然の範囲）</div>
    </div>
  </div>
</header>

<section>
  <h2><span class="n">01</span>どう調べたか</h2>
  <div class="steps">
    <div class="step"><h4>対象はチャンネルの全動画から企業インタビュー回だけを抜き出した</h4>
      <p>全691本のタイトルを取得し、「社長に直接聞いてみた」「ガチ取材」「銘柄勉強会」などを含む109本の詳細（公開日時・概要欄）を確認した。
      対談・投資家コラボ・「注目の2銘柄」回など、特定の1社への取材でないものは除いた。残った{len(ALL)}本の社名は、株探の銘柄ページ名と照合して証券コードを確定した。</p></div>
    <div class="step"><h4>「基準値」と「翌営業日」は公開時刻から決めた</h4>
      <p>基準値は<b>公開時刻より前に大引けを迎えた最後の立会日の終値</b>、翌営業日は<b>公開後に最初に寄り付いた立会日</b>。
      金曜20:00公開なら金曜終値→月曜（祝日なら火曜）になる。{len(FRI)}本が金曜公開（2023年以降はほぼすべて金曜20:00）。
      初期の木曜・月曜などの公開回{len(OK) - len(FRI)}本も同じ方法で計算して一覧に残したが、集計からは除いた。</p></div>
    <div class="step"><h4>比べる相手を2つ用意した</h4>
      <p>① <b>同じ銘柄の平常時</b>：基準日の前250営業日にある「金曜終値→翌営業日」を全部集めた平均。小型株は週明けに動きやすい、といった銘柄のクセを差し引ける。<br>
      ② <b>東証グロース市場250指数</b>（連動ETF 2516の同じ区間）：その週末に地合い全体が動いた分を差し引ける。取材先はほとんどがグロース市場の小型株。</p></div>
    <div class="step"><h4>動画以外の材料が無かったかを確認した</h4>
      <p>取材は決算直後に撮られることが多いので、基準日の大引け後〜翌営業日の寄り付き前に出た適時開示を全件調べた（やのしんTDnet API）。
      該当は{sum(1 for r in OK if r.get('news'))}本だけで、決算や業績修正に当たるものは{sum(1 for r in OK if r.get('material'))}本。これを除いても結果はほぼ変わらない（06の表）。</p></div>
    <div class="step"><h4>株価は Yahoo! ファイナンスの日足（分割調整済み）</h4>
      <p>始値・高値・安値・終値・出来高。ストップ高は東証の値幅制限表から判定した（翌営業日に{sum(1 for r in OK if r.get('stop_high'))}件）。</p></div>
  </div>
</section>

<section>
  <h2><span class="n">02</span>翌営業日の値動き（金曜公開 {len(FRI)}本）</h2>
  <p class="lead">騰落率はすべて<b>金曜終値比</b>（寄り→引けだけは月曜の始値比）。「差」の列は、各回の値から比べる相手の値を引いた平均と、上回った回数。</p>
  <div class="scroll"><table>
    <thead><tr><th>指標</th><th>本数</th><th>平均</th><th>中央値</th><th>プラスの割合</th><th>グロース250との差</th><th>上回った回</th><th>同じ銘柄の平常時との差</th><th>上回った回</th></tr></thead>
    <tbody>
{summary_table(FRI)}
    </tbody>
  </table></div>
  <div class="note">
    <strong>読み方。</strong>同じ銘柄の平常時の「金曜→翌営業日」は平均で終値{f(st.mean(r['ctrl']['close'] for r in FRI if r.get('ctrl')))}%・始値{f(st.mean(r['ctrl']['gap'] for r in FRI if r.get('ctrl')))}%とほぼゼロなのに対し、
    動画の翌営業日は始値で{f(s_gap['mean'])}%、終値で{f(s_close['mean'])}%。<b>上乗せ分は寄り付きの時点で約半分が出ている</b>。
    寄ってからの上昇（寄り→引け）は平均{f(s_oc['mean'])}%あるが、中央値は{f(s_oc['med'])}%、プラスは約半分で、偶然と区別できない。
    5営業日後もグロース250を平均{f(st.mean(diff(FRI, 'd5', 'g')))}pt上回るが、20営業日後はばらつきが大きく、はっきりした差は残らない。
  </div>

  <h3>偶然で説明できるか</h3>
  <p class="small">「同じ銘柄の平常時との差」について、プラスとマイナスの回数から符号検定（両側）、平均からt値を出した。
  ストップ高になった2件（BlueMeme 2024-12-30 +28.9%、ククレブ・アドバイザーズ 2026-02-02 +22.7%）が平均を大きく押し上げているので、除いた場合も並べた。</p>
  <div class="scroll"><table>
    <thead><tr><th>対象 ／ 指標</th><th>本数</th><th>平均</th><th>中央値</th><th>プラス/件数</th><th>p値（符号検定）</th><th>t値</th></tr></thead>
    <tbody>
{sig_rows()}
    </tbody>
  </table></div>
  <p class="small">始値・終値・高値は、ストップ高を除いてもp&lt;0.01（78回中およそ7割が平常時を上回る）。寄り→引けはp&gt;0.4で、効果があるとは言えない。</p>
</section>

<section>
  <h2><span class="n">03</span>回ごとの翌営業日終値</h2>
  <figure>
    {timeline_svg()}
    <figcaption>1本の棒が1回の動画。公開順に並べた。薄い棒は金曜以外の公開回（集計外）。棒にカーソルを置くと日付と社名が出る。±30%を超える値は枠で切っている。</figcaption>
  </figure>

  <h3>年ごとの推移</h3>
  <div class="scroll"><table>
    <thead><tr><th>公開年</th><th>本数</th><th>始値 平均</th><th>終値 平均</th><th>終値 中央値</th><th>終値プラス</th><th>平常時との差（終値）</th></tr></thead>
    <tbody>
{year_rows()}
    </tbody>
  </table></div>
  <p class="small">効果は2025年以降に強まっている（2025年以降の{len(recent)}本では平常時との差が平均{f(st.mean(c_recent))}pt、中央値{f(st.median(c_recent))}pt）。
  チャンネル登録者数の伸びと重なるが、登録者数の推移は取得していないので、因果は確認していない（推測）。</p>

  <h3>分布</h3>
  <figure>
    {hist_svg()}
    <figcaption>金曜公開{len(FRI)}本の翌営業日終値。0〜+5%に集中していて、大きく上げる回が少数混じる形。−5%を下回った回は、2024年8月5日の暴落（令和のブラックマンデー）に当たったクックビズ（−21.3%。同日のグロース250は−17.7%）など少数。</figcaption>
  </figure>
</section>

<section>
  <h2><span class="n">04</span>全{len(ALL)}本の一覧</h2>
  <p class="small">列見出しをクリックすると並べ替え。社名にカーソルを置くと動画タイトル、「開示あり」にカーソルを置くと開示の件名が出る。数字はすべて%（平常時差はpt、出来高倍率は翌営業日の出来高÷基準日までの20日平均）。</p>
  <div class="ctl"><label><input type="checkbox" id="onlyfri"> 金曜公開だけ表示</label></div>
  <div class="scroll"><table id="list">
    <thead><tr><th data-k="0">公開日</th><th>曜日・時刻</th><th data-k="2" data-t="s">企業 ／ 基準日→翌営業日</th><th>コード</th>
    <th data-k="4">始値</th><th data-k="5">高値</th><th data-k="6">安値</th><th data-k="7">終値</th><th data-k="8">寄→引</th><th data-k="9">平常時差</th><th data-k="10">5日後</th><th data-k="11">20日後</th><th data-k="12">出来高倍率</th></tr></thead>
    <tbody>
{list_rows()}
    </tbody>
  </table></div>
</section>

<section>
  <h2><span class="n">05</span>注意点</h2>
  <div class="caveats">
    <div class="cv"><h4><span class="badge i">重複</span>同じ会社が何度も出ている</h4>
      <p>{companies}社で{len(OK)}本。データ・アプリケーション（3848）は金曜公開だけで{dal}回、マイクロアドも6回。
      データ・アプリケーションを除いた{len(c_nodal)}本でも平常時との差は平均{f(st.mean(c_nodal))}pt・中央値{f(st.median(c_nodal))}ptで、結論は変わらない。</p></div>
    <div class="cv"><h4><span class="badge i">スポンサー</span>企業側が費用を出している回がある</h4>
      <p>概要欄に「提供：IR Robotics」とある回など、IR施策として出演している企業が含まれる。選ばれる会社が「株価を上げたい時期の会社」に偏っている可能性は否定できない。
      ただし公開前5営業日の騰落率は平均{f(st.mean(pre5))}%・中央値{f(st.median(pre5))}%で、事前に大きく上げてから出演する傾向は見られない。</p></div>
    <div class="cv"><h4><span class="badge i">決算</span>取材は決算の直後が多い</h4>
      <p>週末の間に出た開示は確認したが、決算発表が数日〜数週間前にあれば、決算後の株価ドリフトが残っている可能性がある。
      同じ銘柄の平常時と比べているので銘柄のクセは差し引けているが、「決算後の週」に限った比較はしていない。</p></div>
    <div class="cv"><h4><span class="badge m">売買</span>実際に取れるかは別の話</h4>
      <p>上昇の多くは月曜の寄り付きまでに出ているので、月曜の寄りで買っても平均的には取れない。金曜20:00の公開直後に夜間PTSで買えば寄り付きの上昇を取れる可能性はあるが、
      PTSの過去の約定価格は取得できず<b>検証していない</b>。小型株なので板が薄く、手数料・スプレッドも考慮していない。</p></div>
    <div class="cv"><h4><span class="badge">除外</span>集計に入っていない回</h4>
      <p>{'、'.join(f"{r['name']}（{r['pub'][:10]}公開・{r['status']}）" for r in excluded) or 'なし'}。
      出来高倍率は株式分割があると日足の分割調整の仕方で歪むことがあり、参考値。金曜公開回の中央値は{st.median(volx):.2f}倍で、出来高が普段より大きく膨らむ回は一部に限られる。</p></div>
  </div>
</section>

<footer>
  データ：YouTube（yt-dlpで公開日時・タイトル・概要欄を取得）、Yahoo! ファイナンス日足、やのしんTDnet API、株探（銘柄名の照合）。
  集計 {data['generated']}。ソースは kabutan-ranking/kensho_1up/（analyze.py → build_page.py）。投資判断の根拠とすることを意図したものではありません。
</footer>
</div>
<script>
(function(){{
  const tb=document.querySelector('#list tbody');
  const rows=[...tb.rows];
  let dir={{}};
  document.querySelectorAll('#list th[data-k]').forEach(th=>{{
    th.addEventListener('click',()=>{{
      const k=+th.dataset.k, s=th.dataset.t==='s';
      dir[k]=-(dir[k]||1);
      const val=r=>{{const c=r.cells[k]; if(!c) return -999; if(s) return c.textContent;
        const v=c.dataset.v; return v===undefined?-999:(isNaN(+v)?v:+v);}};
      rows.sort((a,b)=>{{const x=val(a),y=val(b); return (x>y?1:x<y?-1:0)*dir[k];}});
      rows.forEach(r=>tb.appendChild(r));
    }});
  }});
  const cb=document.getElementById('onlyfri');
  cb.addEventListener('change',()=>rows.forEach(r=>{{r.hidden=cb.checked && r.dataset.fri!=='1';}}));
}})();
</script>
</body>
</html>
"""
open(os.path.join(DOCS, "kensho_1up.html"), "w", encoding="utf-8").write(page)
print("wrote docs/kensho_1up.html", len(page))
