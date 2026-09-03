# -*- coding: utf-8 -*-
"""株マップ.com の「全市場 過去1週間リターンランキング」を毎週金曜に記録する。

上昇側(d=d)・下落側(d=a)それぞれ返ってくる全件(各300位まで)を残す。

画面 https://jp.kabumap.com/servlets/kabumap/Action?SRC=stockRanking/base&ind=rtn1w&exch=all&d=d
は表の中身をJavaScriptで後から描画するので、HTMLを読んでも銘柄は取れない。
実データは kmTable の裏エンドポイント get_page_data が返しており、
**ランキングの条件(指標・市場・昇降順)はURLではなくセッションが持っている**。
そのため必ず「ランキング画面をGETしてセッションを作る → 同じCookieでget_page_dataを叩く」
順序で取得する。1リクエストで300位まで返る(画面の30件/頁は表示上の区切りにすぎない)。

出力:
  docs/data_weekly/YYYY-MM-DD.json … 基準日ごとの上昇側・下落側それぞれ全件
  docs/data_weekly/index.json      … 基準日一覧(新しい順)
"""
import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "docs" / "data_weekly"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HOST = "https://jp.kabumap.com/servlets/kabumap/"
PAGE = HOST + "Action?SRC=stockRanking/base&ind=rtn1w&exch=all&d={d}"
DATA = HOST + "Action?SRC=common/kmTable/get_page_data&localeDate={ts}"
TOP_N = None      # None なら返ってきた全件(=各方向300位まで)を記録する

# 「（ファクター値計算日付：2026/09/02）（騰落率・売買代金日時：2026/09/03 11:16）」
CAP_RE = re.compile(r"ファクター値計算日付：(\d{4})/(\d{2})/(\d{2})")
ASOF_RE = re.compile(r"騰落率・売買代金日時：(\d{4})/(\d{2})/(\d{2})\s*(\d{2}:\d{2})")

# 1行 = [順位, コード(aタグ), 会社名(aタグ), 業種(span), 株価, 前日比, 前日比%,
#        1週間RTN, 売買代金, 25日乖離, PER, PBR]
ROW_RE = re.compile(
    r"\['(\d+)'\s*\n"
    r",'<a href=[^>]*codetext=([0-9A-Z]+)\\\"[^>]*>[^<]*</a>'\s*\n"
    r",'<a href=[^>]*>([^<]*)</a>'\s*\n"
    r",'<span[^>]*>([^<]*)</span>'\s*\n"
    r",'([^']*)'\s*\n,'([^']*)'\s*\n,'([^']*)'\s*\n"
    r",'([^']*)'\s*\n,'([^']*)'\s*\n,'([^']*)'\s*\n"
    r",'([^']*)'\s*\n,'([^']*)'")


def num(s):
    """'3,585.0' -> 3585.0 / '+17.9' -> 17.9 / 'NA' や空 -> None"""
    s = (s or "").replace(",", "").replace("+", "").strip()
    if not s or s in ("NA", "-", "－"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch(direction):
    """direction='d'(上昇順) / 'a'(下落順)。(本文, 基準日, 株価時点) を返す。"""
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", UA)]
    page = PAGE.format(d=direction)

    with op.open(page, timeout=30) as r:      # セッションに条件を持たせる
        r.read()

    ts = urllib.parse.quote(datetime.now().strftime("%Y/%m/%d %H:%M:%S"))
    req = urllib.request.Request(
        DATA.format(ts=ts),
        headers={"X-Requested-With": "XMLHttpRequest", "Referer": page})
    with op.open(req, timeout=30) as r:
        body = r.read().decode("cp932", errors="replace")

    m = CAP_RE.search(body)
    if not m:
        raise RuntimeError("CAPTIONから基準日を取得できませんでした(仕様変更の可能性)")
    base = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    a = ASOF_RE.search(body)
    asof = f"{a.group(1)}-{a.group(2)}-{a.group(3)} {a.group(4)}" if a else None
    return body, base, asof


def parse(body):
    out = []
    for m in ROW_RE.finditer(body):
        g = m.groups()
        out.append({
            "rank": int(g[0]), "code": g[1], "name": g[2].strip(), "sector": g[3].strip(),
            "price": num(g[4]), "chg_pct": num(g[6]), "rtn1w": num(g[7]),
            "value": num(g[8]), "spr25": num(g[9]), "per": num(g[10]), "pbr": num(g[11]),
        })
    return out


def main():
    body_u, base_u, asof = fetch("d")
    up = parse(body_u)[:TOP_N] if TOP_N else parse(body_u)
    body_d, base_d, _ = fetch("a")
    down = parse(body_d)[:TOP_N] if TOP_N else parse(body_d)

    least = TOP_N or 250
    if len(up) < least or len(down) < least:
        print(f"ERROR: 上昇{len(up)}件 / 下落{len(down)}件 しか抽出できませんでした"
              "(仕様変更の可能性)", file=sys.stderr)
        sys.exit(1)
    if base_u != base_d:
        print(f"ERROR: 上昇側と下落側で基準日が違います({base_u} / {base_d})。"
              "取得中に日付が変わった可能性があるので中止します。", file=sys.stderr)
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "base": base_u,        # ファクター値計算日付(=1週間リターンの計算基準日)
        "asof": asof,          # 株価・売買代金の時点
        "fetched": datetime.now().isoformat(timespec="seconds"),
        "n": len(up),
        "up": up, "down": down,
    }
    path = OUT / f"{base_u}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")

    dates = sorted((p.stem for p in OUT.glob("????-??-??.json")), reverse=True)
    (OUT / "index.json").write_text(
        json.dumps({"updated": dates[0], "dates": dates}, ensure_ascii=False),
        encoding="utf-8")

    wd = "月火水木金土日"[datetime.strptime(base_u, "%Y-%m-%d").weekday()]
    print(f"基準日 {base_u}({wd}) / 株価時点 {asof} / "
          f"上昇{len(up)}・下落{len(down)}銘柄 -> {path.name}", file=sys.stderr)
    print(f"  上昇1位 {up[0]['name']}({up[0]['code']}) {up[0]['rtn1w']:+.2f}% / "
          f"下落1位 {down[0]['name']}({down[0]['code']}) {down[0]['rtn1w']:+.2f}%",
          file=sys.stderr)
    if wd != "金":
        print(f"注意: 基準日が金曜ではなく{wd}曜です。"
              "サイト側がまだ金曜分を反映していない可能性があります。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
