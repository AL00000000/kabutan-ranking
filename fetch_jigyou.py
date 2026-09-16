# -*- coding: utf-8 -*-
"""TDnetの適時開示を全件取得し、「事業整理」に当たるものだけを抜き出す。

LLMは使わない。タイトルの正規表現(jigyou_keywords.json)で絞り、当たったものだけ
PDF本文を落として金額を正規表現で拾う。API課金はゼロ。

**TDnetは31日分しか遡れない**ので、全件は raw_tdnet/ に毎日貯める。ここが資産に
なる(後から条件を変えて過去に遡って再判定できる)。判定結果は docs/data_jigyou/ へ。

  py fetch_jigyou.py                    当日分を取得
  py fetch_jigyou.py --date 2026-09-15  日付指定
  py fetch_jigyou.py --backfill 20      直近20営業日をまとめて(初回用)
  py fetch_jigyou.py --dry-run          ファイルを書かず判定結果だけ表示
  py fetch_jigyou.py --no-pdf           PDFを落とさない(判定の当たり外れを見るだけ)

取得元は yanoshin のTDnet API。落ちていたらTDnet本家のHTMLに自動で切り替える。
"""
import argparse
import datetime as dt
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
RAW = BASE / "raw_tdnet"
OUT = BASE / "docs" / "data_jigyou"
RULES = BASE / "jigyou_keywords.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) kabutan-ranking/jigyou"
API = "https://webapi.yanoshin.jp/webapi/tdnet/list/{ymd}.json?limit=3000"
TDNET = "https://www.release.tdnet.info/inbs/I_list_{page:03d}_{ymd}.html"

KEEP_DAYS = 365          # 「過去1年で何回目」を数える窓
PDF_MAX = 60             # 1日に落とすPDFの上限(事故防止。通常は5件前後)


# ---------------------------------------------------------------- 取得

