# -*- coding: utf-8 -*-
"""Hub 级框架集成验证（1 Hub + 6 组件 + 插件系统）。

与既有探针的区别：
    * `run_app_probe` 只**单独构造**六个 App；
    * `run_ext_probe` 只管**槽位寻址**；
    本探针按 **Hub 的真实装配顺序**把两者拼起来，并**真的放一个插件文件进去**，
    验证"框架"这一层：六个内置栏目 + 插件栏目 + 插件贡献全部在同一个运行态里成立。

覆盖：
    1. 六个内置栏目按 TOOLS 顺序装配成功
    2. 插件文件被扫描并注册（PLUGIN_INFO / register(api)）
    3. 插件栏目（register_tool）进入 Hub 的 TOOLS 列表并按 order 排序
    4. 插件对六个组件的贡献在**同一 Hub 运行态**下生效（toolbar / 下拉 / 面板 / 模式 / 格式）
    5. 插件可在 Hub 装配后被重新扫描（重建界面时不炸）

用法: python run_hub_probe.py   （退出码 0=全过）
"""
import os
import shutil
import sys
import tempfile
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
for _s in ("file_system", "font_pack", "plugins"):
    _p = os.path.join(BASE, _s)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# 隔离：探针插件写进**本进程独有**的临时目录。
# 原先写进仓库 plugins/，与 run_ext_probe（也写 zz_*.py）并发时互相覆盖，
# 而且会把别的探针插件算进"插件栏目"计数（`TOOLS 总数 = 6 内置 + 1 插件`
# 因此随机 FAIL）。PluginManager.shared() 接受任意目录，Hub 那条加载路径
# 完全一样，因此隔离不损失覆盖。
PLUGIN_DIR = tempfile.mkdtemp(prefix="hub_probe_plugins_")

PASS, FAIL, SKIP = [], [], []


def check(name, fn, detail=""):
    """fn 抛异常即 FAIL；**显式返回 False 也算 FAIL**。

    早期只判异常，于是 `check("x", lambda: a == b)` 这类"纯布尔表达式"永远不会失败
    —— False 被静默丢弃，断言空转但 PASS 照加。返回 None 仍算通过。
    """
    try:
        r = fn()
    except Exception as e:
        FAIL.append(name)
        print("  FAIL %s -> %s: %s%s" % (name, type(e).__name__, e,
                                         ("  " + detail) if detail else ""))
        for line in traceback.format_exc().strip().splitlines()[-3:]:
            print("       " + line.strip())
        return
    if r is False:
        FAIL.append(name)
        print("  FAIL %s -> 断言返回 False%s" % (name, ("  " + detail) if detail else ""))
        return
    PASS.append(name)
    print("  PASS %s" % name)


def skip(name, why):
    SKIP.append(name)
    print("  SKIP %s（%s）" % (name, why))


PLUGIN_NAME = "zz_hub_probe.py"
PLUGIN_SRC = '''# -*- coding: utf-8 -*-
PLUGIN_INFO = {"name": "Hub集成探针", "version": "0.1", "author": "probe"}


def build_tab(parent):
    """插件栏目：与内置六工具同契约 builder(parent)。"""
    import tkinter as tk
    lbl = tk.Label(parent, text="HUB-PLUGIN-TAB")
    lbl.pack()


def register(api):
    # ① 加一个 Hub 顶级栏目
    api.register_tool("探针栏目", build_tab, order=5)
    # ② 往六个组件里加动作（toolbar 槽）
    api.register_command("act", "HUB-动作", lambda app=None: None)
    for host in ("fs", "convert", "text", "xml", "video", "font"):
        api.register_menu_item(command="act", host=host, location="toolbar")
    # ③ 往已有下拉加条目
    api.register_option_entry("fs", "format", "HUB-格式")
    api.register_option_entry("font", "game", "HUB-游戏")
    # ④ 新建一个下拉（组件本来没有时）
    # register_option 的 label 是**下拉自己的显示名**（控件左侧的标签），
    # choices 才是菜单里逐个渲染的条目值 —— 因此下面这条检查 Text 必须取
    # label（"HUB-选项"），取 choices（'A'/'B'）是查错了对象。
    api.register_option("HUB-选项", ["A", "B"], callback=lambda v, app=None: None,
                        host="video", area="top_bar")
    # ⑤ 贡献一个面板
    api.register_panel("HUB-面板", lambda parent: None, host="xml", area="top_bar")
    # ⑥ 贡献一种比较模式（新列 + 新筛选 + 新算法）
    api.register_compare_mode(
        "HUB-模式",
        [("rel", "文件", 280), ("status", "状态", 60), ("hub_col", "HUB列", 120)],
        lambda ctx, pa, pb, rel: {"rel": rel, "consistent": False, "mode": "HUB-模式",
                                  "hub_col": "v"},
        row_builder=lambda r: ("diff", set()),
        filters=[("全部", ("diff",), None)], order=1)
    # ⑦ 贡献一个格式
    api.register_format("HUB格式", {"unpack": lambda raw: [],
                                    "pack": lambda files: b"HUB", "description": "探针格式"})
'''


