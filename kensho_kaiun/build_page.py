"""result.json -> docs/kensho_kaiun.html (サイトの「仮説検証」タブに埋め込むレポート)."""
import html, json, os, statistics as st
from collections import defaultdict

from stocks import STOCKS, BIG3

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
data = json.load(open(os.path.join(HERE, "result.json"), encoding="utf-8"))
S = data["stocks"]

pbr = open(os.path.join(DOCS, "kensho_pbr.html"), encoding="utf-8").read()
STYLE = pbr[pbr.index("<style>"):pbr.index("</head>")]


SHORT = {"9101": "郵船", "9104": "商船", "9107": "川崎"}


def esc(s):
    return html.escape(str(s))


def f(x, d=1, suf=""):
    return "—" if x is None else f"{x:.{d}f}{suf}"


def pc(x, d=0):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def cls(x):
    return "" if x is None or abs(x) < 1e-9 else ("pos" if x > 0 else "neg")


def ok_pers(code, since=None, until=None):
    return [w[2] for w in S[code]["weekly"] if w[5] == "ok"
            and (since is None or w[0] >= since) and (until is None or w[0] < until)]


def status_share(code):
    ws = [w for w in S[code]["weekly"] if w[5] != "nodata"]
    n = len(ws) or 1
    return {k: sum(w[5] == k for w in ws) / n for k in ("ok", "loss", "undisclosed", "stale")}


# ---- 年ごとの表(年間の中央値・年末値) ----
def year_rows():
    years = sorted({w[0][:4] for c in BIG3 for w in S[c]["weekly"] if w[5] != "nodata"})
    out = []
    for y in years:
        tds = ""
        for c in BIG3:
            ws = [w for w in S[c]["weekly"] if w[0][:4] == y and w[5] != "nodata"]
            pers = [w[2] for w in ws if w[5] == "ok"]
            loss = sum(w[5] == "loss" for w in ws)
            und = sum(w[5] in ("undisclosed", "stale") for w in ws)
            if not ws:
                tds += '<td class="n">—</td><td class="n">—</td>'
                continue
            end = ws[-1]
            endtxt = f(end[2]) if end[5] == "ok" else {"loss": "赤字予想", "undisclosed": "予想なし",
                                                          "stale": "資料欠け"}[end[5]]
            med = f(st.median(pers)) if pers else "—"
            extra = []
            if loss:
                extra.append(f'赤字{loss}週')
            if und:
                extra.append(f'欠{und}週')
            ex = f'<div class="small">{" ".join(extra)}</div>' if extra else ""
            tds += f'<td class="n">{med}{ex}</td><td class="n">{endtxt}</td>'
        ag = [w for w in data["big3"] if w[0][:4] == y]
        agp = [w[1] for w in ag if w[1] is not None]
        tds += f'<td class="n hlc">{f(st.median(agp)) if agp else "—"}</td>'
        out.append(f"<tr><td>{y}</td>{tds}</tr>")
    return "\n".join(out)


def summary_rows():
    out = []
    for c, s in S.items():
        ps = ok_pers(c)
        if not ps:
            continue
        sh = status_share(c)
        last = s["stats"]["last"]
        lastp = f(last[2]) if last[5] == "ok" else {"loss": "赤字予想", "undisclosed": "予想なし"}.get(last[5], "—")
        q = sorted(ps)
        out.append(
            f'<tr{" class=\"hl\"" if c in BIG3 else ""}><td>{esc(s["name"])} <span class="small">{c}</span></td>'
            f'<td class="n">{s["first"][:7]}〜</td>'
            f'<td class="n">{f(st.median(ps))}</td><td class="n">{f(q[int(len(q) * .1)])}〜{f(q[int(len(q) * .9)])}</td>'
            f'<td class="n">{f(min(ps))}</td><td class="n">{f(max(ps))}</td>'
            f'<td class="n">{sh["loss"] * 100:.0f}%</td><td class="n">{(sh["undisclosed"] + sh["stale"]) * 100:.0f}%</td>'
            f'<td class="n"><b>{lastp}</b></td></tr>')
    return "\n".join(out)


