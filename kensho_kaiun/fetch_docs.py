"""海運株の決算短信・業績予想修正PDFを集める.

一覧: やのしんAPI (TDnet, 2009-10以降)
PDF : IRBANK のミラー (2013年頃以降のみ残っている)
出力: cache/docs_{code}.json, cache/pdf/{tid}.pdf
"""
import json, os, re, sys, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
PDF = os.path.join(CACHE, "pdf")
os.makedirs(PDF, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

# 予想EPSが載る開示だけ
PAT = re.compile(r"決算短信|業績予想|予想の修正|予想値|業績見通し|差異")
SKIP = re.compile(r"訂正|英文|配当予想の修正に関する")

from stocks import STOCKS


def doc_list(code):
    path = os.path.join(CACHE, f"docs_{code}.json")
    r = requests.get(f"https://webapi.yanoshin.jp/webapi/tdnet/list/{code}.json?limit=5000",
                     headers=UA, timeout=60)
    r.encoding = "utf-8"
    out = []
    for it in r.json().get("items", []):
        t = it["Tdnet"]
        if not PAT.search(t["title"]) or SKIP.search(t["title"]):
            continue
        m = re.search(r"/(\d{18})\.pdf", t["document_url"])
        if m:
            out.append({"tid": m.group(1), "pub": t["pubdate"], "title": t["title"]})
    out.sort(key=lambda d: d["pub"])
    old = {}
    if os.path.exists(path):
        old = {d["tid"]: d for d in json.load(open(path, encoding="utf-8"))}
    for d in out:
        d.update({k: v for k, v in old.get(d["tid"], {}).items() if k == "pdf"})
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return out


def fetch_pdf(code, d):
    dst = os.path.join(PDF, f"{d['tid']}.pdf")
    if os.path.exists(dst):
        return True
    if d.get("pdf") == "none":
        return False
    x = requests.get(f"https://irbank.net/{code}/{d['tid']}", headers=UA, timeout=30)
    time.sleep(0.7)
    m = re.search(r"https://f\.irbank\.net/pdf/[^\"']+\.pdf", x.text)
    if not m:
        d["pdf"] = "none"
        return False
    y = requests.get(m.group(0), headers=UA, timeout=60)
    time.sleep(0.7)
    if y.status_code != 200 or not y.content.startswith(b"%PDF"):
        d["pdf"] = "none"
        return False
    open(dst, "wb").write(y.content)
    return True


if __name__ == "__main__":
    codes = sys.argv[1:] or list(STOCKS)
    for code in codes:
        docs = doc_list(code)
        ok = sum(fetch_pdf(code, d) for d in docs)
        json.dump(docs, open(os.path.join(CACHE, f"docs_{code}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
        print(code, STOCKS[code], "docs", len(docs), "pdf", ok,
              "first", docs[0]["pub"][:10] if docs else "-", flush=True)
