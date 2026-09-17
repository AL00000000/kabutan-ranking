"""決算短信・業績予想修正PDFから「通期の会社予想EPS」を抜く.

出力: forecasts.csv  code, pub(開示日時), fy_end(予想対象期の末日), eps, ni(百万円), kind, tid, note
 - 数値は PDF の文字列そのまま(分割調整なし)。調整は analyze.py で行う
 - 予想が「未定」「レンジ」の開示は eps 空欄で残す(その期間は予想PERを出さない)
"""
import csv, json, os, re, sys, unicodedata
import pymupdf

from stocks import STOCKS

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = os.path.join(HERE, "cache", "pdf")

NUM = re.compile(r"^[△▲\-－−]?\s*[\d,]+(\.\d+)?$")
DATE = re.compile(r"(平成|令和)?\s*(\d{1,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})?\s*日?")
PERIOD = re.compile(r"[~～〜]\s*(平成|令和)?\s*(\d{1,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


# フォントのToUnicodeが壊れていてAdobe-Japan1のCIDがそのまま出るPDF(商船三井の一部など)用
CID_KANJI = {0x15BA: "年", 0x1B76: "月", 0x1B87: "期", 0x1AA5: "日", 0x33FB: "通", 0x0BA3: "予",
             0x177F: "想", 0x1D17: "業", 0x29BC: "績", 0x3403: "連", 0x2916: "結", 0x0862: "の",
             0x06B9: "△", 0x15B9: "平", 0x1842: "成", 0x0BE7: "令", 0x0FF4: "和", 0x1B59: "未", 0x1B8D: "定"}


def is_broken(s):
    return sum(0 < ord(c) < 0x20 and c not in "\n\t" for c in s) > 20


def fix_cid(s, force=False):
    if not force and not any(0 < ord(c) < 0x20 and c not in "\n\t" for c in s) and not any(0x3E20 <= ord(c) <= 0x3E7E for c in s):
        return s
    out = []
    for c in s:
        o = ord(c)
        if 0 < o <= 0x5F and c not in "\n\t":
            out.append(chr(o + 0x1D))
        elif 0x3E1F <= o <= 0x3E7E:
            out.append(chr(o + 0xC0E2))
        else:
            out.append(CID_KANJI.get(o, c))
    return "".join(out)


def norm(s, force=False):
    s = unicodedata.normalize("NFKC", fix_cid(s, force))
    s = re.sub(r"([△▲])\s+(?=\d)", r"\1", s)
    return s.replace("　", " ")


def year(era, y):
    y = int(y)
    if era == "平成" or (not era and y < 40 and y > 12):
        return 1988 + y if y < 100 else y
    if era == "令和" or (not era and y <= 12):
        return 2018 + y
    return y


def tonum(t):
    t = t.replace(",", "").replace(" ", "")
    neg = t[0] in "△▲-－−"
    v = float(t.lstrip("△▲-－−"))
    return -v if neg else v


def page_lines(path, pages=4):
    """[(page, y0, y1, x0, x1, text)] を返す(行単位)."""
    doc = pymupdf.open(path)
    out = []
    for pn, p in enumerate(list(doc)[:pages]):
        broken = is_broken(p.get_text())
        for b in p.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                t = norm("".join(sp["text"] for sp in l["spans"]), broken).strip()
                if t:
                    x0, y0, x1, y1 = l["bbox"]
                    out.append((pn, y0, y1, x0, x1, t))
    return out


def same_row(pl, label, tol=4.5):
    """label 行と縦位置が重なる、右側の行の数値トークンを x 順に返す."""
    pn, y0, y1, x0, x1, _ = label
    cy = (y0 + y1) / 2
    cells = [r for r in pl if r[0] == pn and r[3] >= x1 - 1 and abs((r[1] + r[2]) / 2 - cy) <= tol
             and r is not label]
    cells.sort(key=lambda r: r[3])
    vals = []
    for r in cells:
        for tok in r[5].split():
            if NUM.match(tok) or tok in ("-", "―", "−", "~", "～"):
                vals.append(tok)
            elif re.fullmatch(r"[\d,.]+~[\d,.]+", tok):
                vals.append("~")
    return vals


def pos_tanshin(pl, fy_month):
    heads = [r for r in pl if re.search(r"期の(連結|個別)?(業績予想|業績見通し)", r[5])
             and re.search(r"^\s*\d\s*[.]", r[5])]
    if not heads:  # 2005〜07年の書式: 番号なし・期間は次の行
        heads = [r for r in pl if re.search(r"月期の連結業績予想", r[5]) and not re.search(r"修正|適切|個別", r[5])]
    for h in heads:
        nxt = " ".join(x[5] for x in pl if x[0] == h[0] and h[1] - 1 <= x[1] <= h[1] + 30)
        ends = fy_from(h[5], fy_month) or fy_from(nxt, fy_month)
        if not ends:
            m = re.search(r"(\d{4})\s*年\s*(\d+)\s*月期|平成\s*(\d+)\s*年\s*(\d+)\s*月期", h[5])
            if m:
                ends = [f"{int(m.group(1))}-{int(m.group(2)):02d}" if m.group(1)
                        else f"{1988 + int(m.group(3))}-{int(m.group(4)):02d}"]
        rows = [r for r in pl if r[0] == h[0] and h[1] < r[1] < h[1] + 260 and re.match(r"^通\s*期|^通$", r[5])]
        if not rows:  # 表が次のページにまたがる
            rows = [r for r in pl if r[0] == h[0] + 1 and r[1] < 260 and re.match(r"^通\s*期|^通$", r[5])]
        for r in rows[:1]:
            vals = [t for t in r[5].split()[1:] if NUM.match(t)] + same_row(pl, r)
            eps, ni, note = pick(vals)
            if eps is None and note != "range":
                eps, ni = ref_eps(pl, h, vals)
            if eps is not None or note == "range":
                return (ends[0] if ends else None), eps, ni, note
        if not rows and ends:
            eps, ni = ref_eps(pl, h, [])
            if eps is not None:
                return ends[0], eps, ni, "ref"
        if ends:
            near = " ".join(r[5] for r in pl if r[0] == h[0] and h[1] <= r[1] < h[1] + 120)
            if re.search(r"未定|記載していません|開示しておりません|見合わせ|差し控え|記載しておりません", near):
                return ends[0], None, None, "undisclosed"
    return None


REF_EPS = re.compile(r"1株当たり予想当期純利益\s*\(通期\)\s*([△▲-]?[\d,]+)\s*円\s*(\d{1,2})\s*銭")


def ref_eps(pl, h, vals):
    """2005〜06年の書式: EPSは表の外に「(参考)1株当たり予想当期純利益(通期) 75円37銭」と書かれる."""
    near = " ".join(r[5] for r in pl if r[0] == h[0] and h[1] <= r[1] < h[1] + 200)
    m = REF_EPS.search(near)
    if not m:
        return None, None
    ints = [tonum(v) for v in vals if NUM.match(v) and "." not in v]
    return tonum(m.group(1) + "." + m.group(2).zfill(2)), (ints[3] if len(ints) >= 4 else None)


def pos_revision(pl, fy_month):
    best = None
    for i, r in enumerate(pl):
        if not REV_ROW.match(r[5]):
            continue
        # 同じページで直上にある期間見出し(~YYYY年M月D日)
        above = sorted((x for x in pl if x[0] == r[0] and x[2] <= r[1] + 1 and PERIOD.search(x[5])),
                       key=lambda x: x[1])
        before = above[-1][5] if above else " ".join(x[5] for x in pl[max(0, i - 60):i])
        ps = list(PERIOD.finditer(before))
        if not ps or int(ps[-1].group(3)) != fy_month:
            continue
        y = year(ps[-1].group(1), ps[-1].group(2))
        vals = [t for t in r[5].split()[1:] if NUM.match(t)] + same_row(pl, r, tol=7)
        eps, ni, note = pick(vals)
        if (eps is not None and ni is not None) or note == "range":
            best = (f"{y}-{fy_month:02d}", eps, ni, note)
    return best


def lines_of(path, pages=4):
    doc = pymupdf.open(path)
    out = []
    for p in list(doc)[:pages]:
        t = p.get_text()
        out += [norm(l, is_broken(t)).strip() for l in t.splitlines()]
    return [l for l in out if l]


def row_after(lines, i, stop):
    """lines[i] の次から数値トークンを拾う。stop に当たるか数値以外が続いたら終わり."""
    vals, junk = [], 0
    for l in lines[i + 1:i + 40]:
        if stop.search(l):
            break
        for tok in l.split():
            if NUM.match(tok):
                vals.append(tok)
                junk = 0
            elif tok in ("-", "―", "−", "~", "～"):
                vals.append(tok)
            else:
                junk += 1
        if junk > 6:
            break
    return vals


def pick(vals):
    """数値列から (EPS, 当期純利益) を取る。EPSは最後の小数2桁、純利益はその手前の整数."""
    if any(v in ("~", "～") for v in vals):
        return None, None, "range"
    eps_i = None
    for k in range(len(vals) - 1, -1, -1):
        if re.search(r"\.\d\d$", vals[k]):
            eps_i = k
            break
    if eps_i is None:
        return None, None, "noeps"
    ni = None
    for v in reversed(vals[:eps_i]):
        if NUM.match(v) and "." not in v:
            ni = tonum(v)
            break
    return tonum(vals[eps_i]), ni, ""


def fy_from(text, fy_month):
    ends = []
    for m in PERIOD.finditer(text):
        y = year(m.group(1), m.group(2))
        if 2000 < y < 2035 and int(m.group(3)) == fy_month:
            ends.append(f"{y}-{int(m.group(3)):02d}")
    return ends


def parse_tanshin(lines, fy_month):
    txt = "\n".join(lines)
    # 「N. ○○年○月期の(連結)業績予想」の見出し
    heads = [i for i, l in enumerate(lines)
             if re.search(r"業績予想", l) and re.search(r"^\s*\d\s*[.．]", l)
             and not re.search(r"修正の有無|適切な利用|注記|説明", l)]
    if not heads:
        heads = [i for i, l in enumerate(lines) if re.search(r"期の(連結)?業績予想", l)]
    for h in heads:
        seg = lines[h:h + 80]
        ends = fy_from(" ".join(seg[:6]), fy_month)
        if not ends:
            m = re.search(r"(\d{4}|平成\s*\d+|令和\s*\d+)\s*年\s*(\d+)\s*月期", seg[0])
            if m:
                ends = [f"{year(*(['平成' if '平成' in m.group(1) else '令和' if '令和' in m.group(1) else None, re.sub(r'\D', '', m.group(1))]))}-{int(m.group(2)):02d}"]
        for j, l in enumerate(seg):
            if re.match(r"^通\s*期", l):
                vals = row_after(seg, j, re.compile(r"^※|^\(注|^注|^\*|^4\.|^[(（]?\d[)）]"))
                # 同じ行に数値が続く形式
                vals = [t for t in l.split()[1:] if NUM.match(t)] + vals
                eps, ni, note = pick(vals)
                return (ends[0] if ends else None), eps, ni, note
        if re.search(r"未定|記載していません|開示しておりません|公表を見合わせ|差し控え", " ".join(seg[:30])):
            return (ends[0] if ends else None), None, None, "undisclosed"
    if re.search(r"業績予想.{0,30}(未定|見合わせ|差し控え|開示しておりません)", txt):
        return None, None, None, "undisclosed"
    return None, None, None, "nohead"


REV_ROW = re.compile(r"^(今回(修正|発表)?予想|修正後|今回予想|今回発表予想)")


def parse_revision(lines, fy_month):
    best = None
    for i, l in enumerate(lines):
        if not REV_ROW.match(l):
            continue
        before = " ".join(lines[max(0, i - 40):i])
        ps = list(PERIOD.finditer(before))
        if not ps:
            continue
        m = ps[-1]
        y = year(m.group(1), m.group(2))
        if int(m.group(3)) != fy_month:
            continue  # 第2四半期累計の表
        vals = [t for t in l.split()[1:] if NUM.match(t)] + row_after(
            lines, i, re.compile(r"^(増減額|増減率|前期実績|\(ご参考|\(参考|参考)"))
        eps, ni, note = pick(vals)
        best = (f"{y}-{fy_month:02d}", eps, ni, note)
    if best:
        return best
    if re.search(r"未定", " ".join(lines)):
        return None, None, None, "undisclosed"
    return None, None, None, "notable"


def fy_month_of(docs):
    for d in docs:
        m = re.search(r"(\d+)\s*月期", norm(d["title"]))
        if m:
            return int(m.group(1))
    return 3


MANUAL = {r["tid"]: r for r in csv.DictReader(open(os.path.join(HERE, "manual.csv"), encoding="utf-8"))}


def main(codes):
    rows = []
    for code in codes:
        docs = json.load(open(os.path.join(HERE, "cache", f"docs_{code}.json"), encoding="utf-8"))
        fm = fy_month_of(docs)
        wb = os.path.join(HERE, "cache", f"docs_wb_{code}.json")
        if os.path.exists(wb):
            # TDnet由来の開示が無い期間(2013年頃まで)だけ Wayback 分を足す
            first = min((d["pub"] for d in docs if os.path.exists(os.path.join(PDF, f"{d['tid']}.pdf"))),
                        default="9999")
            docs = [dict(d, src="wb") for d in json.load(open(wb, encoding="utf-8"))
                    if d["pub"] < first] + docs
        for d in docs:
            path = os.path.join(HERE, "cache", "wb" if d.get("src") == "wb" else "pdf", f"{d['tid']}.pdf")
            if not os.path.exists(path):
                continue
            try:
                lines = lines_of(path)
            except Exception as e:
                rows.append([code, d["pub"], "", "", "", "err", d["tid"], str(e)[:40]])
                continue
            kind = "tanshin" if "短信" in d["title"] else "revision"
            pl = page_lines(path)
            got = (pos_tanshin if kind == "tanshin" else pos_revision)(pl, fm)
            if not got:
                got = (parse_tanshin if kind == "tanshin" else parse_revision)(lines, fm)
            fy, eps, ni, note = got
            if d["tid"] in MANUAL:
                m = MANUAL[d["tid"]]
                if m["eps"]:
                    fy, eps, ni, note = m["fy_end"], float(m["eps"]), float(m["ni"]), "manual"
                else:
                    fy, eps, ni, note = m["fy_end"], None, None, "undisclosed"
            rows.append([code, d["pub"], fy or "", "" if eps is None else eps,
                         "" if ni is None else ni, kind, d["tid"], note])
    with open(os.path.join(HERE, "forecasts_raw.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "pub", "fy_end", "eps", "ni", "kind", "tid", "note"])
        w.writerows(rows)
    return rows


if __name__ == "__main__":
    rows = main(sys.argv[1:] or list(STOCKS))
    for r in rows:
        print(*r)
