# -*- coding: utf-8 -*-
"""検証結果を docs/kensho_pbr.html (サイトの「仮説検証」タブ) に書き出す。

数値はすべて build_page.collect() で再計算する(手で書き写さない)。
配色・組版は docs/kensho.html の <head> をそのまま使い回すので二重管理にならない。

実行: py render.py
"""
import io
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from build_page import ROOT, WINDOWS, collect, svg_flow, svg_rate  # noqa: E402

DST = ROOT / "docs" / "kensho_pbr.html"


def head_from_kensho(title):
    """配色・組版は docs/kensho.html と共有する(二重管理を避ける)。"""
    src = (ROOT / "docs" / "kensho.html").read_text(encoding="utf-8")
    head = src.split("<head>", 1)[1].split("</head>", 1)[0]
    return re.sub(r"<title>.*?</title>", "<title>" + title + "</title>", head, count=1)


def sign_cls(v):
    return "pos" if v >= 0 else "neg"


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    flows, win, _ = collect()
    g, p = flows["G"], flows["P"]
    y25 = 2025
    A, B, C = (w[3] for w in WINDOWS)
    gr = {w[3]: win[(w[3], "G")] for w in WINDOWS}
    pr = {w[3]: win[(w[3], "P")] for w in WINDOWS}

    # --- 勝者テーブルの行 ---
    wrows = ""
    for w in WINDOWS:
        lab = w[3]
        cells = ""
        for gg in "GPS":
            x = win[(lab, gg)]
            cells += ('<td class="n">{n}</td><td class="n">{t:.2f}</td>'
                      '<td class="n">{d:.0f}</td>').format(
                          n=x["n"], t=x["top5"], d=x["nd"])
        wrows += "<tr><td>{0}</td>{1}</tr>".format(lab, cells)

    # --- 資金フローのテーブル行 ---
    NOTE = {2022: "市場再編", 2023: "PBR要請", 2024: "新NISA"}
    frows = ""
    for y in sorted(g):
        if g[y][3] < 40:
            continue
        badge = ""
        if y in NOTE:
            badge = ' <span class="badge i">' + NOTE[y] + "</span>"
        frows += (
            '<tr{hl}><td>{y}年{b}</td>'
            '<td class="n {c1}">{gi:+,.0f}</td><td class="n {c2}">{gf:+,.0f}</td>'
            '<td class="n">{gr:.1f}%</td>'
            '<td class="n {c3}">{pi:+,.0f}</td><td class="n {c4}">{pf:+,.0f}</td></tr>'
        ).format(hl=' class="hl"' if y == 2023 else "", y=y, b=badge,
                 gi=g[y][0], gf=g[y][1], gr=g[y][2], pi=p[y][0], pf=p[y][1],
                 c1=sign_cls(g[y][0]), c2=sign_cls(g[y][1]),
                 c3=sign_cls(p[y][0]), c4=sign_cls(p[y][1]))

    html = HTML.format(
        head=head_from_kensho("PBR要請とグロース株"),
        A=A, B=B, C=C,
        gA=gr[A]["rate"], gB=gr[B]["rate"], gC=gr[C]["rate"],
        pA=pr[A]["rate"], pC=pr[C]["rate"],
        ratio_a=gr[A]["rate"] / pr[A]["rate"], ratio_c=pr[C]["rate"] / gr[C]["rate"],
        g_ind=g[y25][0], p_fgn=p[y25][1],
        gndA=gr[A]["nd"], gndB=gr[B]["nd"], gndC=gr[C]["nd"],
        pndA=pr[A]["nd"], pndC=pr[C]["nd"],
        pnA=pr[A]["n"], pnC=pr[C]["n"],
        prunA=pr[A]["run"], prunC=pr[C]["run"],
        chart_rate=svg_rate(win),
        chart_g=svg_flow(flows, "G", "グロース市場の差引き"),
        chart_p=svg_flow(flows, "P", "プライム市場の差引き"),
        wrows=wrows, frows=frows)

    DST.write_text(html, encoding="utf-8")
    print("wrote {0} ({1:,} bytes)".format(DST, len(html)))
    return 0


