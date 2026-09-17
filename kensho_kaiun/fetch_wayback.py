"""2013年以前の決算短信・業績予想修正を Wayback Machine の保存PDFから集める (大手3社のみ).

TDnet の過去PDFは消えていて IRBANK のミラーも2013年頃から。各社IRサイトの旧URLが
Wayback に残っている分だけ拾う(網羅ではない)。
出力: cache/wb/{tid}.pdf と cache/docs_wb_{code}.json (pub は PDF 冒頭の日付)
"""
import hashlib, json, os, re, sys, time
import requests
import pymupdf

from parse_docs import norm, year

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.join(HERE, "cache", "wb")
os.makedirs(WB, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 research script"}
SKIP_DIR = re.compile(r"(annual|/report/|/ig/|meeting|presentation|/cfh/|/form/|/mrsf/|/kabu/|/kaisha/"
                      r"|/ippan/|/kojin/|/stock_j/|/ir-e/)")
SKIP_FILE = re.compile(r"(^ar-|annual|houkokusho|yuho|i-guide|graph|market|^data\d|^non\d|_non\.pdf|qa|briefing"
                       r"|material|maretial|haitou|rinji|-e\.pdf|_e\.pdf|nbpc)", re.I)
HEAD_DATE = re.compile(r"(平成|令和)?\s*(\d{2,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def pub_date(head, url, ts, code, kind, fy_hint):
    """公開日。冒頭の単独の日付 → ファイル名の年月 → TDnet一覧の修正開示 の順."""
    for m in HEAD_DATE.finditer(head):
        before, after = head[max(0, m.start() - 2):m.start()], head[m.end():m.end() + 3]
        if re.search(r"[~〜]", before + after) or "(" in before:
            continue
        y = year(m.group(1), m.group(2))
        if 2004 < y < 2015:
            return f"{y}-{int(m.group(3)):02d}-{int(m.group(4)):02d}", "head"
    name = url.rsplit("/", 1)[-1].lower()
    m = re.match(r"(?:con|fy)(\d{2})(\d{2})", name)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"20{m.group(1)}-{m.group(2)}-25", "filename"
    if kind == "revision" and fy_hint:
        docs = json.load(open(os.path.join(HERE, "cache", f"docs_{code}.json"), encoding="utf-8"))
        cap = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        y = int(fy_hint[:4])
        pat = re.compile(rf"(平成\s*{y - 1988}|{y})\s*年\s*3\s*月期")
        c = [d for d in docs if "修正" in d["title"] and d["pub"][:10] <= cap and pat.search(d["title"])]
        if c:
            return c[-1]["pub"][:10], "tdnet-list"
    return None, None


def classify(path, url="", ts="", code=""):
    try:
        doc = pymupdf.open(path)
        t = norm(doc[0].get_text())
    except Exception:
        return None
    head = t[:600]
    if re.search(r"決算短信|財務・業績の概況", head):
        kind = "tanshin"
    elif re.search(r"業績予想.{0,15}修正|予想.{0,10}修正に関するお知らせ|業績見通し.{0,10}修正|予想数値の修正", head):
        kind = "revision"
    else:
        return None
    if re.search(r"訂正", head[:300]):
        return None
    if re.search(r"(個別|非連結)", head[:200]) and "連結" not in head[:200].replace("非連結", ""):
        return None
    m = re.search(r"(平成\s*\d+|\d{4})\s*年\s*3\s*月期", head)
    fy_hint = None
    if m:
        v = re.sub(r"\D", "", m.group(1))
        fy_hint = f"{1988 + int(v) if int(v) < 100 else int(v)}-03"
    pub, how = pub_date(head, url, ts, code, kind, fy_hint)
    if not pub:
        return None
    title = re.sub(r"\s+", "", head[:200])[:60]
    return {"kind": kind, "pub": pub + " 15:00:00", "date_src": how,
            "title": ("決算短信 " if kind == "tanshin" else "業績予想の修正 ") + title}


def main(codes):
    cand = json.load(open(os.path.join(HERE, "cache", "wb_candidates.json")))
    for code in codes:
        seen, docs = set(), []
        for row in cand[code]:
            ts, url = row[1], row[2]
            name = url.split("?")[0].rsplit("/", 1)[-1].lower()
            if SKIP_DIR.search(url.split("_material_")[0]) or SKIP_FILE.search(name) or not ("2005" <= ts[:4] <= "2014"):
                continue
            key = url.split("://", 1)[1].replace("www.", "").replace(":80", "")
            if key in seen:
                continue
            seen.add(key)
            tid = "wb" + hashlib.md5(key.encode()).hexdigest()[:12]
            dst = os.path.join(WB, f"{tid}.pdf")
            if not os.path.exists(dst) and not os.path.exists(dst + ".bad"):
                ok = False
                for t in range(3):
                    try:
                        r = requests.get(f"http://web.archive.org/web/{ts}id_/{url}", headers=UA, timeout=90)
                        if r.status_code == 200 and r.content.startswith(b"%PDF"):
                            open(dst, "wb").write(r.content)
                            ok = True
                        break
                    except Exception:
                        time.sleep(8)
                if not ok:
                    open(dst + ".bad", "w").write(url)
                time.sleep(1.5)
            if not os.path.exists(dst):
                continue
            c = classify(dst, url, ts, code)
            if c:
                c.update({"tid": tid, "url": url})
                docs.append(c)
        docs.sort(key=lambda d: d["pub"])
        uniq = {}
        for d in docs:  # 同じ資料が別URLで保存されていることがある
            uniq.setdefault((d["pub"], d["kind"], d["title"]), d)
        docs = list(uniq.values())
        json.dump(docs, open(os.path.join(HERE, "cache", f"docs_wb_{code}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
        print(code, "wayback docs", len(docs), flush=True)
        for d in docs:
            print("  ", d["pub"][:10], d["kind"], d["title"][:40], d["url"].rsplit("/", 1)[-1])


if __name__ == "__main__":
    main(sys.argv[1:] or ["9101", "9104", "9107"])
