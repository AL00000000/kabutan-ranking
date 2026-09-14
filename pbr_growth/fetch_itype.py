# -*- coding: utf-8 -*-
"""投資部門別売買状況(週次)を Wayback から全期間ぶん取る。

「個人の資金がグロースに入りにくくなった」は本来、価格から推測するものではなく
JPXが直接公表している。市場別にシートが分かれていて、個人の売り/買い/差引きが
そのまま読める。

  2015-01〜2022-03 … TSE 1st / TSE 2nd / TSE Mothers / TSE JASDAQ
  2022-04〜        … TSE Prime / TSE Standard / TSE Growth

JPX本家は直近5週しか置いていないので Wayback から拾う。
CDX で拾ったURL一覧(itype_cdx.json)を使う。590週・欠損月ゼロ(2015-01〜2026-07)。

出力: itype_raw/<YYMMW>.xls
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "itype_raw"
CDX = BASE / "itype_cdx.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SLEEP = 3.0          # Wayback は連打すると 429/503 を返す
RETRY = 3


def main():
    OUT.mkdir(exist_ok=True)
    rows = json.load(open(CDX, encoding="utf-8"))
    seen, targets = set(), []
    for ym, ts, orig in sorted(rows):
        if ym in seen:
            continue        # 同じ週の重複スナップショットは1つでよい
        seen.add(ym)
        targets.append((ym, ts, orig))

    done = fail = skip = 0
    failed = []
    for i, (ym, ts, orig) in enumerate(targets, 1):
        dst = OUT / f"{ym}.xls"
        if dst.exists() and dst.stat().st_size > 20000:
            skip += 1
            continue
        u = f"https://web.archive.org/web/{ts}id_/{orig}"
        for a in range(RETRY):
            try:
                d = urllib.request.urlopen(
                    urllib.request.Request(u, headers={"User-Agent": UA}),
                    timeout=120).read()
                if len(d) < 20000:
                    raise ValueError(f"too small {len(d)}")
                dst.write_bytes(d)
                done += 1
                break
            except Exception as e:
                if a == RETRY - 1:
                    fail += 1
                    failed.append([ym, repr(e)[:90]])
                else:
                    time.sleep(10 * (a + 1))
        if i % 25 == 0:
            print(f"{i}/{len(targets)} done={done} skip={skip} fail={fail}", flush=True)
        time.sleep(SLEEP)

    (BASE / "itype_failed.json").write_text(
        json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完了 取得={done} スキップ={skip} 失敗={fail} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
