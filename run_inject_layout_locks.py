# -*- coding: utf-8 -*-
"""注入验证：面板迁移的 6 条新锁，必须能被对应的"错"弄红。

**为什么单独一个脚本、而不是塞进 `run_ci.py`**：它会**临时改写仓库源文件**再跑探针，
中途失败还会留下脏文件。这类验证只适合手动跑、不适合进自动闸门：

    python run_inject_layout_locks.py

每次注入都是：按真实字节改写 → 跑 `run_qt_pilot_probe.py` → 断言目标锁出现在 FAIL 里
→ `finally` 还原并核对 sha256（还原不一致直接算失败）。全部通过时退出码 0。

六条注入对应本次迁移的六条锁（详见 ARCHITECTURE.md §11.2）：

  A. 插件 `_ui()` 永不返回 `api.ui`      → "真实插件面板在 Qt 后端建出来了（panel/ok）"
  B. 插件 `_ui()` 里重新 `import tkinter` → "engine_utf8_patch 里已无 Tk 构造/对话框"
  C. `QtUiFactory.pack()` 的 left/right 归位短路 → "三个动作按钮落在同一个水平行容器里"
  D. `QtUiFactory.row()` 用 `QHBoxLayout`  → "外层容器是竖直堆叠（Tk 默认 pack 方向）…"
  E. 契约清单读取返回空元组（= 悄悄降级）→ "契约清单是从 toolkit_plugin_ui.py 读到的 14 个方法…"
  F. 面板三个按钮全接到 identify     → "实验插件面板的三个按钮点了真的进对应流程…"
     （这条跑的是 **Tk 侧**探针 `run_ext_probe.py`：结构锁只看 command 非空，接线接错照样绿）

C/D 是"布局语义"锁：C 对应"pack 退化空操作"（迁移前行为），D 对应第一版把容器造成横向
（同一份插件代码在两个后端布局不同）。D 那次第一次跑**探针全绿**——原锁只比对了控件顺序的
类型、没查容器方向，收紧成"顺序类型 + isinstance(layout, QVBoxLayout)"后才变红。
"""
import hashlib
import io
import ast
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
QT = os.path.join(BASE, "qt_pilot_plugins.py")
QTH = os.path.join(BASE, "qt_pilot_theme.py")
PLUG = os.path.join(BASE, "plugins", "engine_utf8_patch.py")
TARGETS = (QT, QTH, PLUG)
PY = sys.executable

L_OK = "真实插件面板在 Qt 后端建出来了（panel/ok，而不是 skip）"
L_SRC = "engine_utf8_patch 里已无 Tk 构造/对话框（迁移真的落到 api.ui）"
L_ROW = "三个动作按钮落在同一个水平行容器里（pack(side='left') 语义）"
L_COL = "外层容器是竖直堆叠（Tk 默认 pack 方向），顺序 = 按钮行 → 路径标签 → 结果框"

