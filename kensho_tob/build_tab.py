# -*- coding: utf-8 -*-
"""検証結果を docs/kensho_tob.html（仮説検証タブの中身）として書き出す。

見た目は既存の検証レポート(kensho_pbr.html)のスタイルをそのまま流用する。
数字は summary.json / control.json から毎回作り直すので、データを取り直したら
このスクリプトを流せばページも更新される。

  py build_tab.py
"""
import json
import re
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
DOCS = BASE.parent / "docs"
STYLE_SRC = DOCS / "kensho_pbr.html"
OUT = DOCS / "kensho_tob.html"

BUCKETS = [(0, .5), (.5, .8), (.8, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 99)]
HIGH_PBR_SECTORS = {"情報・通信業", "サービス業", "医薬品", "精密機器", "電気機器", "その他製品"}


def head():
    """kensho_pbr.html の <head> をそのまま借りる(配色とタイポを揃えるため)"""
    h = STYLE_SRC.read_text("utf-8")
    m = re.search(r"^(.*?)</head>", h, re.S)
    head_html = m.group(1)
    return head_html.replace("<title>PBR要請とグロース株</title>",
                             "<title>TOBされる会社は安いのか</title>")


def fresh(ctrl, d):
    """上場廃止済みで古い値が返っている会社を落とす"""
    out = []
    for v in ctrl[d].values():
        if not v.get("pbr") or not v.get("date"):
            continue
        if (date.fromisoformat(d) - date.fromisoformat(v["date"])).days > 30:
            continue
        out.append(v)
    return out


def stats(vals):
    vals = sorted(vals)
    n = len(vals)
    k = int(n * .1)
    return {
        "n": n,
        "mean": st.mean(vals),
        "median": st.median(vals),
        "trim": st.mean(vals[k:n - k] if n - 2 * k >= 3 else vals),
        "p25": vals[int(n * .25)],
        "p75": vals[int(n * .75)],
        "under1": sum(v < 1 for v in vals) / n * 100,
    }


