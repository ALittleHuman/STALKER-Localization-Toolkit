# -*- coding: utf-8 -*-
"""Qt 试点验证（文件系统页）。

定位：这是**试点**的验收，不是替换验收。它锁四类事：
  1. **隔离**：`qt_pilot` 不得把 Tk 拉进来（Tk 路径仍在服役，试点期间两条路必须互不干扰）；
  2. **同清单**：控件清单与 Tk 版一致（按钮/树/面板/目录行/日志栏一个不少）；
  3. **同引擎**：真实往返（封包→扫描→加载→解包逐字节一致→重封包逐字节一致）必须全通过，
     且取字节必须走引擎 `extract_file`（不许自己手搓偏移 —— 试点第一版就是这里错的）；
  4. **线程纪律**：工作线程只经 Qt 信号回 UI，不得直接碰控件。

缺 PySide6 时按 SKIP 处理（与 `run_ui_smoke` / `cross_validate` 同一套口径：SKIP ≠ PASS）。

用法: python run_qt_pilot_probe.py   （退出码 0=全过；仅 FAIL 非零）
"""
import ast
import io
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
PILOT = os.path.join(BASE, "qt_pilot.py")

PASS, FAIL, SKIP = [], [], []
# 缺外部前提时打印这行并 exit 0（run_ci.py 里的 QT_PILOT_SKIP_MARK 必须与此字面量一致）
SKIP_MARK = "SKIP run_qt_pilot_probe"


def check(name, fn):
    try:
        r = fn()
    except Exception as e:
        FAIL.append(name)
        print("  FAIL %s -> %s: %s" % (name, type(e).__name__, e))
        return
    if r is False:
        FAIL.append(name)
        print("  FAIL %s -> 断言返回 False" % name)
        return
    PASS.append(name)
    print("  PASS %s" % name)


def skip(name, why):
    SKIP.append(name)
    print("  SKIP %s（%s）" % (name, why))


def src():
    return io.open(PILOT, encoding="utf-8").read()


