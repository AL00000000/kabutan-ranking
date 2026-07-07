# -*- coding: utf-8 -*-
"""Kabutan 売買代金ランキング (1-10ページ, 50件/頁 = 上位500銘柄) を取得し、
前営業日と比較した順位変動・売買代金変動付きで CSV と公開サイト用 JSON に出力する。

出力:
  history/YYYY-MM-DD.json       … 当日の生データ(翌日以降の比較用)
  output/ranking_YYYY-MM-DD.csv … 当日のランキングCSV(UTF-8)
  docs/data/YYYY-MM-DD.json     … GitHub Pages 用データ
  docs/data/index.json          … 日付一覧(新しい順)
  標準出力に CSV のフルパスを表示する。
"""
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
HISTORY = BASE / "history"
OUTPUT = BASE / "output"
DOCS_DATA = BASE / "docs" / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
# shared_perpage=50 Cookie で1ページ50件表示になる(サイトのsetPageCount実装より)
COOKIE = "shared_perpage=50"
URL = ("https://kabutan.jp/warning/trading_value_ranking"
       "?market=0&capitalization=-1&dispmode=normal&stc=&stm=0&page={page}")
PAGES = 10  # 50件 x 10ページ = 上位500銘柄

# ページ上部の「YYYY年MM月DD日 / HH:MM現在」表記(データ時点)
AS_OF_RE = re.compile(r'(\d{4})年(\d{2})月(\d{2})日</li>\s*<li>(\d{2}:\d{2})現在')

# 値セル: <td>151.1</td> / <td><span class="up">+2.1</span></td> /
# <td><span class="rednodata">－</span></td> / <td><span>+1.41</span>%</td> をすべて許容。
# [^<]* なのでセル境界(タグ)は越えられない。
def _cell(group: str) -> str:
    return rf'<td[^>]*>\s*(?:<span[^>]*>)?(?P<{group}>[^<]*)(?:</span>)?\s*%?\s*</td>'

# アイコンセル: 中身は何でもよいが </td> を越えない(隣のセルを飲み込むと行がズレるため)
_ICON = r'(?:(?!</td>)[\s\S])*</td>'
_SKIP = r'<td[^>]*>\s*(?:<span[^>]*>)?[^<]*(?:</span>)?\s*</td>'  # 前日終値(未使用)

ROW_RE = re.compile(
    r'<tr>\s*'
    r'<td class="tac"><a href="/stock/\?code=(?P<code>[0-9A-Z]+)">[0-9A-Z]+</a></td>\s*'
    r'<th scope="row" class="tal">(?P<name>[^<]+)</th>\s*'
    r'<td class="tac">(?P<market>[^<]*)</td>\s*'
    r'<td class="gaiyou_icon">' + _ICON + r'\s*'
    r'<td class="chart_icon">' + _ICON + r'\s*'
    + _cell('price') + r'\s*'
    + _SKIP + r'\s*'
    + _cell('change') + r'\s*'
    + _cell('change_pct') + r'\s*'
    + _cell('value') + r'\s*'
    + _cell('per') + r'\s*'
    + _cell('pbr') + r'\s*'
    + _cell('yld'))


def fetch(page: int) -> str:
    req = urllib.request.Request(
        URL.format(page=page),
        headers={"User-Agent": UA, "Cookie": COOKIE})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", errors="replace")


def parse(html: str):
    # ランキング本体のテーブル以降のみを対象にする
    body = html.split("<tbody>", 1)[-1]
    rows = []
    for m in ROW_RE.finditer(body):
        d = {k: v.strip() for k, v in m.groupdict().items()}
        rows.append(d)
    return rows


