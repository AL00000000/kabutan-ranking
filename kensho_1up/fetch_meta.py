import json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
ids = open('cand.txt').read().split()
def one(v):
    p = subprocess.run([sys.executable, '-m', 'yt_dlp', '-j', '--skip-download',
        '--extractor-args', 'youtube:lang=ja', '--no-warnings',
        f'https://www.youtube.com/watch?v={v}'], capture_output=True)
    try:
        d = json.loads(p.stdout.decode('utf-8'))
    except Exception:
        return {'id': v, 'error': p.stderr.decode('utf-8', 'replace')[-200:]}
    return {k: d.get(k) for k in ['id','title','description','upload_date','timestamp',
            'release_timestamp','duration','live_status','availability']}
with ThreadPoolExecutor(6) as ex, open('videos_full.jsonl', 'w', encoding='utf-8') as f:
    for r in ex.map(one, ids):
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
