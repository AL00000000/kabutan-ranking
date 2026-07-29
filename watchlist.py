# -*- coding: utf-8 -*-
"""監視銘柄リスト(docs/data_watch/watchlist.json)を操作する CLI。

Claude への指示でも、手元のコマンドでも同じ操作ができるようにするための入口。
フォルダは任意の深さで入れ子にでき、パスは "リスト名/フォルダ名/サブフォルダ名"
の形で指定する(先頭のセグメントは必ずリスト名または リストID)。

使用例:
  py watchlist.py ls
  py watchlist.py ls 狙い株
  py watchlist.py add 6146 7735 --to 狙い株/半導体/SPE
  py watchlist.py rm 6146 --from 狙い株/半導体/SPE
  py watchlist.py mv 6146 --from 狙い株/テーマ・材料 --to 保有/主力
  py watchlist.py mkdir 狙い株/半導体/SPE
  py watchlist.py rmdir 狙い株/半導体/SPE
  py watchlist.py rename 狙い株/半導体 半導体関連
  py watchlist.py mklist 短期
  py watchlist.py line add 6146 55000 --label 前回高値
  py watchlist.py line ls 6146

銘柄を追加しても株価データは自動では取得されない(取得は fetch_watch.py の担当)。
追加後に `py fetch_watch.py --codes 6146` を実行すると、その銘柄だけ取得できる。
"""
import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "docs" / "data_watch"
WATCHLIST = DATA / "watchlist.json"
LINES = DATA / "lines.json"
NAMES = DATA / "names.json"
RANKING_DATA = BASE / "docs" / "data"

CODE_RE = re.compile(r"^[0-9]{4}$|^[0-9]{3}[A-Z]$")
DEFAULT_LINE_COLOR = "#e0a45e"


# ---------------------------------------------------------------- 入出力

def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_watchlist():
    wl = load_json(WATCHLIST, {"version": 1, "lists": []})
    wl.setdefault("version", 1)
    wl.setdefault("lists", [])
    for lst in wl["lists"]:
        normalize_node(lst)
    return wl


def normalize_node(node):
    node.setdefault("codes", [])
    node.setdefault("folders", [])
    for child in node["folders"]:
        normalize_node(child)


# ---------------------------------------------------------------- 銘柄コード

def normalize_code(code):
    c = str(code).strip().upper()
    if not CODE_RE.match(c):
        raise SystemExit(f"銘柄コードの形式が不正です: {code} (例: 6146, 285A)")
    return c


def load_names():
    return load_json(NAMES, {})


def resolve_names(codes, names):
    """未知の銘柄名を、既存のランキングデータ(docs/data)から補完する。"""
    unknown = [c for c in codes if c not in names]
    if not unknown or not RANKING_DATA.exists():
        return names, []
    index = load_json(RANKING_DATA / "index.json", {"dates": []})
    found = []
    for d in index.get("dates", [])[:10]:
        if not unknown:
            break
        day = load_json(RANKING_DATA / f"{d}.json", None)
        if not day:
            continue
        table = {s["code"]: s["name"] for s in day.get("stocks", [])}
        for c in list(unknown):
            if c in table:
                names[c] = table[c]
                found.append(c)
                unknown.remove(c)
    return names, unknown


# ---------------------------------------------------------------- パス解決

def split_path(path):
    parts = [p for p in str(path).split("/") if p.strip()]
    if not parts:
        raise SystemExit("パスが空です (例: 狙い株/テーマ・材料)")
    return parts


def find_list(wl, name):
    for lst in wl["lists"]:
        if lst.get("name") == name or lst.get("id") == name:
            return lst
    raise SystemExit(
        f"リストが見つかりません: {name}\n"
        f"存在するリスト: {', '.join(l['name'] for l in wl['lists']) or '(なし)'}"
    )


def find_node(wl, path, create=False):
    """パスからノード(リスト or フォルダ)を返す。"""
    parts = split_path(path)
    node = find_list(wl, parts[0])
    for i, name in enumerate(parts[1:], start=1):
        child = next((f for f in node["folders"] if f["name"] == name), None)
        if child is None:
            if not create:
                raise SystemExit(f"フォルダが見つかりません: {'/'.join(parts[:i + 1])}")
            child = {"name": name, "codes": [], "folders": []}
            node["folders"].append(child)
        node = child
    return node