def main():
    print("=" * 66)
    print("Hub 级框架集成验证（1 Hub + 6 组件 + 插件系统）")
    print("=" * 66)

    # 放一个真插件进去
    plug_path = os.path.join(PLUGIN_DIR, PLUGIN_NAME)
    with open(plug_path, "w", encoding="utf-8") as f:
        f.write(PLUGIN_SRC)

    root = None
    try:
        import tkinter as tk
        from tkinter import messagebox
        for fn in ("showinfo", "showwarning", "showerror"):
            setattr(messagebox, fn, lambda *a, **k: "ok")
        try:
            from tkinterdnd2 import TkinterDnD
            root = TkinterDnD.Tk()
        except Exception:
            root = tk.Tk()
        root.withdraw()

        from tkinter import ttk
        from toolkit import color, PluginManager, apply_theme
        import stalker_toolkit as HUB

        apply_theme()

        # ── 1. 插件宿主扫描（与 Hub 启动同一路径）──
        pm = PluginManager.shared(PLUGIN_DIR,
                                  log=lambda m, t="info": None,
                                  summary=lambda m, t="info": None)
        pm.scan()

        print("\n[1] 插件系统：扫描与注册")
        loaded = [p["file"] for p in pm.plugins]
        check("探针插件已被扫描到", lambda: PLUGIN_NAME in loaded)
        info = next((p["info"] for p in pm.plugins if p["file"] == PLUGIN_NAME), {})
        check("插件 PLUGIN_INFO 被读取",
              lambda: info.get("name") == "Hub集成探针")
        check("插件 register() 成功（无 load_errors）",
              lambda: not [e for e in pm.load_errors if PLUGIN_NAME in e])

        print("\n[1b] 插件后端契约：Tk 侧必须继续提供 api.backend / api.ui")
        # 迁移 Qt 时给契约新增了两个字段（见 toolkit_plugin_ui.py / ARCHITECTURE 第十一节）：
        #   api.backend —— "tk"/"qt"，插件据此分支；
        #   api.ui      —— 后端无关的控件工厂，插件只写一遍就能跑在两个后端。
        # Tk 侧若哪天把这两个字段丢了，Qt 迁移后的插件就会在 Tk 后端上炸；所以在这里钉住。
        def _tk_api_contract():
            from toolkit_plugin_ui import UI_METHODS
            api = pm._make_api("contract_probe.py", {"name": "契约探针"})
            assert getattr(api, "backend", None) == "tk", \
                "Tk 侧 api.backend 应为 'tk'，实际 %r" % (getattr(api, "backend", None),)
            ui = getattr(api, "ui", None)
            assert ui is not None, "Tk 侧 api.ui 缺失（插件无法只写一遍）"
            missing = [m for m in UI_METHODS if not hasattr(ui, m)]
            assert not missing, "Tk 侧 api.ui 缺方法：%s" % (missing,)
            assert hasattr(api, "widgets"), "api.widgets 必须保留（既有插件仍在用）"
            return True
        check("Tk 侧 api.backend == 'tk' 且 api.ui 方法面完整（api.widgets 保留）",
              _tk_api_contract)

        print("\n[2] 插件栏目进入 Hub 的 TOOLS（直接核对 Hub 的真实清单）")
        # 关键：这里用的是 Hub 模块里的真实常量，而不是探针自己手抄一份。
        # 手抄版曾经是"Hub 少接一个组件也照样全绿"的盲区。
        hub_names = [n for n, _f in HUB.BUILTIN_TOOLS]
        check("Hub 内置栏目恰好 6 个", lambda: len(hub_names) == 6,
              "实际 %d：%s" % (len(hub_names), hub_names))
        check("Hub 内置栏目名称与顺序固定", lambda: hub_names == [
            "文件系统", "编码转换", "文本提取", "XML校对", "视频转换", "汉化包生成"],
            str(hub_names))
        check("Hub 内置栏目的 builder 均可调用",
              lambda: all(callable(f) for _n, f in HUB.BUILTIN_TOOLS))
        TOOLS = list(HUB.BUILTIN_TOOLS)
        for tool in sorted(pm.tools, key=lambda t: t.get("order", 0)):
            TOOLS.append((tool.get("name") or "插件", tool.get("builder")))
        names = [n for n, _f in TOOLS]
        check("内置六栏目固定在前，插件栏目追加在后",
              lambda: names[:6] == hub_names and names[6:] == ["探针栏目"],
              str(names))
        check("TOOLS 总数 = 6 内置 + 1 插件",
              lambda: len(TOOLS) == 7, "实际 %d" % len(TOOLS))
        check("插件栏目 builder 可调用",
              lambda: callable(dict(TOOLS)["探针栏目"]))

        print("\n[3] Hub 装配：逐个 factory(tab)，与 rebuild() 同契约")
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)
        built, failures = {}, []
        for label, factory in TOOLS:
            tab = tk.Frame(nb, bg=color("bg"))
            nb.add(tab, text=label)
            try:
                built[label] = factory(tab)
            except Exception as e:
                failures.append("%s: %s" % (label, e))
        check("七个栏目全部装配成功（无失败）",
              lambda: not failures, "; ".join(failures))
        check("Notebook 里确有 7 个标签页", lambda: len(nb.tabs()) == 7)

        print("\n[4] 插件对六个组件的贡献在同一运行态生效")
        apps = {k: v for k, v in built.items() if k != "探针栏目"}

        def _find_btn(w, text):
            try:
                if isinstance(w, ttk.Button) and str(w.cget("text")) == text:
                    return True
            except Exception:
                pass
            for c in w.winfo_children():
                if _find_btn(c, text):
                    return True
            return False

        for label, host_key in (("文件系统", "fs"), ("编码转换", "convert"),
                                ("文本提取", "text"), ("XML校对", "xml"),
                                ("视频转换", "video"), ("汉化包生成", "font")):
            app = apps.get(label)
            slot = getattr(app, "_slot_bar", None) if app is not None else None
            has = bool(slot is not None and slot.frame is not None
                       and _find_btn(slot.frame, "HUB-动作"))
            check("toolbar 贡献生效 @%s" % host_key, lambda has=has: has)

        check("下拉条目贡献 @fs/format",
              lambda: "HUB-格式" in list(apps["文件系统"].fmt_keys))
        check("下拉条目贡献 @font/game（在游戏版本下拉的取值里）",
              lambda: _find_option_menu(apps["汉化包生成"].root, "HUB-游戏"))
        check("新建下拉贡献 @video",
              lambda: _find_option_menu(apps["视频转换"].root, "HUB-选项"))
        check("面板贡献 @xml",
              lambda: _find_labelframe(apps["XML校对"].root, "HUB-面板"))
        check("比较模式贡献进注册表",
              lambda: "HUB-模式" in pm.compare_modes_for())
        check("比较模式贡献在模式下拉里",
              lambda: "HUB-模式" in list(apps["XML校对"].cb_mode.cget("values")))
        check("格式贡献进格式表",
              lambda: "HUB格式" in [f["name"] for f in pm.formats])
        check("格式贡献出现在 fs 格式下拉",
              lambda: "HUB格式" in list(apps["文件系统"].fmt_keys))

        print("\n[5] 重新扫描（重建界面时不炸）")
        def _rescan():
            pm.scan()
            return [p["file"] for p in pm.plugins]
        check("重复 scan() 仍正常", lambda: PLUGIN_NAME in _rescan())

        print("\n[6] 启动绘制契约（启动白屏修复，用户取证 2026-09-12）")
        # 症状：Tk 建根窗口用系统默认白底，第一次重绘却要等 mainloop；中间扫插件 /
        # 装配六个栏目 —— 实测源码态 0.31 s、冷冻版冷启动 1.47 s 的纯白窗口。
        # 处方：装配前先画一帧（paint_startup），装配中每装完一个栏目再画一帧
        # （rebuild 里的 paint_now）。下面把"接线"和"调用顺序"都锁住 —— 只锁
        # 函数存在是不够的：把 paint_startup 挪到插件扫描之后，白屏照样回来。
        check("Hub 导出 paint_now / paint_startup",
              lambda: callable(getattr(HUB, "paint_now", None))
              and callable(getattr(HUB, "paint_startup", None)))

        def _paint_now_contract():
            calls = []
            real = root.update_idletasks
            root.update_idletasks = lambda: (calls.append(1), real())[1]
            try:
                r = HUB.paint_now(root)
            finally:
                del root.update_idletasks
            assert calls == [1], "paint_now 必须且只能调用一次 update_idletasks，实际 %r" % (calls,)
            assert r is True, "paint_now 应返回 True 供断言，实际 %r" % (r,)
            return True
        check("paint_now 真的走 update_idletasks（只处理空闲任务）", _paint_now_contract)

        def _paint_startup_contract():
            painted = []
            real_paint = HUB.paint_now
            HUB.paint_now = lambda r: painted.append(r) or True
            try:
                hint = HUB.paint_startup(root, "探针装载提示")
            finally:
                HUB.paint_now = real_paint
            try:
                assert painted == [root], "paint_startup 未经过 paint_now，实际 %r" % (painted,)
                assert hint is not None and hint.winfo_exists(), "启动提示标签未创建"
                assert str(hint.cget("text")) == "探针装载提示", \
                    "提示文案未透传：%r" % (hint.cget("text"),)
                return True
            finally:
                # 只在真拿到标签时销毁：否则 hint=None 时 finally 里的
                # AttributeError 会盖掉上面那条真正的断言信息（注入 E 实测）。
                if hint is not None:
                    hint.destroy()
        check("paint_startup 建提示标签并经 paint_now 落笔", _paint_startup_contract)

        def _hub_ast():
            import ast
            with open(os.path.join(BASE, "stalker_toolkit.py"), encoding="utf-8") as f:
                return ast.parse(f.read())

        def _main_calls(tree):
            import ast
            block = None
            for node in tree.body:
                if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) \
                        and getattr(node.test.left, "id", None) == "__name__":
                    block = node
                    break
            assert block is not None, "stalker_toolkit.py 找不到 __main__ 块"
            first = {}
            for stmt in block.body:
                for n in ast.walk(stmt):
                    if isinstance(n, ast.Call):
                        nm = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                        if nm and nm not in first:
                            first[nm] = n.lineno
            return first

        def _startup_order():
            calls = _main_calls(_hub_ast())
            need = ("_BaseTk", "paint_startup", "shared", "build_hub")
            missing = [k for k in need if k not in calls]
            assert not missing, "启动路径上缺少调用：%s" % (missing,)
            assert calls["_BaseTk"] < calls["paint_startup"], \
                "paint_startup 必须在建根窗口之后（否则窗口还没映射）"
            assert calls["paint_startup"] < calls["shared"], \
                "paint_startup 必须早于插件扫描（放到后面白屏就回来了）"
            assert calls["paint_startup"] < calls["build_hub"], \
                "paint_startup 必须早于 build_hub（装配六个栏目）"
            return True
        check("AST：paint_startup 排在插件扫描与装配之前", _startup_order)

        def _progressive_paint():
            import ast
            tree = _hub_ast()
            paint_in_rebuild = False
            theme_in_loop = False
            uses_scheduler = False
            passthrough = False
            before_rebuild = False
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if node.name == "rebuild":
                    for n in ast.walk(node):
                        if isinstance(n, ast.Call):
                            nm = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                            if nm == "paint_now":
                                paint_in_rebuild = True
                            elif nm == "build_tabs":
                                uses_scheduler = True
                                # defer_rest 必须**透传**：写死 False 就退回"装完才进
                                # mainloop"。行为锁只测调度器本身，抓不到这种接线回归，
                                # 所以这一条必须在源码形状上锁。
                                for kw in n.keywords:
                                    if kw.arg == "defer_rest" and not (
                                            isinstance(kw.value, ast.Constant)
                                            and kw.value.value is False):
                                        passthrough = True
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.For):
                            for inner in ast.walk(sub):
                                if isinstance(inner, ast.Call) and \
                                        getattr(inner.func, "id", None) == "apply_theme":
                                    # 装配循环里重配主题 = 约 100 条 ttk 样式 × 栏目数。
                                    # 加 paint_now 时它被顺手缩进进来过一次，实跑日志
                                    # 显示启动被拖慢（见 UI 回执）。
                                    theme_in_loop = True
                if node.name == "build_hub":
                    pn, rb = [], []
                    for n in ast.walk(node):
                        if isinstance(n, ast.Call):
                            nm = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                            if nm == "paint_now":
                                pn.append(n.lineno)
                            elif nm == "rebuild":
                                rb.append(n.lineno)
                    before_rebuild = bool(pn) and bool(rb) and min(pn) < min(rb)
            assert paint_in_rebuild, "rebuild() 里没有 paint_now：栏目装完不会重绘"
            assert uses_scheduler, "rebuild() 没用 build_tabs 调度器（分帧装配会丢）"
            assert passthrough, \
                "rebuild() 没把 defer_rest 透传给 build_tabs（写死 False = 退回一次性装配）"
            assert not theme_in_loop, \
                "apply_theme() 被缩进进了装配循环：会按栏目数重复配置约 100 条 ttk 样式（拖慢启动）"
            assert before_rebuild, "build_hub() 里 paint_now 必须早于 rebuild（外壳先落地）"
            return True
        check("AST：rebuild 走 build_tabs、含 paint_now，apply_theme 仍在循环外",
              _progressive_paint)

        def _deferred_assembly():
            class FakeRoot:
                def __init__(self):
                    self.afters = []

                def after(self, ms, fn):
                    self.afters.append((ms, fn))

            tools = [("A", 1), ("B", 2), ("C", 3)]
            built, dones = [], []
            fr = FakeRoot()
            _sync, rest = HUB.build_tabs(
                fr, tools, lambda lab, fac: built.append(lab),
                defer_rest=True, on_done=lambda: dones.append(1))
            assert built == ["A"], "启动路径只应同步装配首个栏目，实际 %r" % (built,)
            assert rest == 2, "剩余待装配数应为 2，实际 %r" % (rest,)
            assert len(fr.afters) == 1, "分帧必须排一次 after，实际 %r" % (len(fr.afters),)
            guard = 0
            while fr.afters:
                guard += 1
                assert guard < 10, "after 回调无限续链"
                _ms, fn = fr.afters.pop(0)
                fn()
            assert built == ["A", "B", "C"], "分帧没把剩余栏目装完：%r" % (built,)
            assert dones == [1], "on_done 必须且只调一次，实际 %r" % (dones,)
            # 一次性模式必须与旧实现等价：同步装完、不排 after。
            built2, dones2 = [], []
            fr2 = FakeRoot()
            _s2, rest2 = HUB.build_tabs(
                fr2, tools, lambda lab, fac: built2.append(lab),
                defer_rest=False, on_done=lambda: dones2.append(1))
            assert built2 == ["A", "B", "C"] and rest2 == 0 and not fr2.afters, \
                "defer_rest=False 应一次性装完且不排 after：%r/%r" % (built2, fr2.afters)
            assert dones2 == [1]
            return True
        check("启动装配：首栏目同步、其余分帧（mainloop 才早跑起来）", _deferred_assembly)

        print("\n[7] 分隔条与布局契约（用户口径 2026-09-12「拖拽一卡一卡 / 非最大化布局差」）")
        # 三件事是 ttk 自己给不了、必须由本工程保证的（都在 toolkit_widgets.SplitPane）：
        #   ① pane 没有 minsize → 主工作区实测被挤到 55 px、日志栏 1 px；
        #   ② 拖动逐帧重排太贵（实测 33 ms/步）→ 改为预览线，松手才应用一次；
        #   ③ `panes()` 返回的是 Tcl 路径**字符串** → refresh_children 一直空转。
        _SP_STATE = {}

        def _split_pane_fixture():
            """造一个"总空间不够、必须靠 minsize 收敛"的真 Tk 场景。

            几何与请求值**全部走 px()**：本机缩放 150%，写死的 600x300 配上
            px(200)/px(250) 会变成"最小尺寸之和 420 > 窗口 300"这种不可能满足的组合
            —— 那时 `_clamp` 什么都不做才是对的，夹具也就测不出收敛（实测踩过）。
            这里取"最小值之和 280 ≤ 窗口 340、但后一个 pane 的原生分配只有 100"，
            于是只有"从右往左"那趟能把后一个 pane 顶到 120。
            """
            import tkinter as _tk
            from toolkit import SplitPane as _SP
            from toolkit import color as _color
            from toolkit import px as _px

            top = _tk.Toplevel(root)
            top.geometry("%dx%d" % (_px(600), _px(340)))
            sp = _SP(top, orient="vertical")
            sp.pack(fill="both", expand=True)
            a = _tk.Frame(sp, bg=_color("bg"), height=_px(300))
            b = _tk.Frame(sp, bg=_color("bg"), height=_px(100))
            a.pack_propagate(False)
            b.pack_propagate(False)
            # 前一个 pane 塞成"重窗格"：freeze 档只冻结控件数超过阈值的窗格，
            # 空 Frame 不该被冻结（那样就测不到降载这条规则了）。propagate 已关，
            # 塞控件不会改变 a 的请求尺寸，不影响上面的 minsize 夹具。
            for i in range(45):
                _tk.Label(a, text="l%d" % i, bg=_color("bg")).pack()
            sp.add(a, weight=3, minsize=_px(160))
            sp.add(b, weight=1, minsize=_px(120))
            top.update()
            _SP_STATE.update(top=top, sp=sp, a=a, b=b, px=_px, color=_color,
                             heavy=a, light=b)
            return sp

        def _split_minsize():
            sp = _split_pane_fixture()
            px_ = _SP_STATE["px"]
            a, b = _SP_STATE["a"], _SP_STATE["b"]
            native = (a.winfo_height(), b.winfo_height())
            for _ in range(3):
                sp._clamp()
                _SP_STATE["top"].update_idletasks()
            assert a.winfo_height() >= px_(160), \
                "前一个 pane 只有 %d px（min %d）：minsize 没收敛" % (a.winfo_height(), px_(160))
            assert b.winfo_height() >= px_(120), \
                "后一个 pane 只有 %d px（min %d，原生分配 %s）：需要从右往左那趟收敛" \
                % (b.winfo_height(), px_(120), native)
            return True
        check("SplitPane：minsize 真的生效（ttk 没有这个能力，自己实现）", _split_minsize)

        def _split_panes_are_widgets():
            sp = _SP_STATE["sp"]
            panes = sp._panes()
            assert len(panes) == 2, "pane 数应为 2：%r" % (panes,)
            for p in panes:
                assert hasattr(p, "winfo_height"), \
                    "panes() 给的是 Tcl 路径字符串，不是控件：%r（历史 bug：refresh_children 因此空转）" % (p,)
            assert sp._children == panes, "_children 应与实际 pane 对齐：%r" % (sp._children,)
            return True
        check("SplitPane：pane 句柄是真控件（字符串会让 refresh_children 静默空转）",
              _split_panes_are_widgets)

        def _split_refresh_reaches_ctree():
            from toolkit import CanvasTree as _CT
            sp = _SP_STATE["sp"]
            a = _SP_STATE["a"]
            ct = _CT(a, with_chk=False)
            ct.get().pack(fill="both", expand=True)
            _SP_STATE["top"].update()
            calls = []
            real = ct._draw
            ct._draw = lambda: (calls.append(1), real())[1]
            try:
                sp.refresh_children()
            finally:
                ct._draw = real
            assert calls, "refresh_children 没走到 pane 里的 CanvasTree（自绘控件就不会重绘）"
            return True
        check("SplitPane：refresh_children 真的触达 CanvasTree._draw", _split_refresh_reaches_ctree)

        def _split_drag_is_preview():
            """拖动期只记最新位置（不逐事件重排），松手一定落到目标位置。

            同一把尺子实测（含重绘，root.update 口径）：逐事件实时 108 ms/次拖动风暴、
            冻结重页面后 45 ms、只挪预览线 4.5 ms。三档都必须在"松手一定落到目标位置"
            上一致 —— 否则用户拖到哪、分隔条停在哪就对不上了。
            """
            sp = _SP_STATE["sp"]
            top = _SP_STATE["top"]
            top.update()

            class _Ev:
                pass

            pos = int(sp.sashpos(0))
            w_ = sp.winfo_width()
            ev = _Ev(); ev.x = w_ // 2; ev.y = pos
            rc = sp._rb_press(ev)
            assert rc == "break", "命中 sash 必须阻止 ttk 的逐事件重排，返回 %r" % (rc,)
            assert sp._drag == 0, "按下后应进入拖动：%r" % (sp._drag,)
            before = int(sp.sashpos(0))
            ev2 = _Ev(); ev2.x = w_ // 2; ev2.y = pos + 30
            sp._rb_motion(ev2)
            assert int(sp.sashpos(0)) == before, \
                "运动事件本身不许同步改几何（每个 motion 都重排 = 一卡一卡的来源）"
            sp._rb_release(ev2)
            top.update_idletasks()
            assert int(sp.sashpos(0)) != before, "松手必须真正应用一次尺寸变化"
            assert sp._drag is None, "松手后应退出拖动状态"
            assert not sp._frozen, "松手后不许残留冻结重绘的窗口（否则窗口再也不刷新）"
            return True
        check("SplitPane：合并 motion（拖动期不同步改几何）、松手应用一次且不留冻结",
              _split_drag_is_preview)

        def _split_drag_mode_and_freeze():
            from toolkit import SplitPane as _SP
            assert _SP.LIVE_DRAG in ("full", "freeze", "line"), \
                "LIVE_DRAG 只允许 full/freeze/line，实际 %r" % (_SP.LIVE_DRAG,)
            sp = _SP_STATE["sp"]
            top = _SP_STATE["top"]
            sp._thaw_pane_redraw()
            top.update()

            class _Ev:
                pass

            pos = int(sp.sashpos(0))
            ev = _Ev(); ev.x = sp.winfo_width() // 2; ev.y = pos
            sp._rb_press(ev)
            if _SP.LIVE_DRAG == "freeze":
                assert sp._frozen, "freeze 档按下后应冻结重窗格的重绘（否则没有降载效果）"
                assert len(sp._frozen) == 1, \
                    "只该冻结重窗格：夹具里重窗格 1 个、轻窗格 1 个，实际冻结 %d 个" % len(sp._frozen)
            else:
                assert not sp._frozen, "%s 档不该冻结重绘" % (_SP.LIVE_DRAG,)
            ev2 = _Ev(); ev2.x = ev.x; ev2.y = pos + 20
            sp._rb_release(ev2)
            top.update_idletasks()
            assert not sp._frozen, "松手必须解冻"
            return True
        check("SplitPane：LIVE_DRAG 三档合法；freeze 档按下冻结、松手解冻",
              _split_drag_mode_and_freeze)

        def _split_bindings_wired():
            """真实事件路径：event_generate 走 Tk 绑定链（不是直接调处理器）。

            直接调 `_rb_*` 只能证明逻辑对，证明不了"绑定还挂着、`break` 真的生效" ——
            重构把 `self.bind(...)` 删掉时，那种锁会照样绿。
            """
            sp = _SP_STATE["sp"]
            top = _SP_STATE["top"]
            from toolkit import SplitPane as _SP2
            # 先把 sash 放到中间：夹具的两侧最小尺寸都在，±40 的拖动不会被 min 收敛
            # 或越界夹住 —— 否则断言测的是"夹取结果"，不是"松手落到目标"。
            sp.sashpos(0, int(top.winfo_height() * 0.5))
            top.update()
            cx = sp.winfo_width() // 2
            sash = int(sp.sashpos(0))
            sp.event_generate("<Button-1>", x=cx, y=sash)
            top.update()
            assert sp._drag is not None, "真实 Button-1 没进拖动：bind 掉了？"
            if _SP2.LIVE_DRAG == "freeze":
                assert sp._frozen, "freeze 档真实按下后应已冻结重窗格重绘"
            sp.event_generate("<B1-Motion>", x=cx, y=sash + 40)
            # line 档：运动只挪预览线，几何要等松手；其余档：合并后由 after 应用一次。
            if _SP2.LIVE_DRAG == "line":
                top.update_idletasks()
                assert int(sp.sashpos(0)) == sash, "line 档拖动期不该改几何"
            else:
                # 合并后的应用排在 after(1)：要让它到期才跑（真实拖动时 motion
                # 连续到达，事件循环一直在转，不会有这个空档；单发事件才需要等一下）。
                time.sleep(0.02)
                top.update()
                assert int(sp.sashpos(0)) == sash + 40, \
                    "实时档在事件循环跑完后应落到最新目标位置，实际 %d" % int(sp.sashpos(0))
            sp.event_generate("<ButtonRelease-1>", x=cx, y=sash + 40)
            top.update()
            assert int(sp.sashpos(0)) == sash + 40, "真实 ButtonRelease-1 没落到目标位置"
            assert not sp._frozen, "真实松手后不许残留冻结"
            # 点在不含 sash 的位置：不能被吞掉（否则普通点击全失效）
            sp.event_generate("<Button-1>", x=cx, y=max(1, sash - 40))
            top.update()
            assert sp._drag is None, "普通位置的点击被误判成拖动"
            return True
        check("SplitPane：真实事件路径可用（绑定未丢、break 生效、普通点击不被吞）",
              _split_bindings_wired)

        def _split_thaw_repaints_children():
            """解冻必须让**整棵子树**补画，不能只失效父窗口。

            用户录屏实证（2026-09-12）：只对 pane 自己 `InvalidateRect`，子窗口留在
            `WM_SETREDRAW(0)` 期间的状态 —— 页面整片空白 + 错位陈旧像素，且不会自愈。
            屏幕抓图逐像素比对实测：旧实现与参考图差 **16.3%**，现实现 **1.65%**
            （噪声底 1.54%）。
            """
            import inspect
            from toolkit import SplitPane as _SP3
            src = inspect.getsource(_SP3._thaw_pane_redraw)
            assert "RedrawWindow" in src, \
                "解冻没有用 RedrawWindow：子窗口不会补画（页面会留大片空白）"
            assert "0x0080" in src or "RDW_ALLCHILDREN" in src, \
                "RedrawWindow 少了 RDW_ALLCHILDREN：只补画父窗口，子窗口仍是陈旧像素"
            assert "FREEZE_MAX_MS" in inspect.getsource(_SP3._freeze_pane_redraw), \
                "冻结没有设看门狗：release 丢失时窗口会永远不再重绘"
            return True
        check("SplitPane：解冻递归补画子树 + 冻结有看门狗（录屏实证的空白页 bug）",
              _split_thaw_repaints_children)

        def _split_preview_filled():
            """line 档拖动期：预览必须是**填色区域**，不是一条线（用户口径 2026-09-13）。

            用户原话："拖拽的时候预览框不能只是一条线，而是要把那部分相应的背景也进行填充，
            不然很难看。" 顺带锁住 line 档的全部价值：**拖动期不改窗格几何**（只挪预览）。
            """
            import toolkit_widgets as _tw_local      # 第 [7] 段时 `_tw` 还没导入
            top = tk.Toplevel(root)
            top.geometry("500x300+2000+2000")
            try:
                sp = _tw_local.SplitPane(top, orient="vertical")
                sp.pack(fill="both", expand=True)
                a = tk.Frame(sp, bg="#333333")
                sp.add(a, weight=1)
                b = tk.Frame(sp, bg="#444444")
                sp.add(b, weight=1)
                top.update()
                sash0 = sp.sashpos(0)
                wx = sp.winfo_width() // 2
                sp.event_generate("<Button-1>", x=wx, y=sash0)
                top.update()
                sp.event_generate("<B1-Motion>", x=wx, y=max(2, sash0 - 60))
                top.update()
                fill = getattr(sp, "_drag_fill", None)
                info = dict(fill.place_info()) if fill is not None else {}
                band_h = int(info.get("height", 0) or 0)
                band_bg = str(fill.cget("bg")) if fill is not None else ""
                sash_mid = sp.sashpos(0)
                sp.event_generate("<ButtonRelease-1>", x=wx, y=max(2, sash0 - 60))
                top.update()
                sash_end = sp.sashpos(0)
                still = bool(fill.place_info()) if fill is not None else False
                theme_colors = {color(r) for r in ("bg", "surface", "surface2")}
            finally:
                try:
                    top.destroy()
                except Exception:
                    pass
            return {"band_h": band_h, "band_bg": band_bg, "sash0": sash0,
                    "sash_mid": sash_mid, "sash_end": sash_end,
                    "hidden_after": not still, "bg_is_theme": band_bg in theme_colors}

        _pv = _split_preview_filled()
        print("        预览实测：%r" % (_pv,))
        check("拖动预览是**填色区域**（高度跟手、底色取自主题）而不是一条线",
              lambda: _pv["band_h"] >= 40 and _pv["bg_is_theme"])
        check("line 档：拖动期**不动窗格几何**（sashpos 不变）",
              lambda: _pv["sash_mid"] == _pv["sash0"])
        check("line 档：松手**应用一次**并收掉预览",
              lambda: _pv["sash_end"] != _pv["sash0"] and _pv["hidden_after"])

        def _split_collapse_sticks():
            """日志栏式"可完全收起且不弹回"（用户口径 2026-09-13）。

            用户原话："日志栏做成可以完全收起的，不要自动往上弹。并且如果已经完全收起，
            那么在改变主窗口大小的时候，也不会再上来。"

            夹具：竖排两栏，**下面那栏给最小值 110**（就是日志栏那种），把它拖到几乎 0。
            要同时成立三件事：① 收起后它确实很小；② 立刻再跑一次 `_clamp()`（松手会跑）
            也不弹回；③ 改变窗口尺寸（触发 `_on_configure → _clamp`）同样不弹回；
            ④ 再把它拉回超过 110 → 最小值恢复、它真的变大。
            """
            import toolkit_widgets as _tw_local
            top = tk.Toplevel(root)
            top.geometry("500x420+2000+2000")
            try:
                sp = _tw_local.SplitPane(top, orient="vertical")
                sp.pack(fill="both", expand=True)
                a = tk.Frame(sp, bg="#333333")
                sp.add(a, weight=3, minsize=60)
                b = tk.Frame(sp, bg="#444444")
                sp.add(b, weight=1, minsize=110)      # 被测那一栏
                top.update()
                log_pane = sp._panes()[1]
                wx = sp.winfo_width() // 2

                class _Ev:
                    pass

                def press(y):
                    e = _Ev(); e.x = wx; e.y = int(y)
                    sp._rb_press(e)

                def motion(y):
                    e = _Ev(); e.x = wx; e.y = int(y)
                    sp._rb_motion(e)

                def release(y):
                    e = _Ev(); e.x = wx; e.y = int(y)
                    sp._rb_release(e)

                # 直接调 handler + 假事件（与本探针其它拖动锁同一套路）。
                # 为什么不用 event_generate：离屏的 Toplevel 里 Tk 不投递生成事件，
                # 那样测出来的"没动"是假象（我第一版就这么被骗过一次：sash 停在权重位置）。
                sash0 = sp.sashpos(0)
                press(sash0)
                motion(sp.winfo_height() - 3)
                release(sp.winfo_height() - 3)
                top.update(); time.sleep(0.15); top.update()
                total_h = sp.winfo_height()
                collapsed_h = max(0, total_h - sp.sashpos(0) - 6)   # 6 ≈ sash 宽
                min_dropped = log_pane not in sp._mins
                saved = log_pane in sp._saved_mins
                # ② 松手后 `_clamp` 已经跑过一次；再来一次模拟"又被收敛"
                sp._clamp()
                top.update(); time.sleep(0.15); top.update()
                after_clamp = max(0, sp.winfo_height() - sp.sashpos(0) - 6)
                # ③ 改变窗口尺寸 → `_on_configure → _clamp`
                top.geometry("500x300+2000+2000")
                top.update()
                time.sleep(0.25)          # clamp 有 120ms 去抖
                top.update()
                sp._clamp()
                top.update(); time.sleep(0.15); top.update()
                after_resize = max(0, sp.winfo_height() - sp.sashpos(0) - 6)
                # ④ 拖回去 → 恢复
                sash1 = sp.sashpos(0)
                press(sash1)
                motion(max(5, sash1 - 200))
                release(max(5, sash1 - 200))
                top.update(); time.sleep(0.15); top.update()
                restored_h = max(0, sp.winfo_height() - sp.sashpos(0) - 6)
                min_back = sp._mins.get(log_pane)
            finally:
                try:
                    top.destroy()
                except Exception:
                    pass
            return {"collapsed_h": collapsed_h, "min_dropped": min_dropped, "saved": saved,
                    "after_clamp": after_clamp, "after_resize": after_resize,
                    "restored_h": restored_h, "min_back": min_back}

        _cl = _split_collapse_sticks()
        print("        收起实测：%r" % (_cl,))
        check("收起：拖到底后那一栏确实几乎为 0，且它的最小值已被撤下（记为收起）",
              lambda: _cl["collapsed_h"] <= 8 and _cl["min_dropped"] and _cl["saved"])
        check("★收起后**不弹回**：再跑 `_clamp()` 尺寸不变（松手那一下就会跑收敛）",
              lambda: _cl["after_clamp"] <= 8)
        check("★收起后**改窗口尺寸也不上来**（Configure → `_clamp` 同样不恢复它）",
              lambda: _cl["after_resize"] <= 8)
        check("拉回来即恢复：超过原最小值后最小值装回去、且该栏真的变大",
              lambda: _cl["min_back"] == 110 and _cl["restored_h"] > 60)

        # ── 加载遮罩：启动装配期间盖住"控件一个个跳出来" ──────────────────
        print("\n[7b] 加载遮罩（BusyOverlay：转圈 + 看门狗 + 幂等收掉）")
        import toolkit_widgets as _tw9
        import toolkit as _tk9

        def _busy_checks():
            import tkinter as _tk
            top = _tk.Toplevel(root)
            top.geometry("420x300+2000+2000")
            try:
                host = _tk.Frame(top, bg="#222222")
                host.pack(fill="both", expand=True)
                b = _tw9.BusyOverlay(host, text="正在加载组件…")
                shown_before = bool(b.winfo_manager())
                b.start()
                top.update()
                covered = (b.winfo_manager() == "place"
                           and b.winfo_width() >= host.winfo_width() - 2
                           and b.winfo_height() >= host.winfo_height() - 2)
                a0 = b.angle()
                time.sleep(0.25)          # 让它真的转几帧
                top.update()
                a1 = b.angle()
                running = b.running()
                b.stop()
                top.update()
                hidden = not b.winfo_manager()
                still = b.running()
                b.stop()                  # 幂等
                ok_idem = not b.winfo_manager()
                watchdog = getattr(_tw9.BusyOverlay, "MAX_MS", 0)
                exported = hasattr(_tk9, "BusyOverlay")
            finally:
                try:
                    top.destroy()
                except Exception:
                    pass
            return {"shown_before": shown_before, "covered": covered, "a0": a0, "a1": a1,
                    "running": running, "hidden": hidden, "still": still,
                    "ok_idem": ok_idem, "watchdog": watchdog, "exported": exported}

        _bz = _busy_checks()
        print("        实测：%r" % (_bz,))
        check("BusyOverlay：start() 后**铺满**父容器（盖住逐个跳出来的控件）",
              lambda: _bz["covered"] and not _bz["shown_before"])
        check("BusyOverlay：真的在转（两帧之间角度变了）且动画在跑",
              lambda: _bz["a1"] != _bz["a0"] and _bz["running"])
        check("BusyOverlay：stop() 收掉遮罩并取消动画（不留孤儿定时器）",
              lambda: _bz["hidden"] and not _bz["still"])
        check("BusyOverlay：stop() 幂等（重复调用不炸、状态一致）", lambda: _bz["ok_idem"])
        check("BusyOverlay：有看门狗（on_done 万一没来也不会永远盖着）且已导出",
              lambda: _bz["watchdog"] >= 5000 and _bz["exported"])

        def _busy_wired():
            """AST：Hub 必须建遮罩，并把 stop 交给装配的 on_done 收尾。"""
            import ast
            import io as _io          # 本段跑在 [8] 之前，那里才 import io
            src = _io.open(os.path.join(BASE, "stalker_toolkit.py"), encoding="utf-8").read()
            tree = ast.parse(src)
            built = done_hook = False
            for node in ast.walk(tree):
                if not (isinstance(node, ast.FunctionDef) and node.name == "build_hub"):
                    continue
                for n in ast.walk(node):
                    if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "BusyOverlay":
                        built = True
                    for kw in getattr(n, "keywords", []):
                        if kw.arg == "on_done_extra":
                            done_hook = True
            return built and done_hook
        check("AST：Hub 建了加载遮罩，且把收尾（stop）挂进装配 on_done", _busy_wired)

        def _hub_layout_wiring():
            """AST：栏目页**必须**向上传递高度；两栏都要有 minsize。

            2026-09-13 反转（用户实机："这些地方应该出现滚动条"）：原来这里锁的是
            "必须关 pack_propagate"（因为页面请求高度会把日志栏压成 1px）。现在栏目区
            pane 是 fit="content" 的裁剪视口 —— 页面说出自己的高度，视口据此决定要不要出
            纵向滚动条；**关掉** propagate 会让页面请求高度变成 1px，于是页面被裁却
            **没有滚动条**（用户圈出的右侧空条）。
            """
            import ast
            tree = _hub_ast()
            disables = []
            minsizes = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_build_one":
                    for n in ast.walk(node):
                        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "pack_propagate":
                            for arg in n.args:
                                if getattr(arg, "value", True) is False:
                                    disables.append(n.lineno)
                if isinstance(node, ast.FunctionDef) and node.name == "build_hub":
                    for n in ast.walk(node):
                        # 栏目区那条走 `add_clipped(..., minsize=)`，日志栏走 `add(..., minsize=)`
                        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in (
                                "add", "add_clipped"):
                            for kw in n.keywords:
                                if kw.arg == "minsize":
                                    minsizes.append(kw.value)
            assert not disables, \
                "栏目页又被 pack_propagate(False) 关掉了高度传递（第 %r 行）：页面请求高度会是 " \
                "1px，栏目区视口就以为装得下 → 页面被裁却没有滚动条" % (disables,)
            assert len(minsizes) >= 2, \
                "Hub 两栏都要给 minsize（栏目区/日志栏各一），实际 %d 处" % len(minsizes)
            return True
        check("AST：栏目页向上传递高度（不再关 pack_propagate）+ 两栏都有 minsize",
              _hub_layout_wiring)

        # ── [8] 自动隐藏滚动条（用户口径：装得下就不该常驻）──────────────────
        print("\n[8] 自动隐藏滚动条（AutoScrollbar：装得下收起、超出才出现、收起时让出空间）")
        import io
        import toolkit
        import toolkit_widgets as _tw

        def _sb_checks():
            import tkinter as _tk
            top = _tk.Toplevel(root)
            top.geometry("300x200+2000+2000")
            try:
                # ① pack 场景：滚动条 + 一个 fill=both expand 的内容块
                host = _tk.Frame(top, width=300, height=120)
                host.pack(fill="both", expand=True)
                host.pack_propagate(False)
                sb = _tw.AutoScrollbar(host, orient="vertical")
                body = _tk.Frame(host, bg="#222222")
                sb.pack(side="right", fill="y")
                body.pack(side="left", fill="both", expand=True)
                top.update()

                # 装得下 → 收起，且内容块拿到整宽
                sb.set(0.0, 1.0)
                top.update()
                hidden = not sb.winfo_manager()        # forget 之后 manager 为空串
                w_hidden = body.winfo_width()
                # 超出 → 出现，内容块让出滚动条宽度
                sb.set(0.0, 0.4)
                top.update()
                shown = bool(sb.winfo_manager())
                w_shown = body.winfo_width()
                # 滞回：0.999 仍算"超出"（不许在临界点闪）
                sb.set(0.0, 1.0)
                top.update()
                sb.set(0.0, 0.999)
                top.update()
                hyster = bool(sb.winfo_manager())
                # 再装得下 → 又收起
                sb.set(0.0, 1.0)
                top.update()
                back = not sb.winfo_manager()

                # ② grid 场景：收起/放回必须回到原来的格位
                g = _tk.Frame(top)
                g.grid_columnconfigure(0, weight=1)
                tree = _tk.Frame(g, width=120, height=80)
                gsb = _tw.AutoScrollbar(g, orient="vertical")
                tree.grid(row=0, column=0, sticky="nsew")
                gsb.grid(row=0, column=1, sticky="ns")
                top.update()
                before = dict(gsb.grid_info())
                gsb.set(0.0, 1.0); top.update()
                g_hidden = not gsb.winfo_manager()
                gsb.set(0.0, 0.2); top.update()
                after = dict(gsb.grid_info())
                same_cell = (str(before.get("row")) == str(after.get("row"))
                             and str(before.get("column")) == str(after.get("column"))
                             and str(before.get("sticky")) == str(after.get("sticky")))
            finally:
                try:
                    top.destroy()
                except Exception:
                    pass
            return {"hidden": hidden, "shown": shown, "back": back, "hyster": hyster,
                    "w_hidden": w_hidden, "w_shown": w_shown,
                    "g_hidden": g_hidden, "same_cell": same_cell}

        _sb = _sb_checks()
        print("        实测：%r" % (_sb,))
        check("AutoScrollbar：装得下时收起、超出时出现、再装得下又收起",
              lambda: _sb["hidden"] and _sb["shown"] and _sb["back"])
        check("AutoScrollbar：收起时真的把宽度让给内容（真几何，不是配置）",
              lambda: _sb["w_hidden"] > _sb["w_shown"])
        check("AutoScrollbar：临界点有滞回（hi=0.999 仍显示，不许闪烁）",
              lambda: _sb["hyster"])
        check("AutoScrollbar：grid 场景收起/放回回到原来的格位",
              lambda: _sb["g_hidden"] and _sb["same_cell"])
        check("AutoScrollbar 是 ttk.Scrollbar 的子类（调用方可当它用）",
              lambda: issubclass(_tw.AutoScrollbar, ttk.Scrollbar))
        check("toolkit 导出 AutoScrollbar（六个 App 从 toolkit 取）",
              lambda: hasattr(toolkit, "AutoScrollbar"))

        def _no_raw_scrollbar():
            """收敛锁：活代码里不许再有裸 `ttk.Scrollbar(` 调用点。

            用户口径是"**所有**滚动条都该这样"。只要漏一处，那一处就还是常驻占宽。
            允许的例外只有 `toolkit_plugin_ui.py` 里那句 `_SB = ttk.Scrollbar` 回退
            （没有括号，不匹配这个模式 —— 它的设计目标是最小依赖，单独 import 时也能工作）。
            """
            bad = []
            targets = [os.path.join(BASE, "toolkit_widgets.py"),
                       os.path.join(BASE, "toolkit_plugin_ui.py")]
            for dp, dn, fn in os.walk(os.path.join(BASE, "apps")):
                dn[:] = [d for d in dn if d != "__pycache__"]
                targets += [os.path.join(dp, f) for f in fn if f.endswith(".py")]
            for p in targets:
                src = io.open(p, encoding="utf-8").read()
                if "ttk.Scrollbar(" in src:
                    bad.append(os.path.relpath(p, BASE))
            return bad
        _raw = _no_raw_scrollbar()
        print("        仍用裸 ttk.Scrollbar( 的文件：%r" % (_raw,))
        check("收敛：活代码里没有裸 ttk.Scrollbar( 调用点（滚动条统一走 AutoScrollbar）",
              lambda: not _raw)

        # ── ScrollViewport：内容不许被压扁，装不下就滚 ──────────────────────
        def _viewport_checks():
            import tkinter as _tk
            top = _tk.Toplevel(root)
            top.geometry("420x260+2000+2000")
            try:
                # 横向视口 300x200：内容自然宽 500 > 视口 → 横向必须出滚动条；
                # 纵向是否出由 **minsize_y** 决定（不是由内容请求高度决定 —— 见下面的回归锁）
                vp = _tw.ScrollViewport(top, horizontal=True, minsize_y=400, minsize_x=100)
                vp.place(x=0, y=0, width=300, height=200)
                inner = _tk.Frame(vp.content, width=500, height=400, bg="#333333")
                inner.pack()
                top.update()
                vp._sync(); top.update()
                big_v = bool(vp.vbar.winfo_manager())
                big_h = bool(vp.hbar.winfo_manager())
                w_big = vp.content.winfo_width()
                # 视口放大到 700x600（比 minsize_y 高）→ 两条滚动条都该收起、内容铺满
                vp.place_configure(width=700, height=600)
                top.update()
                vp._sync(); top.update()
                small_v = not vp.vbar.winfo_manager()
                small_h = not vp.hbar.winfo_manager()
                w_small = vp.content.winfo_width()
                # 竖向：minsize_y 生效（内容比视口矮时也不低于 minsize）
                vp.place_configure(width=700, height=120)
                top.update()
                vp._sync(); top.update()
                h_min = vp.content.winfo_height()
                # ★ 回归锁（实机截图抓到的 bug）：**内容的请求高度不得把视口顶出滚动条**。
                # 容器的请求高度 = 内部各栏请求之和，通常远大于视口；一旦拿它当内容高度，
                # 视口就永远装不下 —— 右侧常驻滚动条、内容底部被裁掉（发行包实测就是这样）。
                vp3 = _tw.ScrollViewport(top, horizontal=False, minsize_y=150)
                vp3.place(x=0, y=0, width=320, height=240)
                tall = _tk.Frame(vp3.content, width=100, height=900, bg="#333333")
                tall.pack()
                top.update()
                vp3._sync(); top.update()
                regress_v = not vp3.vbar.winfo_manager()      # 不该出滚动条
                regress_h = vp3.content.winfo_height()        # 应等于视口高
                # ★ fit="content"（栏目区 pane 用）：内容**保持自己需要的高度**，视口矮了就滚。
                # 用户口径 2026-09-13："日志是不归主窗口滚动条管的" → 反过来栏目区要自己管自己。
                vp4 = _tw.ScrollViewport(top, horizontal=False, fit="content", minsize_y=100)
                vp4.place(x=0, y=0, width=320, height=200)
                _tk.Frame(vp4.content, width=100, height=700, bg="#333333").pack()
                top.update()
                vp4._sync(); top.update()
                content_scrolls = bool(vp4.vbar.winfo_manager())
                content_h = vp4.content.winfo_height()
                # 纵向视口：内容横向必须铺满（否则页面会留一条缝）
                vp2 = _tw.ScrollViewport(top, horizontal=False)
                vp2.place(x=0, y=0, width=250, height=150)
                _tk.Frame(vp2.content, height=40).pack(fill="x")
                top.update()
                vp2._sync(); top.update()
                fill_w = vp2.content.winfo_width()
            finally:
                try:
                    top.destroy()
                except Exception:
                    pass
            return {"big_v": big_v, "big_h": big_h, "w_big": w_big,
                    "small_v": small_v, "small_h": small_h, "w_small": w_small,
                    "content_scrolls": content_scrolls, "content_h": content_h,
                    "h_min": h_min, "fill_w": fill_w,
                    "regress_v": regress_v, "regress_h": regress_h}

        _vp = _viewport_checks()
        print("        实测：%r" % (_vp,))
        check("ScrollViewport：minsize_y 大于视口高 → 纵向滚动条出现（横向超宽 → 横向也出现）",
              lambda: _vp["big_v"] and _vp["big_h"])
        check("ScrollViewport：视口比 minsize_y 高 → 两条滚动条都收起，内容铺满",
              lambda: _vp["small_v"] and _vp["small_h"])
        check("ScrollViewport：内容**不被压扁**（保持自然宽度 500，而不是被拉到视口宽）",
              lambda: _vp["w_big"] >= 500)
        check("ScrollViewport：minsize_y 生效（视口矮于它时内容不低于它）",
              lambda: _vp["h_min"] >= 150)
        check("★回归：内容的**请求高度**不得把视口顶出滚动条（否则内容底部被裁 + 常驻滚动条）",
              lambda: _vp["regress_v"] and _vp["regress_h"] == 240)
        check("fit=\"content\"：内容保持自己需要的高度、视口矮了就自己滚（栏目区 pane 靠它）",
              lambda: _vp["content_scrolls"] and _vp["content_h"] >= 700)
        check("ScrollViewport：纵向视口里内容横向铺满（页面不留缝）",
              lambda: _vp["fill_w"] >= 240)

        def _wheel_rules():
            """统一规则（用户口径 2026-09-13）：**能滚才吃事件，滚不动放行**。

            两条断言（都按源码 AST，不靠人眼）：
              ① `CanvasTree._on_wheel` 必须**有条件** break（原来无条件 break → 鼠标停在
                 树上时整页滚不动，用户："这很反直觉"）；
              ② `ScrollViewport.scroll_wheel` 必须**跳过内层可滚控件**（Text/Listbox/CanvasTree），
                 否则文本框滚了、整页也跟着滚（双滚）。
            """
            import ast
            src = io.open(os.path.join(BASE, "toolkit_widgets.py"), encoding="utf-8").read()
            tree = ast.parse(src)
            cond_break = False
            skip_inner = False
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_on_wheel":
                    for n in ast.walk(node):
                        if isinstance(n, ast.Return) and isinstance(n.value, ast.IfExp):
                            cond_break = True
                if isinstance(node, ast.FunctionDef) and node.name == "scroll_wheel":
                    for n in ast.walk(node):
                        if isinstance(n, ast.Attribute) and n.attr in ("Text", "Listbox"):
                            skip_inner = True
                        if isinstance(n, ast.Constant) and n.value == "_ctree":
                            skip_inner = True
            return {"cond_break": cond_break, "skip_inner": skip_inner}
        _wr = _wheel_rules()
        print("        滚轮规则：%r" % (_wr,))
        check("滚轮规则①：CanvasTree 只在**真的滚动了**时才 break（滚不动则冒泡给外层）",
              lambda: _wr["cond_break"])
        check("滚轮规则②：视口滚轮**跳过内层可滚控件**（避免整页跟着一起滚）",
              lambda: _wr["skip_inner"])

        def _scroll_panel_rule():
            """统一滚动面板：出现条件 = **面板里有东西显示不完全**（用户口径 2026-09-13）。

            用户原话："底下滚动条出现的条件是该窗口有东西显示不完全。包括控件和里面的内容。……
            这种控件不应该是统一写统一调用的吗？"
            夹具：面板里放一行 8 个按钮；面板宽 → 装得下（无横向滚动条）；
            把面板压到 220px → 按钮行显示不完全 → **必须出现**横向滚动条。
            """
            import tkinter as _tk
            top = _tk.Toplevel(root)
            top.geometry("700x300+2000+2000")
            try:
                p = _tw9.ScrollPanel(top, "测试面板")
                # 注意"宽"必须**真的够宽**：夹具第一版给 700，而这一行 8 个按钮的内容
                # 实际要 816 —— 于是"宽面板"也出滚动条（那是对的），锁却报红。
                # 这正是本项目的常客：夹具先要满足前置条件，否则测的是别的东西。
                p.place(x=0, y=0, width=980, height=220)
                row = _tk.Frame(p.body)
                for i in range(8):
                    ttk.Button(row, text="按钮%d" % i, width=8).pack(side="left", padx=(0, 4))
                row.pack(fill="x")
                top.update(); p.refresh(); top.update()
                wide = bool(p.view.hbar.winfo_manager())
                p.place_configure(width=220)
                top.update(); p.refresh(); top.update()
                narrow = bool(p.view.hbar.winfo_manager())
                body_w = p.body.winfo_width()
            finally:
                try:
                    top.destroy()
                except Exception:
                    pass
            return {"wide_hbar": wide, "narrow_hbar": narrow, "body_w": body_w}

        _sp = _scroll_panel_rule()
        print("        统一滚动面板实测：%r" % (_sp,))
        check("ScrollPanel：装得下时**不出**横向滚动条（宽面板）",
              lambda: not _sp["wide_hbar"])
        check("ScrollPanel：★有东西显示不完全时**必须出**横向滚动条（窄面板）",
              lambda: _sp["narrow_hbar"])
        check("ScrollPanel：是 LabelFrame 的子类（六页按同一 API 调用）",
              lambda: issubclass(_tw9.ScrollPanel, ttk.LabelFrame))
        def _hub_window_scroll_wiring():
            """AST：**标签条钉住、滚动发生在页面内部**（2026-09-13 实机录屏后的结构定稿）。

            录屏抓到的错误结构：整个 Notebook（**含标签条**）被塞进一个滚动视口 ——
            页面一滚，主导航（文件系统/编码转换/…）也被滚走（用户截到的那一帧里标签条没了）。
            定稿结构：
              ① `build_hub` 里**没有** `ScrollViewport` 包住 Notebook（标签条不许被滚走）；
                 也**没有**窗口级视口包两栏（日志栏不归主窗口滚动条管，用户早先已否决）；
              ② 每个栏目页自己是一个 `ScrollViewport(fit="content", min_y=page_min_h())`
                 （见 `rebuild._build_one`）—— 页面内部滚，标签条不动；
              ③ 滚轮走**统一路由**（绑在窗口上，从指针下的控件沿 master 链找第一个能滚的视口）。
            """
            import ast
            src = io.open(os.path.join(BASE, "stalker_toolkit.py"), encoding="utf-8").read()
            tree = ast.parse(src)
            found = {"hub_viewport": False, "page_viewport": False, "wheel": False,
                     "clip_pane": False}
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "build_hub":
                    for n in ast.walk(node):
                        if not isinstance(n, ast.Call):
                            continue
                        fname = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                        if fname == "ScrollViewport":
                            found["hub_viewport"] = True
                        if fname == "add_clipped":
                            found["clip_pane"] = True
                        if (fname == "bind" and n.args
                                and getattr(n.args[0], "value", "") == "<MouseWheel>"):
                            found["wheel"] = True
                if isinstance(node, ast.FunctionDef) and node.name == "_build_one":
                    for n in ast.walk(node):
                        if (isinstance(n, ast.Call)
                                and getattr(n.func, "id", None) == "ScrollViewport"):
                            for kw in n.keywords:
                                if kw.arg == "fit" and getattr(kw.value, "value", "") == "content":
                                    found["page_viewport"] = True
            assert not found["hub_viewport"], \
                "build_hub 又用 ScrollViewport 包住了 Notebook/两栏：标签条会被滚走（录屏实证）"
            assert not found["clip_pane"], \
                "栏目区不该再走 add_clipped（滚动移到页面内部了）"
            assert found["page_viewport"], \
                "每个栏目页必须自己套 ScrollViewport(fit='content') —— 页面内部滚、标签条钉住"
            assert found["wheel"], "滚轮没绑到窗口（页面/面板滚不动）"
            return True
        check("AST：标签条钉住 + 页面内部自己滚（ScrollViewport fit=content）+ 窗口绑滚轮路由",
              _hub_window_scroll_wiring)


        # ── 裁剪式窗格：拖分隔条时远侧边框不动、内容左对齐、装不下出横向滚动条 ──
        print("        裁剪式窗格（SplitPane.add_clipped）：")
        def _clipped_pane_checks():
            import tkinter as _tk
            top = _tk.Toplevel(root)
            top.geometry("900x300+2000+2000")
            try:
                sp = _tw.SplitPane(top, orient="horizontal")
                sp.pack(fill="both", expand=True)
                c1 = sp.add_clipped(weight=1)
                _tk.Frame(c1, width=600, height=200, bg="#333333").pack(fill="both", expand=True)
                c2 = sp.add_clipped(weight=1)
                _tk.Frame(c2, width=500, height=200, bg="#333333").pack(fill="both", expand=True)
                top.update()
                panes = sp._panes()
                p1, p2 = panes[0], panes[1]
                types_ok = (isinstance(p1, _tw.ScrollViewport)
                            and isinstance(p2, _tw.ScrollViewport))
                left0 = p1.winfo_rootx()
                right0 = p2.winfo_rootx() + p2.winfo_width()
                # 往右拖：把右窗格压到比内容窄
                sp.sashpos(0, 620)
                top.update()
                left1 = p1.winfo_rootx()
                right1 = p2.winfo_rootx() + p2.winfo_width()
                content_x = c2.winfo_x()
                narrowed = p2.winfo_width() < p2.content.winfo_reqwidth()
                hbar = bool(p2.hbar.winfo_manager()) if p2.hbar is not None else False
                content_w = c2.winfo_width()
                req_w = c2.winfo_reqwidth()
                pane_w = p2.winfo_width()
            finally:
                try:
                    top.destroy()
                except Exception:
                    pass
            return {"types": types_ok, "p1L": (left0, left1), "p2R": (right0, right1),
                    "content_x": content_x, "narrowed": narrowed, "hbar": hbar,
                    "content_w": content_w, "req_w": req_w, "pane_w": pane_w}

        _cp = _clipped_pane_checks()
        print("        实测：%r" % (_cp,))
        check("add_clipped：窗格确实是 ScrollViewport（裁剪式而不是直接塞控件）",
              lambda: _cp["types"])
        check("裁剪窗格：拖分隔条后**两侧远侧边框都不动**（左窗格左 / 右窗格右）",
              lambda: _cp["p1L"][0] == _cp["p1L"][1] and _cp["p2R"][0] == _cp["p2R"][1])
        check("裁剪窗格：内容左对齐（x 偏移恒为 0，没有被推走）",
              lambda: _cp["content_x"] == 0)
        check("裁剪窗格：**不配横向滚动条**（滚动条只归真正需要它的控件自己 —— "
              "窗格级滚动条会画在面板外面、且各处有无不一）",
              lambda: not _cp["hbar"])
        check("裁剪窗格：窗格变窄时内容**跟着伸缩**（宽 == 窗格宽）",
              lambda: _cp["content_w"] == _cp["pane_w"])

        def _pages_use_clipped():
            """源码锁：两个横向分栏的页面都必须用 add_clipped（漏一个那处就还是老行为）。"""
            bad = []
            for f in ("fs_app.py", "font_pack_app.py"):
                src = io.open(os.path.join(BASE, "apps", f), encoding="utf-8").read()
                if "add_clipped" not in src:
                    bad.append(f)
            return bad
        _pc = _pages_use_clipped()
        print("        仍用旧式 add() 的横向分栏页面：%r" % (_pc,))
        check("收敛：所有横向分栏页面都用 add_clipped（fs / font）", lambda: not _pc)

        # ── 回归：sash 落点越界会把**所有** pane 压成 1px（实机抓到的塌陷）──
        def _no_collapse_when_tight():
            """空间远小于 minsize 时，收敛不得把 pane 压成 1px。

            实机现象：页面里的横向分栏只剩 **1×1 px**，于是"右边没锁定、拖动乱动"、
            左栏内容被挡却没有滚动条。根因是 `sashpos` 被设到超出可用空间的位置，
            ttk 会把所有 pane 一起压扁。现在：落点夹在 [1,total-1]，空间不够时按
            最小值比例分配。
            """
            import tkinter as _tk
            top = _tk.Toplevel(root)
            top.geometry("600x120+2000+2000")
            try:
                sp = _tw.SplitPane(top, orient="vertical")
                sp.pack(fill="both", expand=True)
                a = _tk.Frame(sp, bg="#333333")
                sp.add(a, weight=3, minsize=400)          # 最小值远超可用空间
                b = _tk.Frame(sp, bg="#444444")
                sp.add(b, weight=1, minsize=200)
                top.update()
                sp.sashpos(0, 900)        # 故意设一个越界值（模拟窗口变小后的陈旧值）
                top.update()
                sp._clamp()
                top.update()
                sizes = [p.winfo_height() for p in sp._panes()]
                pos = sp.sashpos(0)
                total = sp.winfo_height()
            finally:
                try:
                    top.destroy()
                except Exception:
                    pass
            return {"sizes": sizes, "pos": pos, "total": total}

        _col = _no_collapse_when_tight()
        print("        实测（可用高 %d，两栏最小 400/200）：%r" % (_col["total"], _col))
        check("★回归：sash 越界后收敛，不得把 pane 压成 1px（至少都 >1 且落点在内）",
              lambda: all(s > 1 for s in _col["sizes"])
                      and 1 <= _col["pos"] <= max(1, _col["total"] - 1))

        # 记完这一段的 Toplevel 收尾
        try:
            _SP_STATE["top"].destroy()
        except Exception:
            pass

    finally:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass
        try:
            os.remove(plug_path)
        except Exception:
            pass
        shutil.rmtree(PLUGIN_DIR, ignore_errors=True)

        # 真实仓库的 plugins/ 也必须能被无损扫描（用独立实例，不动共享实例）。
        # 这一条替换掉原来"在真目录里造插件"的做法，隔离与覆盖两者都要。
        def _scan_real_plugins():
            from toolkit_plugins import PluginManager as _PM
            real = _PM(os.path.join(BASE, "plugins"),
                       log=lambda m, t="info": None, summary=lambda m, t="info": None)
            real.scan()
            assert not real.load_errors, "加载错误：%s" % (real.load_errors[:3],)

        check("真实 plugins/ 目录可无损扫描（无加载错误）", _scan_real_plugins)

    print("\n" + "=" * 66)
    print("PASS %d  FAIL %d  SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("失败：")
        for n in FAIL:
            print("  - " + n)
    print("=" * 66)
    return 1 if FAIL else 0


def _find_option_menu(w, text):
    """在控件树里找一个**真的下拉控件**，其取值或标签含 text。

    两种"下拉里能看到 text"的形态，本函数都要认：
      1. text 是下拉的**取值** —— `register_option_entry` 往已有下拉加的条目
         （如 font 的"游戏版本"下拉取值里多出 "HUB-游戏"），体现为选项值；
      2. text 是下拉的**显示名** —— `register_option` 新建的下拉，它的 label
         由 `plugin_options_area` 渲染成同容器里紧邻的 ttk.Label，而菜单条目
         是 choices（本探针注册的 'A'/'B'），此时 menu label 里根本不会出现 text。
        早先这条检查拿"显示名"当"取值"查，永远找不到，于是把**已经渲染出来的
        下拉**误判成没生效。

    工程里的下拉**实际是 `ttk.OptionMenu`**（`toolkit_widgets.tool_dropdown` 与
    `plugin_options_area` 都用它）。`ttk.OptionMenu` 继承的是 `ttk.Menubutton`，
    **不是** `tk.OptionMenu` / `tk.Menubutton` —— 早先这里只判后两者，同样会
    "看不见"控件。
    注意 `tk` 必须在函数内导入：它原本只在 main() 里绑定，模块级没有这个名字，
    于是 `tk.Menubutton` 抛 NameError 并被下面的 except 吞掉 —— 表现同样是
    "永远找不到"，与判据错误一样隐蔽。
    """
    import tkinter as tk
    from tkinter import ttk
    try:
        if isinstance(w, (tk.Menubutton, ttk.Menubutton)):
            menu = w["menu"]
            n = menu.index("end")
            if n is not None:
                for i in range(n + 1):
                    try:
                        if str(menu.entrycget(i, "label")) == text:
                            return True                  # 形态 1：text 是取值
                    except Exception:
                        pass
                # 形态 2：text 是下拉显示名 —— 相邻（同容器、紧前一个）的标签文本
                parent = w.master
                if parent is not None:
                    kids = parent.winfo_children()
                    idx = kids.index(w)
                    if idx > 0 and isinstance(kids[idx - 1], (tk.Label, ttk.Label)):
                        lab = str(kids[idx - 1].cget("text")).strip()
                        if lab == text or lab.rstrip(":：").strip() == text:
                            return True
    except Exception:
        pass
    for c in w.winfo_children():
        if _find_option_menu(c, text):
            return True
    return False


def _find_labelframe(w, text):
    from tkinter import ttk
    try:
        if isinstance(w, ttk.LabelFrame) and text.strip() in str(w.cget("text")):
            return True
    except Exception:
        pass
    for c in w.winfo_children():
        if _find_labelframe(c, text):
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())

