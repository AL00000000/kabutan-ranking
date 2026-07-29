"""監視銘柄の日足を取得して docs/data_watch を GitHub に push する。

Windows のタスクスケジューラから平日 16:30 に実行する想定。
土曜は --full を付けて全銘柄を1年分取り直し、分割・併合による過去値のズレを是正する。

タスクスケジューラ登録時の注意:
  - 操作の「開始(作業ディレクトリ)」に必ずこのリポジトリのパスを指定する
    (空だと git がリポジトリを見つけられず push に失敗する)
  - 「ユーザーがログオンしているときのみ実行」にする
    (ログオンなしだと Git Credential Manager が使えず push が落ちる)
  - 「スケジュールされた時刻に開始できなかった場合、すぐにタスクを開始する」を有効化
    (PCが落ちていた日を翌起動時に回収できる)

同リポジトリには他の日次更新もあるため、push 前に git pull --rebase で最新を取り込む。
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import fetch_watch

BASE = Path(__file__).parent
LOG = BASE / "daily_watch.log"


def log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, check=True):
    result = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stdout} {result.stderr}")
    return result


def main():
    full = datetime.now().weekday() == 5  # 土曜は1年分を取り直す
    log(f"=== watch daily run start ({'full' if full else 'incremental'}) ===")
    try:
        code = fetch_watch.main(["--full"] if full else [])
        if code != 0:
            log("ERROR: 全銘柄の取得に失敗しました")
            sys.exit(1)
    except Exception as e:
        log(f"ERROR during fetch: {e}")
        sys.exit(1)

    try:
        run(["git", "add", "docs/data_watch"])
        status = run(["git", "status", "--porcelain", "--", "docs/data_watch"]).stdout.strip()
        if not status:
            log("no changes to commit")
            log("=== watch daily run done ===")
            return
        today = datetime.now().strftime("%Y-%m-%d")
        run(["git", "commit", "-m", f"Update watchlist daily bars for {today}"])
        # 他の日次更新との競合回避のため、push前に最新を取り込む
        run(["git", "pull", "--rebase", "--autostash"], check=False)
        push = run(["git", "push"], check=False)
        if push.returncode != 0:
            log(f"push retry (first failed: {push.stderr.strip()})")
            run(["git", "pull", "--rebase", "--autostash"], check=False)
            run(["git", "push"])
        log("pushed to GitHub")
    except Exception as e:
        log(f"ERROR during git push: {e}")
        sys.exit(1)

    log("=== watch daily run done ===")


if __name__ == "__main__":
    main()