def main():
    today = date.today().isoformat()
    stocks = []
    as_of = None
    for page in range(1, PAGES + 1):
        html = fetch(page)
        if as_of is None:
            m = AS_OF_RE.search(html)
            if m:
                as_of = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}"
        rows = parse(html)
        if not rows:
            print(f"ERROR: page {page} から行を抽出できませんでした(ページ構造の変更の可能性)",
                  file=sys.stderr)
            sys.exit(1)
        stocks.extend(rows)
        time.sleep(1.5)

    # 念のため重複コードを除去(ページ跨ぎの重複対策)して順位を振り直す
    seen = set()
    stocks = [s for s in stocks if not (s["code"] in seen or seen.add(s["code"]))]
    for i, s in enumerate(stocks, 1):
        s["rank"] = i

    # 前回(直近の過去ファイル)のデータを読み込み
    HISTORY.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    prev_files = sorted(p for p in HISTORY.glob("*.json") if p.stem < today)
    prev_data = {}  # code -> {rank, value}
    prev_date = None
    if prev_files:
        prev_date = prev_files[-1].stem
        prev = json.loads(prev_files[-1].read_text(encoding="utf-8"))
        prev_data = {s["code"]: {"rank": s["rank"], "value": s["value"]} for s in prev}

    def parse_number(s: str) -> float:
        """売買代金や価格のようなカンマ区切りの数値文字列をfloatに変換"""
        try:
            return float(s.replace(",", "").replace("+", "").replace("－", "0"))
        except (ValueError, AttributeError):
            return 0.0

    for s in stocks:
        if s["code"] in prev_data:
            prev = prev_data[s["code"]]
            # 順位変動
            diff = prev["rank"] - s["rank"]
            if diff > 0:
                s["move"] = f"↑{diff}"
            elif diff < 0:
                s["move"] = f"↓{-diff}"
            else:
                s["move"] = "→"
            s["prev_rank"] = prev["rank"]
            s["move_num"] = diff
            s["is_new"] = False

            # 売買代金の変動
            curr_value = parse_number(s["value"])
            prev_value = parse_number(prev["value"])
            if prev_value > 0:
                value_diff = curr_value - prev_value
                value_pct = (value_diff / prev_value) * 100
                s["value_move_pct_num"] = round(value_pct, 1)
                if value_diff > 0:
                    s["value_move"] = f"+{value_diff:,.0f}"
                    s["value_move_pct"] = f"+{value_pct:.1f}%"
                elif value_diff < 0:
                    s["value_move"] = f"{value_diff:,.0f}"
                    s["value_move_pct"] = f"{value_pct:.1f}%"
                else:
                    s["value_move"] = "0"
                    s["value_move_pct"] = "0.0%"
            else:
                s["value_move"] = ""
                s["value_move_pct"] = ""
                s["value_move_pct_num"] = None
        else:
            s["move"] = "NEW" if prev_data else ""
            s["prev_rank"] = ""
            s["move_num"] = None
            s["is_new"] = bool(prev_data)
            s["value_move"] = ""
            s["value_move_pct"] = ""
            s["value_move_pct_num"] = None

    # 当日データを保存(同日再実行時は上書き)
    (HISTORY / f"{today}.json").write_text(
        json.dumps(stocks, ensure_ascii=False, indent=1), encoding="utf-8")

    # 公開サイト(GitHub Pages)用データを保存
    site_payload = {
        "date": today,
        "as_of": as_of,
        "prev_date": prev_date,
        "count": len(stocks),
        "stocks": stocks,
    }
    (DOCS_DATA / f"{today}.json").write_text(
        json.dumps(site_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    dates = sorted((p.stem for p in DOCS_DATA.glob("????-??-??.json")), reverse=True)
    (DOCS_DATA / "index.json").write_text(
        json.dumps({"dates": dates}, ensure_ascii=False), encoding="utf-8")

    # CSV を保存
    csv_path = OUTPUT / f"ranking_{today}.csv"
    header = ["順位", "順位変動", "前日順位", "コード", "銘柄名", "市場",
              "株価", "前日比", "前日比%", "売買代金(百万円)", "売買代金前日比(百万円)", "売買代金変動%", "PER", "PBR", "利回り"]
    lines = [",".join(header)]
    for s in stocks:
        cells = [str(s["rank"]), s["move"], str(s["prev_rank"]), s["code"],
                 s["name"], s["market"], s["price"], s["change"],
                 s["change_pct"], s["value"], s["value_move"], s["value_move_pct"],
                 s["per"], s["pbr"], s["yld"]]
        lines.append(",".join('"' + c.replace('"', '""') + '"' for c in cells))
    csv_path.write_text("\n".join(lines), encoding="utf-8")

    print(str(csv_path))
    print(f"銘柄数: {len(stocks)}, 比較対象: {prev_date or 'なし(初回)'}", file=sys.stderr)


if __name__ == "__main__":
    main()
