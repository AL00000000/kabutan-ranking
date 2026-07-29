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

## 注意

- データの取得元は kabutan.jp です。データの正確性は保証しません。投資判断は自己責任でお願いします。
- 市場休場日は更新されません。
