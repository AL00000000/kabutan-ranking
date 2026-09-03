# -*- coding: utf-8 -*-
"""手動記録していたGoogleスプレッドシート4冊を「週間騰落ログ」タブの形式に取り込む。

各シート(タブ)が1週間分のスナップショットで、**日付はセル内に無くシート名にしかない**
(例: "1/12-18" "930‐1006" "12/30-1/12")。read_file_content はシート名を落として
表だけを順番に連結して返すので、**シート名の並び順とブロックの並び順が同じ**であることを
利用して対応づける。

基準日は「その週に含まれる金曜日」とする(現行の自動記録が金曜基準のため)。
範囲に金曜が複数入る場合(年末年始の2週分など)は最後の金曜を採る。

使い方:
  py import_weekly_history.py --dry-run   … 対応づけだけ表示(書き込まない)
  py import_weekly_history.py             … docs/data_weekly/ に書き出す
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / "docs" / "data_weekly"
TR = Path(r"C:\Users\yt\.claude\projects\C--Users-yt\7d3d363c-b157-4ea1-8cdb-c6b6fafc9539\tool-results")

# (保存済みレスポンス, 開始年, シート名一覧) — シート名はブラウザで読み取ったもの
FILES = [
    ("mcp-b8945409-8451-4e47-807a-8710be42639d-read_file_content-1788403447273.txt", 2024,
     ["9/23-29", "930‐1006", "107‐1013", "1013－1020", "1021-27", "1028 -1103",
      "1104-10", "1111-17", "1118-24", "1125-1201", "12/2-8", "12/9-15",
      "12/16-22", "12/23-29", "12/30-1/12", "1/13-19", "1/27-2/2", "2/3-9",
      "2/10-16", "2/17-23", "2/24-3/2", "3/3-10", "3/11-17", "3/18-3/24", "3/25-31"]),
    ("mcp-b8945409-8451-4e47-807a-8710be42639d-read_file_content-1788403279675.txt", 2025,
     ["2025/01-5-11", "1/12-18", "1/19-25", "1-26-2/1", "2/2-2/8", "2/9-15",
      "2/16-22", "2/23-28", "3/2-8", "3/9-15", "3/16-22"]),
    ("mcp-b8945409-8451-4e47-807a-8710be42639d-read_file_content-1788403452686.txt", 2025,
     ["2025/3/31‐4/6", "4/7-4/13", "4/14-4/20", "4/21-28", "4/28-5/4", "5/5-5/11",
      "5/12-18", "5/19-25", "5/26-6/1", "6/2-8", "6/9-15", "6/16-22", "6/23-29"]),
    ("mcp-b8945409-8451-4e47-807a-8710be42639d-read_file_content-1788403458260.txt", 2025,
     ["7/7-7/13", "7/14-20", "7/21-27", "7/28-8/3", "8/4-9", "8/10-8/17",
      "8/18-24", "8/25-31", "9/1-7", "9/8-14", "9/15-21", "9/22-9/28",
      "9/29-10/05", "10/6-10/12", "10/13-19", "10/20-26", "10/27-11/2",
      "11/10-16", "11/17-23", "11/24-30", "12/1-7", "12/8-14", "12/15-21", "12/22-28"]),
]


def tokens(name):
    """シート名を開始・終了のトークンに割る。区切りは -, ‐, －, / と全角空白が混在する。"""
    s = re.sub(r"^\d{4}/", "", name.strip())          # 先頭の "2025/" を落とす
    s = s.replace("‐", "-").replace("－", "-").replace(" ", "").replace("　", "")
    parts = [x for x in s.split("-") if x]
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) == 3:                                # "1-26-2/1" = 1/26 - 2/1
        return parts[0] + "/" + parts[1], parts[2]
    raise ValueError(f"シート名を解釈できません: {name}")


def md_candidates(tok):
    """トークンから (月, 日) の候補を全部返す。
    '107' は 1/07 とも 10/7 とも読めるので両方返し、前週との連続性で選ぶ。"""
    out = []
    if "/" in tok:
        a, b = tok.split("/")[:2]
        out.append((int(a), int(b)))
        return out
    if len(tok) <= 2:
        out.append((None, int(tok)))                   # 日だけ(月は文脈から)
    elif len(tok) == 3:
        out.append((int(tok[:1]), int(tok[1:])))       # 1/07
        out.append((int(tok[:2]), int(tok[2:])))       # 10/7
    else:
        out.append((int(tok[:2]), int(tok[2:])))       # 1013 -> 10/13
    return [(m, d) for m, d in out if (m is None or 1 <= m <= 12) and 1 <= d <= 31]


def nearest(cands, ref, fallback_month=None):
    """候補のうち ref に日付が最も近いものを date で返す。"""
    best, bestgap = None, None
    for m, d in cands:
        for y in (ref.year - 1, ref.year, ref.year + 1):
            mm = m if m is not None else (fallback_month or ref.month)
            try:
                cand = date(y, mm, d)
            except ValueError:
                continue
            gap = abs((cand - ref).days)
            if bestgap is None or gap < bestgap:
                best, bestgap = cand, gap
    if best is None:
        raise ValueError(f"日付候補を解決できません: {cands} (基準 {ref})")
    return best


def base_date(name, cursor):
    """シート名 -> (基準日=その週の金曜, 開始, 終了)。cursor は前週の終了日+1。"""
    t1, t2 = tokens(name)
    start = nearest(md_candidates(t1), cursor)
    end = nearest(md_candidates(t2), start + timedelta(days=6), start.month)
    if end < start:                                    # 年跨ぎ("12/30-1/12"など)
        end = date(end.year + 1, end.month, end.day)

    fridays = []
    d = start
    while d <= end:
        if d.weekday() == 4:
            fridays.append(d)
        d += timedelta(days=1)
    if not fridays:
        raise ValueError(f"{name}: 範囲に金曜が含まれません({start}〜{end})")
    return fridays[-1], start, end


def num(s):
    s = (s or "").replace("\\", "").replace(",", "").replace("+", "").strip()
    if not s or s in ("NA", "-", "－", "　"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def blocks(content):
    """区切り行(:-:)ごとにブロックへ切り分け、各ブロックのデータ行を返す。"""
    out, cur = [], None
    for ln in content.split("\n"):
        if ":-:" in ln:
            if cur is not None:
                out.append(cur)
            cur = []
            continue
        if cur is None:
            continue
        if ln.strip().startswith("|") and ln.count("|") >= 12:
            cur.append(ln)
    if cur:
        out.append(cur)
    return out


def parse_rows(lines):
    """シートによっては同じ行がコピペで二重に入っているため、コードで重複を除く。"""
    rows, seen = [], set()
    for i, ln in enumerate(lines, 1):
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(c) < 12 or not re.match(r"^[0-9A-Z]{4}$", c[1]):
            continue
        if c[1] in seen:
            continue
        seen.add(c[1])
        rows.append({
            "rank": int(c[0]) if c[0].isdigit() else i,
            "code": c[1], "name": c[2].strip(), "sector": c[3].strip(),
            "price": num(c[4]), "chg_pct": num(c[6]), "rtn1w": num(c[7]),
            "value": num(c[8]), "spr25": num(c[9]), "per": num(c[10]),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    weeks, problems = {}, []
    for fname, year0, tabs in FILES:
        path = TR / fname
        if not path.exists():
            print(f"NG: 保存済みレスポンスが見つかりません: {path}", file=sys.stderr)
            return 1
        content = json.loads(path.read_text(encoding="utf-8"))["fileContent"]
        bl = blocks(content)
        if len(bl) != len(tabs):
            problems.append(f"{fname[-20:]}: ブロック{len(bl)}件 vs シート名{len(tabs)}件 (不一致)")
        cursor = date(year0, 1, 1)
        first = True
        for tab, lines in zip(tabs, bl):
            if first:
                # 1枚目だけはファイルの開始年を手がかりにする
                t1, _ = tokens(tab)
                cands = md_candidates(t1)
                cursor = min((date(year0, m or 1, d) for m, d in cands
                              if m is not None), default=date(year0, 1, 1))
                first = False
            fri, s, e = base_date(tab, cursor)
            cursor = e + timedelta(days=1)
            rows = parse_rows(lines)
            if not rows:
                continue                                # 中身が空のシートは飛ばす
            key = fri.isoformat()
            if key in weeks and len(weeks[key]["up"]) >= len(rows):
                continue                                # 重複週は件数が多い方を残す
            # シートによっては利用者が行を手で入れ替えているが、rank列は元の順位を
            # 保持している。行順ではなくrank列を正としてソートし、順位は振り直さない。
            rows.sort(key=lambda r: r["rank"])
            weeks[key] = {
                "base": key, "asof": None, "source": "manual-sheet",
                "sheet": tab, "range": f"{s.isoformat()}〜{e.isoformat()}",
                "n": len(rows), "up": rows, "down": [],
            }

    print(f"取り込み対象: {len(weeks)}週  ({min(weeks)} 〜 {max(weeks)})")
    for p in problems:
        print("  警告:", p)
    ks = sorted(weeks)
    print("\n--- 先頭5 ---")
    for k in ks[:5]:
        w = weeks[k]
        print(f"  {k}(金) シート'{w['sheet']}' 範囲{w['range']} {w['n']}銘柄 "
              f"1位={w['up'][0]['name'] if w['up'] else '-'}")
    print("--- 末尾5 ---")
    for k in ks[-5:]:
        w = weeks[k]
        print(f"  {k}(金) シート'{w['sheet']}' 範囲{w['range']} {w['n']}銘柄 "
              f"1位={w['up'][0]['name'] if w['up'] else '-'}")
    bad = [k for k in ks if weeks[k]["n"] < 50]
    if bad:
        print("\n件数が少ない週:", [(k, weeks[k]["n"]) for k in bad])

    if args.dry_run:
        print("\n(--dry-run のため書き込みなし)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    wrote = 0
    for k in ks:
        p = OUT / f"{k}.json"
        if p.exists():
            continue                                    # 自動記録ぶんは上書きしない
        p.write_text(json.dumps(weeks[k], ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
        wrote += 1
    dates = sorted((p.stem for p in OUT.glob("????-??-??.json")), reverse=True)
    (OUT / "index.json").write_text(
        json.dumps({"updated": dates[0], "dates": dates}, ensure_ascii=False),
        encoding="utf-8")
    print(f"\n書き出し {wrote}件 / data_weekly の総週数 {len(dates)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
