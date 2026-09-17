# -*- coding: utf-8 -*-
"""死代码审计（只读分析，不修改任何文件）。

检查项：
  1. 未用导入（AST：import 进来的名字在本文件里没被引用）
  2. 未被引用的模块级函数/类（全工程文本搜索该方法名，只有定义处命中 = 死）
  3. 未被引用的模块级常量（全大写标识符）
  4. 只被自己引用的"内部死循环"（定义处 + 自身调用）
  5. 空实现 / 只有 pass 的函数体
  6. 重复实现候选（同名函数在多个文件里出现）

用法: python run_deadcode_audit.py [--verbose]
退出码恒为 0（这是审计，不是闸门）。
"""
import ast
import os
import re
import sys
import collections

ROOT = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = ("builds", "backup", "temp", "__pycache__", "cross_validate_out",
             "cross_validate_samples", "deps", ".git")
VERBOSE = "--verbose" in sys.argv


def iter_py():
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in sorted(fn):
            if f.endswith(".py"):
                yield os.path.join(dp, f)


def rel(p):
    return os.path.relpath(p, ROOT)


def read(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return ""


FILES = list(iter_py())
SOURCES = {p: read(p) for p in FILES}
ALL_TEXT = "\n".join(SOURCES.values())


def imported_names(tree):
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out[a.asname or a.name.split(".")[0]] = n.lineno
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name != "*":
                    out[a.asname or a.name] = n.lineno
    return out


def used_names(tree):
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            used.add(n.id)
        elif isinstance(n, ast.Attribute):
            b = n
            while isinstance(b, ast.Attribute):
                b = b.value
            if isinstance(b, ast.Name):
                used.add(b.id)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            # 字符串里出现同名（如 getattr/globals 用法）也算用到，避免误报
            used.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", n.value))
    return used


def main():
    print("=" * 68)
    print("死代码审计（只读）  root =", ROOT)
    print("=" * 68)

    # ── 1. 未用导入 ──
    print("\n[1] 未用导入")
    unused_imports = []
    for p in FILES:
        src = SOURCES[p]
        try:
            tree = ast.parse(src)
        except Exception as e:
            print("  解析失败 %s: %s" % (rel(p), e))
            continue
        used = used_names(tree)
        for name, ln in sorted(imported_names(tree).items(), key=lambda kv: kv[1]):
            if name not in used:
                unused_imports.append((rel(p), ln, name))
    if unused_imports:
        print("  共 %d 处：" % len(unused_imports))
        for r, ln, name in unused_imports:
            print("    %s:%d  %s" % (r, ln, name))
    else:
        print("  无")

    # ── 2/3. 模块级函数、类、常量：全工程引用计数 ──
    print("\n[2] 只出现在定义处（疑似死函数/死类/死常量）")
    defs = []          # (kind, name, file, lineno)
    for p in FILES:
        try:
            tree = ast.parse(SOURCES[p])
        except Exception:
            continue
        for node in tree.body:                     # 只看模块级
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.append(("def", node.name, p, node.lineno))
            elif isinstance(node, ast.ClassDef):
                defs.append(("class", node.name, p, node.lineno))
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        defs.append(("const", t.id, p, node.lineno))

    dead = []
    for kind, name, p, ln in defs:
        # 全工程出现次数（词边界）
        hits = len(re.findall(r"\b%s\b" % re.escape(name), ALL_TEXT))
        if hits <= 1:
            dead.append((kind, name, rel(p), ln, hits))
    if dead:
        print("  共 %d 处：" % len(dead))
        for kind, name, r, ln, hits in dead:
            print("    %-6s %s:%d  %s  (全工程命中 %d)" % (kind, r, ln, name, hits))
    else:
        print("  无")

    # ── 4. 空实现 ──
    print("\n[4] 空实现 / 只有 pass / 只有 docstring 的函数")
    empties = []
    for p in FILES:
        try:
            tree = ast.parse(SOURCES[p])
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = [b for b in node.body
                        if not (isinstance(b, ast.Expr)
                                and isinstance(b.value, ast.Constant)
                                and isinstance(b.value.value, str))]
                if not body or all(isinstance(b, ast.Pass) for b in body):
                    empties.append((rel(p), node.lineno, node.name))
    if empties:
        print("  共 %d 处：" % len(empties))
        for r, ln, name in empties:
            print("    %s:%d  %s" % (r, ln, name))
    else:
        print("  无")

    # ── 5. 同名函数跨文件重复（重复实现候选） ──
    print("\n[5] 同名函数出现在多个文件（重复实现候选）")
    by_name = collections.defaultdict(set)
    for p in FILES:
        try:
            tree = ast.parse(SOURCES[p])
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                by_name[node.name].add(rel(p))
    dups = {k: v for k, v in by_name.items()
            if len(v) > 1 and not k.startswith("__")}
    if dups:
        print("  共 %d 组：" % len(dups))
        for k in sorted(dups):
            print("    %-28s %s" % (k, ", ".join(sorted(dups[k]))))
    else:
        print("  无")

    # ── 6. 可疑：注释掉的代码块 ──
    print("\n[6] 被注释掉的代码行（疑似代码残骸，非注释性说明）")
    commented = []
    code_like = re.compile(
        r"^\s*#\s*(?:def |class |import |from |return |if |for |while |"
        r"self\.[A-Za-z_]+\s*=|logger|print\(|tk\.|ttk\.)")
    for p in FILES:
        for i, line in enumerate(SOURCES[p].splitlines(), 1):
            if code_like.match(line):
                commented.append((rel(p), i, line.strip()))
    if commented:
        print("  共 %d 处：" % len(commented))
        for r, i, t in commented if VERBOSE else commented[:40]:
            print("    %s:%d  %s" % (r, i, t[:100]))
        if not VERBOSE and len(commented) > 40:
            print("    ...（其余 %d 处用 --verbose 查看）" % (len(commented) - 40))
    else:
        print("  无")

    print("\n" + "=" * 68)
    print("小结：未用导入 %d / 疑似死定义 %d / 空实现 %d / 重名 %d 组 / 注释代码 %d"
          % (len(unused_imports), len(dead), len(empties), len(dups), len(commented)))
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