def find_parent(wl, path):
    """パスの親ノードと、末端の名前を返す。"""
    parts = split_path(path)
    if len(parts) == 1:
        return None, parts[0]
    return find_node(wl, "/".join(parts[:-1])), parts[-1]


def walk(node, prefix):
    """(パス, ノード) を深さ優先で列挙する。"""
    yield prefix, node
    for child in node["folders"]:
        yield from walk(child, f"{prefix}/{child['name']}")


def all_nodes(wl):
    for lst in wl["lists"]:
        yield from walk(lst, lst["name"])


# ---------------------------------------------------------------- 表示

def count_codes(node):
    n = len(node["codes"])
    for child in node["folders"]:
        n += count_codes(child)
    return n


def print_tree(node, names, indent=0, label=None):
    pad = "  " * indent
    title = label if label is not None else node["name"]
    total = count_codes(node)
    direct = len(node["codes"])
    extra = f" ({direct}銘柄" + (f" / 配下計{total}" if total != direct else "") + ")"
    print(f"{pad}{'📁 ' if indent else '📂 '}{title}{extra}")
    for code in node["codes"]:
        print(f"{pad}    {code} {names.get(code, '')}".rstrip())
    for child in node["folders"]:
        print_tree(child, names, indent + 1)


# ---------------------------------------------------------------- コマンド

def cmd_ls(args):
    wl = load_watchlist()
    names = load_names()
    if args.path:
        node = find_node(wl, args.path)
        print_tree(node, names, label=args.path)
    else:
        if not wl["lists"]:
            print("リストがありません。`watchlist.py mklist 狙い株` で作成してください。")
        for lst in wl["lists"]:
            print_tree(lst, names)
            print()
    return False


def cmd_add(args):
    wl = load_watchlist()
    node = find_node(wl, args.to, create=args.create)
    names = load_names()
    added = []
    for raw in args.codes:
        code = normalize_code(raw)
        if code in node["codes"]:
            print(f"すでに登録済み: {code} ({args.to})")
            continue
        node["codes"].append(code)
        added.append(code)
    if args.name and len(added) == 1:
        names[added[0]] = args.name
    if not added:
        return False

    names, unknown = resolve_names(added, names)
    save_json(NAMES, dict(sorted(names.items())))
    save_json(WATCHLIST, wl)
    for code in added:
        print(f"追加: {code} {names.get(code, '')} -> {args.to}")
    if unknown:
        print(f"※ 銘柄名が未取得: {', '.join(unknown)} "
              f"(--name で指定するか、fetch_watch.py 実行時に取得されます)")
    print(f"※ 株価データは未取得です。`py fetch_watch.py --codes {','.join(added)}` で取得できます。")
    return True


def cmd_rm(args):
    wl = load_watchlist()
    targets = [normalize_code(c) for c in args.codes]
    removed = []
    if args.source:
        nodes = [(args.source, find_node(wl, args.source))]
    else:
        nodes = list(all_nodes(wl))
    for path, node in nodes:
        for code in targets:
            if code in node["codes"]:
                node["codes"].remove(code)
                removed.append((code, path))
    if not removed:
        where = args.source or "すべてのリスト"
        raise SystemExit(f"該当する銘柄がありません: {', '.join(targets)} ({where})")
    save_json(WATCHLIST, wl)
    for code, path in removed:
        print(f"削除: {code} <- {path}")
    return True


def cmd_mv(args):
    wl = load_watchlist()
    src = find_node(wl, args.source)
    dst = find_node(wl, args.to, create=args.create)
    moved = []
    for raw in args.codes:
        code = normalize_code(raw)
        if code not in src["codes"]:
            print(f"移動元にありません: {code} ({args.source})")
            continue
        src["codes"].remove(code)
        if code not in dst["codes"]:
            dst["codes"].append(code)
        moved.append(code)
    if not moved:
        return False
    save_json(WATCHLIST, wl)
    for code in moved:
        print(f"移動: {code} {args.source} -> {args.to}")
    return True


