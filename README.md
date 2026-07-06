# 売買代金ランキング (東証)

[Kabutan](https://kabutan.jp/warning/trading_value_ranking) の売買代金ランキング上位60銘柄を平日ごとに取得したデータです。

## データ

- [output/](output/) … 日次のランキングCSV (`ranking_YYYY-MM-DD.csv`, UTF-8)
  - 順位 / 順位変動(前営業日比) / コード / 銘柄名 / 市場 / 株価 / 前日比 / 売買代金(百万円) / 売買代金前日比 / PER / PBR / 利回り
- [history/](history/) … 比較計算用の生データ (JSON)

順位変動の表記: `↑n`(n位上昇) / `↓n`(n位下降) / `→`(変わらず) / `NEW`(前営業日圏外から登場)

## 取得スクリプト

[fetch_ranking.py](fetch_ranking.py) — Python標準ライブラリのみで動作します。

```
py fetch_ranking.py
```

## 注意

- データの取得元は kabutan.jp です。データの正確性は保証しません。投資判断は自己責任でお願いします。
- 市場休場日は更新されません。