def http(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch_api(ymd):
    """yanoshin のTDnet API。1日分をまとめて返す。"""
    js = json.loads(http(API.format(ymd=ymd)).decode("utf-8"))
    out = []
    for it in js.get("items", []):
        t = it["Tdnet"]
        url = t.get("document_url") or ""
        # yanoshin のリダイレクタ経由になっているので本家のURLに戻す
        if "rd.php?" in url:
            url = url.split("rd.php?", 1)[1]
        out.append({
            "id": t.get("id"),
            "time": (t.get("pubdate") or "")[11:16],
            "code": (t.get("company_code") or "")[:4],
            "name": (t.get("company_name") or "").strip(),
            "title": (t.get("title") or "").strip(),
            "url": url,
            "market": (t.get("markets_string") or "").strip(),
        })
    return out


ROW = re.compile(
    r'kjTime[^>]*>([^<]*)<.*?kjCode[^>]*>([^<]*)<.*?kjName[^>]*>([^<]*)<'
    r'.*?kjTitle[^>]*><a href="([^"]+)"[^>]*>(.*?)</a>.*?kjPlace[^>]*>([^<]*)<',
    re.S)


def fetch_html(ymd):
    """本家TDnetのHTML。yanoshinが落ちたときの予備。ページ送りを最後まで辿る。"""
    out, page = [], 1
    while page <= 20:
        try:
            html = http(TDNET.format(page=page, ymd=ymd)).decode("utf-8", "replace")
        except urllib.error.HTTPError:
            break
        rows = ROW.findall(html)
        if not rows:
            break
        for tm, code, name, href, title, place in rows:
            out.append({
                "id": href.rsplit("/", 1)[-1].replace(".pdf", ""),
                "time": tm.strip(),
                "code": code.strip()[:4],
                "name": re.sub(r"\s+", "", name),
                "title": re.sub(r"<[^>]+>", "", title).strip(),
                "url": "https://www.release.tdnet.info/inbs/" + href,
                "market": re.sub(r"\s+", "", place),
            })
        page += 1
    return out


def fetch_day(ymd, log=print):
    for name, fn in (("yanoshin API", fetch_api), ("TDnet本家HTML", fetch_html)):
        try:
            items = fn(ymd)
            if items:
                log(f"  {ymd}: {len(items)}件 ({name})")
                return items
            log(f"  {ymd}: {name} は0件")
        except Exception as e:
            log(f"  {ymd}: {name} 失敗 {type(e).__name__}: {e}")
    return []


# ---------------------------------------------------------------- 判定

class Rules:
    def __init__(self, cfg):
        self.excl = [re.compile(p) for p in cfg["exclude"]]
        self.cats = {k: [re.compile(p) for p in v] for k, v in cfg["categories"].items()}
        self.weak = set(cfg.get("weak_categories", []))
        self.confirm = re.compile("|".join(cfg.get("body_confirm", ["(?!x)x"])))


def load_rules():
    with RULES.open(encoding="utf-8") as f:
        return Rules(json.load(f))


def classify(title, rules):
    """当たったカテゴリ名のリストを返す。除外に当たったら空。"""
    if any(p.search(title) for p in rules.excl):
        return []
    return [k for k, pats in rules.cats.items() if any(p.search(title) for p in pats)]


def confidence(cats, rules, body):
    """タイトルだけで言い切れるかを高/中/低で返す。

    「特別損失の計上」のような弱いカテゴリだけに当たった開示は、本文に撤退・閉鎖などの
    語があるかで裏を取る。本文が無い(--no-pdf や取得失敗)ときは判定を保留する。
    """
    if set(cats) - rules.weak:
        return "高"
    if body is None:
        return "保留"
    return "中" if rules.confirm.search(body) else "低"


# ---------------------------------------------------------------- PDFから数値

# 「約1,234百万円」「△500 百万円」「18 百万円」を拾う
AMT = re.compile(r"(?:約)?(?:△|▲|-|−)?\s*[\d,]+(?:\.\d+)?\s*(?:兆円|億円|百万円|千万円|万円|千円|円)")

# 開示の中身を表す見出し。**金額は見出しの前にも後にも来る**(「18百万円が特別利益として
# 計上される」)うえ、PDFでは改行や表組みで分断されるので、見出しから前方に探す正規表現では
# 当たらない。金額を先に全部拾ってから、その金額が含まれる一文に見出しがあるかを見る。
LABELS = [
    "譲渡価額", "譲渡価格", "譲渡予定価格", "譲渡予定価額", "売却価額",
    "譲渡益", "譲渡損", "売却益", "売却損",
    "特別利益", "特別損失", "減損損失", "事業整理損", "事業構造改善費用",
    "関係会社株式評価損", "影響額",
    # 簿価は金額そのものが欲しいわけではなく、「簿価○円(減損損失を計上しているため)」の
    # ような書き方で簿価が減損損失として誤って拾われるのを、より近い見出しで防ぐため。
    "簿価",
]
SCALE_LABELS = ["売上高", "純資産", "総資産", "当期純利益", "営業利益"]

# 見出しと金額がこれ以上離れていたら別物とみなす(空白を潰したあとの字数)。
# **表組みには句点が無い**ので「同じ文か」では判定できない。窓を広く取ると、財務諸表の
# 表で縦に並んだ別の行の数字を拾ってしまう(当期純利益の値を譲渡価額として出す等)。
MAXDIST = 24


def pick_amounts(txt, labels, limit):
    """本文中の金額を、いちばん近い見出しと結びつけて返す。見出しごとに最初の1件だけ。

    金額は見出しの前にも後にも来る(「18百万円が特別利益として計上される」)ので両側を見る。
    近くに見出しが無い金額は捨てる。取りこぼすより誤った見出しを付けるほうが害が大きい。
    """
    flat = re.sub(r"\s+", "", txt)
    out, seen = [], set()
    for m in AMT.finditer(flat):
        s, e = m.start(), m.end()
        best, bestd = None, MAXDIST + 1
        for lb in labels:
            if lb in seen:
                continue
            before = flat.rfind(lb, max(0, s - MAXDIST), s)
            after = flat.find(lb, e, e + MAXDIST)
            for d in ((s - (before + len(lb))) if before >= 0 else None,
                      (after - e) if after >= 0 else None):
                if d is not None and d < bestd:
                    best, bestd = lb, d
        if best:
            seen.add(best)
            out.append({"k": best,
                        "v": m.group(0).replace("▲", "△").replace("−", "△")})
            if len(out) >= limit:
                break
    return out

IMPACT = [
    ("軽微", re.compile(r"(業績に(与える|及ぼす)影響|業績への影響|連結業績への影響)[^。]{0,60}?(軽微|ありません|限定的|僅少)")),
    ("精査中", re.compile(r"(精査中|算定中|確定次第|未定であ|判明次第)")),
]
REASON = re.compile(r"(?:理由|目的|背景|経緯)[^\n]{0,4}\n?([^\n]{20,160})")


def pdf_text(url, pages=3):
    from pypdf import PdfReader
    raw = http(url, timeout=60)
    txt = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages[:pages])
    # 表組みは空白で桁が割れるので、金額の直前の空白だけ潰す
    txt = txt.replace("　", " ")
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"(?<=\d) (?=[\d,])", "", txt)
    return txt