def main():
    print("=" * 66)
    print("Qt 试点验证（文件系统页 · PySide6）")
    print("=" * 66)

    try:
        sys.path.insert(0, os.path.join(BASE, "file_system"))
        import qt_pilot
    except Exception as e:
        skip("全部", "导入 qt_pilot 失败：%r" % (e,))
        print("\n%s（导入失败）" % SKIP_MARK)
        print("\nPASS 0  FAIL 0  SKIP 1")
        return 0

    if not qt_pilot.QT_AVAILABLE:
        skip("全部", "PySide6 不可用：%s" % (qt_pilot.QT_IMPORT_ERROR,))
        print("\n%s（缺 PySide6）" % SKIP_MARK)
        print("\nPASS 0  FAIL 0  SKIP 1")
        return 0
    if not qt_pilot.ENGINE_AVAILABLE:
        skip("全部", "stalker_fs 不可用：%s" % (qt_pilot.ENGINE_IMPORT_ERROR,))
        print("\n%s（缺 stalker_fs）" % SKIP_MARK)
        print("\nPASS 0  FAIL 0  SKIP 1")
        return 0

    print("\n[1] 隔离：试点不得把 Tk 拉进来（两条路互不干扰）")
    code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); "
            "import qt_pilot; "
            "print('tkinter' in sys.modules, 'toolkit' in sys.modules)" % (BASE, os.path.join(BASE, "file_system")))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=BASE)
    out = (p.stdout or "").strip()
    check("qt_pilot 导入后 sys.modules 里没有 tkinter/toolkit",
          lambda: out == "False False", )
    if out != "False False":
        print("        实际：%r（stderr: %s）" % (out, (p.stderr or "")[-200:]))

    app = qt_pilot.make_app([])
    app.processEvents()                     # QApplication 必须先建（控件构造需要它）
    page = qt_pilot.QtFSPage()

    print("\n[2] 同清单：控件/面板/日志栏一个不少")
    for text in qt_pilot.TOP_BUTTONS:
        check("顶部按钮存在：%s" % text,
              lambda t=text: page.findChild(object, "btn_" + t) is not None
              or any(b.text() == t for b in page.findChildren(qt_pilot.QtWidgets.QPushButton)))
    check("数据包列表六个按钮齐全（%s）" % "、".join(qt_pilot.DB_BUTTONS),
          lambda: all(page.findChild(object, "btn_db_" + t) is not None
                      for t in qt_pilot.DB_BUTTONS))
    check("包内文件按钮齐全（%s）" % "、".join(qt_pilot.FILE_BUTTONS),
          lambda: all(page.findChild(object, "btn_file_" + t) is not None
                      for t in qt_pilot.FILE_BUTTONS))
    check("封包区按钮齐全（%s）" % "、".join(qt_pilot.PACK_BUTTONS),
          lambda: page.findChild(object, "btn_pack") is not None
          and all(page.findChild(object, "btn_pack_" + t) is not None
                  for t in qt_pilot.PACK_BUTTONS if t != "封包"))
    check("三个面板 + 三棵树 + 进度/状态/目录行存在",
          lambda: all(page.findChild(object, n) is not None for n in (
              "panel_db", "panel_file", "panel_pack", "tree_db", "tree_file", "tree_pack",
              "progress", "status", "ed_input", "ed_output", "ed_search",
              "cb_format", "cb_pack_format", "lbl_autodetect")))

    print("\n[3] 扫描规则必须与 Tk 版逐字一致（最后一个点起 .db/.sq）")
    samples = [("a.db", True), ("A.DB", True), ("a.sq", True), ("a.sqf", True),
               ("a.xdb", False), ("a.db.bak", False), ("a.txt", False), ("noext", False),
               ("dir/a.db", True), ("a.sqfs", True)]
    check("is_db_name 判定表全部一致",
          lambda: all(qt_pilot.is_db_name(n) is want for n, want in samples)) or \
        print("        " + ", ".join("%s→%s" % (n, qt_pilot.is_db_name(n)) for n, _w in samples))

    print("\n[4] 同引擎：取字节必须走 extract_file（不许手搓偏移）")
    s = src()
    check("源码里调用 engine extract_file", lambda: "extract_file(raw" in s)
    check("源码里没有手搓偏移切片（+ 8 那种）",
          lambda: not re.search(r"off\s*=\s*8\s*\+", s) and "raw[off:off" not in s)

    print("\n[5] 真实往返（临时目录内，同一份引擎）")
    rows = qt_pilot.selftest()
    for name, good, detail in rows:
        if good:
            PASS.append(name)
            print("  PASS %s%s" % (name, ("  [%s]" % detail) if detail else ""))
        else:
            FAIL.append(name)
            print("  FAIL %s  [%s]" % (name, detail))

    print("\n[6] 线程纪律：工作线程只经 Qt 信号回 UI")
    tree = ast.parse(s)

    def work_bodies():
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "work":
                found.append(node)
        return found

    def only_signals_in_work():
        for node in work_bodies():
            body = ast.dump(node)
            for bad in ("tree_db", "tree_file", "tree_pack", "progress.setValue",
                        "setText", "addTopLevelItem", "setEnabled"):
                if bad in body:
                    return False
        return bool(work_bodies())
    check("work() 里不直接碰控件（只 emit）", only_signals_in_work)
    check("work() 里确实 emit 到 bridge",
          lambda: all("bridge" in ast.dump(n) for n in work_bodies()))

    print("\n[7] 性能兜底（只防灾难性回归；绝对值随机器状态波动，不在 CI 里当硬指标）")
    r = qt_pilot.bench(repeats=12)
    print("        实时拖动 中位 %.2f ms 最大 %.2f ms ；窗口缩放 中位 %.2f ms 最大 %.2f ms"
          % (r["drag_med"], r["drag_max"], r["resize_med"], r["resize_max"]))
    check("实时拖动中位 < 150 ms（兜底阈值）", lambda: r["drag_med"] < 150.0)
    check("试点窗口逻辑尺寸与 Tk 版一致（1280x860）",
          lambda: (qt_pilot.PilotWindow().size().width() == 1280
                   and qt_pilot.PilotWindow().size().height() == 860))

    # ══════════════════════════════════════════════════════════════════
    print("\n[8] 插件槽兼容性（迁移里唯一的第三方契约风险）")
    # 契约里只有三处与工具包耦合：api.widgets、register_panel/tool 的 builder。
    # 这里锁四件事：①两个后端的 api.ui 方法面一致；②闭源插件的注册项在 Qt 宿主可用；
    # ③只认 Tk 的 builder 被如实上报且不崩；④同一份插件源码在两个后端都能建出控件。
    try:
        import qt_pilot_plugins as QPP
    except Exception as e:
        skip("插件槽兼容性", "导入 qt_pilot_plugins 失败：%r" % (e,))
        QPP = None

    if QPP is not None:
        check("契约清单是从 toolkit_plugin_ui.py 读到的 14 个方法（没降级成空/旧清单）",
              lambda: len(QPP.UI_METHODS) == 14)
        check("Qt 后端工厂与 Tk 后端工厂方法面一致",
              lambda: all(hasattr(QPP.QtUiFactory, m) for m in QPP.UI_METHODS))
        check("契约清单自己不依赖导入 Tk 模块（sys.modules 里没有 toolkit_plugin_ui）",
              lambda: "toolkit_plugin_ui" not in sys.modules)
        check("Qt 工厂声明 backend='qt'（插件可据此分支）",
              lambda: QPP.QtUiFactory.backend == "qt")

        # 真实插件目录（含闭源 nlc_sqfs.py；不在仓库时按 SKIP）
        real_dir = os.path.join(BASE, "plugins")
        closed = os.path.join(real_dir, "nlc_sqfs.py")

        def _scan_real():
            from toolkit_plugins import PluginManager
            mgr = PluginManager(real_dir, log=lambda *a, **k: None,
                                summary=lambda *a, **k: None,
                                ui_factory=QPP.QtUiFactory())
            mgr.scan()
            return mgr
        mgr = _scan_real()
        print("        真实插件注册期错误：%r | 加载错误：%r"
              % (mgr.registration_errors[:2], mgr.load_errors[:2]))
        check("真实插件在 Qt 后端的注册期无错误",
              lambda: not mgr.registration_errors and not mgr.load_errors)
        if os.path.isfile(closed):
            check("闭源插件 nlc_sqfs 的解密器在 Qt 宿主里可用（0 处 Tk 构造）",
                  lambda: len(mgr.decryptors) >= 1)
        else:
            skip("闭源插件 nlc_sqfs 解密器", "plugins/nlc_sqfs.py 不在仓库（闭源、不入库）")

        host = QPP.QtPluginHost(mgr)
        holder = qt_pilot.QtWidgets.QWidget()
        hl = qt_pilot.QtWidgets.QVBoxLayout(holder)
        rep = host.render_all("font", hl)
        print("        插件报告：%s" % rep.counts())
        for line in rep.lines():
            print("          " + line)
        check("engine_utf8_patch 的三个动作在 Qt 宿主里生成了按钮",
              lambda: len(host.buttons) == 3)

        # ── 真实插件面板：迁移后必须**真的在 Qt 上建出来**，不再是"注册了但跳过" ──
        # 这是 10.7 的验收点：api.ui 契约把 engine_utf8_patch 从 tk-only 变成可移植。
        import tempfile
        QW = qt_pilot.QtWidgets
        _ebox = None
        for _b in getattr(host, "panels", []):
            if any(x.text() == "识别" for x in _b.findChildren(QW.QPushButton)):
                _ebox = _b
                break
        _erows = [(r["kind"], r["status"], r["reason"][:40]) for r in rep.rows]
        print("        面板行：%r" % (_erows,))
        check("真实插件面板在 Qt 后端建出来了（panel/ok，而不是 skip）",
              lambda: _ebox is not None
                      and any(r["kind"] == "panel" and r["status"] == "ok" for r in rep.rows))
        check("可移植贡献没有 fail 行（不得靠异常收场）",
              lambda: not [r for r in rep.rows if r["status"] == "fail"])

        _ebtns = {b.text(): b for b in (_ebox.findChildren(QW.QPushButton) if _ebox else [])}
        _eviews = _ebox.findChildren(QW.QPlainTextEdit) if _ebox else []
        check("Qt 面板里三个动作按钮齐全", lambda: all(k in _ebtns for k in ("识别", "校验", "生成")))
        check("Qt 面板里有 1 个只读结果视图（对应 Tk 侧 state=disabled 的 Text）",
              lambda: len(_eviews) == 1 and _eviews[0].isReadOnly())

        # 布局语义：Tk 的 pack(side="left") 在这里必须落成同一水平行，其余自上而下堆叠
        _epars = {id(b.parentWidget()) for b in _ebtns.values()}
        check("三个动作按钮落在同一个水平行容器里（pack(side='left') 语义）",
              lambda: len(_epars) == 1
                      and isinstance(_ebtns["识别"].parentWidget().layout(), QW.QHBoxLayout))

        def _ecol():
            """面板竖直序列：box → wrap（builder 的外层容器）→ 按钮行 / 路径标签 / 结果框。

            多一层 wrap 是对的：Tk 侧同样是 LabelFrame → wrap(ttk.Frame) → row/label/tv。
            """
            lay = _ebox.layout()
            if lay is None or lay.count() == 0:
                return []
            wrap = lay.itemAt(0).widget()
            if wrap is None or wrap.layout() is None:
                return []
            wl = wrap.layout()
            return [type(wl.itemAt(i).widget()).__name__
                    for i in range(wl.count()) if wl.itemAt(i).widget() is not None]

        def _ecol_vertical():
            """外层容器必须真是**竖直**布局 —— 只查控件顺序类型是不够的：
            把 row() 换成 QHBoxLayout 时顺序类型照样对得上，但控件会横着排（注入验证抓过这个漏）。"""
            lay = _ebox.layout()
            wrap = lay.itemAt(0).widget() if lay is not None and lay.count() else None
            return wrap is not None and isinstance(wrap.layout(), QW.QVBoxLayout)
        _ecol_txt = (["%s/%s" % (t, "V" if _ecol_vertical() else "H")
                      for t in _ecol()[:3]] if _ebox else None)
        print("        面板竖直序列：%r" % (_ecol_txt,))
        check("外层容器是竖直堆叠（Tk 默认 pack 方向），顺序 = 按钮行 → 路径标签 → 结果框",
              lambda: _ecol()[:3] == ["QWidget", "QLabel", "QPlainTextEdit"]
                      and _ecol_vertical())

        # 回调真的绑上了：把插件的 GUI 流程换成记录器再点（不弹对话框）
        _eng = next((p["module"] for p in mgr.plugins
                     if p.get("file") == "engine_utf8_patch.py"), None)
        _calls = []
        _orig_run = getattr(_eng, "_gui_run", None) if _eng is not None else None
        if _orig_run is not None:
            _eng._gui_run = lambda op, parent=None: _calls.append(op)
        try:
            for _n in ("识别", "校验", "生成"):
                if _n in _ebtns:
                    _ebtns[_n].click()
        finally:
            if _orig_run is not None:
                _eng._gui_run = _orig_run
        print("        点击后进入插件流程的动作：%r" % (_calls,))
        check("三个按钮点了真的进插件流程（回调不是空的）",
              lambda: _calls == ["identify", "verify", "apply"])

        # 源码级：插件里不能再有 Tk 专有构造/对话框（docstring 里的说明字不算）
        def _tk_uses_in_plugin_source():
            import ast
            src_p = os.path.join(real_dir, "engine_utf8_patch.py")
            if not os.path.isfile(src_p):
                return ["<文件不存在>"]
            tree = ast.parse(io.open(src_p, encoding="utf-8").read())
            bad = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name.split(".")[0] == "tkinter":
                            bad.append("import %s" % a.name)
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").split(".")[0] == "tkinter":
                        bad.append("from %s import ..." % node.module)
                elif isinstance(node, ast.Attribute):
                    base = node.value
                    if isinstance(base, ast.Name) and base.id in ("tk", "ttk",
                                                                 "filedialog", "messagebox"):
                        bad.append("%s.%s" % (base.id, node.attr))
            return sorted(set(bad))
        _tku = _tk_uses_in_plugin_source()
        print("        插件源码里残留的 Tk 代码用法：%r" % (_tku,))
        check("engine_utf8_patch 里已无 Tk 构造/对话框（迁移真的落到 api.ui）",
              lambda: not _tku)

        # 反例锁：**故意**只认 Tk 的 builder 仍必须被如实上报为 skip（检测没失效）
        TKONLY = ('PLUGIN_INFO = {"name": "tkonly"}\n'
                  'import tkinter as tk\n'
                  'from tkinter import ttk\n'
                  'def register(api):\n'
                  '    api.register_panel("只认Tk的面板", build_panel, host="font")\n'
                  'def build_panel(parent):\n'
                  '    f = ttk.Frame(parent)\n'
                  '    f.pack(fill="x")\n'
                  '    return f\n')
        d2 = tempfile.mkdtemp(prefix="qt_tkonly_plugin_")
        io.open(os.path.join(d2, "tkonly_plugin.py"), "w", encoding="utf-8").write(TKONLY)

        def _tkonly_rows():
            from toolkit_plugins import PluginManager
            m2 = PluginManager(d2, log=lambda *a, **k: None, summary=lambda *a, **k: None,
                               ui_factory=QPP.QtUiFactory())
            m2.scan()
            h2 = QPP.QtPluginHost(m2)
            hl2 = qt_pilot.QtWidgets.QVBoxLayout(qt_pilot.QtWidgets.QWidget())
            r2 = h2.render_all("font", hl2)
            return [(x["kind"], x["status"], x["reason"]) for x in r2.rows]
        _tko = _tkonly_rows()
        print("        只认 Tk 的样例上报：%r" % ([x[:2] for x in _tko],))
        check("只认 Tk 的 builder 仍被识别为 tk-only 并上报（不崩、不算 fail）",
              lambda: any(k == "panel" and s == "skip" and "tk-only" in why
                          for k, s, why in _tko))

        check("报告里可移植贡献全部 ok", lambda: rep.counts().get("ok", 0) >= 3)

        # 双后端：同一份插件源码，Qt 侧与 Tk 侧都要能建出控件
        DUAL = ('PLUGIN_INFO = {"name": "dual"}\n'
                'def register(api):\n'
                '    open(__file__ + ".backend", "w").write(str(getattr(api, "backend", None)))\n'
                'def build_panel(parent, ui):\n'
                '    row = ui.row(parent)\n'
                '    ui.label(row, "样例：")\n'
                '    btn = ui.button(row, "点我", on_click=lambda: None)\n'
                '    ui.pack(btn)\n')
        import tempfile
        d = tempfile.mkdtemp(prefix="qt_dual_plugin_")
        dual_src = os.path.join(d, "dual_plugin.py")
        io.open(dual_src, "w", encoding="utf-8").write(DUAL)

        def _dual_qt():
            from toolkit_plugins import PluginManager
            m = PluginManager(d, log=lambda *a, **k: None, summary=lambda *a, **k: None,
                              ui_factory=QPP.QtUiFactory())
            m.scan()
            be = io.open(dual_src + ".backend", encoding="utf-8").read().strip()
            import importlib.util
            spec = importlib.util.spec_from_file_location("dual_qt", dual_src)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            h = QPP.QtPluginHost(m)
            panel = h.add_panel("双后端面板", mod.build_panel, "font", None)
            btns = panel.findChildren(qt_pilot.QtWidgets.QPushButton) if panel else []
            return be == "qt" and any(b.text() == "点我" for b in btns), be
        ok_qt, be_qt = _dual_qt()
        check("同一份插件源码在 Qt 后端建出控件（backend=%s）" % be_qt, lambda: ok_qt)

        def _dual_tk():
            snippet = (
                "import io, os, sys\n"
                "R = r'%s'\n"
                "sys.path.insert(0, R); sys.path.insert(0, os.path.join(R, 'file_system'))\n"
                "import tkinter as tk\n"
                "from tkinter import ttk\n"
                "from toolkit_plugins import PluginManager\n"
                "from toolkit_plugin_ui import TkUiFactory\n"
                "D = r'%s'\n"
                "m = PluginManager(D, log=lambda *a, **k: None, summary=lambda *a, **k: None)\n"
                "m.scan()\n"
                "import importlib.util\n"
                "spec = importlib.util.spec_from_file_location('dual_tk', os.path.join(D, 'dual_plugin.py'))\n"
                "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
                "root = tk.Tk(); root.withdraw()\n"
                "frame = ttk.Frame(root)\n"
                "mod.build_panel(frame, TkUiFactory())\n"
                "n = sum(1 for row in frame.winfo_children() for c in row.winfo_children()\n"
                "        if c.winfo_class() == 'TButton')\n"
                "print('TK_BACKEND', io.open(os.path.join(D, 'dual_plugin.py.backend'), encoding='utf-8').read().strip())\n"
                "print('TK_BUTTONS', n)\n"
                "root.destroy()\n" % (BASE, d))
            p2 = subprocess.run([sys.executable, "-c", snippet], cwd=BASE, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=180)
            out2 = p2.stdout or ""
            return ("TK_BACKEND tk" in out2 and "TK_BUTTONS 1" in out2), out2.strip()[-120:]
        ok_tk, det_tk = _dual_tk()
        print("        Tk 侧实测输出：%s" % det_tk)
        check("同一份插件源码在 Tk 后端也建出控件（独立进程实测）", lambda: ok_tk)

    # ══════════════════════════════════════════════════════════════════
    print("\n[9] 主题映射：色板/字体来自 toolkit_theme 的同一份真值，且真能切换")
    # 为什么这一节的关键锁是"子进程取 Tk 真值 + 逐角色对拍"而不是"看 Qt 侧的值":
    # Qt 侧按 AST 读的就是那份表，自己和自己比永远相等（一条永远为真的锁）。
    # 只有把 Tk **运行时**的 palette() 取回来对拍，才证明"两边同一份色板"。
    try:
        import json
        import qt_pilot_theme as qth
    except Exception as e:
        skip("主题映射", "导入 qt_pilot_theme 失败：%r" % (e,))
        qth = None

    if qth is not None:
        if not qth.theme_source_ok():
            check("toolkit_theme 拿得到（真值来源可用）", lambda: False)
            print("        导入错误：%s" % (qth.theme_import_error(),))
            qth = None
    if qth is not None:
        check("Qt 主题模块直接 import 了 toolkit_theme（同一份真值，不是抄表）",
              lambda: qth.theme_source_ok() and len(qth.COLOR_ROLES) == 18)

        # 隔离要在**子进程**里断言，不能看本进程：跑到这一节时 plugins/ 里的真实插件
        # 已经被加载过了，而它 `register()` 里写着 `from toolkit import ...` ——
        # 那会把 tkinter 拉进来（试点本体与此无关，是第三方插件的既有写法）。
        # 所以这里只证明"试点自己的主题链不含 Tk"，而且必须用独立进程证明。
        iso_code = (
            "import sys; sys.path.insert(0, %r); "
            "import qt_pilot_theme as q; "
            "print('THEMEISO', 'tkinter' in sys.modules, 'toolkit_base' in sys.modules, "
            "q.palette('dark')['bg'])" % BASE)
        ip = subprocess.run([sys.executable, "-c", iso_code], cwd=BASE,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=180)
        iout = ""
        for line in (ip.stdout or "").splitlines():
            if line.startswith("THEMEISO"):
                iout = line
        print("        主题链隔离（独立进程）：%r" % (iout or (ip.stderr or "")[-160:],))
        check("独立进程 import qt_pilot_theme 后没有 tkinter/toolkit_base（Tk 依赖确实断了）",
              lambda: iout == "THEMEISO False False %s" % qth.palette("dark")["bg"])

        # 反向证明：拦截 `import tkinter` 后仍能 import 主题链 —— 拿不到就该失败，
        # 而不是"悄悄降级成一份内置色板"。
        block_code = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "class B:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] in ('tkinter', '_tkinter', 'tkinterdnd2'):\n"
            "            raise ImportError('blocked: ' + name)\n"
            "        return None\n"
            "sys.meta_path.insert(0, B())\n"
            "import toolkit_platform, toolkit_theme, qt_pilot_theme as q\n"
            "print('BLOCKTEST', q.theme_source_ok(), q.palette('light')['bg'],\n"
            "      'tkinter' in sys.modules)\n" % BASE)
        bp = subprocess.run([sys.executable, "-c", block_code], cwd=BASE,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=240)
        bout = ""
        for line in (bp.stdout or "").splitlines():
            if line.startswith("BLOCKTEST"):
                bout = line
        print("        拦截 tkinter 后的结果：%r%s" % (
            bout, "" if bout else "（stderr: %s）" % (bp.stderr or "")[-200:]))
        check("拦截 tkinter 后仍能 import toolkit_platform/toolkit_theme/qt_pilot_theme",
              lambda: bout == "BLOCKTEST True %s False" % qth.palette("light")["bg"])

        # Tk 运行时真值（子进程里 Tk 可用；本进程必须没有 tkinter）
        dump_code = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "import toolkit_theme as th\n"
            "print('DSH_THEME ' + json.dumps({m: {'roles': th.THEMES[m],\n"
            "      'fonts': {k: list(v) for k, v in th._FONTS.items()}}\n"
            "      for m in th.THEMES}, ensure_ascii=False))" % BASE)
        dp = subprocess.run([sys.executable, "-c", dump_code], cwd=BASE,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=180)
        tk_theme = None
        for line in (dp.stdout or "").splitlines():
            if line.startswith("DSH_THEME "):
                tk_theme = json.loads(line[len("DSH_THEME "):])
        print("        Tk 侧运行时色板：%s" % (
            "取到 %d 个模式" % len(tk_theme) if tk_theme else "取不到（stderr: %s）"
            % (dp.stderr or "")[-160:]))
        check("子进程取到 Tk 运行时色板（真值可用，且两模式同名单）",
              lambda: bool(tk_theme) and sorted(tk_theme) == sorted(qth.modes()))

        def _roles_match():
            if not tk_theme:
                return False
            for m in tk_theme:
                qp_ = qth.palette(m)
                for r in qth.COLOR_ROLES:
                    if qp_.get(r) != tk_theme[m]["roles"].get(r):
                        print("          差异 %s/%s: Qt=%r Tk=%r"
                              % (m, r, qp_.get(r), tk_theme[m]["roles"].get(r)))
                        return False
            return True
        check("Qt 侧色板与 Tk 运行时**逐角色**一致（两个模式 × 全部 18 个颜色角色）",
              _roles_match)

        def _fonts_match():
            if not tk_theme:
                return False
            for m in tk_theme:
                for r in qth.FONT_ROLES:
                    spec = qth.font_spec(r, m)
                    tk_spec = tk_theme[m]["fonts"].get(r)
                    if spec is None or not tk_spec:
                        print("          缺字体角色 %s/%s" % (m, r))
                        return False
                    if (str(spec[0]), int(spec[1])) != (str(tk_spec[0]), int(tk_spec[1])):
                        print("          字体差异 %s/%s: Qt=%r Tk=%r" % (m, r, spec, tk_spec))
                        return False
                    if bool(spec[2]) != (len(tk_spec) > 2):
                        print("          加粗差异 %s/%s: Qt=%r Tk=%r" % (m, r, spec, tk_spec))
                        return False
            return True
        check("Qt 侧字体与 Tk 运行时逐角色一致（family / 磅值 / 加粗，两模式 × 6 角色）",
              _fonts_match)

        # ── 真像素：把控件渲染出来，采样**实际填充色**（不是读配置）──
        # 采样器只有一处实现（`qt_pilot.sample_theme_colors`）：开发态的这条锁与
        # 冻结包里的 `qt_pilot.py --themecheck` 共用它 —— 两份实现必然漂移，
        # 而 device-pixel-ratio 那条口径错一次就会得出错误结论（第一版就是）。
        def _sample(mode):
            return qt_pilot.sample_theme_colors(mode, app, show=True)
        s_dark = _sample("dark")
        s_light = _sample("light")
        print("        采样(暗): %r" % (s_dark,))
        print("        采样(亮): %r" % (s_light,))

        def _px_expect(sample, mode, tag):
            P = qth.palette(mode)
            want = dict((k, P[role]) for k, role in qt_pilot.SAMPLE_ROLES.items())
            bad = [k for k, want_v in want.items() if sample.get(k) != want_v]
            if bad:
                print("          %s 不符：%s" % (
                    tag, ", ".join("%s 实得 %s 期望 %s"
                                   % (k, sample.get(k), want[k]) for k in bad)))
            return not bad
        check("真实像素：暗色下 7 处平面填充等于色板对应角色（bg/surface/surface2/accent/entry_bg）",
              lambda: _px_expect(s_dark, "dark", "暗色"))
        check("真实像素：亮色下同样等于色板（切换换的是真颜色，不只是配置）",
              lambda: _px_expect(s_light, "light", "亮色"))
        check("切换真的改变了像素（两模式采样值不同，不是同一套色画两遍）",
              lambda: s_dark.get("host_bg") != s_light.get("host_bg")
                      and s_dark.get("group") != s_light.get("group"))
        check("亮暗返回：apply('dark') 后像素与 mode 都回到暗色",
              lambda: qth.apply(app, "dark") == "dark"
                      and _sample("dark").get("host_bg") == qth.palette("dark")["bg"])

        # style 参数必须真的生效（试点第一版把它丢了：插件写的 Dim.TLabel 在 Qt 上变正文色）
        check("`style=\"Dim.TLabel\"` 映射到 role=dim 且用 font_sm 磅值",
              lambda: s_dark.get("dim_role") == "dim"
                      and s_dark.get("dim_font_pt") == qth.font_spec("font_sm")[1])
        check("QSS 里 Dim/Title/Accent 三类语义样式各自的颜色都来自色板",
              lambda: all(('color:%s' % qth.role_color(r)) in qth.stylesheet("dark")
                          for r in ("text_dim", "text_bright", "accent")))

        # ── 不许有第二份色板 / 不许双重缩放 ──
        def _hex_literals(name):
            s = io.open(os.path.join(BASE, name), encoding="utf-8").read()
            return re.findall(r"""['"]#[0-9a-fA-F]{6}['"]""", s)
        _lit = dict((f, _hex_literals(f)) for f in
                    ("qt_pilot.py", "qt_pilot_plugins.py", "qt_pilot_theme.py"))
        print("        颜色字面量：%s" % dict((k, len(v)) for k, v in _lit.items()))
        check("Qt 界面代码里没有第二份色板（qt_pilot.py / qt_pilot_plugins.py 零颜色字面量）",
              lambda: not _lit["qt_pilot.py"] and not _lit["qt_pilot_plugins.py"])
        check("主题映射模块只允许 1 个颜色字面量（强调色上的文字色，与 Tk 侧同一处语义）",
              lambda: len(_lit["qt_pilot_theme.py"]) == 1)

        def _no_px():
            """按 AST 找真的 `px(...)` 调用。

            不能用正则：第一版正则 `\\bpx\\s*\\(` 把**文档里**解释"别用 px()"的那句话
            也当成了调用（探针当场红给我看）。注释/docstring 里的说明不算调用。
            """
            bad = []
            for f in ("qt_pilot.py", "qt_pilot_plugins.py", "qt_pilot_theme.py"):
                tree = ast.parse(io.open(os.path.join(BASE, f), encoding="utf-8").read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    fn = node.func
                    if isinstance(fn, ast.Name) and fn.id == "px":
                        bad.append("%s: px(...)" % f)
                    elif isinstance(fn, ast.Attribute) and fn.attr == "px":
                        bad.append("%s: %s.px(...)" % (f, getattr(fn.value, "id", "?")))
            return bad
        print("        误用 px() 的文件：%r" % (_no_px(),))
        check("Qt 代码里不调用 toolkit 的 px()（Qt 是设备无关逻辑像素，再乘一次就是双重缩放）",
              lambda: not _no_px())

        def _theme_imports():
            """主题模块不得引入**任何会把 Tk 带进来**的模块。

            `toolkit_theme` 是**允许**的（它就是那份真值，且本身 Tk 无关 —— 这一点由上面
            那条"拦截 tkinter 后仍能 import"的锁证明）；`toolkit_paths` 同理。
            第一版把 `toolkit_theme` 也列进黑名单，结果在改成真 import 之后这条锁自己红了
            —— 锁的口径得跟着设计走，不能停在旧假设上。
            """
            tree = ast.parse(io.open(os.path.join(BASE, "qt_pilot_theme.py"),
                                     encoding="utf-8").read())
            bad = []
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                for m in mods:
                    if m.split(".")[0] in ("tkinter", "tkinterdnd2", "toolkit",
                                           "toolkit_base", "toolkit_widgets"):
                        bad.append(m)
            return bad
        print("        主题模块里的 Tk 相关导入：%r" % (_theme_imports(),))
        check("主题映射模块不 import 任何 Tk 侧模块（冻结的 Qt 包里没有 Tcl/Tk）",
              lambda: not _theme_imports())

        # ── 持久化：真写一次 user.ltx（重定向到临时目录），确认两段都在 ──
        def _persist_roundtrip():
            """走真实代码路径写盘，但把 app_dir 指到临时目录（与 run_app_probe 同一打桩方式）。

            为什么要预置一个 `[ffmpeg]` 段：`user.ltx` 是**所有**工具共用的设置文件，
            "存一次主题把别的段抹掉"是这份文件最危险的失败模式（toolkit_platform 的
            docstring 专门写了这条）。所以这里不看"主题存住了没"，而是看**两段都在不在**。
            """
            import toolkit_platform as tp
            d = tempfile.mkdtemp(prefix="qt_theme_persist_")
            real = tp.app_dir
            tp.app_dir = lambda: d
            try:
                tp.save_user_values("ffmpeg", {"path": r"E:\x\ffmpeg.exe"})
                qth.save_mode("light")
                first = io.open(os.path.join(d, "user.ltx"), "rb").read().decode("utf-8")
                got = qth.load_mode()
                qth.save_mode("dark")
                second = io.open(os.path.join(d, "user.ltx"), "rb").read().decode("utf-8")
                return {"first": first, "second": second, "got": got,
                        "theme_ok": ("[theme]" in first and "light" in first
                                     and got == "light"),
                        "kept": ("[ffmpeg]" in first and "ffmpeg.exe" in first
                                 and "[ffmpeg]" in second and "ffmpeg.exe" in second)}
            finally:
                tp.app_dir = real
        _pt = _persist_roundtrip()
        print("        user.ltx（第一次写入）：%r"
              % (_pt["first"].replace("\r\n", " | ").strip(),))
        check("主题持久化：save_mode 写出的 user.ltx 里有 [theme] mode=light 且读回一致",
              lambda: _pt["theme_ok"])
        check("主题持久化不吞别的段：预置的 [ffmpeg] 段两次写入后都还在（真读文件字节）",
              lambda: _pt["kept"])

        def _no_own_ltx_write():
            """主题模块不得自己解析/整文件重写 user.ltx（必须转调 toolkit_theme）。"""
            tree = ast.parse(io.open(os.path.join(BASE, "qt_pilot_theme.py"),
                                     encoding="utf-8").read())
            bad = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                    if name in ("open", "write_text", "write_bytes", "replace"):
                        bad.append(name)
            return bad
        print("        主题模块里自己写盘的调用：%r" % (_no_own_ltx_write(),))
        check("主题模块不自己写 user.ltx（持久化走 toolkit_theme，避免整文件覆盖）",
              lambda: not _no_own_ltx_write())
        qth.apply(app, "dark")          # 收尾：把进程模式与全局样式表还原成暗色

    print("\n" + "=" * 66)
    print("PASS %d  FAIL %d  SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("失败：")
        for n in FAIL:
            print("  - " + n)
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