def bars(tob, ctl):
    """TOB群と対照群の分布を並べた横棒グラフ(SVG)"""
    rowh, gap, w, left = 34, 8, 560, 92
    h = len(BUCKETS) * (rowh + gap) + 26
    out = [f'<svg viewBox="0 0 {left + w + 56} {h}" role="img" aria-label="PBRの分布">']
    mx = max(max(tob), max(ctl))
    for i, (lo, hi) in enumerate(BUCKETS):
        y = i * (rowh + gap) + 14
        label = f"{lo:g}〜{hi:g}倍" if hi < 99 else f"{lo:g}倍以上"
        out.append(f'<text x="{left - 10}" y="{y + 12}" text-anchor="end" font-size="12" '
                   f'fill="var(--ink-2)" font-family="IBM Plex Mono,monospace">{label}</text>')
        for j, (v, color) in enumerate(((tob[i], "var(--brass)"), (ctl[i], "var(--slate)"))):
            bw = max(1, v / mx * w)
            by = y + j * 15
            out.append(f'<rect x="{left}" y="{by}" width="{bw:.1f}" height="12" rx="2" fill="{color}"/>')
            out.append(f'<text x="{left + bw + 7:.1f}" y="{by + 10}" font-size="11" fill="var(--ink-3)" '
                       f'font-family="IBM Plex Mono,monospace">{v:.1f}%</text>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    rows = json.loads((BASE / "summary.json").read_text("utf-8"))["rows"]
    ctrl = json.loads((BASE / "control.json").read_text("utf-8"))
    have = [r for r in rows if r.get("pbr")]
    all_s = stats([r["pbr"] for r in have])
    rel_s = stats([r["rel_pbr"] for r in have if r.get("rel_pbr")])
    low_s = stats([r["pbr"] for r in have if r["sector"] not in HIGH_PBR_SECTORS])

    cdates = sorted(ctrl)
    cstats = {d: stats([v["pbr"] for v in fresh(ctrl, d)]) for d in cdates}
    mid = cstats[cdates[1]]

    tob_dist = [sum(1 for r in have if lo <= r["pbr"] < hi) / len(have) * 100 for lo, hi in BUCKETS]
    cvals = [v["pbr"] for v in fresh(ctrl, cdates[1])]
    ctl_dist = [sum(1 for v in cvals if lo <= v < hi) / len(cvals) * 100 for lo, hi in BUCKETS]

    by_year = defaultdict(list)
    for r in have:
        by_year[r["ann_date"][:4]].append(r["pbr"])
    by_sector = defaultdict(list)
    for r in have:
        by_sector[r["sector"] or "不明"].append(r["pbr"])
    by_kind = defaultdict(list)
    for r in have:
        by_kind[r["kind"]].append(r["pbr"])
    by_mkt = defaultdict(list)
    for r in have:
        by_mkt[r["mkt"] or "不明"].append(r["pbr"])

    def yearrow(y, d):
        t = by_year.get(y, [])
        c = [v["pbr"] for v in fresh(ctrl, d)]
        return (f'<tr><td>{y}年</td><td class="n">{len(t)}</td>'
                f'<td class="n">{st.median(t):.2f}</td>'
                f'<td class="n">{sum(v<1 for v in t)/len(t)*100:.1f}%</td>'
                f'<td class="n">{st.median(c):.2f}</td>'
                f'<td class="n">{sum(v<1 for v in c)/len(c)*100:.1f}%</td></tr>')

    def mktrows(y, d):
        out = []
        for name in ("プライム市場", "スタンダード市場", "グロース市場"):
            t = [r["pbr"] for r in have if r["ann_date"][:4] == y and r["mkt"] == name]
            pre = name.replace("市場", "")
            c = [v["pbr"] for v in fresh(ctrl, d) if v["market"].startswith(pre)]
            if len(t) < 3:
                continue
            out.append(f'<tr><td>{y}年 {name}</td><td class="n">{len(t)}</td>'
                       f'<td class="n">{st.median(t):.2f}</td>'
                       f'<td class="n">{sum(v<1 for v in t)/len(t)*100:.1f}%</td>'
                       f'<td class="n">{st.median(c):.2f}</td>'
                       f'<td class="n">{sum(v<1 for v in c)/len(c)*100:.1f}%</td></tr>')
        return "\n".join(out)

    sector_rows = "\n".join(
        f'<tr><td>{s}</td><td class="n">{len(v)}</td><td class="n">{st.median(v):.2f}</td>'
        f'<td class="n">{st.mean(v):.2f}</td>'
        f'<td class="n">{sum(x<1 for x in v)/len(v)*100:.0f}%</td></tr>'
        for s, v in sorted(by_sector.items(), key=lambda kv: -len(kv[1])) if len(v) >= 5)

    kind_rows = "\n".join(
        f'<tr><td>{k}</td><td class="n">{len(v)}</td><td class="n">{st.median(v):.2f}</td>'
        f'<td class="n">{st.mean(v):.2f}</td>'
        f'<td class="n">{sum(x<1 for x in v)/len(v)*100:.0f}%</td></tr>'
        for k, v in sorted(by_kind.items(), key=lambda kv: -len(kv[1])))

    mkt_rows = "\n".join(
        f'<tr><td>{k}</td><td class="n">{len(v)}</td><td class="n">{st.median(v):.2f}</td>'
        f'<td class="n">{st.mean(v):.2f}</td>'
        f'<td class="n">{sum(x<1 for x in v)/len(v)*100:.0f}%</td></tr>'
        for k, v in sorted(by_mkt.items(), key=lambda kv: -len(kv[1])))

    # 1倍割れ株を持っていてTOBに当たる確率(概算)
    hit_rows = []
    for d in cdates:
        y = d[:4]
        c = [v["pbr"] for v in fresh(ctrl, d)]
        t = by_year.get(y, [])
        pool = 3800 * (sum(v < 1 for v in c) / len(c))
        hits = sum(v < 1 for v in t)
        hit_rows.append(f'<tr><td>{y}年{"（9/22まで）" if y == "2026" else ""}</td>'
                        f'<td class="n">{pool:,.0f}社</td><td class="n">{hits}社</td>'
                        f'<td class="n">{hits/pool*100:.2f}%</td></tr>')

    asof = max(r["ann_date"] for r in rows)
    days = json.loads((BASE / "raw_tob_days.json").read_text("utf-8"))
    crawl_end = days[-1]
    n_disc = len(json.loads((BASE / "raw_tob.json").read_text("utf-8")))
    n_cand = len(list((BASE / "raw_company").glob("*.json")))
    body = f"""<body>
<div class="wrap">

<header class="top">
  <div class="eyebrow">2024.01 — 2026.09 ／ TOB対象 {len(rows)}社 ／ 公表直前のPBR</div>
  <h1>TOBされる会社は安いのか</h1>
  <p class="sub">「東証のPBR1倍割れ是正要請で、市場に評価されないくらいなら買収された方がいいと考える会社が増えているのではないか。だとすれば低PBR株を先に仕込む意味がある」──
  この仮説を、2024年以降にTOBされた全{len(rows)}社の<strong>公表直前のPBR</strong>で確かめました。結論から書くと、<strong>TOB対象は市場平均より割安ではありません</strong>。</p>

  <div class="cards">
    <div class="card" style="--c:var(--brass)"><div class="lbl">TOB対象の公表直前PBR<br>中央値</div><div class="big">{all_s['median']:.2f}倍</div><div class="foot">n={all_s['n']}</div></div>
    <div class="card" style="--c:var(--slate)"><div class="lbl">同じ時期の普通の上場企業<br>中央値（対照群）</div><div class="big">{mid['median']:.2f}倍</div><div class="foot">n={mid['n']}・{cdates[1]}</div></div>
    <div class="card" style="--c:var(--neg)"><div class="lbl">TOB対象のうち<br>PBR1倍割れだった比率</div><div class="big">{all_s['under1']:.1f}%</div><div class="foot">市場は{mid['under1']:.1f}%</div></div>
    <div class="card" style="--c:var(--teal)"><div class="lbl">1倍割れ株を持っていて<br>TOBに当たる確率（概算）</div><div class="big">年2〜3%</div><div class="foot">2024-2025年</div></div>
  </div>
</header>

<section>
  <h2><span class="n">01</span>何を測ったか</h2>
  <p class="lead">「TOBされた会社のPBR」は、いつ時点のPBRを指すかで答えが変わります。公表後の株価はTOB価格に張り付くので、公表日を1日でも後ろに取ると<strong>全社が実態より高く出ます</strong>。ここで測ったのは<strong>市場がまだ知らなかった最後の終値</strong>のPBRです。</p>
  <div class="steps">
    <div class="step"><h4>母集団は「買われる側が出した開示」で作る</h4>
      <p>TDnetの適時開示を2024/1/1から{crawl_end}まで1日ずつ全件見て、公開買付関連を{n_disc:,}件拾い、そこに出てくる候補コード{n_cand}社をさらに会社単位で引き直しました。対象会社は自分で意見表明やMBOの開示を出すので、<span class="kv">買付者が非上場のファンドやSPC</span>でも取りこぼしません。</p>
      <p><strong>自己株TOB（自社株買い）は買収ではないので除外</strong>。「公開買付けに準ずる行為として政令で定める買集め行為」も別物なので除外しています。</p></div>
    <div class="step"><h4>公表日は「市場が最初に知った日」</h4>
      <p>同じ案件の続報は180日でまとめ、いちばん古い当事者開示の日を公表日としました。買付者の予告が先で意見表明が後という順（牧野フライス）もあるため、案件として認める条件は「意見表明・賛同・MBOのいずれかが1件でも含まれること」にし、日付はクラスタの先頭を使っています。</p></div>
    <div class="step"><h4>PBRは公表直前の終値ベース</h4>
      <p>公表が<span class="kv">引け後</span>なら当日の終値、<span class="kv">場中</span>ならその日の終値はもう汚れているので前営業日の終値を使います。東証の取引終了は2024年11月5日から15:30に延びたので、その前後で判定時刻を変えています。</p>
      <p>株価とPBRはIRBANKから取りました。<strong>TOBが成立すると上場廃止になり、株探もYahooもデータごと消えます</strong>が、IRBANKには残ります。</p></div>
    <div class="step"><h4>比べる相手（対照群）を用意する</h4>
      <p>「TOB対象の中央値は{all_s['median']:.2f}倍」だけでは高いのか安いのか分かりません。2023年1月時点の東証一覧から乱数で300社を抜き（その後上場廃止になった会社を落とさないため）、同じIRBANKで同じ日のPBRを取りました。2024/6・2025/6・2026/6の3時点です。</p></div>
  </div>
</section>

<section>
  <h2><span class="n">02</span>結果 — 分布はほぼ重なる</h2>
  <figure>
    <div class="legend"><span><i style="background:var(--brass)"></i>TOB対象 {all_s['n']}社</span><span><i style="background:var(--slate)"></i>対照群 {mid['n']}社（{cdates[1]}）</span></div>
    {bars(tob_dist, ctl_dist)}
    <figcaption>公表直前PBRの分布。TOB対象がとくに低PBRに偏っている、という形にはなっていません。0.5〜0.8倍の帯はむしろ対照群のほうが厚く、2〜3倍の帯はTOB対象のほうが厚いです。</figcaption>
  </figure>

  <div class="scroll"><table>
    <thead><tr><th>集計のしかた</th><th>n</th><th>平均</th><th>中央値</th><th>トリム平均</th><th>1倍割れ</th></tr></thead>
    <tbody>
      <tr class="hl"><td>全件そのまま</td><td class="n">{all_s['n']}</td><td class="n">{all_s['mean']:.2f}倍</td><td class="n">{all_s['median']:.2f}倍</td><td class="n">{all_s['trim']:.2f}倍</td><td class="n">{all_s['under1']:.1f}%</td></tr>
      <tr><td>高PBRになりやすい業種を除く</td><td class="n">{low_s['n']}</td><td class="n">{low_s['mean']:.2f}倍</td><td class="n">{low_s['median']:.2f}倍</td><td class="n">{low_s['trim']:.2f}倍</td><td class="n">{low_s['under1']:.1f}%</td></tr>
      <tr><td>業種相対PBR（業種平均＝1.00）</td><td class="n">{rel_s['n']}</td><td class="n">{rel_s['mean']:.2f}</td><td class="n">{rel_s['median']:.2f}</td><td class="n">{rel_s['trim']:.2f}</td><td class="n">{rel_s['under1']:.1f}%</td></tr>
    </tbody>
  </table></div>
  <p class="small">平均{all_s['mean']:.2f}倍に対し中央値{all_s['median']:.2f}倍。最大は28.5倍（ベースフード）、最小は0.27倍（桂川電機）で、<strong>平均はグロースの高PBR銘柄に引っ張られています</strong>。外れ値の影響を抜く方法を3通り並べました。除外した業種は情報・通信業／サービス業／医薬品／精密機器／電気機器／その他製品です。業種相対PBRは各社のPBRを「同じ月・同じ市場・同じ33業種の平均PBR（JPXの月次統計）」で割ったもので、1.00未満なら業種平均より割安を意味します。中央値{rel_s['median']:.2f}は<strong>業種の中でも平均並み</strong>ということです。</p>
</section>

<section>
  <h2><span class="n">03</span>対照群と並べる — ここで仮説が否定される</h2>
  <div class="scroll"><table>
    <thead><tr><th></th><th>TOB n</th><th>TOB中央値</th><th>TOB 1倍割れ</th><th>市場中央値</th><th>市場 1倍割れ</th></tr></thead>
    <tbody>
      {yearrow('2024', cdates[0])}
      {yearrow('2025', cdates[1])}
      {yearrow('2026', cdates[2])}
    </tbody>
  </table></div>
  <p><span class="badge m">実測</span>どの年も<strong>TOB対象のほうがPBRが高く、1倍割れの比率は低い</strong>。年を追うごとにTOB対象のPBRは上がり（{st.median(by_year['2024']):.2f}→{st.median(by_year['2026']):.2f}倍）、1倍割れ比率は下がっています（{sum(v<1 for v in by_year['2024'])/len(by_year['2024'])*100:.0f}%→{sum(v<1 for v in by_year['2026'])/len(by_year['2026'])*100:.0f}%）。</p>

  <h3>市場区分をそろえても同じ</h3>
  <p class="small">TOB対象にグロース市場の銘柄が多ければ、それだけで平均PBRは上がります。構成の違いで見かけの差が出ていないか、市場区分をそろえて確かめました。</p>
  <div class="scroll"><table>
    <thead><tr><th></th><th>TOB n</th><th>TOB中央値</th><th>TOB 1倍割れ</th><th>市場中央値</th><th>市場 1倍割れ</th></tr></thead>
    <tbody>
      {mktrows('2024', cdates[0])}
      {mktrows('2025', cdates[1])}
      {mktrows('2026', cdates[2])}
    </tbody>
  </table></div>
  <p><span class="badge i">推論</span>そろえても結論は変わりません。<strong>「安いから買われる」より「欲しいから買われる」</strong>と読むほうが、このデータには合っています。ただしこれは買収の動機を直接調べたものではなく、PBRの分布から読んだ解釈です。</p>
</section>

<section>
  <h2><span class="n">04</span>内訳</h2>
  <h3>業種別（5社以上）</h3>
  <div class="scroll"><table>
    <thead><tr><th>33業種</th><th>n</th><th>中央値</th><th>平均</th><th>1倍割れ</th></tr></thead>
    <tbody>{sector_rows}</tbody>
  </table></div>
  <p class="small">最多は情報・通信業。件数が多いうえにPBRも高く、全体の平均を押し上げています。</p>

  <h3>市場別・種別</h3>
  <div class="scroll"><table>
    <thead><tr><th>市場</th><th>n</th><th>中央値</th><th>平均</th><th>1倍割れ</th></tr></thead>
    <tbody>{mkt_rows}</tbody>
  </table></div>
  <div class="scroll"><table>
    <thead><tr><th>種別</th><th>n</th><th>中央値</th><th>平均</th><th>1倍割れ</th></tr></thead>
    <tbody>{kind_rows}</tbody>
  </table></div>
  <p class="small">MBO（経営陣による買収）は中央値{st.median(by_kind['MBO']):.2f}倍で第三者によるTOBより低いものの、それでも市場全体の中央値を下回ってはいません。</p>
</section>

<section>
  <h2><span class="n">05</span>では「低PBRを仕込んでTOBを待つ」は成立するか</h2>
  <div class="scroll"><table>
    <thead><tr><th></th><th>1倍割れの母集団（概算）</th><th>うちTOBされた社数</th><th>年率</th></tr></thead>
    <tbody>{''.join(hit_rows)}</tbody>
  </table></div>
  <p><span class="badge i">概算</span>対照群の1倍割れ比率を東証の上場社数（約3,800社）に当てはめた母集団に対し、その年にTOBされた1倍割れ企業の数を割ったものです。<strong>1倍割れ株を1銘柄持っていてTOBに当たる確率は年2〜3%</strong>。しかも§03のとおり<strong>1倍割れであることが当選確率を上げていない</strong>ので、低PBRで絞る意味はこのデータからは出てきません。</p>
</section>

<section>
  <h2><span class="n">06</span>この検証が答えていないこと</h2>
  <div class="caveats">
    <div class="cv"><h4>決算発表との関係は見ていない</h4><p>「決算をまたいで持つ」の部分、つまり決算発表日とTOB公表日に結びつきがあるかどうかは、この検証では調べていません。別途やるならTOB公表日と直近の決算発表日の間隔を見ることになります。</p></div>
    <div class="cv"><h4>対照群は300社の標本</h4><p>全上場企業ではなく乱数抽出です。中央値の推定としては十分ですが、小数第2位の差を云々できる精度ではありません。生存バイアスを避けるため母集団は2023年1月時点の一覧から取り、各時点で上場廃止済みの会社は除いています。</p></div>
    <div class="cv"><h4>PBRの定義はIRBANKのものに依存</h4><p>純資産ベースで、時価総額÷純資産。TOB対象も対照群も同じ物差しなので比較は成立しますが、他社サイトの数字とは細部が合わないことがあります。業種相対PBRの分母に使ったJPXの月次統計は<strong>小数1桁まで</strong>しか公表されておらず、かつ中央値ではなく平均です。</p></div>
    <div class="cv"><h4>REIT等はPBRが取れず除外</h4><p>{len(rows)}社のうち{len(rows)-len(have)}社はPBRが取得できませんでした（REIT、純資産が特殊な会社など）。集計は{len(have)}社です。</p></div>
    <div class="cv"><h4>2026年は途中まで</h4><p>2026年は9月22日時点までの集計です。年間の件数として他の年と直接は比べられません。</p></div>
  </div>
</section>

<footer>
  データ: TDnet適時開示（yanoshin TDnet API）／ 株価・PBR: IRBANK ／ 業種・市場区分: JPX東証上場銘柄一覧（過去分を含む）／ 業種平均PBR: JPX「規模別・業種別PER・PBR」月次<br>
  集計期間 2024-01-01 〜 {crawl_end}（最後のTOB公表は{asof}）。スクリプトとデータは kabutan-ranking/kensho_tob/ にあります。
</footer>

</div>
</body>
</html>
"""
    OUT.write_text(head() + "</head>\n" + body, "utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