def extract(url, rules):
    """PDFから金額・影響・理由を拾う。失敗しても判定自体は残す。

    戻り値の "body" は確度判定用の本文(JSONには残さない)。
    """
    try:
        txt = pdf_text(url)
    except Exception as e:
        return {"pdf_error": f"{type(e).__name__}", "body": None}

    amounts = pick_amounts(txt, LABELS, 5)
    scale = pick_amounts(txt, SCALE_LABELS, 4)
    impact = next((lb for lb, rx in IMPACT if rx.search(txt)), None)
    rm = REASON.search(txt)
    return {
        "amounts": amounts[:5],
        "scale": scale[:4],
        "impact": impact,
        "excerpt": re.sub(r"\s+", " ", rm.group(1)).strip()[:150] if rm else None,
        "chars": len(txt),
        "body": txt,
    }


# ---------------------------------------------------------------- 保存

def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def save_raw(ymd, items):
    """全件アーカイブ。取得元が一部落とすことがあるのでidでマージして減らさない。"""
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{ymd}.json"
    old = load(path, {}) or {}
    merged = {i["id"]: i for i in old.get("items", [])}
    for i in items:
        merged[i["id"]] = i
    rows = sorted(merged.values(), key=lambda r: (r["time"], r["code"]), reverse=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"date": ymd, "items": rows}, f, ensure_ascii=False, separators=(",", ":"))
    return rows


def repeat_counts(date, codes):
    """過去1年に同じ会社が何回この網に掛かったかを数える(「進んでいる」の代用)。"""
    cnt = {c: 0 for c in codes}
    for p in sorted(OUT.glob("20*.json")):
        d = p.stem
        if d >= date or (dt.date.fromisoformat(date) - dt.date.fromisoformat(d)).days > KEEP_DAYS:
            continue
        for it in (load(p, {}) or {}).get("items", []):
            if it["code"] in cnt:
                cnt[it["code"]] += 1
    return cnt


def write_index():
    dates = sorted((p.stem for p in OUT.glob("20*.json")), reverse=True)
    with (OUT / "index.json").open("w", encoding="utf-8") as f:
        json.dump({"dates": dates,
                   "updated": dates[0] if dates else None,
                   "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M")},
                  f, ensure_ascii=False, indent=1)
    write_summary(dates)


