# -*- coding: utf-8 -*-
"""静态守卫的自测（证明守卫不是"永远 OK"的空壳）。

一个从不报错的守卫等于没有守卫，所以这里用**故意违规的样例**验证每条规则都能命中，
并用**合法样例**验证不误伤（否则守卫会被绕过或长期挂红）。

用法: python run_guard_selftest.py   （退出码 0=守卫可信，1=守卫失效）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolkit_guard as G  # noqa: E402

# 必须被拦下（每条规则至少一个样例）
MUST_FAIL = {
    "颜色字面量": 'label = tk.Label(root, fg="#f14c4c")\n',
    "字体字面量": 'txt = tk.Text(root, font=("Consolas", 10))\n',
    "手写窗口标志": 'subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW)\n',
    "硬编码槽位": 'plugin_slot_bar(self.root, "fs", app=self)\n',
    "硬编码槽位-area": 'tool_dropdown(top, HOST_FS, "format", var, vals)\n',
    "硬编码槽位-查询方法": 'keys = plugins.option_entries_for("fs", "format")\n',
    "硬编码槽位-查询方法2": 'items = plugins.menu_items_for("xml", "toolbar")\n',
}

# 必须放行（否则会误伤，守卫就没人愿意留）
MUST_PASS = {
    "语义色": 'label = tk.Label(root, fg=color("text_dim"))\n',
    "主题字体": 'e = tk.Entry(root, font=color("font_mono"))\n',
    "T 里取字体": 'e = ttk.Entry(row, font=T["font_mono"])\n',
    "常量槽位": 'plugin_slot_bar(self.root, HOST_FS, app=self)\n',
    "常量 area": 'tool_dropdown(top, HOST_FS, AREA_FORMAT, var, vals)\n',
    "隐藏标志走封装": 'subprocess.run(cmd, **hidden_kwargs())\n',
    "逃生舱": 'x = tk.Label(root, fg="#fff")  # guard: allow 设计器要求固定白\n',
}


def _scan(source):
    with tempfile.TemporaryDirectory() as d:
        apps = os.path.join(d, "apps")
        os.makedirs(apps)
        with open(os.path.join(apps, "sample_app.py"), "w", encoding="utf-8") as f:
            f.write(source)
        return G.check_apps(apps)


# 覆盖集：正则必须认得常量表里的**每一个**挂载点。
# 防的是"守卫的点名清单与 toolkit_plugins 漂移"：原先两处各手抄一份，往表里加一个
# 新挂载点（HOST_X / AREA_X）时守卫不会覆盖它 —— 规则对新位置**静默失效**。
# 现在正则由常量表派生，这里再从两个方向钉住：
#   ① 逐名命中：表里每个名字都必须真被守卫抓到（证明派生出来的正则确实工作）；
#   ② 清单不漂移：派生的点名集合必须与下面这份**钉住**的清单一致 ——
#      刻意加/改挂载点时请同步这里，别让覆盖范围悄悄缩水（少了名字也要同步）。
PINNED_HOSTS = ("convert", "font", "fs", "text", "video", "xml")
PINNED_AREAS = ("bottom", "context", "filter", "format", "game", "lang",
                "pack_format", "size", "source_enc", "suffix", "toolbar", "top_bar")


def main():
    ok = True
    print("=== 必须被拦下（每条规则都要能命中） ===")
    for name, src in MUST_FAIL.items():
        found = _scan(src)
        hit = bool(found)
        print("  %-4s %s%s" % ("PASS" if hit else "FAIL", name,
                               "" if hit else "   <- 守卫漏检，规则失效"))
        ok = ok and hit

    print("=== 必须放行（不得误伤合法写法） ===")
    for name, src in MUST_PASS.items():
        found = _scan(src)
        clean = not found
        print("  %-4s %s%s" % ("PASS" if clean else "FAIL", name,
                               "" if clean else "   <- 误伤: %s" % found))
        ok = ok and clean

    print("=== 组合：违规与合法混在同一文件 ===")
    mixed = MUST_PASS["语义色"] + MUST_FAIL["颜色字面量"] + MUST_PASS["常量槽位"]
    found = _scan(mixed)
    good = len(found) == 1 and found[0][2] == "颜色字面量"
    print("  %-4s 只报违规那一行" % ("PASS" if good else "FAIL"))
    ok = ok and good

    print("=== 覆盖集：常量表里每个挂载点都必须被守卫认得 ===")
    for label, names, tmpl, pinned in (
            ("host", G.HOST_POINT_NAMES,
             'plugin_slot_bar(self.root, "%s", app=self)\n', PINNED_HOSTS),
            ("area", G.AREA_POINT_NAMES,
             'tool_dropdown(top, HOST_FS, "%s", var, vals)\n', PINNED_AREAS)):
        miss = [n for n in names if not _scan(tmpl % n)]
        print("  %-4s %s 逐名命中（%d 个）%s"
              % ("PASS" if not miss else "FAIL", label, len(names),
                 "" if not miss else "   <- 守卫不认识: %s" % ", ".join(miss)))
        ok = ok and not miss
        drift = sorted(set(names) ^ set(pinned))
        print("  %-4s %s 点名清单与钉住的一致%s"
              % ("PASS" if not drift else "FAIL", label,
                 "" if not drift else
                 "   <- 差异 %s（改挂载点就要同步本文件，别让覆盖缩水）" % (drift,)))
        ok = ok and not drift

    print("\n结果:", "守卫可信" if ok else "守卫失效")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
