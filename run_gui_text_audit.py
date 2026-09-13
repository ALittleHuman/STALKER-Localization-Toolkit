# -*- coding: utf-8 -*-
"""扫多行弹窗/提示文本（messagebox / tool_text / text= 里的 \n 串）。只读。"""
import ast
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.abspath(__file__))


def files():
    out = []
    for t in ("apps", "stalker_toolkit.py", "build_gui.py"):
        p = os.path.join(ROOT, t)
        if os.path.isfile(p):
            out.append(p)
        else:
            for d, _dirs, ns in os.walk(p):
                for n in ns:
                    if n.endswith(".py"):
                        out.append(os.path.join(d, n))
    return sorted(out)


def const_str(node):
    """把 Constant / BinOp(Add) / JoinedStr 里的字面量尽量拼出来。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a = const_str(node.left)
        b = const_str(node.right)
        if a is not None or b is not None:
            return (a or "<expr>") + (b or "<expr>")
    if isinstance(node, ast.JoinedStr):
        return "<f-string>"
    return None


rows = []
for p in files():
    src = io.open(p, encoding="utf-8", errors="replace").read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        nm = getattr(f, "id", None) or getattr(f, "attr", None)
        # messagebox.* / dialog_window / _finish_dialog / errbox
        if nm not in ("showinfo", "showwarning", "showerror", "askyesno",
                      "askokcancel", "errbox", "tool_text"):
            continue
        texts = []
        for a in node.args:
            t = const_str(a)
            if t:
                texts.append(t)
        for k in node.keywords:
            if k.arg in ("text", "message", "title"):
                t = const_str(k.value)
                if t:
                    texts.append(t)
        joined = " ⏎ ".join(texts)
        if len(joined) >= 30:
            rows.append((len(joined), os.path.relpath(p, ROOT), node.lineno, nm, joined))

rows.sort(reverse=True)
print("弹窗 / 说明类文本（>=30 字符，含多行）：共 %d 条" % len(rows))
print("=" * 100)
for ln, f, line, nm, s in rows:
    print("\n  %3d  %s L%-5d %s" % (ln, f, line, nm))
    for part in s.split(" ⏎ "):
        print("        %s" % part.replace("\n", "\\n"))