HTML = """<!doctype html>
<html lang="ja" data-theme="dark">
<head>{head}</head>
<body>
<div class="wrap">

<header class="top">
  <div class="eyebrow">仮説検証 / 2023-03-31 TSE</div>
  <h1>PBR是正要請のあと、<br>グロース株に何が起きたのか</h1>
  <p class="sub">「プライムの株主還元が厚くなって個人の資金がグロースに入らなくなり、
  決算のときしか動かなくなった」という仮説を、日足10年ぶんと、JPXが公表している
  市場別・投資部門別の売買実績で検証した。結論は<b>結果は確認、原因は否定</b>。</p>

  <div class="cards">
    <div class="card" style="--c:var(--brass)">
      <div class="lbl">3年で株価2倍になった割合<br>グロース系</div>
      <div class="big" style="font-size:25px">{gA:.1f}% → {gC:.1f}%</div>
      <div class="foot">{A} → {C}</div>
    </div>
    <div class="card" style="--c:var(--slate)">
      <div class="lbl">同・プライム系<br>（完全に逆転した）</div>
      <div class="big" style="font-size:25px">{pA:.1f}% → {pC:.1f}%</div>
      <div class="foot">{A} → {C}</div>
    </div>
    <div class="card" style="--c:var(--pos)">
      <div class="lbl">個人のグロース買い越し<br>（抜けるどころか増えた）</div>
      <div class="big">{g_ind:+,.0f}</div>
      <div class="foot">億円 / 2025年</div>
    </div>
    <div class="card" style="--c:var(--nikkei)">
      <div class="lbl">海外投資家のプライム買い越し<br>（買ったのはこちら）</div>
      <div class="big">{p_fgn:+,.0f}</div>
      <div class="foot">億円 / 2025年</div>
    </div>
  </div>
</header>

<section>
  <h2><span class="n">01</span>仮説を3つに分けた</h2>
  <p class="lead">元の仮説はひと続きの因果だが、検証可能性がまったく違う3つの主張でできている。
  分けないと、どれが確かめられてどれが確かめられていないのか分からなくなる。</p>
  <div class="steps">
    <div class="step"><h4>A　要請でプライムの株主還元が厚くなった</h4>
      <p>実測可能。方向としてはほぼ確実だが、今回の直接の検証対象ではない。</p></div>
    <div class="step"><h4>B　その結果、個人の資金がグロースに入らなくなった</h4>
      <p><b>価格から推測する必要がない。</b>JPXが市場別・週次で投資部門別の売買実績を
      公表していて、グロース市場で個人がいくら買い越したかがそのまま読める。
      ここを価格の動きから推論しようとするのが、そもそもの遠回りだった。</p></div>
    <div class="step"><h4>C　だから決算でしか動かなくなった</h4>
      <p>日足で測れる。ただし後述のとおり、<b>「決算に集中したか」は決算発表日の
      データなしには原理的に測れない</b>ことが検証の途中で分かった。</p></div>
  </div>
  <div class="note"><strong>因果そのものは、この設計では証明できない。</strong>
  2023年3月の前後には日銀のYCC修正・マイナス金利解除（2024-03）・新NISA開始（2024-01）・
  グロース市場の上場維持基準の見直し議論が重なっていて、要請の効果だけを取り出せない。
  到達できるのは「現象が起きたか」と「タイミングが整合的か」まで。</div>
</section>

<section>
  <h2><span class="n">02</span>母集団の作り方でほぼ決まる</h2>
  <p>JPXの上場銘柄一覧は<b>現時点のスナップショットしか配っていない</b>。
  これをそのまま使うと、グロースからプライムへ市場変更した銘柄——つまり成功した会社——が
  母集団から抜ける。抜けた集団を見て「グロースは上がらなくなった」と言うのは同語反復になる。</p>
  <p>そこで Wayback Machine から過去のマスタを5時点ぶん復元して所属履歴を作り、
  <b>各期間の期首時点の市場区分でコホートを固定</b>した。市場変更しても追跡を続けている。</p>
  <div class="scroll"><table>
    <thead><tr><th>2023年1月時点のグロース 513銘柄のその後</th><th>銘柄数</th><th>割合</th></tr></thead>
    <tbody>
      <tr><td>グロースのまま</td><td class="n">416</td><td class="n">81.1%</td></tr>
      <tr class="hl"><td>スタンダードへ市場変更</td><td class="n">37</td><td class="n">7.2%</td></tr>
      <tr class="hl"><td>プライムへ市場変更</td><td class="n">17</td><td class="n">3.3%</td></tr>
      <tr><td>消滅（上場廃止・TOB等）</td><td class="n">43</td><td class="n">8.4%</td></tr>
    </tbody></table></div>
  <p class="small">現在の市場区分だけで母集団を切ると、この18.9%（97銘柄）が丸ごと落ちる。
  2016年まで遡るとさらに深刻で、2016年8月のマザーズ系277銘柄のうち、10年後もグロース系に
  残っているのは39.7%しかない。</p>
</section>

<section>
  <h2><span class="n">03</span>結果1 ── 勝者の頭数が逆転した</h2>
  <p class="lead">各3年窓で、その窓の間に株価が2倍以上になった銘柄の割合。
  選抜は期間ごとに独立して行っている（現時点から振り返って勝者を選ぶと後知恵になるため）。</p>
  <figure>
    <div class="legend">
      <span><i style="background:var(--brass)"></i>グロース系</span>
      <span><i style="background:var(--slate)"></i>プライム系</span>
      <span><i style="background:var(--teal)"></i>スタンダード系</span>
    </div>
    {chart_rate}
    <figcaption>期首時点の市場区分で固定したコホート。市場変更した銘柄も追跡を継続している。</figcaption>
  </figure>
  <p>{A}はグロースがプライムの<b>{ratio_a:.1f}倍</b>の確率で2倍になっていた。
  {C}はプライムがグロースの<b>{ratio_c:.1f}倍</b>。完全にひっくり返っている。
  体感されていた「グロースが上がらない」は、この意味では正しい。</p>
</section>

<section>
  <h2><span class="n">04</span>結果2 ── 個人の資金は抜けていない</h2>
  <p class="lead">ここが仮説の中心であり、そして<b>実測と食い違った</b>ところ。</p>
  <figure>
    <div class="legend">
      <span><i style="background:var(--slate)"></i>個人</span>
      <span><i style="background:var(--nikkei)"></i>海外投資家</span>
    </div>
    {chart_g}
    <figcaption><b>グロース市場</b>の売買差引き（縦軸は億円、買い越しが上）。
    2022年3月までは東証マザーズ、2022年4月からは東証グロース。</figcaption>
  </figure>
  <figure>
    {chart_p}
    <figcaption><b>プライム市場</b>（2022年3月までは東証一部）。
    縦軸は兆円。グロースとは桁が2つ違う点に注意。</figcaption>
  </figure>
  <div class="scroll"><table>
    <thead><tr><th>年</th><th>G 個人</th><th>G 海外</th><th>G 個人比率</th>
      <th>P 個人</th><th>P 海外</th></tr></thead>
    <tbody>{frows}</tbody></table></div>
  <p class="small">単位は億円、買い越しが+。週次データを年で合計している。通年ぶんのデータが揃わない2026年は、グラフ・表とも除外した。</p>
  <p><b>個人はグロースを買い越し続けている。</b>しかも金額は減るどころか増えていて、
  総売買代金で正規化しても比率は上がっている。個人比率も52〜57%で安定していて低下していない。
  一方で<b>個人はプライムを大幅に売り越している</b>。</p>
  <p>プライムを買ったのは<b>海外投資家</b>だった。2015〜2022年はほぼ売り越しだったのが、
  2023年に転じて以降は一貫した買い越しになっている。グロースでは逆に海外が売り手で、
  それを個人が引き受ける形になっている。個人が買い越しているのに株価が下がるのは、
  海外の売りを吸収しているためで、矛盾しない。</p>
  <div class="note">つまり「個人の資金がグロースから株主還元銘柄へ移った」のではなく、
  <strong>「海外投資家がプライムに入りグロースから抜けた。個人はその逆をやって買い支えたが、
  足りなかった」</strong>というのが実際の需給。仮説Bは否定された。</div>
</section>

<section>
  <h2><span class="n">05</span>結果3 ── 値動きの質はグロース側では変わっていない</h2>
  <p class="lead">各期間の勝者だけを取り出して、上昇がどれだけ少数の日に偏っていたかを見る。
  「実質何日」は、上昇の大きい日から順に足していって3年間の累積リターンに届くまでの日数
  （約730営業日中）。</p>
  <div class="scroll"><table>
    <thead><tr><th rowspan="2">期間</th>
      <th colspan="3">グロース系</th><th colspan="3">プライム系</th><th colspan="3">スタンダード系</th></tr>
      <tr><th>勝者</th><th>上位5日</th><th>実質何日</th>
        <th>勝者</th><th>上位5日</th><th>実質何日</th>
        <th>勝者</th><th>上位5日</th><th>実質何日</th></tr></thead>
    <tbody>{wrows}</tbody></table></div>
  <p><b>グロースの勝者は昔から{gndA:.0f}日前後で上昇していた。</b>
  {A}が{gndA:.0f}日、{C}が{gndC:.0f}日でほとんど変わらない。
  最も集中していたのは{B}（{gndB:.0f}日）で、要請後ではない。
  グロース側には、要請のタイミングと結びつく変化が見当たらない。</p>
  <p>変わったのはプライムで、勝者が{pnA}社→{pnC}社に増えたうえ、上昇の仕方が
  {pndA:.0f}日→{pndC:.0f}日と<b>より分散した</b>。
  連騰の平均日数も {prunA:.2f}日→{prunC:.2f}日 と伸びている。</p>
  <div class="note"><strong>体感の位置がずれていた可能性が高い。</strong>
  「じりじり上がる銘柄が消えた」ように見えるのは、グロースで起きた変化ではなく、
  グロースに元々そういう銘柄が少なく、プライム側でそれが増えたことの反映と読める。
  <span class="badge i">解釈</span>これは測定結果からの解釈であって、因果の主張ではない。</div>
</section>

<section>
  <h2><span class="n">06</span>測れなかったこと</h2>
  <p class="lead">検証の途中で、当初使うつもりだった指標が<b>目的に対して無効</b>だと分かった。
  結果と同じくらい重要なので記録しておく。</p>
  <p>「絶対値の大きい上位N日」でリターンを分ける方式（集中度、イベント／非イベント内訳）は、
  <b>日次リターンの順序を入れ替えても値がまったく変わらない</b>。
  上位N日の選び方が集合演算なので当然で、実際にシャッフルして確認した。</p>
  <div class="scroll"><table>
    <thead><tr><th>系列</th><th>集中度</th><th>イベント日リターン</th>
      <th>分散比(20日)</th><th>連騰平均</th></tr></thead>
    <tbody>
      <tr class="hl"><td>原系列</td><td class="n">0.0831</td><td class="n">-0.0762</td>
        <td class="n">0.697</td><td class="n">1.903</td></tr>
      <tr><td>シャッフル1</td><td class="n">0.0831</td><td class="n">-0.0762</td>
        <td class="n">0.408</td><td class="n">1.735</td></tr>
      <tr><td>シャッフル2</td><td class="n">0.0831</td><td class="n">-0.0762</td>
        <td class="n">1.119</td><td class="n">1.844</td></tr>
      <tr><td>シャッフル3</td><td class="n">0.0831</td><td class="n">-0.0762</td>
        <td class="n">0.907</td><td class="n">2.070</td></tr>
    </tbody></table></div>
  <p>つまりこれらは<b>リターン分布の裾の形を要約しているだけ</b>で、
  「いつ動いたか」の情報をひとつも持っていない。
  順序に依存する＝タイミングを測れるのは<b>分散比と連騰日数だけ</b>だった。</p>
  <p>したがって<b>「決算にリターンが集中するようになったか」は、統計的なジャンプの定義では
  原理的に判定できない</b>。決算発表日そのもののデータが要る。これは未着手。</p>
  <p>なお、タイミングを測れる分散比のほうで見ると、トレンド持続性の低下は
  グロース（0.634→0.614）よりプライム（0.732→0.658）のほうが大きく、仮説とは逆向きだった。</p>
</section>

<section>
  <h2><span class="n">07</span>この数字を割り引くべき理由</h2>
  <div class="caveats">
    <div class="cv"><h4>消滅した銘柄が入っていない</h4>
      <p>2023年1月のグロースコホートの8.4%（43銘柄）は、株価データの取得元が上場廃止銘柄を
      返さないため分析に含められない。TOBによる高値での退出と経営難による廃止が混在していて、
      除外がリターン分布をどちらに歪めるかは事前には言えない。</p></div>
    <div class="cv"><h4>分散比は市場間で比較できない</h4>
      <p>ビッド・アスク・バウンスが1日分散を膨らませるため、流動性の低い銘柄ほど分散比が
      低く出る。使えるのは同一グループ内の時系列変化だけで、水準の比較は無効。</p></div>
    <div class="cv"><h4>市場全体の急落日が混入している</h4>
      <p>2024年8月5日の暴落のような日は、ほぼ全銘柄で「絶対値上位の日」になる。
      銘柄固有のイベントを見るには、市場成分を除いた残差リターンで測り直す必要がある。</p></div>
    <div class="cv"><h4>マザーズとグロースは厳密には同じでない</h4>
      <p>2022年4月の市場再編をまたぐ比較では、マザーズをグロースの前身として扱っている。
      JASDAQがスタンダードとグロースに分かれた分の不連続は残る。</p></div>
    <div class="cv"><h4>因果は示せていない</h4>
      <p>同時期に日銀の政策変更・新NISA・上場維持基準の見直し議論が重なっている。
      示せたのは現象と需給の実態までで、PBR要請がその原因だとは言えない。</p></div>
  </div>
</section>

<footer>
  データ出所 ── 日足: Yahoo Finance（10年・分割調整済み、3,711銘柄）／
  市場区分の履歴: JPX「東証上場銘柄一覧」5時点（Wayback Machine 経由で復元）／
  投資部門別売買状況: JPX 週次589ファイル・2015-01〜2026-07（同上。本家は直近5週のみ公開）。<br>
  集計スクリプトは <span class="kv">kabutan-ranking/pbr_growth/</span>。
  未着手 ── 決算発表日を構築して、上昇が集中している日が決算日なのかを判定すること。
</footer>

</div>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
