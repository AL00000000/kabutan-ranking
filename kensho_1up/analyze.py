"""1UP投資部屋の企業インタビュー動画 公開後の値動き検証.

入力: interviews.csv (video_id, code, name) と videos_full.jsonl (yt-dlp メタデータ)
出力: result.json (docs/kensho_1up.html の埋め込みデータ)

基準値 = 公開時刻より前の最後の立会日の終値 (金曜引け後公開なら金曜終値)
翌営業日 = 公開時刻より後に始まる最初の立会日 (金曜夜公開なら月曜/祝日明け)
ベンチマーク = 東証グロース市場250ETF(2516) と TOPIX ETF(1306) の同じ区間の騰落率
"""
import csv, json, os, re, time, urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)
JST = timezone(timedelta(hours=9))
URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}.T"
       "?period1=1609459200&period2=1790000000&interval=1d")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def bars(code):
    path = os.path.join(CACHE, f"{code}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    req = urllib.request.Request(URL.format(sym=code), headers=UA)
    try:
        j = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print("fetch fail", code, e)
        return None
    r = (j.get("chart") or {}).get("result") or []
    if not r:
        return None
    r = r[0]
    q = r["indicators"]["quote"][0]
    off = r["meta"].get("gmtoffset", 32400)
    out = []
    for i, ts in enumerate(r.get("timestamp") or []):
        o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c) or not v:
            continue          # 出来高0(気配のみ)の日は立会なしとみなす
        d = datetime.fromtimestamp(ts + off, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append([d, o, h, l, c, v])
    json.dump(out, open(path, "w", encoding="utf-8"))
    time.sleep(0.4)
    return out


def split_at(bs, pub):
    """公開時刻 pub(JST datetime) で、基準日インデックスと翌営業日インデックスを返す."""
    # その日の立会が「公開前に終わっている」なら基準日に含める(15:30以降)
    base = nxt = None
    for i, b in enumerate(bs):
        d = datetime.strptime(b[0], "%Y-%m-%d").replace(tzinfo=JST)
        close_t = d + timedelta(hours=15, minutes=30)
        open_t = d + timedelta(hours=9)
        if close_t <= pub:
            base = i
        elif open_t >= pub and nxt is None:
            nxt = i
    return base, nxt


TDNET = "https://webapi.yanoshin.jp/webapi/tdnet/list/{code}.json?limit=5000"
MATERIAL = re.compile("決算|業績|修正|配当|自己株式|自己株|優待|中期経営計画|中計|提携|買収|取得|受注|月次|KPI|株式分割|TOB|公開買付|上場")


def disclosures(code):
    path = os.path.join(CACHE, f"td_{code}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    req = urllib.request.Request(TDNET.format(code=code), headers=UA)
    items = json.loads(urllib.request.urlopen(req, timeout=60).read())["items"]
    out = [[i["Tdnet"]["pubdate"][:16], i["Tdnet"]["title"],
            i["Tdnet"]["document_url"].split("rd.php?")[-1]] for i in items]
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    time.sleep(0.5)
    return out


def close_time(d):
    """大引け時刻 (2024-11-05 から 15:30、それ以前は 15:00)."""
    return "15:30" if d >= "2024-11-05" else "15:00"


LIMITS = [(100, 30), (200, 50), (500, 80), (700, 100), (1000, 150), (1500, 300),
          (2000, 400), (3000, 500), (5000, 700), (7000, 1000), (10000, 1500),
          (15000, 3000), (20000, 4000), (30000, 5000), (50000, 7000),
          (70000, 10000), (100000, 15000)]


def limit_up(pc):
    for th, w in LIMITS:
        if pc < th:
            return pc + w
    return pc * 1.3


def control(bs, bi):
    """同じ銘柄の、基準日より前250営業日にある「金曜→翌営業日」の平均."""
    g, c, h = [], [], []
    for i in range(max(0, bi - 250), bi - 1):
        d = datetime.strptime(bs[i][0], "%Y-%m-%d")
        if d.weekday() != 4:
            continue
        pc, nx = bs[i][4], bs[i + 1]
        g.append(nx[1] / pc - 1); c.append(nx[4] / pc - 1); h.append(nx[2] / pc - 1)
    if len(c) < 20:
        return None
    m = lambda a: round(sum(a) / len(a) * 100, 3)
    return {"n": len(c), "gap": m(g), "close": m(c), "high": m(h)}


def pct(a, b):
    return None if a is None or b is None else round((a / b - 1) * 100, 3)


def main():
    meta = {}
    for line in open(os.path.join(HERE, "videos_full.jsonl"), encoding="utf-8"):
        d = json.loads(line)
        meta[d["id"]] = d
    bench = {k: bars(k) for k in ("2516", "1306")}
    rows = []
    for r in csv.DictReader(open(os.path.join(HERE, "interviews.csv"), encoding="utf-8")):
        m = meta[r["video_id"]]
        ts = m.get("release_timestamp") or m.get("timestamp")
        pub = datetime.fromtimestamp(ts, tz=JST)
        row = {"vid": r["video_id"], "code": r["code"], "name": r["name"],
               "title": m["title"], "pub": pub.strftime("%Y-%m-%d %H:%M"),
               "wd": "月火水木金土日"[pub.weekday()], "dur": m.get("duration")}
        bs = bars(r["code"])
        if not bs:
            row["status"] = "株価取得不可(上場廃止など)"
            rows.append(row)
            continue
        bi, ni = split_at(bs, pub)
        if bi is None or ni is None:
            row["status"] = "該当する立会日なし"
            rows.append(row)
            continue
        base, nx = bs[bi], bs[ni]
        pc = base[4]
        row.update({
            "status": "ok", "base_d": base[0], "next_d": nx[0], "pc": pc,
            "o": nx[1], "h": nx[2], "l": nx[3], "c": nx[4],
            "gap": pct(nx[1], pc), "high": pct(nx[2], pc), "low": pct(nx[3], pc),
            "close": pct(nx[4], pc), "oc": pct(nx[4], nx[1]),
            "stop_high_like": nx[1] == nx[2] == nx[3] == nx[4],
        })
        lu = limit_up(pc)
        row["stop_high"] = nx[2] >= lu * 0.995 and nx[4] == nx[2]
        row["ctrl"] = control(bs, bi)
        # 基準日の大引け後〜翌営業日の寄り前に出た適時開示 (動画以外の材料)
        lo, hi = f"{base[0]} {close_time(base[0])}", f"{nx[0]} 09:00"
        news = [n for n in disclosures(r["code"]) if lo <= n[0] < hi]
        row["news"] = news
        row["material"] = any(MATERIAL.search(n[1]) for n in news)
        # 出来高倍率 (翌営業日 / 基準日までの20日平均)
        prev = [b[5] for b in bs[max(0, bi - 19):bi + 1]]
        row["vol_x"] = round(nx[5] / (sum(prev) / len(prev)), 2) if prev else None
        # 事前の値動き (基準日までの5日)
        if bi >= 5:
            row["pre5"] = pct(pc, bs[bi - 5][4])
        for n in (5, 20):
            j = ni + n - 1
            row[f"d{n}"] = pct(bs[j][4], pc) if j < len(bs) else None
        # ベンチマーク
        for k, key in (("2516", "g"), ("1306", "t")):
            bb = {b[0]: b for b in bench[k]}
            bd = [b[0] for b in bench[k]]
            if base[0] in bb and nx[0] in bb:
                row[f"{key}_close"] = pct(bb[nx[0]][4], bb[base[0]][4])
                row[f"{key}_gap"] = pct(bb[nx[0]][1], bb[base[0]][4])
                for n in (5, 20):
                    if row.get(f"d{n}") is None:
                        continue
                    ed = bs[ni + n - 1][0]
                    if ed in bb:
                        row[f"{key}_d{n}"] = pct(bb[ed][4], bb[base[0]][4])
        rows.append(row)
    json.dump({"generated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
               "rows": rows},
              open(os.path.join(HERE, "result.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    ok = [r for r in rows if r["status"] == "ok"]
    print(len(rows), "rows", len(ok), "ok")


if __name__ == "__main__":
    main()
