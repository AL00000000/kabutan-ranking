"""平日15:50に fetch_intraday を実行し、docs/data_intraday を GitHub に push する。

同リポジトリには 16:30 の売買代金ランキング更新もあるため、push 前に
git pull --rebase で最新を取り込み、非fast-forward拒否を避ける。
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import fetch_intraday

BASE = Path(__file__).parent
LOG = BASE / "daily_intraday.log"


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
    log("=== intraday daily run start ===")
    try:
        fetch_intraday.main()
    except Exception as e:
        log(f"ERROR during fetch: {e}")
        sys.exit(1)

    try:
        run(["git", "add", "docs/data_intraday"])
        status = run(["git", "status", "--porcelain", "--", "docs/data_intraday"]).stdout.strip()
        if not status:
            log("no changes to commit")
            log("=== intraday daily run done ===")
            return
        today = datetime.now().strftime("%Y-%m-%d")
        run(["git", "commit", "-m", f"Add intraday 15:24->close analysis for {today}"])
        # 16:30ランキング更新との競合回避のため、push前に最新を取り込む
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

    log("=== intraday daily run done ===")


if __name__ == "__main__":
    main()