def fy_rows():
    out = []
    by = defaultdict(dict)
    for r in data["fy_table"]:
        if r["code"] in BIG3:
            by[r["fy"]][r["code"]] = r
    for fy in sorted(by):
        tds = ""
        for c in BIG3:
            r = by[fy].get(c)
            if not r:
                tds += '<td class="n">—</td>' * 3
                continue
            fe, ac = r["first"], r["actual"]
            if fe is None:
                rt, cl = "期初は未定", ""
            elif fe > 0 and ac > 0:
                ratio = ac / fe
                rt = f"{ratio:.2f}倍"
                cl = "pos" if ratio > 1.05 else ("neg" if ratio < .95 else "")
            elif fe > 0:
                rt, cl = "黒字予想→赤字", "neg"
            elif ac > 0:
                rt, cl = "赤字予想→黒字", "pos"
            else:
                rt, cl = "赤字予想→赤字", "neg"
            tds += (f'<td class="n">{f(r["per_first"])}</td><td class="n">{f(r["per_actual"])}</td>'
                    f'<td class="n {cl}" title="期初予想EPS {r["first"] if r["first"] is not None else "未定"} → 実績 {r["actual"]}（期初予想 {r["first_pub"]}）">{rt}</td>')
        out.append(f"<tr><td>{fy[:4]}年{int(fy[5:])}月期</td>{tds}</tr>")
    return "\n".join(out)


def bucket_rows():
    out = []
    for b in data["buckets"]:
        out.append(f'<tr><td>{b["label"]}</td><td class="n">{b["n"]:,}</td><td class="n">{b["years"]}</td>'
                   f'<td class="n {cls(b["median"])}">{pc(b["median"])}</td>'
                   f'<td class="n {cls(b["mean"])}">{pc(b["mean"])}</td>'
                   f'<td class="n">{b["win"] * 100:.0f}%</td>'
                   f'<td class="n small">{" / ".join(str(b["by"][c]) for c in BIG3)}</td></tr>')
    return "\n".join(out)


def source_note():
    parts = []
    for c in BIG3:
        d = S[c]["docs"]
        wb = [x for x in d if x["src"] == "wb"]
        td = [x for x in d if x["src"] == "tdnet"]
        parts.append(f'{S[c]["name"]}：Wayback {len(wb)}件（{wb[0]["pub"][:7] + "〜" + wb[-1]["pub"][:7] if wb else "なし"}）＋TDnet {len(td)}件（{td[0]["pub"][:7]}〜）')
    return "、".join(parts)


MANUAL_N = sum(1 for _ in open(os.path.join(HERE, "manual.csv"), encoding="utf-8")) - 1

# ---- 04/05の注記用 ----
FYB = [r for r in data["fy_table"] if r["code"] in BIG3]
both = [r for r in FYB if r["first"] and r["first"] > 0 and r["actual"] > 0]
up2 = [r for r in both if r["actual"] / r["first"] >= 1.5]
dn2 = [r for r in both if r["actual"] / r["first"] <= 1 / 1.5]
turn = [r for r in FYB if r["first"] and r["first"] > 0 and r["actual"] <= 0]
near = [r for r in both if .8 <= r["actual"] / r["first"] <= 1.25]


def fyname(r):
    return f'{SHORT[r["code"]]}{r["fy"][2:4]}/{int(r["fy"][5:])}'


# ---- チャート用データ(週次) ----
chart = {"big3": [[w[0], w[1], w[2], w[3]] for w in data["big3"]], "stocks": {}}
for c, s in S.items():
    chart["stocks"][c] = {"name": s["name"], "big3": c in BIG3,
                          "w": [[w[0], w[1], w[2], w[5][0]] for w in s["weekly"]]}

agg_now = next((w for w in reversed(data["big3"]) if w[1] is not None), None)
agg_all = [w[1] for w in data["big3"] if w[1] is not None]
agg_since = next(w[0] for w in data["big3"] if w[1] is not None)
peak_low = min((w for w in data["big3"] if w[1] is not None), key=lambda w: w[1])
b = {x["label"]: x for x in data["buckets"]}