def write_summary(dates):
    """銘柄別の集計。単発の開示ではなく「何回出ているか」が事業整理の進み具合にあたる。

    確度『低』は数に入れない(単なる評価損を回数に混ぜると意味が薄れるため)。
    """
    by = {}
    for d in dates:
        for it in (load(OUT / f"{d}.json", {}) or {}).get("items", []):
            if it.get("conf") == "低":
                continue
            r = by.setdefault(it["code"], {
                "code": it["code"], "name": it["name"], "n": 0,
                "cats": {}, "first": d, "last": d, "rows": []})
            r["n"] += 1
            r["name"] = it["name"]
            for c in it["cats"]:
                r["cats"][c] = r["cats"].get(c, 0) + 1
            r["first"] = min(r["first"], d)
            r["last"] = max(r["last"], d)
            if len(r["rows"]) < 12:
                r["rows"].append({"date": d, "title": it["title"][:70],
                                  "url": it["url"], "cats": it["cats"]})
    rows = sorted(by.values(), key=lambda r: (-r["n"], r["last"]), reverse=False)
    rows.sort(key=lambda r: (-r["n"], r["code"]))
    for r in rows:
        r["rows"].sort(key=lambda x: x["date"], reverse=True)
    with (OUT / "summary.json").open("w", encoding="utf-8") as f:
        json.dump({"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "span": [dates[-1], dates[0]] if dates else None,
                   "stocks": rows}, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 本体

def run_day(day, rules, use_pdf=True, dry=False, log=print):
    ymd = day.strftime("%Y%m%d")
    iso = day.isoformat()
    items = fetch_day(ymd, log)
    if not items:
        log(f"  {iso}: 開示なし(休場日か取得失敗)。スキップ")
        return None
    if not dry:
        items = save_raw(ymd, items)

    hits = []
    for it in items:
        c = classify(it["title"], rules)
        if c:
            hits.append(dict(it, cats=c))

    # 再実行でPDFを落とし直さないよう、前回の抽出結果を引き継ぐ
    prev = {i["url"]: i for i in (load(OUT / f"{iso}.json", {}) or {}).get("items", [])}
    for n, h in enumerate(hits):
        body = None
        if use_pdf and n < PDF_MAX:
            old = prev.get(h["url"])
            if old and old.get("pdf") and "pdf_error" not in old["pdf"]:
                h["pdf"] = old["pdf"]
                h["conf"] = old.get("conf", "高")
            else:
                pdf = extract(h["url"], rules)
                body = pdf.pop("body", None)
                h["pdf"] = pdf
                time.sleep(0.6)      # TDnetに連打しない
                log(f"    PDF {n + 1}/{min(len(hits), PDF_MAX)} {h['code']} "
                    f"{pdf.get('chars', '-')}字")
        if "conf" not in h:
            h["conf"] = confidence(h["cats"], rules, body)

    rep = repeat_counts(iso, [h["code"] for h in hits])
    for h in hits:
        h["repeat"] = rep.get(h["code"], 0) + 1

    kept = [h for h in hits if h["conf"] != "低"]
    data = {
        "date": iso,
        "as_of": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "counts": {"all": len(items), "hit": len(hits), "weak": len(hits) - len(kept)},
        "items": hits,
    }
    log(f"  {iso}: 全{len(items)}件 → 事業整理 {len(hits)}件"
        f"(確度高・中 {len(kept)}件 / 低 {len(hits) - len(kept)}件)")
    for h in hits:
        amt = "/".join(f"{a['k']}{a['v']}" for a in h.get("pdf", {}).get("amounts", []))
        log(f"    {h['conf']} [{'|'.join(h['cats'])}] {h['code']} {h['name'][:12]} "
            f"{h['title'][:38]}" + (f"  ({amt})" if amt else ""))

    if not dry:
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / f"{iso}.json").open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD")
    ap.add_argument("--backfill", type=int, default=0, help="直近N営業日をまとめて取得")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args()

    rules = load_rules()
    if a.backfill:
        days, d = [], dt.date.today()
        while len(days) < a.backfill:
            if d.weekday() < 5:
                days.append(d)
            d -= dt.timedelta(days=1)
        days.reverse()
    else:
        days = [dt.date.fromisoformat(a.date) if a.date else dt.date.today()]

    total = 0
    for d in days:
        r = run_day(d, rules, use_pdf=not a.no_pdf, dry=a.dry_run)
        if r:
            total += r["counts"]["hit"]
    if not a.dry_run:
        write_index()
    print(f"done: {len(days)}日 / 事業整理 計{total}件")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
