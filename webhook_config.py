# -*- coding: utf-8 -*-
"""Discord webhook の取得口。

このリポジトリは**公開**しているため、webhookのURLをソースにもJSONにも置かない。
実体は C:\\Users\\yt\\automation\\webhooks.json (git管理外) に置き、ここから読む。
環境変数(キー名を大文字にして _WEBHOOK を付けたもの)があればそちらを優先する。

  from webhook_config import get_webhook
  url = get_webhook("d0901")        # 環境変数 D0901_WEBHOOK があればそれを使う
"""
import json
import os
from pathlib import Path

WEBHOOK_FILE = Path(r"C:\Users\yt\automation\webhooks.json")


def get_webhook(key):
    env = os.environ.get(key.upper() + "_WEBHOOK")
    if env:
        return env
    try:
        with WEBHOOK_FILE.open(encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, ValueError) as e:
        raise RuntimeError(f"{WEBHOOK_FILE} を読めません: {e}") from e
    url = cfg.get(key)
    if not url:
        raise RuntimeError(
            f'{WEBHOOK_FILE} に "{key}" がありません。'
            f'環境変数 {key.upper()}_WEBHOOK でも指定できます')
    return url
