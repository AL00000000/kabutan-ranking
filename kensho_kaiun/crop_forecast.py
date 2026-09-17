"""文字が図形化されていてテキストが取れない短信について、予想表の部分だけ画像に切り出す.

WindowsのOCR(ocr.ps1)で「…期の連結業績予想」の見出し位置を探し、その下を切り出す。
数値はOCRだと小数点・カンマが落ちるので、切り出した画像を目で読んで manual.csv に入力する。
出力: cache/crop/{code}_{pub}_{tid}.png
"""
import csv, json, os, re, subprocess, sys
import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cache", "crop")
TMP = os.path.join(HERE, "cache", "img")
os.makedirs(OUT, exist_ok=True)
os.makedirs(TMP, exist_ok=True)
DPI = 150


def ocr_words(png):
    js = png[:-4] + ".json"
    if not os.path.exists(js):
        subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", os.path.join(HERE, "ocr.ps1"), png, js],
                       check=True, capture_output=True)
    txt = open(js, encoding="utf-8-sig").read().strip()
    return json.loads(txt) if txt else []


def find_head(words):
    rows = {}
    for w in words:
        rows.setdefault(round(w["y"] / 10), []).append(w)
    for k in sorted(rows):
        line = "".join(w["t"] for w in sorted(rows[k], key=lambda w: w["x"]))
        if re.search(r"月期の(連結|個別)?業績予想", line) and not re.search(r"修正|適切", line):
            return min(w["y"] for w in rows[k])
    return None


def main():
    manual = {r["tid"] for r in csv.DictReader(open(os.path.join(HERE, "manual.csv"), encoding="utf-8"))}
    rows = list(csv.DictReader(open(os.path.join(HERE, "forecasts_raw.csv"), encoding="utf-8")))
    for r in rows:
        if r["kind"] != "tanshin" or r["eps"] or r["tid"] in manual or r["tid"].startswith("wb"):
            continue
        doc = pymupdf.open(os.path.join(HERE, "cache", "pdf", f"{r['tid']}.pdf"))
        if sum(len(p.get_text()) for p in list(doc)[:2]) > 200:
            continue
        name = f"{r['code']}_{r['pub'][:10]}_{r['tid']}.png"
        if os.path.exists(os.path.join(OUT, name)):
            continue
        done = False
        for pn in range(min(3, doc.page_count)):
            png = os.path.join(TMP, f"{r['tid']}_p{pn}.png")
            pix = doc[pn].get_pixmap(dpi=DPI)
            pix.save(png)
            y = find_head(ocr_words(png))
            if y is None:
                continue
            clip = pymupdf.Rect(0, max(0, y * 72 / DPI - 8), doc[pn].rect.width, min(doc[pn].rect.height, y * 72 / DPI + 150))
            doc[pn].get_pixmap(dpi=110, clip=clip).save(os.path.join(OUT, name))
            done = True
            break
        print(r["code"], r["pub"][:10], r["tid"], "ok" if done else "NOT FOUND", flush=True)


if __name__ == "__main__":
    main()
