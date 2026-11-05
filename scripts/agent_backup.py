import os
import sqlite3
import sys


def backup(src: str, dest_dir: str, name: str) -> None:
    if not os.path.exists(src):
        print("missing", src)
        return
    source = sqlite3.connect("file:" + src + "?mode=ro", uri=True)
    target = sqlite3.connect(os.path.join(dest_dir, name))
    source.backup(target)
    target.close()
    source.close()
    print("backed up", name)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: agent_backup.py <dest-dir>")
    dest = os.path.abspath(sys.argv[1])
    os.makedirs(dest, exist_ok=True)
    backup(os.path.expanduser("~/codespace/ai-hedge-fund/fund.db"), dest, "fund.db")
    backup(
        os.path.expanduser("~/.hedge-fund/research/providers.db"),
        dest,
        "providers.db",
    )


if __name__ == "__main__":
    main()