def cmd_mkdir(args):
    wl = load_watchlist()
    find_node(wl, args.path, create=True)
    save_json(WATCHLIST, wl)
    print(f"フォルダ作成: {args.path}")
    return True


def cmd_rmdir(args):
    wl = load_watchlist()
    parent, name = find_parent(wl, args.path)
    if parent is None:
        raise SystemExit("リストの削除は rmlist を使ってください。")
    target = next((f for f in parent["folders"] if f["name"] == name), None)
    if target is None:
        raise SystemExit(f"フォルダが見つかりません: {args.path}")
    n = count_codes(target)
    if n and not args.force:
        raise SystemExit(f"{args.path} には{n}銘柄が入っています。削除するなら --force を付けてください。")
    parent["folders"].remove(target)
    save_json(WATCHLIST, wl)
    print(f"フォルダ削除: {args.path} ({n}銘柄ごと)" if n else f"フォルダ削除: {args.path}")
    return True


def cmd_rename(args):
    wl = load_watchlist()
    parts = split_path(args.path)
    if len(parts) == 1:
        node = find_list(wl, parts[0])
    else:
        parent, name = find_parent(wl, args.path)
        node = next((f for f in parent["folders"] if f["name"] == name), None)
        if node is None:
            raise SystemExit(f"フォルダが見つかりません: {args.path}")
    old = node["name"]
    node["name"] = args.newname
    save_json(WATCHLIST, wl)
    print(f"改名: {old} -> {args.newname}")
    return True


def cmd_mklist(args):
    wl = load_watchlist()
    if any(l.get("name") == args.name for l in wl["lists"]):
        raise SystemExit(f"同名のリストがすでにあります: {args.name}")
    list_id = args.id or f"list{len(wl['lists']) + 1}"
    if any(l.get("id") == list_id for l in wl["lists"]):
        raise SystemExit(f"同じIDのリストがすでにあります: {list_id}")
    wl["lists"].append({"id": list_id, "name": args.name, "codes": [], "folders": []})
    save_json(WATCHLIST, wl)
    print(f"リスト作成: {args.name} (id={list_id})")
    return True


def cmd_rmlist(args):
    wl = load_watchlist()
    lst = find_list(wl, args.name)
    n = count_codes(lst)
    if n and not args.force:
        raise SystemExit(f"{args.name} には{n}銘柄が入っています。削除するなら --force を付けてください。")
    wl["lists"].remove(lst)
    save_json(WATCHLIST, wl)
    print(f"リスト削除: {args.name}")
    return True


# ---------------------------------------------------------------- ライン

def load_lines():
    data = load_json(LINES, {"version": 1, "lines": {}})
    data.setdefault("lines", {})
    return data


def cmd_line(args):
    data = load_lines()
    lines = data["lines"]

    if args.line_command == "ls":
        codes = [normalize_code(args.code)] if args.code else sorted(lines)
        names = load_names()
        for code in codes:
            entries = lines.get(code, [])
            print(f"{code} {names.get(code, '')}".rstrip())
            for i, e in enumerate(entries):
                label = f" {e['label']}" if e.get("label") else ""
                print(f"  [{i}] {e['price']}円{label}")
            if not entries:
                print("  (なし)")
        return False

    code = normalize_code(args.code)
    if args.line_command == "add":
        entry = {"price": float(args.price), "label": args.label or "",
                 "color": args.color or DEFAULT_LINE_COLOR}
        lines.setdefault(code, []).append(entry)
        lines[code].sort(key=lambda e: e["price"], reverse=True)
        save_json(LINES, data)
        print(f"ライン追加: {code} {entry['price']}円 {entry['label']}".rstrip())
        return True

    if args.line_command == "rm":
        entries = lines.get(code, [])
        if not entries:
            raise SystemExit(f"{code} にラインがありません。")
        if args.index is not None:
            if not 0 <= args.index < len(entries):
                raise SystemExit(f"インデックスが範囲外です: {args.index} (0〜{len(entries) - 1})")
            gone = entries.pop(args.index)
        elif args.price is not None:
            target = float(args.price)
            gone = next((e for e in entries if abs(e["price"] - target) < 1e-6), None)
            if gone is None:
                raise SystemExit(f"{code} に {target}円 のラインがありません。")
            entries.remove(gone)
        else:
            raise SystemExit("削除するラインを --index か --price で指定してください。")
        if not entries:
            lines.pop(code)
        save_json(LINES, data)
        print(f"ライン削除: {code} {gone['price']}円 {gone.get('label', '')}".rstrip())
        return True

    if args.line_command == "clear":
        if code not in lines:
            raise SystemExit(f"{code} にラインがありません。")
        n = len(lines.pop(code))
        save_json(LINES, data)
        print(f"ライン全削除: {code} ({n}本)")
        return True

    return False


