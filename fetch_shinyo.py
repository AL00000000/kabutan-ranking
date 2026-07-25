# -*- coding: utf-8 -*-
"""トレーダーズ・ウェブ「信用残の推移」から東証二市場の週次データ全件を取得し、
信用評価損益率チャート(docs/shinyo.html)を再生成する。

出所側は毎週第2営業日までに前週分の申込日を追加する(週1回更新)。
本スクリプトは全ページを取り直して総入れ替えするため、何度走らせても冪等。
新しい申込日が増えていなければ出力は前回と同一になり、
run_task.py 側の「no changes to commit」で自然に空振りする。

出力:
  docs/shinyo.html              … データ埋め込み済みの単体チャートページ
  docs/data_shinyo/index.json   … 申込日一覧(新しい順)と反映日 updated
  docs/data_shinyo/weekly.csv   … 週次の生データ(UTF-8 BOM付き)
"""
import csv
import io
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime
from html import unescape
from pathlib import Path

BASE = Path(__file__).parent
TEMPLATE = BASE / "shinyo_template.html"
OUT_HTML = BASE / "docs" / "shinyo.html"
OUT_DIR = BASE / "docs" / "data_shinyo"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
URL = "https://www.traders.co.jp/margin_derivatives/margin_transition"
# ページ送りはクエリではなくパス末尾(/margin_transition/13)
PAGE_URL = URL + "/{page}"
SLEEP = 1.0          # 出所への負荷を避けるためページ間で待つ
MAX_PAGES = 60       # 週次なので年+1ページ程度しか増えない。暴走止め

# 相場イベント注記(年月キー)
EVENTS = [
    ("2003/04", "ITバブル後の大底"),
    ("2008/10", "リーマンショック"),
    ("2011/03", "東日本大震災"),
    ("2013/01", "アベノミクス"),
    ("2020/03", "コロナショック"),
    ("2024/08", "令和のブラックマンデー"),
]

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
DATE_RE = re.compile(r"^20\d\d/\d\d/\d\d$")
PAGE_LINK_RE = re.compile(r"margin_transition/(\d+)#")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_rows(html):
    """表の行を [申込日, 売残株数, ..., 評価損益率, 信用倍率] の配列で返す。"""
    out = []
    for m in ROW_RE.finditer(html):
        cells = [unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in CELL_RE.findall(m.group(1))]
        if len(cells) >= 11 and DATE_RE.match(cells[0]):
            out.append([c.replace(",", "") for c in cells[:11]])
    return out


def collect():
    """1ページ目からページ数を割り出し、全ページ分の行を日付昇順で返す。"""
    first = fetch(URL)
    pages = PAGE_LINK_RE.findall(first)
    last = min(max((int(p) for p in pages), default=1), MAX_PAGES)
    print(f"pages: {last}")

    rows = parse_rows(first)
    for p in range(2, last + 1):
        time.sleep(SLEEP)
        rows += parse_rows(fetch(PAGE_URL.format(page=p)))

    # 申込日で重複排除(ページ跨ぎの取りこぼし対策)して昇順に
    uniq = {}
    for r in rows:
        uniq.setdefault(r[0], r)
    return [uniq[k] for k in sorted(uniq)]


def tnum(datestr):
    """年を小数で表した時間軸(チャートのX座標用)。"""
    y, m, d = map(int, datestr.split("/"))
    start = date(y, 1, 1)
    days = (date(y + 1, 1, 1) - start).days
    return round(y + (date(y, m, d) - start).days / days, 4)


def resolve_updated(rows):
    """反映日は「新しい申込日が増えたとき」だけ進める。

    毎回 today を入れると、データが増えていない曜日でも差分が出て
    無意味なコミットが走り、サイト側のNEWバッジも誤爆するため。
    """
    latest = rows[-1][0].replace("/", "-")
    old = OUT_DIR / "index.json"
    if old.is_file():
        try:
            prev = json.loads(old.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            prev = {}
        dates = prev.get("dates") or []
        if dates and dates[0] == latest and prev.get("updated"):
            return prev["updated"]
    return date.today().isoformat()


def build_payload(rows, updated):
    weekly, missing = [], []
    for r in rows:
        v = r[9]
        if not v or v in ("-", "--"):
            missing.append(r[0])
            continue
        weekly.append([tnum(r[0]), r[0], float(v)])

    # 月次OHLC: [t, "YYYY/MM", 始値, 高値, 安値, 終値, 週数]
    months = {}
    order = []
    for t, d, v in weekly:
        k = d[:7]
        if k not in months:
            months[k] = []
            order.append(k)
        months[k].append(v)

    monthly = []
    for k in order:
        vs = months[k]
        y, m = map(int, k.split("/"))
        monthly.append([round(y + (m - 1) / 12, 4), k,
                        round(vs[0], 2), round(max(vs), 2),
                        round(min(vs), 2), round(vs[-1], 2), len(vs)])

    by_month = {m[1]: m for m in monthly}
    events = [[by_month[k][0], label] for k, label in EVENTS if k in by_month]

    return {
        "weekly": weekly,
        "monthly": monthly,
        "events": events,
        "meta": {"missing": missing, "updated": updated},
    }


def write_outputs(rows, payload, updated):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tpl = TEMPLATE.read_text(encoding="utf-8")
    if "/*__DATA__*/" not in tpl:
        raise RuntimeError(f"placeholder missing in {TEMPLATE}")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT_HTML.write_text(tpl.replace("/*__DATA__*/", data), encoding="utf-8")

    dates = [r[0].replace("/", "-") for r in reversed(rows)]
    index = {
        "dates": dates,
        "updated": updated,
        "note": "dates=信用残の申込日(週次) / updated=当サイトでデータを反映した日",
    }
    (OUT_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    header = ["申込日", "売残_株数(百万株)", "売残_前週比(%)", "売残_金額(百万円)",
              "売残金額_前週比(%)", "買残_株数(百万株)", "買残_前週比(%)",
              "買残_金額(百万円)", "買残金額_前週比(%)", "評価損益率(%)", "信用倍率"]
    with io.open(OUT_DIR / "weekly.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    rows = collect()
    if not rows:
        print("ERROR: 行を1件も取得できませんでした(サイト構造の変更かネットワーク障害)",
              file=sys.stderr)
        return 1

    # 取りこぼしで既存データを痩せさせないための安全弁
    old = OUT_DIR / "index.json"
    if old.is_file():
        prev = len(json.loads(old.read_text(encoding="utf-8")).get("dates", []))
        if len(rows) < prev:
            print(f"ERROR: 取得 {len(rows)} 件が既存 {prev} 件を下回るため中止", file=sys.stderr)
            return 1

    updated = resolve_updated(rows)
    payload = build_payload(rows, updated)
    write_outputs(rows, payload, updated)

    w = payload["weekly"]
    print(f"週次 {len(w)} 件 ({w[0][1]} 〜 {w[-1][1]}) / 月次 {len(payload['monthly'])} 件")
    print(f"反映日(updated): {updated}")
    if payload["meta"]["missing"]:
        print("評価損益率が欠損: " + ", ".join(payload["meta"]["missing"]))
    print(f"wrote {OUT_HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