page = f"""<!doctype html>
<html lang="ja" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>海運株の予想PER</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Shippori+Mincho+B1:wght@600;700&family=Zen+Kaku+Gothic+New:wght@400;500;700&family=IBM+Plex+Mono:wght@400;600&display=swap">
{STYLE}
<style>
.ctl{{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 4px}}
.ctl button{{font:inherit;font-size:12.5px;padding:4px 11px;border:1px solid var(--line);background:var(--surface);color:var(--ink-2);border-radius:14px;cursor:pointer}}
.ctl button.on{{background:var(--brass);border-color:var(--brass);color:var(--bg);font-weight:700}}
#chart{{position:relative}}
#chart svg{{width:100%;height:auto;display:block}}
#tip{{position:absolute;pointer-events:none;background:var(--surface-2);border:1px solid var(--line);border-radius:3px;padding:6px 9px;font-size:12px;line-height:1.5;display:none;white-space:nowrap;box-shadow:var(--shadow)}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink-2);margin-top:6px}}
.legend i{{display:inline-block;width:14px;height:9px;margin-right:5px;vertical-align:middle}}
td.hlc{{color:var(--brass);font-weight:600}}
table td:first-child{{text-align:left}}
</style>
</head>
<body>
<div class="wrap">

<header class="top">
  <div class="eyebrow">仮説検証 / 海運株 × 予想PER</div>
  <h1>海運株の予想PERは、<br>20年でどう動いてきたか</h1>
  <p class="sub">日本郵船・商船三井・川崎汽船の大手3社（と中堅5社）について、<b>その日までに会社が出していた最新の通期予想EPS</b>で割った「予想PER」を、
  決算短信・業績予想の修正のPDFから1本ずつ作り直した。サイトに出ている現在値ではなく、<b>当時の投資家が見ていた数字</b>を再現している。
  結論は<b>海運株の予想PERは景気敏感株の典型で、1倍台から赤字予想（算出不能）まで振れる。水準で割安・割高を判断すると逆を掴みやすい</b>。</p>

  <div class="cards">
    <div class="card" style="--c:var(--brass)">
      <div class="lbl">大手3社合算の予想PER（{agg_now[0]}）<br>時価総額合計 ÷ 予想純利益合計</div>
      <div class="big">{f(agg_now[1])}倍</div>
      <div class="foot">{agg_since[:4]}年以降の中央値 {f(st.median(agg_all))}倍</div>
    </div>
    <div class="card" style="--c:var(--teal)">
      <div class="lbl">3社合算の最低値<br>（コンテナ運賃バブル期）</div>
      <div class="big">{f(peak_low[1])}倍</div>
      <div class="foot">{peak_low[0]}</div>
    </div>
    <div class="card" style="--c:var(--neg)">
      <div class="lbl">大手3社の「赤字予想」だった期間<br>（予想PERが出せない）</div>
      <div class="big">{st.mean(status_share(c)['loss'] for c in BIG3) * 100:.0f}%</div>
      <div class="foot">{' / '.join(f"{SHORT[c]} {status_share(c)['loss'] * 100:.0f}%" for c in BIG3)}</div>
    </div>
    <div class="card" style="--c:var(--pos)">
      <div class="lbl">予想PER5倍未満の日に買った1年後<br>（配当込み・中央値）</div>
      <div class="big">{pc(b['5倍未満']['median'])}</div>
      <div class="foot">25倍以上なら {pc(b['25倍以上']['median'])}（ただし年数が少ない）</div>
    </div>
  </div>
</header>

<section>
  <h2><span class="n">01</span>予想PERの推移</h2>
  <p class="lead">左軸が予想PER、右軸が株価（どちらも対数目盛）。線が途切れているところは<b>赤字予想</b>（赤い帯）か<b>予想が出ていない・資料が欠けている</b>（灰色の帯）期間。
  「3社合算」は3社の時価総額の合計を予想純利益の合計で割ったもので、1社が赤字予想でも合計が黒字なら出る。</p>
  <div class="ctl" id="btns"></div>
  <div id="chart"><div id="tip"></div></div>
  <div class="legend">
    <span><i style="background:var(--brass)"></i>予想PER</span>
    <span><i style="background:var(--slate);opacity:.6"></i>株価（右軸・分割調整後。大手3社表示では時価総額合計）</span>
    <span><i style="background:var(--neg);opacity:.35"></i>赤字予想</span>
    <span><i style="background:var(--ink-3);opacity:.3"></i>予想なし・資料欠け</span>
  </div>
  <p class="small">点線は10倍と20倍。100倍を超える週は上端に張り付けている（予想純利益がほぼゼロの週）。</p>
</section>

<section>
  <h2><span class="n">02</span>年ごとの水準（大手3社）</h2>
  <p class="small">年内の週次の中央値と、年末（最終週）の値。「赤字n週」「欠n週」はその年のうち予想PERが出せなかった週数。</p>
  <div class="scroll"><table>
    <thead><tr><th rowspan="2">年</th><th colspan="2">日本郵船</th><th colspan="2">商船三井</th><th colspan="2">川崎汽船</th><th rowspan="2">3社合算<br>中央値</th></tr>
    <tr><th>中央値</th><th>年末</th><th>中央値</th><th>年末</th><th>中央値</th><th>年末</th></tr></thead>
    <tbody>
{year_rows()}
    </tbody>
  </table></div>
</section>

<section>
  <h2><span class="n">03</span>銘柄ごとのまとめ</h2>
  <div class="scroll"><table>
    <thead><tr><th>銘柄</th><th>データ</th><th>中央値</th><th>10〜90%の範囲</th><th>最低</th><th>最高</th><th>赤字予想</th><th>予想なし・欠け</th><th>足元</th></tr></thead>
    <tbody>
{summary_rows()}
    </tbody>
  </table></div>
  <p class="small">中央値・範囲は予想PERが出せた週だけで計算（赤字予想の週は含まない）。中堅5社はTDnetのPDFが残る2013年秋以降のみ。
  NSユナイテッド海運は2026年7月31日に日本郵船がTOBを予定と発表しており、以降の株価はTOB価格に張り付いている。</p>
</section>

<section>
  <h2><span class="n">04</span>会社予想はどれだけ外れたか</h2>
  <p class="lead">予想PERが「安く見える」「高く見える」原因の多くは、分母の予想EPSが後で大きく変わることにある。
  期初予想が出た日の株価で、①期初予想EPSで割ったPERと、②その期の実績EPSで割ったPER（後から見た本当のPER）を並べた。</p>
  <div class="scroll"><table>
    <thead><tr><th rowspan="2">期</th><th colspan="3">日本郵船</th><th colspan="3">商船三井</th><th colspan="3">川崎汽船</th></tr>
    <tr><th>期初予想PER</th><th>実績PER</th><th>実績÷予想</th><th>期初予想PER</th><th>実績PER</th><th>実績÷予想</th><th>期初予想PER</th><th>実績PER</th><th>実績÷予想</th></tr></thead>
    <tbody>
{fy_rows()}
    </tbody>
  </table></div>
  <p class="small">実績EPSは、IRBANKの決算まとめにある実績の当期純利益を、その期の予想（予想純利益÷予想EPS）から逆算した株数（現在の株数基準）で割って出した。IRBANKが表示している実績EPSは、株式分割の調整が一部の年で片方しか反映されていないため使っていない。期初の本決算短信が手元に無い期は表から外した。「実績÷予想」にカーソルを置くと元の数字が出る。
  「—」は期初予想PERが出せない（赤字予想・未定）か、実績が赤字の期。</p>
  <div class="note">
    <strong>読み方。</strong>期初予想で黒字だった{len(FYB) - sum(1 for r in FYB if not r["first"] or r["first"] <= 0)}期のうち、
    実績が予想の0.8〜1.25倍に収まったのは{len(near)}期だけ。<b>1.5倍以上に上振れた期が{len(up2)}</b>（{"、".join(fyname(r) for r in up2)}）、
    <b>2/3以下に下振れた期が{len(dn2)}</b>、<b>黒字予想が赤字で終わった期が{len(turn)}</b>（{"、".join(fyname(r) for r in turn)}）。
    上振れはコンテナ運賃が高騰した2021〜2022年3月期に集中していて、川崎汽船の2022年3月期は期初予想PER {f(next((r["per_first"] for r in FYB if r["code"] == "9107" and r["fy"] == "2022-03"), None))}倍が、実績で見ると{f(next((r["per_actual"] for r in FYB if r["code"] == "9107" and r["fy"] == "2022-03"), None))}倍だった。
    逆に市況が悪化した年は、期初に10〜15倍に見えていたものが赤字で終わっている。
  </div>
</section>

<section>
  <h2><span class="n">05</span>予想PERの水準で買ったら、1年後どうなったか</h2>
  <p class="lead">大手3社の毎営業日を「その日の予想PER」で分け、250営業日後までの配当込みリターンを集計した。</p>
  <div class="scroll"><table>
    <thead><tr><th>その日の予想PER</th><th>観測日数</th><th>該当した年の数</th><th>1年後 中央値</th><th>平均</th><th>プラスの割合</th><th>郵船/商船/川崎の日数</th></tr></thead>
    <tbody>
{bucket_rows()}
    </tbody>
  </table></div>
  <div class="note">
    <strong>読み方。</strong>予想PERが低い日ほどその後1年の成績が良く、<b>5倍未満では中央値{pc(b["5倍未満"]["median"])}・プラス{b["5倍未満"]["win"] * 100:.0f}%</b>、
    <b>25倍以上では中央値{pc(b["25倍以上"]["median"])}・プラス{b["25倍以上"]["win"] * 100:.0f}%</b>だった。
    「景気敏感株は低PERで売り、高PERで買え」という通説とは逆の結果になっている。ただし5倍未満の日は{b["5倍未満"]["years"]}年分しかなく、大半は2021〜2023年のコンテナ運賃高騰期
    （予想が上方修正され続け、PERが低いまま株価が上がった局面）。残りは2008年秋〜2009年初めのリーマン・ショック後の急落局面で、ここは期中の下方修正を拾えていない（資料欠け）ため、実際より低いPERになっている可能性がある。
    25倍以上は、赤字からの回復期に小さな利益予想で割った値が多い（2010〜2011年、2017年など）。
    10〜25倍の「普通の水準」ではほぼ五分五分で、水準だけからは方向が読めない。
  </div>
</section>

<section>
  <h2><span class="n">06</span>どう作ったか</h2>
  <div class="steps">
    <div class="step"><h4>分母は「その日までに開示された最新の会社予想」</h4>
      <p>決算短信（四半期ごと）と「業績予想の修正に関するお知らせ」から、通期の1株当たり当期純利益の予想値と、予想純利益を抜き出した。
      開示が引け前（2024年11月4日までは15:00、以降15:30）ならその日の終値から、引け後なら翌営業日から反映。
      予想の対象期は「開示済みの予想のうち最も新しい期」とし、期末を過ぎても本決算の発表までは旧期の予想を使う（株探などの表示と同じ考え方）。</p></div>
    <div class="step"><h4>資料は TDnet（2013年秋以降）と Wayback Machine（それ以前）</h4>
      <p>TDnetの過去PDFはすでに消えているため、IRBANKが保存しているPDF（2013年10月以降）を使った。それ以前は、各社IRサイトの旧URLのうち
      Wayback Machineに保存が残っていたPDFだけを拾った（{source_note()}）。<b>2013年以前は資料に抜けがあり、途中の修正を拾えていない期間がある</b>。
      最新の予想が400日以上前のものしか無い日と、予想の対象期が終わって80日を過ぎても翌期の予想が見つからない日（本決算短信が欠けている）は「資料欠け」として予想PERを出していない。冒頭に日付が無い商船三井の旧資料は、ファイル名の年月（con0508 → 2005年8月）から公開日を25日と仮定した。</p></div>
    <div class="step"><h4>株式併合・分割は「予想純利益 ÷ 予想EPS ＝ 株数」で基準を判定</h4>
      <p>3社とも2017年10月に10株→1株の併合、2022年に1株→3株の分割（川崎汽船は2024年にも1株→3株）をしている。
      効力発生の数か月前から新しい株数で予想EPSを書く会社があるため、開示ごとに逆算した株数が前後の開示と揃う方を採用し、すべて現在の株数基準に直した。
      株価はYahoo!ファイナンスの日足（分割調整済み。1年後リターンは配当込みの調整後終値）。</p></div>
    <div class="step"><h4>PDFの読み取り</h4>
      <p>表の数字は座標で同じ行にあるものを拾い、EPSは「小数2桁の最後の数値」、予想純利益はその手前の整数とした。
      文字コードが壊れたPDF（CIDがそのまま出るもの）は変換表で戻し、文字が図形化されていて読めなかった{MANUAL_N}件（商船三井の2025年4月〜2026年1月の4件と、乾汽船・共栄タンカーなど中堅株）は、WindowsのOCRで表の位置を探して切り出し、数値は画像から目で読んで入力した（manual.csv）。</p></div>
  </div>
</section>

<section>
  <h2><span class="n">07</span>注意点</h2>
  <div class="caveats">
    <div class="cv"><h4><span class="badge i">資料</span>2013年以前は抜けがある</h4>
      <p>Wayback Machineに残っていた分だけで作っているため、期中の業績修正の一部は反映されていない可能性がある。特に2008年のリーマン・ショック前後は、
      実際には何度も下方修正されている。この期間の値は「おおよその水準」として見てほしい。</p></div>
    <div class="cv"><h4><span class="badge i">独立性</span>1年後リターンの表は見かけより証拠が弱い</h4>
      <p>毎日の観測を数えているので、隣り合う日はほぼ同じ1年間を見ている。「5倍未満」の日はほぼ2021〜2023年のコンテナ運賃高騰期に集中しており、
      実質的には1〜2回の景気循環の結果にすぎない。統計的な検定はしていない。</p></div>
    <div class="cv"><h4><span class="badge m">解釈</span>低PERは「割安」ではなく「予想が追いついていない」か「ピーク」</h4>
      <p>2021年は予想が何度も上方修正され、PERは低いまま株価が上がり続けた。一方で2022年後半以降は、PER1〜2倍でも翌期の減益が見えていて株価は伸びなかった。
      どちらになるかは運賃市況の方向で決まり、PERの水準だけでは区別できない（これは結果からの解釈で、検証はしていない）。</p></div>
    <div class="cv"><h4><span class="badge">範囲</span>含めていないもの</h4>
      <p>乾汽船など中堅株は2013年以降だけ。上場廃止済みの海運株（川崎近海汽船など）は含めていない。
      実績PER（前期実績ベース）や、アナリスト予想（コンセンサス）ベースのPERとは値が異なる。</p></div>
  </div>
</section>

<footer>
  データ：TDnet開示PDF（IRBANK保存分）、各社IRサイトの旧PDF（Wayback Machine）、やのしんTDnet API（開示一覧）、Yahoo! ファイナンス日足、IRBANK（実績純利益）。
  集計 {data['generated']}。ソースは kabutan-ranking/kensho_kaiun/（fetch_docs.py・fetch_wayback.py → parse_docs.py → analyze.py → build_page.py）。投資判断の根拠とすることを意図したものではありません。
</footer>
</div>
<script>
const D = {json.dumps(chart, ensure_ascii=False, separators=(",", ":"))};
const FY = {json.dumps([r for r in data["fy_table"] if r["code"] in BIG3], ensure_ascii=False, separators=(",", ":"))};
const order = ["big3", {", ".join(json.dumps(c) for c in STOCKS)}];
let cur = "big3";
const btns = document.getElementById("btns");
for (const k of order) {{
  const b = document.createElement("button");
  b.textContent = k === "big3" ? "大手3社（重ねて表示）" : D.stocks[k].name;
  b.onclick = () => {{ cur = k; draw(); }};
  b.dataset.k = k;
  btns.appendChild(b);
}}
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const W = 900, H = 420, L = 46, R = 66, T = 30, B = 30;
const lo = Math.log(0.8), hi = Math.log(100);
const yP = v => T + (hi - Math.log(Math.min(100, Math.max(0.8, v)))) / (hi - lo) * (H - T - B);
function draw() {{
  for (const b of btns.children) b.classList.toggle("on", b.dataset.k === cur);
  const box = document.getElementById("chart");
  const t0 = Date.parse("2005-01-01"), t1 = Date.now();
  const x = d => L + (Date.parse(d) - t0) / (t1 - t0) * (W - L - R);
  let s = `<svg viewBox="0 0 ${{W}} ${{H}}">`;
  for (let y = 2005; y <= 2026; y++) {{
    const xx = x(y + "-01-01");
    s += `<line x1="${{xx}}" x2="${{xx}}" y1="${{T}}" y2="${{H - B}}" stroke="var(--line-soft)"/>`;
    if (y % 3 === 2 || y === 2026) s += `<text x="${{xx + 2}}" y="${{H - B + 16}}" font-size="11" fill="var(--ink-3)" class="num">${{y}}</text>`;
  }}
  for (const g of [1, 2, 5, 10, 20, 50, 100]) {{
    s += `<line x1="${{L}}" x2="${{W - R}}" y1="${{yP(g)}}" y2="${{yP(g)}}" stroke="var(--line)" ${{g === 10 || g === 20 ? 'stroke-dasharray="4 4"' : ''}} stroke-width=".7"/>`;
    s += `<text x="${{L - 6}}" y="${{yP(g) + 4}}" text-anchor="end" font-size="11" fill="var(--ink-3)" class="num">${{g}}倍</text>`;
  }}
  // 株価(右軸・対数)。大手3社表示では3社の時価総額合計
  const priceAxis = (pts, fmt, label) => {{
    const pl = Math.log(Math.min(...pts.map(r => r[1]))), ph = Math.log(Math.max(...pts.map(r => r[1])));
    const yQ = v => T + 6 + (ph - Math.log(v)) / (ph - pl) * (H - T - B - 6);
    const line = pts.map((r, i) => (i ? "L" : "M") + x(r[0]).toFixed(1) + " " + yQ(r[1]).toFixed(1)).join("");
    s += `<path d="${{line}}L${{x(pts[pts.length - 1][0]).toFixed(1)}} ${{H - B}}L${{x(pts[0][0]).toFixed(1)}} ${{H - B}}Z" fill="var(--slate)" opacity=".10"/>`;
    s += `<path d="${{line}}" fill="none" stroke="var(--slate)" stroke-width="1.3" opacity=".85"/>`;
    for (let k = 0; k <= 4; k++) {{
      const v = Math.exp(pl + (ph - pl) * k / 4);
      s += `<text x="${{W - R + 6}}" y="${{yQ(v) + 4}}" font-size="11" fill="var(--slate)" class="num">${{fmt(v)}}</text>`;
    }}
    s += `<text x="${{W - 4}}" y="${{T - 2}}" text-anchor="end" font-size="11" fill="var(--slate)">${{label}}</text>`;
    s += `<text x="${{L}}" y="${{T - 2}}" font-size="11" fill="var(--brass)">予想PER（左軸）</text>`;
  }};
  const yen = v => v >= 10000 ? (v / 10000).toFixed(v >= 100000 ? 0 : 1) + "万円" : Math.round(v).toLocaleString() + "円";
  const series = [];
  if (cur === "big3") {{
    priceAxis(D.big3.filter(r => r[3] > 0).map(r => [r[0], r[3]]),
      v => v >= 10000 ? (v / 10000).toFixed(1) + "兆円" : Math.round(v).toLocaleString() + "億円", "3社の時価総額合計（右軸）");
    const cols = ["var(--teal)", "var(--pos)", "var(--nikkei)"];
    ["9101", "9104", "9107"].forEach((c, i) => series.push({{name: D.stocks[c].name, col: cols[i], w: D.stocks[c].w, width: 1.1, op: .7}}));
    series.push({{name: "3社合算", col: "var(--brass)", w: D.big3.map(r => [r[0], null, r[1], r[1] === null ? "n" : "o", r[3]]), width: 2.4, op: 1}});
  }} else {{
    const st = D.stocks[cur];
    // 状態の帯
    let run = null;
    const flush = (end) => {{ if (run) {{ s += `<rect x="${{x(run.s)}}" y="${{T}}" width="${{Math.max(1, x(end) - x(run.s))}}" height="${{H - T - B}}" fill="${{run.k === 'l' ? 'var(--neg)' : 'var(--ink-3)'}}" opacity="${{run.k === 'l' ? .18 : .14}}"/>`; run = null; }} }};
    for (const r of st.w) {{
      const k = r[3] === "l" ? "l" : (r[3] === "u" || r[3] === "s") ? "u" : null;
      if (!k || (run && run.k !== k)) flush(r[0]);
      if (k && !run) run = {{k, s: r[0]}};
    }}
    flush(st.w[st.w.length - 1][0]);
    priceAxis(st.w.filter(r => r[1] > 0), yen, "株価（右軸・分割調整後）");
    series.push({{name: st.name, col: "var(--brass)", w: st.w, width: 1.9, op: 1}});
  }}
  for (const se of series) {{
    let d = "", pen = false;
    for (const r of se.w) {{
      if (r[2] == null) {{ pen = false; continue; }}
      d += (pen ? "L" : "M") + x(r[0]).toFixed(1) + " " + yP(r[2]).toFixed(1);
      pen = true;
    }}
    s += `<path d="${{d}}" fill="none" stroke="${{se.col}}" stroke-width="${{se.width}}" opacity="${{se.op}}" stroke-linejoin="round"/>`;
  }}
  if (cur === "big3") {{
    let lx = L + 8;
    for (const se of series) {{
      s += `<rect x="${{lx}}" y="${{T + 6}}" width="12" height="3" fill="${{se.col}}"/><text x="${{lx + 16}}" y="${{T + 11}}" font-size="11.5" fill="var(--ink-2)">${{se.name}}</text>`;
      lx += 26 + se.name.length * 12;
    }}
  }}
  s += `<line id="hair" x1="0" x2="0" y1="${{T}}" y2="${{H - B}}" stroke="var(--ink-3)" stroke-width=".7" style="display:none"/>`;
  s += `<rect x="${{L}}" y="${{T}}" width="${{W - L - R}}" height="${{H - T - B}}" fill="transparent" id="hit"/></svg>`;
  box.innerHTML = s + '<div id="tip"></div>';
  const svg = box.querySelector("svg"), tip = box.querySelector("#tip"), hair = box.querySelector("#hair");
  const lab = {{o: "", l: "赤字予想", u: "予想なし", s: "資料欠け", n: "—"}};
  svg.addEventListener("mousemove", ev => {{
    const pt = svg.getBoundingClientRect();
    const vx = (ev.clientX - pt.left) / pt.width * W;
    const t = t0 + (vx - L) / (W - L - R) * (t1 - t0);
    let lines = [], dd = null;
    for (const se of series) {{
      let best = null;
      for (const r of se.w) {{ if (Date.parse(r[0]) <= t) best = r; else break; }}
      if (!best) continue;
      dd = best[0];
      const v = best[2] != null ? best[2].toFixed(1) + "倍" : lab[best[3]] || "—";
      const px = best[1] ? `株価 ${{Math.round(best[1]).toLocaleString()}}円` : (best[4] ? `時価総額計 ${{(best[4] / 10000).toFixed(2)}}兆円` : "");
      lines.push(`<span style="color:${{se.col}}">■</span> ${{se.name}} PER ${{v}}` + (px ? ` <span style="color:var(--slate)">／ ${{px}}</span>` : ""));
    }}
    if (!dd) return;
    hair.setAttribute("x1", x(dd)); hair.setAttribute("x2", x(dd)); hair.style.display = "";
    tip.innerHTML = `<b>${{dd}}</b><br>` + lines.join("<br>");
    tip.style.display = "block";
    const px = (ev.clientX - pt.left);
    tip.style.left = (px > pt.width * .6 ? px - tip.offsetWidth - 12 : px + 12) + "px";
    tip.style.top = "20px";
  }});
  svg.addEventListener("mouseleave", () => {{ tip.style.display = "none"; hair.style.display = "none"; }});
}}
draw();
</script>
</body>
</html>
"""

open(os.path.join(DOCS, "kensho_kaiun.html"), "w", encoding="utf-8").write(page)
print("wrote", len(page))