INJECTIONS = [
    (PLUG, "run_qt_pilot_probe.py", "_ui() 永不返回 api.ui（等于仍自己造 Tk 控件）",
     "    ui = getattr(api if api is not None else _API, \"ui\", None)\n    if ui is not None:",
     "    ui = getattr(api if api is not None else _API, \"ui\", None)\n    if False and ui is not None:",
     L_OK),
    (PLUG, "run_qt_pilot_probe.py", "_ui() 里重新 import tkinter",
     "    from toolkit_plugin_ui import TkUiFactory",
     "    import tkinter  # noqa: F401  注入用\n    from toolkit_plugin_ui import TkUiFactory",
     L_SRC),
    (QT, "run_qt_pilot_probe.py", "pack 退化为空操作（left/right 不归位）",
     'if parent is not None and side in ("left", "right"):',
     'if False and parent is not None and side in ("left", "right"):',
     L_ROW),
    (QT, "run_qt_pilot_probe.py", "row() 退回横向容器",
     "            lay = QtWidgets.QVBoxLayout(w)",
     "            lay = QtWidgets.QHBoxLayout(w)",
     L_COL),
    (QT, "run_qt_pilot_probe.py", "契约清单读取失败（返回空元组，等于悄悄降级）",
     "                return tuple(ast.literal_eval(node.value))",
     "                return ()",
     "契约清单是从 toolkit_plugin_ui.py 读到的 14 个方法（没降级成空/旧清单）"),
    # ⑧ 接线接错：三个按钮都去 identify。结构锁（command 非空）抓不到，必须真 invoke()。
    #    这条同时跑 **Tk 侧**探针（run_ext_probe），因为"两个后端行为一致"才是迁移的验收点。
    (PLUG, "run_ext_probe.py", "面板三个按钮全部接到 identify（接线接错）",
     "on_click=lambda o=op: _gui_run(o, wrap)",
     'on_click=lambda o=op: _gui_run("identify", wrap)',
     "实验插件面板的三个按钮点了真的进对应流程（不只是 command 非空）"),
    # ── 主题映射（[9] 段）：错法都取"看起来对、其实漂了/错了"的那一类 ──
    (QTH, "run_qt_pilot_probe.py", "色板被篡改（bg 借用 surface：Qt 与 Tk 不再是同一份）",
     "    return TT.palette(mode)",
     "    _p = TT.palette(mode)\n    _p[\"bg\"] = _p[\"surface\"]   # 注入\n    return _p",
     "逐角色**一致（两个模式 × 全部 18 个颜色角色）"),
    (QTH, "run_qt_pilot_probe.py", "样式表里按钮底色写成 bg（配置对照全绿、真实像素不对）",
     '% (P["surface2"], P["text"], P["border"], ff("font")))',
     '% (P["bg"], P["text"], P["border"], ff("font")))',
     "真实像素：暗色下 7 处平面填充等于色板对应角色"),
    (QT, "run_qt_pilot_probe.py", "插件工厂里又抄了一份颜色字面量（第二份色板）",
     "    except Exception:\n        return {}",
     "    except Exception:\n        return {\"bg\": \"#123456\"}",
     "Qt 界面代码里没有第二份色板"),
    (QTH, "run_qt_pilot_probe.py", "主题模块里误用 toolkit 的 px()（Qt 会双重缩放）",
     '_CURRENT = {"mode": "dark"}',
     '_INJECTED = __import__("toolkit_theme").px(24)   # 注入：误用 px()\n'
     '_CURRENT = {"mode": "dark"}',
     "Qt 代码里不调用 toolkit 的 px()"),
    # ⑪⑫ 主题持久化接上之后新加的两条：把"断开的 Tk 依赖"接回去 / 自己整文件重写 user.ltx
    (QTH, "run_qt_pilot_probe.py", "主题模块又把 toolkit_base 拉回来（Tk 依赖重新接上）",
     "    import toolkit_theme as TT",
     "    import toolkit_base  # 注入：重新接上 Tk 依赖\n    import toolkit_theme as TT",
     "独立进程 import qt_pilot_theme 后没有 tkinter/toolkit_base"),
    (QTH, "run_qt_pilot_probe.py", "save_mode 自己整文件重写 user.ltx（会吞掉别的段）",
     "        return bool(TT.save_user_theme(mode))",
     "        import io as _io, os as _os, toolkit_platform as _tp\n"
     "        _io.open(_os.path.join(_tp.app_dir(), 'user.ltx'), 'w',\n"
     "                 encoding='utf-8').write('[theme]\\nmode = %s\\n' % mode)\n"
     "        return True",
     "主题持久化不吞别的段"),
    # ⑬ 冻结产物那条：把 Tk 依赖重新写回主题模块 → 构建期 `--exclude-module tkinter`
    #    会让冻结包在 **运行期** 直接起不来（这正是 exclude 存在的意义）。
    #    注意：单独把 exclude 拆掉是**测不出来**的（没人 import tkinter 时包出来照样干净），
    #    所以这条注入必须注入"依赖"，而不是注入"开关"。
    (QTH, "run_qt_build_probe.py", "主题模块重新 import tkinter（冻结产物须当场暴露）",
     "    import toolkit_theme as TT",
     "    import tkinter      # 注入：把 Tk 依赖接回来\n    import toolkit_theme as TT",
     "冻结 exe --themecheck：ok>0 且 bad=0"),
]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    for p in TARGETS:
        if not os.path.isfile(p):
            print("[SKIP] 缺文件（闭源/未在工作区）：%s" % p)
            return 0
    orig = {p: io.open(p, "rb").read() for p in TARGETS}
    orig_sha = {p: sha(b) for p, b in orig.items()}
    for p in TARGETS:
        print("%s sha256=%s bytes=%d" % (os.path.basename(p), orig_sha[p], len(orig[p])))
    bad = 0
    try:
        for target, probe, name, old, new, expect in INJECTIONS:
            text = orig[target].decode("utf-8")
            n = text.count(old)
            if n != 1:
                print("[SKIP] 注入点出现 %d 次（应为 1）: %s" % (n, name))
                bad += 1
                continue
            io.open(target, "wb").write(text.replace(old, new).encode("utf-8"))
            # 注入文本自己必须先能解析：否则探针会因为**语法错**而整节 SKIP，
            # 看起来像"锁没抓住"（本工具第一次跑 12 条时就这么被误导过一次：
            # 注入的第二行漏了缩进，把 try 块写坏了）。
            try:
                ast.parse(io.open(target, encoding="utf-8").read())
            except SyntaxError as e:
                print("\n=== 注入(%s): %s ===" % (os.path.basename(target), name))
                print("    [!!] 注入文本自身语法错误（这不是锁的问题）：%s" % (e,))
                bad += 1
                io.open(target, "wb").write(orig[target])
                continue
            print("\n=== 注入(%s): %s ===" % (os.path.basename(target), name))
            p = subprocess.run([PY, probe], cwd=BASE,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=1800)
            out = (p.stdout or "") + (p.stderr or "")
            fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
            tail = [ln for ln in out.splitlines() if ln.startswith("PASS ") and " FAIL " in ln]
            print("    探针 %s exit=%d  %s"
                  % (probe, p.returncode, tail[-1] if tail else "(无汇总)"))
            for ln in fails:
                print("    " + ln)
            hit = any(expect in ln for ln in fails)
            print("    %s 目标锁变红: %s" % ("[OK]" if hit else "[!!]", expect))
            if not hit:
                bad += 1
            if p.returncode == 0:
                print("    [!!] 注入后探针仍然全绿 —— 锁没抓住这个错")
                bad += 1
            io.open(target, "wb").write(orig[target])
            now = sha(io.open(target, "rb").read())
            print("    还原 %s" % ("一致" if now == orig_sha[target] else "不一致!!"))
            if now != orig_sha[target]:
                bad += 1
    finally:
        for p in TARGETS:
            io.open(p, "wb").write(orig[p])
        for p in TARGETS:
            now = sha(io.open(p, "rb").read())
            print("最终还原 %s: %s" % (os.path.basename(p),
                                      "一致" if now == orig_sha[p] else "不一致!!"))
            if now != orig_sha[p]:
                bad += 1
    print("\n注入验证结果: %s" % ("全部符合预期" if bad == 0 else "%d 处不符合预期" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
