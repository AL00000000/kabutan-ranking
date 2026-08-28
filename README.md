# 売買代金ランキング (東証)

[Kabutan](https://kabutan.jp/warning/trading_value_ranking) の売買代金ランキング上位500銘柄を平日ごとに取得したデータです。

**📊 閲覧用サイト: https://al00000000.github.io/kabutan-ranking/**
(日付切替・列ソート・銘柄検索ができます)

## データ

- [docs/data/](docs/data/) … 閲覧用サイトが読み込む日次JSON
- [output/](output/) … 日次のランキングCSV (`ranking_YYYY-MM-DD.csv`, UTF-8)
  - 順位 / 順位変動(前営業日比) / コード / 銘柄名 / 市場 / 株価 / 前日比 / 売買代金(百万円) / 売買代金前日比 / PER / PBR / 利回り
- [history/](history/) … 比較計算用の生データ (JSON)

順位変動の表記: `↑n`(n位上昇) / `↓n`(n位下降) / `→`(変わらず) / `NEW`(前営業日圏外から登場)

## 取得スクリプト

[fetch_ranking.py](fetch_ranking.py) — Python標準ライブラリのみで動作します。

```
py fetch_ranking.py
```

## 52週新高値ブレイク

売買代金10億円以上の東証銘柄(東P/東S/東G)のうち、その日に52週新高値を更新した銘柄。
既定表示は「前回新高値から6営業日以上あいた銘柄」だけで、毎日のように新高値を更新している
継続銘柄は画面のトグルで出す。

- [fetch_newhigh.py](fetch_newhigh.py) … 平日16:20に実行(`\StockAutomation\newhigh-break`)
- [docs/data_newhigh/](docs/data_newhigh/) … 日次JSON
- 判定は**高値ベース**(当日高値 > 前日までの52週間の最高値)。同値で並んだだけの日は更新に数えない
- 母集団は株探の売買代金ランキング16ページ(16:00現在の確定値)、日足はYahoo Finance
- `cache_bars/` に日足をキャッシュするため、同じ日に取り直しても数十秒で終わる

```
py fetch_newhigh.py
py fetch_newhigh.py --codes 4722   # 1銘柄だけ判定を確認する
```

## 出来高52週最低

出来高が52週間の最低を更新した銘柄。新高値タブとは逆に「動かなくなった銘柄」を拾い、
出来高の枯れを相場の転換点のサインとして見るためのもの。

- [fetch_lowvolume.py](fetch_lowvolume.py) … 平日16:45に実行(`\StockAutomation\lowvolume-screen`)
- [docs/data_lowvolume/](docs/data_lowvolume/) … 日次JSON
- 判定は2種類。**単日**(当日の出来高が直近52週のどの日より少ない)と
  **5日平均**(5日移動平均が直近52週のどの5日平均より少ない)。枯れの判断には5日平均のほうが向く
- 母集団は新高値と同じ売買代金10億円以上の東証銘柄に**監視銘柄リスト全銘柄**を足したもの。
  出来高が枯れた銘柄は売買代金も落ちてランキングから消えるため、監視銘柄は圏外でも必ず判定する
- **ストップ高・安の気配日(高値==安値の日)は除外**している。買い気配のストップ高は誰も買えないので
  出来高が極端に小さくなるが、これは閑散ではなく過熱で意味が逆になるため。
  過去の気配日も比較の窓から除く(除かないと異常に低い出来高が52週最小として居座り、
  本物の閑散日が二度と最低を更新できなくなる)
- 日足キャッシュ(`cache_bars/`)は fetch_newhigh.py と共有する。newhigh-break(16:20)の後に走るので、
  ランキング分はキャッシュが効き、Yahooへの取得は監視銘柄のはみ出し分だけで済む

```
py fetch_lowvolume.py
py fetch_lowvolume.py --codes 7203   # 1銘柄だけ判定を確認する
py fetch_lowvolume.py --pages 4      # 母集団を狭くして軽く試す
```

## 期間騰落率

好きな期間を選んで、その期間の上昇率ランキングを出すタブ。既定は2026-06-23から最新営業日まで。

- [fetch_period.py](fetch_period.py) … 平日17:10に実行(`\StockAutomation\period-returns`)
- [docs/data_period/prices.json](docs/data_period/) … 全銘柄の6か月ぶんの終値(1ファイル・約1MB)。
  期間の計算はブラウザ側でやるので、開始日・終了日を変えても再取得は起きない
- 母集団は **docs/data/ に保存した売買代金ランキング全日分の和集合**(現在約960銘柄)。
  上位500位は日によって顔ぶれが変わるので、和集合にすることで「期間の途中まで上位だったが今は圏外」
  の銘柄も拾える
- 株価はYahoo Financeの**分割調整済み終値**。毎回6か月ぶんを取り直すのは、分割・併合で過去の調整値が
  後から変わるのを自動で取り込むため
- TOPIX(1306) / 日経225(1321) / グロース250(2516) を同時に取得し、「対TOPIX」列(超過リターン)と
  カードの指数騰落率に使う
- タブ見出しの最終更新日判定は軽い `index.json` を見る(prices.json は1MB近いため)

```
py fetch_period.py
py fetch_period.py --no-fetch   # 取得せずキャッシュから prices.json を作り直す
```

## 監視銘柄リスト (開発中)

フォルダで階層分けした監視銘柄リストと、その日足チャート一覧。

- [docs/data_watch/watchlist.json](docs/data_watch/watchlist.json) … リスト定義。第1階層がリスト(狙い株/保有…)、その下にフォルダを任意の深さで入れ子にできる
- [docs/data_watch/codes/](docs/data_watch/codes/) … 銘柄ごとの日足(約1年分, 1銘柄あたり約11KB)
- [docs/data_watch/summary.json](docs/data_watch/summary.json) … 全銘柄の最新値と騰落率(当日/1週/1ヶ月/3ヶ月/6ヶ月/1年/年初来)
- [docs/data_watch/lines.json](docs/data_watch/lines.json) … 銘柄ごとの「意識するライン」

### リストの編集

```
py watchlist.py ls
py watchlist.py add 6146 7735 --to 狙い株/半導体/SPE
py watchlist.py mv 6146 --from 狙い株/半導体/SPE --to 保有/主力
py watchlist.py rm 6146 --from 保有/主力
py watchlist.py mkdir 狙い株/半導体/SPE
py watchlist.py rename 狙い株/半導体 半導体関連
py watchlist.py mklist 短期
py watchlist.py line add 6146 55000 --label 前回高値
```

### 株価の取得

```
py fetch_watch.py --init        # 初回: 全銘柄1年分
py fetch_watch.py               # 差分更新
py fetch_watch.py --codes 6146  # 銘柄を追加した直後だけ
```

保存済みデータの最終日と今日の差から取得レンジを自動で広げるため、数日実行できなくても
次回実行時に穴が埋まる。[daily_watch.py](daily_watch.py) をタスクスケジューラで平日16:30に
実行する想定で、土曜は自動的に1年分を取り直す(分割・併合の是正)。

## 信用需給分析・宇宙銘柄（手動収集）

松井証券アプリの「銘柄詳細 → 売買分析 → 過去情報」から
売買内訳(現物買/新規買/返済買/現物売/新規売/返済売/空売り、千株)を1日ずつ読み取って集計したもの。
自動取得ではなくアプリ画面からの手動読み取りのため、銘柄・月を足したいときだけ手で読み取って追加する。

生データは1つで、そこから**2つのタブ**を作っている(`build_jukyu.py` の `DATASETS`)。

| タブ | 銘柄 | 月 | 出力 |
| --- | --- | --- | --- |
| 信用需給分析 | 全20銘柄 | 2026年6月・7月(各22営業日) | `docs/data_jukyu/analysis.json` |
| 宇宙銘柄 | 宇宙専業5銘柄 | 2026年4月(21) / 5月(18) / 6月(22) + 4〜6月累計 | `docs/data_uchu/analysis.json` |

### 追加のしかた

1. `docs/data_jukyu/raw/<コード>_<YYYY-MM>.json` に日次の生データ(千株)を保存
2. `docs/data_jukyu/stocks.json` に銘柄(発行済株式数)を追記
3. `python build_jukyu.py` … 全日検算した上で両方の `analysis.json` を再生成する

読み取りの手順と落とし穴、指標の読み方は `C:\Users\yt\shinyo-jukyu-request-template.md` にまとめてある
(新しいチャットにはこのファイルのパスを渡すだけでよい)。**月や銘柄の構成を変えるとき**は
`build_jukyu.py` の `DATASETS` と `docs/index.html` の `JK_VIEWS` を対で直すこと
(表の描画は2タブで `makeJukyuView` を共有しているので、直すのは設定だけでよい)。

- [build_jukyu.py](build_jukyu.py) … 検算 + 指標計算 + JSON生成
- [docs/data_jukyu/raw/](docs/data_jukyu/raw/) … 銘柄×月ごとの生データ(千株)。これが一次データ
- [docs/data_jukyu/analysis.json](docs/data_jukyu/analysis.json) … 生成物。手で編集しない。月次集計(20銘柄×2ヶ月)と日次データ(880行)
- [docs/data_uchu/analysis.json](docs/data_uchu/analysis.json) … 同上(5銘柄×3ヶ月+累計、日次305行)
- ネットの定義 … 現物ネット = 現物買 − 現物売 / 買い残ネット = 新規買 − 返済売 /
  売り残ネット = 空売り + 新規売 − 返済買
- 検算 … 日々の「買い合計 = 売り合計 = 出来高」と累計の「現物ネット + 買残ネット − 売残ネット = 0」を
  全20銘柄 × 44営業日(宇宙5銘柄はさらに4月・5月の39営業日)で確認済み
- **④買残ネット÷発行済がプラスに大きいほど信用買い残が滞留**＝上値のシコリ。
  ほぼ全銘柄で④はゼロ近傍で、現物の買い越しを受けているのは信用買いではなく売り建て側という構図
- ①現物ネット÷買残ネットは④がゼロ近傍だと分母割れで発散するため、`|④| < 0.05%` の銘柄は `*` 付きの参考値
- 「空売り」列は当日中に買い戻す高頻度売買を多く含むため、**⑤をそのまま信用売り残高の増加としては読めない**

## 注意

- データの取得元は kabutan.jp です。データの正確性は保証しません。投資判断は自己責任でお願いします。
- 市場休場日は更新されません。
