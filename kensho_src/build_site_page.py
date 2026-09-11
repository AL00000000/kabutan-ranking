# -*- coding: utf-8 -*-
"""highdiv.html (Artifact用) -> docs/kensho.html (サイト埋め込み用) に変換する。
   サイトは固定ダークテーマなので data-theme="dark" を固定し、配色をサイト側に寄せる。"""
import io, os
SRC = 'highdiv.html'
DST = r'C:\Users\yt\kabutan-ranking\docs\kensho.html'

body = open(SRC, encoding='utf-8').read()

OVERRIDE = """
<style>
/* --- サイト(kabutan-ranking)のダーク配色に合わせる --- */
:root[data-theme="dark"]{
  --bg:#0a0f1c; --surface:#101830; --surface-2:#16203c; --line:#1e2a48; --line-soft:#17203a;
  --ink:#dbe4f5; --ink-2:#9fb0cd; --ink-3:#7787a5;
  --brass:#ffd166; --brass-soft:#c9952f; --teal:#5fd3b4; --slate:#4da3ff; --nikkei:#ff8f7a;
  --pos:#4da3ff; --neg:#ff5b6a; --band:#16203c;
  --shadow:0 1px 2px rgba(0,0,0,.45),0 8px 24px -12px rgba(0,0,0,.75);
}
body{font-size:15px}
.wrap{max-width:100%;padding:0 4px 48px}
header.top{padding:20px 0 26px}
</style>
"""

html = (
    '<!doctype html>\n<html lang="ja" data-theme="dark">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
    + body.split('<div class="wrap">')[0]      # head部(title/fonts/style)
    + OVERRIDE +
    '</head>\n<body>\n'
    + '<div class="wrap">' + body.split('<div class="wrap">', 1)[1]
    + '\n</body>\n</html>\n'
)
os.makedirs(os.path.dirname(DST), exist_ok=True)
open(DST, 'w', encoding='utf-8').write(html)
print('wrote', DST, len(html), 'bytes')