# ---------------------------------------------------------------- エントリポイント

def build_parser():
    p = argparse.ArgumentParser(description="監視銘柄リストの編集")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("ls", help="リスト/フォルダをツリー表示")
    s.add_argument("path", nargs="?", help="リスト名 または リスト名/フォルダ名")
    s.set_defaults(func=cmd_ls)

    s = sub.add_parser("add", help="銘柄を追加")
    s.add_argument("codes", nargs="+")
    s.add_argument("--to", required=True, help="追加先のパス (例: 狙い株/半導体/SPE)")
    s.add_argument("--name", help="銘柄名を明示指定する(1銘柄のときのみ)")
    s.add_argument("--create", action="store_true", help="追加先のフォルダがなければ作る")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("rm", help="銘柄を削除")
    s.add_argument("codes", nargs="+")
    s.add_argument("--from", dest="source", help="削除元のパス(省略時は全リストから削除)")
    s.set_defaults(func=cmd_rm)

    s = sub.add_parser("mv", help="銘柄を別のフォルダへ移動")
    s.add_argument("codes", nargs="+")
    s.add_argument("--from", dest="source", required=True)
    s.add_argument("--to", required=True)
    s.add_argument("--create", action="store_true", help="移動先のフォルダがなければ作る")
    s.set_defaults(func=cmd_mv)

    s = sub.add_parser("mkdir", help="フォルダを作成(親も自動で作る)")
    s.add_argument("path")
    s.set_defaults(func=cmd_mkdir)

    s = sub.add_parser("rmdir", help="フォルダを削除")
    s.add_argument("path")
    s.add_argument("--force", action="store_true", help="銘柄が入っていても削除する")
    s.set_defaults(func=cmd_rmdir)

    s = sub.add_parser("rename", help="リスト/フォルダの名前を変更")
    s.add_argument("path")
    s.add_argument("newname")
    s.set_defaults(func=cmd_rename)

    s = sub.add_parser("mklist", help="リストを作成")
    s.add_argument("name")
    s.add_argument("--id", help="内部ID(省略時は自動採番)")
    s.set_defaults(func=cmd_mklist)

    s = sub.add_parser("rmlist", help="リストを削除")
    s.add_argument("name")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_rmlist)

    s = sub.add_parser("line", help="意識するラインの編集")
    ls_ = s.add_subparsers(dest="line_command", required=True)

    t = ls_.add_parser("add")
    t.add_argument("code")
    t.add_argument("price", type=float)
    t.add_argument("--label", help="ラベル (例: 前回高値)")
    t.add_argument("--color", help=f"色 (既定: {DEFAULT_LINE_COLOR})")

    t = ls_.add_parser("rm")
    t.add_argument("code")
    t.add_argument("--index", type=int, help="`line ls` で表示される番号")
    t.add_argument("--price", type=float, help="価格で指定")

    t = ls_.add_parser("clear")
    t.add_argument("code")

    t = ls_.add_parser("ls")
    t.add_argument("code", nargs="?")

    s.set_defaults(func=cmd_line)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        changed = args.func(args)
    except BrokenPipeError:  # head などに繋いだとき
        return 0
    if changed:
        print("\n変更を保存しました。git commit & push を忘れずに。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
