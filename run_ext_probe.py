# -*- coding: utf-8 -*-
"""扩展点一致性测试（可进 CI）

把验收标准「加东西不改 app 文件」变成可机器检查的测试：
  正例 —— 装一个覆盖各类注册的探针插件，按 Hub 真实路径构造六个工具，
          检查每条注册**是否真的落地**（注册成功但无人消费 = 静默失效，判 FAIL）；
  负例 —— 灌入常见错误写法，要求**既不生效、又留下可见记录**（不允许静默）。

退出码非 0 表示存在缺口（打印缺口清单）。运行：python run_ext_probe.py
"""
import os
import shutil
import sys
import tempfile
import tkinter as tk
from tkinter import ttk

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "file_system"))

# 隔离：探针插件写进**本进程独有**的临时目录，不再写仓库的 plugins/。
# 原因：CI 与多个探针（run_hub_probe 也写 zz_*.py）可能并发运行，固定文件名会
# 互相覆盖；更糟的是 Hub 级探针会把别的探针插件算成自己的注册，于是
# "6 内置 + 1 插件"这类计数随机飘。
PLUGIN_DIR = tempfile.mkdtemp(prefix="ext_probe_plugins_")
PROBE_PLUGIN = os.path.join(PLUGIN_DIR, "zz_probe_ext.py")
BAD_PLUGIN = os.path.join(PLUGIN_DIR, "zz_probe_bad.py")

PROBE_SRC = '''PLUGIN_INFO = {"name": "探针插件"}

def register(api):
    api.register_command("export_csv", "P-导出CSV", lambda app=None: None)
    api.register_menu_item(command="export_csv", host="xml", location="toolbar")
    api.register_menu_item(command="export_csv", host="convert", location="toolbar")
    api.register_command("reparse", "P-重新解析", lambda app=None: None, when={"loaded": False})
    api.register_menu_item(command="reparse", host="fs", location="toolbar")
    api.register_menu_item(command="reparse", host="fs", location="context")
    api.register_option_entry("fs", "format", "P-格式")
    api.register_option_entry("convert", "source_enc", "P-编码")
    api.register_option_entry("xml", "filter", "P-筛选")
    api.register_option_entry("font", "game", "P-游戏")
    api.register_option("P-下拉", ["A", "B"], callback=lambda v, app=None: None,
                        host="video", area="top_bar")
    api.register_panel("P-面板", lambda parent: None, host="xml", area="top_bar")
    # 挂载顺序可调：order 升序，同值保注册顺序
    api.register_command("ord3", "P-序3", lambda app=None: None)
    api.register_command("ord1", "P-序1", lambda app=None: None)
    api.register_command("ord2", "P-序2", lambda app=None: None)
    api.register_menu_item(command="ord3", host="text", location="toolbar", order=30)
    api.register_menu_item(command="ord1", host="text", location="toolbar", order=10)
    api.register_menu_item(command="ord2", host="text", location="toolbar", order=20)
    api.register_panel("P-面板后", lambda parent: None, host="xml", area="top_bar", order=5)
    api.register_panel("P-面板前", lambda parent: None, host="xml", area="top_bar", order=1)
    api.register_decryptor(lambda p: False, lambda p: b"")
    api.register_format("probe-fmt", {"unpack": lambda raw: [], "pack": lambda files: b""})
    # ── A1 验收：贡献一种**全新的比较模式**（不碰任何 app 文件）──
    # 新列用与内置不同的 key（plugin_a / plugin_b），才能证明"新列被加进去了"。
    api.register_compare_mode(
        "P-探针模式",
        [("rel", "文件", 280), ("status", "状态", 60),
         ("plugin_a", "插件列A", 90), ("plugin_b", "插件列B", 90)],
        lambda ctx, pa, pb, rel: {"rel": rel, "consistent": False, "mode": "P-探针模式",
                                  "plugin_a": "A" + rel, "plugin_b": "B" + rel},
        row_builder=lambda r: ("diff", {"only"}),
        filters=[("全部", ("diff",), None), ("P-只看差异", ("diff",), ("only",))],
        order=99,
    )
    # 带 when 的条件命令：用于验证"槽位刷新后 when 真的生效"
    api.register_command("cond", "P-条件", lambda app=None: None,
                         when={"flag": True})
    api.register_menu_item(command="cond", host="font", location="toolbar")
'''

# 常见错误写法：每一条都必须被拒绝并留下记录
BAD_SRC = '''PLUGIN_INFO = {"name": "错误写法探针"}

def register(api):
    api.register_menu_item(command="whatever", host="notexist")          # 非法 host
    api.register_menu_item(command="whatever", host="fs", location="nowhere")  # 非法 slot
    api.register_menu_item(command="never_registered_cmd", host="fs")    # 引用未注册命令
    api.register_command("dup", "第一次", lambda app=None: None)
    api.register_command("dup", "第二次", lambda app=None: None)          # 同插件内重复 id
    api.register_command("bad name!", "非法动作名", lambda app=None: None)
    api.register_command("no_handler", "handler 不可调用", None)
    api.register_panel("坏面板", None, host="fs")                        # builder 不可调用
    api.register_compare_mode("P-重复模式", [("rel", "文件")],            # 同插件内重复模式名
                              lambda ctx, pa, pb, rel=None: None,
                              lambda r: ("diff", set()))
    api.register_compare_mode("P-重复模式", [("rel", "文件")],
                              lambda ctx, pa, pb, rel=None: None,
                              lambda r: ("diff", set()))
'''

SYNTAX_BAD = os.path.join(PLUGIN_DIR, "zz_probe_syntax.py")

for p, src in ((PROBE_PLUGIN, PROBE_SRC), (BAD_PLUGIN, BAD_SRC),
               (SYNTAX_BAD, "def register(api)\n    pass\n")):
    with open(p, "w", encoding="utf-8") as f:
        f.write(src)

# 实验性插件 engine_utf8_patch（xrEngine UTF-8 补丁）——把**真实插件文件**复制进
# 本进程独有的临时插件目录，于是下面所有断言针对的都是真货，而不是探针里手抄的替身。
# 手抄替身的老问题：替身怎么写都能过，真插件少注册一条却没人发现。
#
# ★ 缺件必须是 SKIP 而不是 FAIL：`plugins/*` 已被 .gitignore（只留 .gitkeep），
#   所以**干净克隆里 plugins/ 是空的**，公开 CI（windows-latest 跑 run_ci.py --fast）
#   会因此在仓库上永久变红。这与 run_ci.py 对闭源插件 nlc_sqfs 的
#   `SKIP (closed-source plugin not in repository)` 是同一条纪律：
#   缺件不算失败、退出码仍为 0；只有真失败才 FAIL、才非零退出。
ENGINE_PLUGIN = "engine_utf8_patch.py"
_engine_src = os.path.join(BASE, "plugins", ENGINE_PLUGIN)
ENGINE_PLUGIN_PRESENT = os.path.isfile(_engine_src)
ENGINE_SKIP_WHY = ("%s 不在仓库里（找不到 %s；plugins/* 已被 .gitignore，"
                   "干净克隆里 plugins/ 是空的），实验性插件的断言整批跳过"
                   % (ENGINE_PLUGIN, _engine_src))
if ENGINE_PLUGIN_PRESENT:
    shutil.copyfile(_engine_src, os.path.join(PLUGIN_DIR, ENGINE_PLUGIN))
else:
    print("  注意：%s" % ENGINE_SKIP_WHY)

import toolkit_log
from toolkit import (_BaseTk, apply_theme, PluginManager, invoke_plugin_callback,
                     attach_plugin_context_menu)
from apps.fs_app import FSToolApp
from apps.convert_app import ConvertApp
from apps.text_extract_app import TextExtractApp
from apps.xml_compare_app import XMLCompareApp
from apps.video_ogm_app import VideoOGMApp
from apps.font_pack_app import FontPackApp

TOOLS = [("fs", FSToolApp), ("convert", ConvertApp), ("text", TextExtractApp),
         ("xml", XMLCompareApp), ("video", VideoOGMApp), ("font", FontPackApp)]
PASS, FAIL, SKIP = [], [], []


def check(name, ok, detail=""):
    """记录一条断言。`ok` 可以用三种写法：

      * 布尔表达式 —— `check("x", a == b)`；
      * **可调用对象** —— `check("x", lambda: a == b)` 或 `check("x", 已经写好的函数)`；
        这时求值**一次**，抛异常即 FAIL 并把异常文本放进 detail；
      * 返回 `None` 的可调用对象 —— 内部用 `assert` 断言的函数（本仓库另两个探针
        run_hub_probe / run_app_probe 就是这个约定：函数体里 assert、不返回值），
        `None` 视为**通过**，assert 失败时会抛 AssertionError 从而判 FAIL。

    ★ 为什么 `check` 必须自己支持可调用对象（而不是"在调用处记得加括号"）：
      本探针曾有 **5 条** 断言写成 `check("...", lambda: ...)` / `check("...", 函数名)`。
      lambda 对象和函数对象**恒为真**，于是那 5 条永远 PASS —— 断言在，但从不生效。
      只在调用处补 `()` 只能堵住已知的 5 处；把"可调用即求值"做进 `check` 本体，
      才能把**这一类写法**（含嵌在表达式里的 lambda）全部堵死。
      这条语义由 `_check_semantics_selftest()` 自锁：谁把这里改回"直接当真假值"，
      自测会立刻报 FAIL。
    """
    if callable(ok):
        try:
            r = ok()
        except Exception as e:
            ok = False
            detail = ("求值抛异常 %s: %s" % (type(e).__name__, e)
                      + ("  " + detail if detail else ""))
        else:
            # None → 通过（内部用 assert 的函数约定）；其余按真假判定，
            # 于是 `lambda: cond`、`lambda: False` 都照常生效。
            ok = True if r is None else bool(r)
    (PASS if ok else FAIL).append(name)
    print("  %-4s %s%s" % ("PASS" if ok else "FAIL", name,
                           "" if ok else "   <- " + detail))


def _check_semantics_selftest():
    """自锁 `check()` 的可调用语义：返回 False / 抛异常都必须判 FAIL。

    为什么要有这条：`check` 支持可调用对象这件事本身就是"防止断言空转"的闸门，
    闸门自己必须被验证 —— 否则一次"把 check 改回直接判真假"的重构会让 5 条断言
    重新变成永远 PASS，而探针照样全绿。
    用 PASS/FAIL 的临时快照跑，不污染本探针的统计；输出重定向掉，避免刷屏。
    """
    import contextlib
    import io
    global PASS, FAIL
    keep_p, keep_f = PASS, FAIL
    results = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            PASS, FAIL = [], []
            check("_selftest_false", lambda: False)
            results["false"] = (list(PASS), list(FAIL))
            PASS, FAIL = [], []
            check("_selftest_true", lambda: True)
            results["true"] = (list(PASS), list(FAIL))
            PASS, FAIL = [], []
            check("_selftest_none", lambda: None)
            results["none"] = (list(PASS), list(FAIL))

            def _boom():
                raise RuntimeError("自测故意抛错")
            PASS, FAIL = [], []
            check("_selftest_boom", _boom)
            results["boom"] = (list(PASS), list(FAIL))
            PASS, FAIL = [], []
            check("_selftest_bare_func", _check_semantics_bare_assert_ok)
            results["bare"] = (list(PASS), list(FAIL))
    finally:
        PASS, FAIL = keep_p, keep_f
    return (results.get("false") == ([], ["_selftest_false"])
            and results.get("true") == (["_selftest_true"], [])
            and results.get("none") == (["_selftest_none"], [])
            and results.get("boom") == ([], ["_selftest_boom"])
            and results.get("bare") == (["_selftest_bare_func"], []))


def _check_semantics_bare_assert_ok():
    """内部只用 assert、不返回值 —— 模拟 run_hub_probe/run_app_probe 那种写法。"""
    a = 1
    assert a == 1
    return None


def skip(name, why):
    """记一条 SKIP。**缺件**（不在仓库里）走这里，不写 FAIL、不影响退出码。

    与 run_hub_probe.py 的 skip() 同形；reason 必须自解释（带上路径与原因），
    否则读日志的人只会看到一个没有上下文的 SKIP。
    """
    SKIP.append(name)
    print("  SKIP %s（%s）" % (name, why))


def collect(w, out):
    try:
        if isinstance(w, (ttk.Button, tk.Button)):
            out["buttons"].append(str(w.cget("text")))
        if isinstance(w, tk.Menu):
            n = w.index("end")
            if n is not None:
                for i in range(n + 1):
                    try:
                        if w.type(i) != "separator":
                            out["menu"].append(str(w.entrycget(i, "label")))
                    except Exception:
                        pass
        if isinstance(w, ttk.Combobox):
            out["combo"] += [str(v) for v in w.cget("values")]
        if isinstance(w, ttk.LabelFrame):
            out["labs"].append(str(w.cget("text")).strip())
        v = getattr(w, "vars", None)
        if isinstance(v, dict):
            out["opts"] += list(v.keys())
    except Exception:
        pass
    for c in w.winfo_children():
        collect(c, out)


logs = []
toolkit_log.set_gui_sink(lambda m, t="info": logs.append((m, t)))
root = _BaseTk()
apply_theme()
pm = PluginManager.shared(PLUGIN_DIR, log=lambda m, t="info": None,
                          summary=lambda m, t="info": None)
nb = ttk.Notebook(root)
nb.pack(fill="both", expand=True)

ev = {}
ev_tab = {}          # host -> 该组件的 Tab 控件（供"面板里的控件真的建出来了"这类断言用）
for host, cls in TOOLS:
    tab = tk.Frame(nb)
    nb.add(tab, text=host)
    ev_tab[host] = tab
    try:
        app = cls(tab)
    except Exception as e:
        app = None
        logs.append(("构造失败 %s: %s" % (host, e), "err"))
    out = {"buttons": [], "menu": [], "combo": [], "labs": [], "opts": []}
    if app is not None:
        collect(tab, out)
    ev[host] = out

print("=== 0. 探针自身：check() 的可调用语义（防止断言空转的那道闸门） ===")
# ★ 这一条**故意立刻调用**（`()`），跟别处"把函数对象交给 check"的写法不同：
#   它要防的恰恰是"check 退回直接判真假"。若把函数对象本身交给 check，一旦 check
#   真的被改回 bool-API，函数对象恒为真 → **这条自锁自己就变成空转**，什么都抓不住
#   （实测：注入回退后 `check(name, _check_semantics_selftest)` 仍然 PASS）。
#   自锁必须 eagerly 求值成布尔，才不受它自己要检测的那个缺陷影响。
check("check() 可调用语义自锁（False/异常→FAIL，True/None→PASS）",
      _check_semantics_selftest())

print("=== 正例：注册是否真的落地（注册成功但无人消费 = 静默失效） ===")
CASES = [
    ("toolbar @xml", "P-导出CSV", "xml", "buttons"),
    ("toolbar @convert", "P-导出CSV", "convert", "buttons"),
    ("toolbar @fs(带 when)", "P-重新解析", "fs", "buttons"),
    ("context @fs", "P-重新解析", "fs", "menu"),
    ("下拉条目 @fs/format", "P-格式", "fs", "menu"),
    ("下拉条目 @convert/source_enc", "P-编码", "convert", "combo"),
    ("下拉条目 @xml/filter", "P-筛选", "xml", "combo"),
    ("下拉条目 @font/game", "P-游戏", "font", "menu"),
    ("新建下拉 @video", "P-下拉", "video", "opts"),
    ("面板 @xml", "P-面板", "xml", "labs"),
]
for name, label, host, bucket in CASES:
    check(name, label in ev[host][bucket], "已注册但组件未消费/未接线")

print("=== 隔离：给 xml 的动作不得出现在 fs ===")
check("跨组件隔离", "P-导出CSV" not in ev["fs"]["buttons"])

print("=== 挂载顺序可调（order 升序，同值保注册顺序） ===")
_ord_btns = [b for b in ev["text"]["buttons"] if b in ("P-序1", "P-序2", "P-序3")]
check("toolbar 动作按 order 排序", _ord_btns == ["P-序1", "P-序2", "P-序3"],
      "实际 %s" % _ord_btns)
_panels = [l.strip() for l in ev["xml"]["labs"] if l.strip() in ("P-面板前", "P-面板后")]
check("面板按 order 排序（面板在前、P-面板居中、P-面板后在后）",
      _panels == ["P-面板前", "P-面板后"], "实际 %s" % _panels)
_txt_ctx = [it.get("label") for it in pm.menu_items_for("text", "toolbar", None)]
check("menu_items_for 返回顺序 = order 升序",
      _txt_ctx == ["P-序1", "P-序2", "P-序3"], "实际 %s" % _txt_ctx)

print("=== 实验性插件 engine_utf8_patch：贡献点是否真的落地 ===")
# 这组断言针对的是从 plugins/ 里复制进来的**真实插件文件**。
# 插件文件不在仓库里时（plugins/* 被 gitignore）整批记 SKIP —— 见 _engine_check。
#
# ★ 挂载点（2026-09 用户要求从 fs 挪到"汉化包生成"）：
#     动作 → HOST_FONT 的 toolbar；面板 → HOST_FONT 的 AREA_BOTTOM（真·底部）。
#   这里连"确实从 fs 搬走了"一起钉住，免得将来又飘回文件系统 Tab。
ENGINE_HOST = "font"
ENGINE_HOST_OTHER = ("fs", "convert", "text", "xml", "video")
ENGINE_TOOLBAR = ("补丁·识别", "补丁·校验", "补丁·生成")
ENGINE_PANEL_TITLE = "引擎 UTF-8 补丁（实验性·内部测试）"
# 这 10 条断言的**唯一名字来源**：实跑时逐条登记，空仓库时按同一批名字整批 SKIP。
ENGINE_CHECK_NAMES = (
    "实验插件被真实加载（无 load_errors）",
    "实验插件注册了 identify/verify/apply 三个命令",
    "实验插件的三个动作挂在 汉化包生成 的 toolbar 槽",
    "实验插件在 汉化包生成 里真的渲染出三个按钮",
    "实验插件只贡献到 汉化包生成（不污染其余五个组件）",
    "实验插件的面板进了 汉化包生成 的底部区域（AREA_BOTTOM，且真的在最下方）",
    "实验插件没有新增 Hub 栏目（内置六栏目的计数锁不被扰动）",
    "实验插件的面板：3 个按钮都绑了回调 + 一个只读结果框",
    "实验插件的识别/生成/校验真的可调用（含缺陷形态负例）",
    "实验插件已从文件系统组件搬走（fs 里既无面板也无动作）",
    "实验插件面板的三个按钮点了真的进对应流程（不只是 command 非空）",
)
_engine_seen = []


def _engine_check(name, ok, detail=""):
    """实验性插件断言的统一入口：文件不在仓库里 → SKIP，否则正常 check。

    为什么要有这个分派：`plugins/*` 已被 .gitignore，干净克隆里 `plugins/` 是空的。
    若缺件时照常 check，这 11 条会在公开 CI 上永久 FAIL，等于用"缺件"把仓库判红。
    缺件 ≠ 失败 —— 与 run_ci.py 对闭源插件 nlc_sqfs 的 SKIP 处理同一条纪律。

    注意 `ok` 在缺件时也会被**求值**（调用点是 eager 的），所以每个判定表达式
    都必须是"插件不在时也能安全算完"的纯只读判断（本节的 10 条都满足：
    最坏只是 _engine_patch_logic_ok 返回 "没拿到插件模块实例"）。
    """
    _engine_seen.append(name)
    if not ENGINE_PLUGIN_PRESENT:
        skip(name, ENGINE_SKIP_WHY)
        return
    check(name, ok, detail)


def _iter_widgets(w):
    yield w
    for c in w.winfo_children():
        for sub in _iter_widgets(c):
            yield sub


def _engine_panel_bottom_problem():
    """面板必须真的落在「汉化包生成」Tab 的**底部区域**（AREA_BOTTOM）。

    两个条件缺一不可：
      ① 面板 LabelFrame 出现在 font Tab 的控件树里（注册了却没渲染 = 静默失效）；
      ② 承载它的容器是按 `pack(side="bottom")` 排进去的。
    为什么②也要断：只断①的话，将来把 `tool_panel(...)` 的 `pack_kw` 从
    `side="bottom"` 改回默认的 top，面板会跑到 Tab 顶部，而"面板在不在"照样为真 ——
    用户的要求是"放在最下面"，所以**位置**同样是契约的一部分。

    返回 "" 表示没问题，否则返回具体原因（返回值不是布尔，所以调用处必须显式
    求值成布尔，不能把函数对象交给 check）。
    """
    lf = next((w for w in _iter_widgets(ev_tab[ENGINE_HOST])
               if isinstance(w, ttk.LabelFrame)
               and ENGINE_PANEL_TITLE in str(w.cget("text"))), None)
    if lf is None:
        return "汉化包生成 Tab 里找不到面板 LabelFrame（labs=%s）" % ev[ENGINE_HOST]["labs"]
    holder = lf.master
    side = ""
    try:
        side = str(holder.pack_info().get("side", ""))
    except Exception as e:
        return "读不到面板容器的 pack side: %s" % e
    if side != "bottom":
        return "面板容器不是按 side='bottom' 排的（实际 side=%r）→ 不在最下方" % side
    return ""


def _engine_panel_problem():
    """面板里必须真的有 3 个**绑了回调**的按钮 + 1 个只读结果框。

    "注册成功"≠"界面上能用"：builder 什么也没建、按钮 command 为空、
    结果框没建出来或可写，都属于"注册了但用户点不动"，必须在这里抓住。
    返回 "" 表示没问题，否则返回具体原因（注意本函数返回布尔以外的值，
    所以**不能**把函数对象直接交给 check —— 那正是本探针里
    `check(..., lambda: ...)` 那种写法永远为真的空转陷阱）。
    """
    lf = next((w for w in _iter_widgets(ev_tab[ENGINE_HOST])
               if isinstance(w, ttk.LabelFrame)
               and ENGINE_PANEL_TITLE in str(w.cget("text"))), None)
    if lf is None:
        return "汉化包生成 Tab 里找不到面板 LabelFrame"
    btns = {str(b.cget("text")): b for b in _iter_widgets(lf)
            if isinstance(b, ttk.Button)}
    missing = [n for n in ("识别", "校验", "生成") if n not in btns]
    if missing:
        return "面板里缺按钮 %s（实有 %s）" % (missing, sorted(btns))
    inert = [n for n in ("识别", "校验", "生成") if not str(btns[n].cget("command"))]
    if inert:
        return "面板按钮没绑回调（点了不会有反应）: %s" % inert
    texts = [w for w in _iter_widgets(lf) if isinstance(w, tk.Text)]
    if not texts:
        return "面板里没有结果文本框"
    if str(texts[0].cget("state")) != "disabled":
        return "结果框不是只读（state=%s）" % texts[0].cget("state")
    return ""


def _engine_patch_logic_ok():
    """贡献点背后的功能真的能跑（用插件自带的合成镜像，不碰游戏目录）。

    只断言"注册成功"是不够的：插件完全可能注册了一堆永远抛异常的回调。
    这里直接拿宿主加载进来的**那个模块实例**跑一遍识别/生成/校验，
    并顺手验一条负例（helper 覆盖 thunk 的缺陷形态必须被抓出来）。
    """
    mod = next((p["module"] for p in pm.plugins if p["file"] == ENGINE_PLUGIN), None)
    if mod is None:
        return False, "没拿到插件模块实例"
    orig = mod._synthetic_original()
    if mod.identify(orig, "<probe>")["verdict"] != "原版":
        return False, "合成原版被误判"
    built = mod.build_patched(orig)
    if not built["ok"]:
        return False, "生成失败: %s" % built["reason"]
    if mod.identify(built["patched"], "<probe>")["verdict"] != "v4(正确)":
        return False, "生成结果被误判"
    v = mod.verify(built["patched"], "<probe>")
    if not (v["ok"] and v["thunk_ok"] and v["present"] and v["corrected"]):
        return False, "校验未通过: %s" % v["verdict"]
    if mod.verify(mod._synth_shifted(orig, 9, True), "<probe>")["thunk_ok"]:
        return False, "缺陷形态（helper 覆盖 thunk）没被抓出来"
    return True, ""


# ── 11 条断言：调用顺序必须与 ENGINE_CHECK_NAMES 完全一致（末尾有 assert 兜底）──
_pm_files = [p["file"] for p in pm.plugins]
_engine_check(ENGINE_CHECK_NAMES[0],
              ENGINE_PLUGIN in _pm_files
              and not [e for e in pm.load_errors if ENGINE_PLUGIN in e],
              "已加载 %r / load_errors %s" % (_pm_files, pm.load_errors[-2:]))
_engine_check(ENGINE_CHECK_NAMES[1],
              all(("%s:%s" % (ENGINE_PLUGIN, a)) in pm.commands
                  for a in ("identify", "verify", "apply")),
              "commands=%s" % sorted(pm.commands))
_font_toolbar_labels = [it.get("label")
                        for it in pm.menu_items_for(ENGINE_HOST, "toolbar", None)]
_engine_check(ENGINE_CHECK_NAMES[2],
              all(lb in _font_toolbar_labels for lb in ENGINE_TOOLBAR),
              "font toolbar=%s" % _font_toolbar_labels)
_engine_check(ENGINE_CHECK_NAMES[3],
              all(lb in ev[ENGINE_HOST]["buttons"] for lb in ENGINE_TOOLBAR),
              "font buttons=%s" % ev[ENGINE_HOST]["buttons"])
_engine_check(ENGINE_CHECK_NAMES[4],
              not any(lb in ev[h]["buttons"] for h in ENGINE_HOST_OTHER
                      for lb in ENGINE_TOOLBAR),
              "其余组件的按钮: %s"
              % {h: ev[h]["buttons"] for h in ENGINE_HOST_OTHER})
_engine_panel_bottom_why = _engine_panel_bottom_problem()
_engine_check(ENGINE_CHECK_NAMES[5],
              not _engine_panel_bottom_why, _engine_panel_bottom_why)
_engine_check(ENGINE_CHECK_NAMES[6],
              not [t for t in pm.tools if t.get("plugin") == ENGINE_PLUGIN],
              "实验插件贡献的栏目: %s" % [t.get("name") for t in pm.tools
                                          if t.get("plugin") == ENGINE_PLUGIN])
_engine_panel_why = _engine_panel_problem()
_engine_check(ENGINE_CHECK_NAMES[7],
              not _engine_panel_why, _engine_panel_why)
_engine_logic_ok, _engine_logic_why = _engine_patch_logic_ok()
_engine_check(ENGINE_CHECK_NAMES[8], _engine_logic_ok, _engine_logic_why)

# ⑩ "确实从 fs 搬走了"：fs 上既不能有本插件的**面板**（注册表 + 渲染），
#    也不能有本插件的 **toolbar 挂载点**。这条是防"将来又飘回文件系统组件"的锁 ——
#    用户明确要求把它挪出 fs，光靠"font 上有"是证明不了"fs 上没有"的。
_fs_panels = [p for p in pm.panels_for("fs", None, None)
              if p.get("plugin") == ENGINE_PLUGIN]
_fs_mounts = [it for it in pm.menu_items_for("fs", "toolbar", None)
              if it.get("plugin") == ENGINE_PLUGIN]
_fs_render = [str(l).strip() for l in ev["fs"]["labs"]
              if ENGINE_PANEL_TITLE in str(l)]
_engine_check(ENGINE_CHECK_NAMES[9],
              not _fs_panels and not _fs_mounts and not _fs_render,
              "fs 残留: 面板注册 %s / toolbar 挂载 %s / 已渲染 %s"
              % ([p.get("title") for p in _fs_panels],
                 [it.get("label") for it in _fs_mounts], _fs_render))

# ⑪ "回调非空" ≠ "点了做对的事"：真 `invoke()` 一次，看进的是不是对应的那个 op。
#    为什么迁移后必须补这条：面板改用 `api.ui` 之后三个按钮都由同一个 builder 造，
#    接线接错（比如三个都接 identify）时"command 非空 + 控件齐全"照样全绿。
def _engine_panel_click_ok():
    mod = next((p["module"] for p in pm.plugins if p["file"] == ENGINE_PLUGIN), None)
    if mod is None:
        return False, "没拿到插件模块实例"
    lf = next((w for w in _iter_widgets(ev_tab[ENGINE_HOST])
               if isinstance(w, ttk.LabelFrame)
               and ENGINE_PANEL_TITLE in str(w.cget("text"))), None)
    if lf is None:
        return False, "找不到面板 LabelFrame"
    btns = {str(b.cget("text")): b for b in _iter_widgets(lf)
            if isinstance(b, ttk.Button)}
    orig = getattr(mod, "_gui_run", None)
    if orig is None:
        return False, "插件里没有 _gui_run（面板接线的前提已变）"
    calls = []
    mod._gui_run = lambda op, parent=None: calls.append(op)
    try:
        for text in ("识别", "校验", "生成"):
            if text in btns:
                btns[text].invoke()
    finally:
        mod._gui_run = orig
    if calls != ["identify", "verify", "apply"]:
        return False, "点击进入的流程是 %r（应为 identify/verify/apply）" % (calls,)
    return True, ""


_engine_click_ok, _engine_click_why = _engine_panel_click_ok()
_engine_check(ENGINE_CHECK_NAMES[10], _engine_click_ok, _engine_click_why)

# 名单不许漂移：空仓库时按 ENGINE_CHECK_NAMES 整批 SKIP，两处必须完全一致，
# 否则会出现"实跑 11 条、SKIP 只报 10 条"这种静默漏报。
# 用 assert 而不是 check()：这是探针自身的完整性检查，不占用 PASS/FAIL/SKIP 名额。
assert tuple(_engine_seen) == ENGINE_CHECK_NAMES, (
    "实验插件断言名单漂移：实跑 %r / 登记 %r" % (tuple(_engine_seen), ENGINE_CHECK_NAMES))

print("=== A1 验收：插件贡献「新比较模式」——只写插件，改 0 个 app 文件 ===")
_modes = pm.compare_modes_for()
check("新模式已进注册表", "P-探针模式" in _modes)
check("内置模式仍在（未被插件顶掉）",
      "行数/ID 统计" in _modes and "ID 文本对比" in _modes)
check("模式按 order 排序（插件 order=99 排在内置之后）",
      list(_modes)[-1] == "P-探针模式" if _modes else False,
      "实际顺序 %s" % list(_modes))

# 负例：同一个插件里注册**两次同名**比较模式 —— 只进注册表一次。
# 这里的判重曾经写成 `if name in pm.compare_modes` —— 而 compare_modes 是
# "模式字典的列表"，字符串永远不在其中，于是这段检查是**死代码**，第二个注册
# 会静默进入注册表（compare_modes_for 用 setdefault 保留先注册者，后者的
# compare 永远不会被调用）。
#
# 语义订正（与 Hub 真实顺序对齐）：**同一插件**重复注册同名模式不是 bug，而是
# "重新扫描"的正常结果 —— scan() 会清空插件侧全部注册表，只有 compare_modes
# 因为内置与插件共用一张表而不能整表清空，于是每次 scan() 插件都会重新跑一遍
# register()。所以正确行为是**幂等**：表里始终只有一条，且以**最后一次**注册的
# 那份为准（热重载插件后新函数才会生效），而不是把它记成 load_errors 里的
# "插件加载失败"（Hub 启动弹窗会照此误报）。
# 注：不能拿"内置模式名"来当重复对象 —— 内置模式是**随 App 构造**才注册的
# （要拿到 PluginManager 实例才能注册），而 Hub 的顺序是"先扫插件、后建 App"，
# 因此插件注册同名内置模式时判重表里还没有内置项，插件会**抢占**该名字，
# 随后内置模式注册被 return False 静默丢弃。这是当前实现的真实顺序，另行记录。
_dup_modes = [m for m in pm.compare_modes if m["name"] == "P-重复模式"]
check("负例：同插件内重复模式名只进注册表一次（幂等，不记错误）",
      len(_dup_modes) == 1 and not any("P-重复模式" in e for e in pm.load_errors),
      "注册表 %d 条，load_errors: %s" % (len(_dup_modes), pm.load_errors[-3:]))
check("负例：重复注册后以最后一次为准（旧函数不得留下）",
      bool(_dup_modes) and getattr(_dup_modes[0]["compare"], "__module__", "").endswith("zz_probe_bad"))

# 同名冲突时内置必须赢，**与注册顺序无关**（单实例、单元级验证）。
# 背景：内置模式的注册需要 PluginManager 实例，因此随 App 构造才发生，
# 而 Hub 是"先扫插件、后建 App" → 插件会先占住名字。若只靠"内置先注册"，
# 插件（可能只是无意重名）就会把内置模式顶掉。
def _builtin_wins_on_name_clash():
    from toolkit_plugins import PluginManager as _PM
    plug = {"columns": [], "compare": None, "row_builder": None,
            "filters": None, "detail_builder": None, "order": 0}
    # ① 插件先占名字，内置**后**注册 —— 必须仍然生效（真实顺序就是这样）
    tmp = _PM(PLUGIN_DIR, log=lambda m, t="info": None,
              summary=lambda m, t="info": None)
    tmp.register_compare_mode("同名模式", [("rel", "文件")], None, plugin="some_plugin.py")
    ok_late = tmp.register_compare_mode("同名模式", [("rel", "文件")], None)
    assert ok_late is True, "插件先占名字后，内置注册被挡回去了（内置将永远进不了表）"
    got = tmp.compare_modes_for()["同名模式"]
    assert got.get("plugin") == "<builtin>", \
        "内置被插件顶掉了：plugin=%r" % got.get("plugin")

    # ② 重复构造 App 不应让注册表无限增长
    assert tmp.register_compare_mode("同名模式", [("rel", "文件")], None) is False, \
        "同一内置名字被重复登记"
    assert len([m for m in tmp.compare_modes if m["name"] == "同名模式"]) == 2, \
        "注册表条目数异常：%d" % len([m for m in tmp.compare_modes
                                     if m["name"] == "同名模式"])

    # ③ 非内置（插件）想顶内置名字 → 拒绝
    assert tmp.register_compare_mode("同名模式", [("rel", "文件")], None,
                                     plugin="another_plugin.py") is False
    assert plug is not None
check("同名比较模式冲突时内置优先（插件先占名字也不顶掉内置）",
      _builtin_wins_on_name_clash)
_xml_app = None
for _h, _c in TOOLS:
    if _h == "xml":
        _t = tk.Frame(nb)
        try:
            _xml_app = _c(_t)
        except Exception as _e:
            logs.append(("xml 二次构造失败: %s" % _e, "err"))
if _xml_app is not None:
    check("模式下拉包含插件模式",
          "P-探针模式" in list(_xml_app.cb_mode.cget("values")))
    _xml_app.mode_var.set("P-探针模式")
    _xml_app.results = [{"rel": "x.xml", "consistent": False, "mode": "P-探针模式",
                         "plugin_a": "A", "plugin_b": "B"}]
    _cols = _xml_app._apply_columns()
    _ids = [c[0] for c in _cols]
    check("插件声明的新列真的进了表格",
          "plugin_a" in _ids and "plugin_b" in _ids, "实际列 %s" % _ids)
    _xml_app.filter_var.set("全部")
    _xml_app._refresh_tree()
    check("插件模式的行能渲染出来",
          len(_xml_app.tree.get_children()) == 1)
else:
    check("xml 二次构造", False, "构造失败")

print("=== A1 验收：插件贡献「新格式」——只写插件，改 0 个 app 文件 ===")
_fmt_names = [f["name"] for f in pm.formats]
check("新格式已进插件格式表", "probe-fmt" in _fmt_names)
_fs_app = None
for _h, _c in TOOLS:
    if _h == "fs":
        _t = tk.Frame(nb)
        try:
            _fs_app = _c(_t)
        except Exception as _e:
            logs.append(("fs 二次构造失败: %s" % _e, "err"))
if _fs_app is not None:
    _vals = list(_fs_app.fmt_keys)
    check("新格式出现在 fs 的格式下拉候选里", "probe-fmt" in _vals,
          "实际 %r" % (_vals,))
    _pack_vals = list(_fs_app.pack_fmt_keys)
    check("新格式也出现在封包格式下拉候选里", "probe-fmt" in _pack_vals)
    # 真调用：先调用一次插件 handler 的 pack/unpack，证明"派发可用"而不是"能查到"
    _found = next((f for f in _fs_app.plugins.formats if f["name"] == "probe-fmt"), None)
    # 真调用：先调用一次插件 handler 的 pack/unpack，证明"派发可用"而不是"能查到"
    _h = (_found or {}).get("handler") or {}
    try:
        _packed = _h["pack"]([("a.txt", b"hi", False)])
        _unpacked = _h["unpack"](_packed)
    except Exception as _e:
        _packed, _unpacked = None, None
        logs.append(("插件格式 handler 调用失败: %s" % _e, "err"))
    check("插件格式的 pack/unpack 能被真实调用",
          isinstance(_packed, (bytes, bytearray)) and _unpacked is not None)
    # 关键：直接测**派发**是否真的走了插件分支（而不是只证明 handler 存在）
    try:
        _via_dispatch = _fs_app._pack_with_format([("a.txt", b"hi", False)], "probe-fmt")
    except Exception as _e:
        _via_dispatch = None
        logs.append(("格式派发失败: %s" % _e, "err"))
    check("封包派发真的走插件分支（_pack_with_format）",
          _via_dispatch == _packed,
          "派发结果 %r / 直接调用 %r" % (_via_dispatch, _packed))
    # 反例：内置格式仍走 pack_db（没有被插件分支误吃）
    try:
        _via_builtin = _fs_app._pack_with_format([("a.txt", b"hi", False)], "xdb")
        _builtin_ok = isinstance(_via_builtin, (bytes, bytearray)) and len(_via_builtin) > 0
    except Exception as _e:
        _builtin_ok = False
        logs.append(("内置格式派发失败: %s" % _e, "err"))
    check("内置格式仍走 pack_db（未被插件分支误吃）", _builtin_ok)
else:
    check("fs 二次构造", False, "构造失败")

print("=== when 条件必须随状态变化生效（槽位刷新机制） ===")
_font_app = None
for _h, _c in TOOLS:
    if _h == "font":
        _t = tk.Frame(nb)
        try:
            _font_app = _c(_t)
        except Exception as _e:
            logs.append(("font 二次构造失败: %s" % _e, "err"))
if _font_app is not None:
    _slot = getattr(_font_app, "_slot_bar", None)
    if _slot is None:
        check("font 持有槽位句柄", False, "未保存 _slot_bar")
    else:
        def _bar_has(label):
            f = _slot.frame
            if f is None:
                return False
            for w in f.winfo_children():
                try:
                    if str(w.cget("text")) == label:
                        return True
                except Exception:
                    pass
            return False

        check("context 不满足时带 when 的命令不可见",
              lambda: not _bar_has("P-条件"))
        _slot._context = {"flag": True}
        _slot.refresh()
        check("刷新后 context 满足 → 命令出现", lambda: _bar_has("P-条件"))
        _slot._context = {"flag": False}
        _slot.refresh()
        check("再次刷新 → 命令消失（不是建了就不管）",
              lambda: not _bar_has("P-条件"))
else:
    check("font 二次构造", False, "构造失败")

print("=== 负例：常见错误写法必须被拒绝且留下记录 ===")
errs = pm.registration_errors
def has(sub):
    return any(sub in e for e in errs)
check("非法 host 被拒", has("notexist"))
check("非法 location 被拒", has("nowhere"))
check("引用未注册命令被拒", has("never_registered_cmd"))
check("同插件内重复 id 被拒", has("重复注册"))
check("非法动作名被拒", has("bad name!"))
check("handler 不可调用被拒", has("不可调用"))
check("panel builder 不可调用被拒", any("builder" in e for e in errs))
def _other_plugin_same_mode_rejected():
    """**别的**插件想用已占用的模式名仍必须被拒绝并留痕（幂等只限同一插件）。

    同名模式"同一插件 = 重扫（幂等）" / "另一个插件 = 真冲突（拒绝）" 是两条
    不同的语义，分开验证，避免把判重整体放水。

    ★ 为什么走插件入口（Api）而不是 `PluginManager.register_compare_mode`：
      本函数原先用 `_PM.register_compare_mode(..., plugin="third_plugin.py")`
      这条**内部方法**模拟"另一个插件"，并要求 `registration_errors` 里有记录。
      那条路按它自己的文档只承诺"**返回 False** 拒绝"（toolkit_plugins.py:507），
      **不承诺留痕** —— 实测它的 `registration_errors` 为 `[]`。于是这条断言在
      `check()` 支持 callable 之后立刻暴露为 FAIL：它测的是错了的那一层。
      真实插件只会拿到 `PluginManager.scan()` 用 `_make_api()` 建出来的 Api 对象，
      拒绝与留痕都发生在 `Api.register_compare_mode` 那条路上。
      因此这里把两件事**分开**钉住，既不放过"插件重名被静默接受"，也不把内部方法
      没承诺过的行为当成缺陷：
        ① 插件入口：另一个插件重名 → 表里不新增条目 + `registration_errors` 留痕；
        ② 内部方法：按文档对非内置重名返回 False（不要求它留痕）。
    """
    from toolkit_plugins import PluginManager as _PM

    def _cmp(ctx, pa, pb, rel):
        return {"rel": rel, "consistent": False}

    # ① 插件入口（真实路径）
    tmp = _PM(PLUGIN_DIR, log=lambda m, t="info": None,
              summary=lambda m, t="info": None)
    api_b = tmp._make_api("other_plugin.py", {})
    api_c = tmp._make_api("third_plugin.py", {})
    api_b.register_compare_mode("占用名", [("rel", "文件")], _cmp, None)
    api_c.register_compare_mode("占用名", [("rel", "文件")], _cmp, None)
    assert len([m for m in tmp.compare_modes if m["name"] == "占用名"]) == 1, \
        ("另一个插件的重名模式进了注册表：%s"
         % [m.get("plugin") for m in tmp.compare_modes])
    assert any("已存在" in e for e in tmp.registration_errors), \
        "插件入口的拒绝必须留痕：%s" % tmp.registration_errors

    # ② 内部方法（组件注册内置模式用的那条）：文档契约 = 返回 False
    tmp2 = _PM(PLUGIN_DIR, log=lambda m, t="info": None,
               summary=lambda m, t="info": None)
    assert tmp2.register_compare_mode("占用名2", [("rel", "文件")], _cmp,
                                      plugin="other_plugin.py") is True
    assert tmp2.register_compare_mode("占用名2", [("rel", "文件")], _cmp,
                                      plugin="third_plugin.py") is False, \
        "内部方法对别的插件重名应返回 False"
    assert len([m for m in tmp2.compare_modes if m["name"] == "占用名2"]) == 1
check("另一个插件重名仍被拒绝并留痕（插件入口）/内部方法返回 False",
      _other_plugin_same_mode_rejected)

load_errs = [e for e in pm.load_errors if "zz_probe" in e]
check("register() 抛错/语法错进 load_errors", len(load_errs) >= 2,
      "load_errors 命中 %d 条" % len(load_errs))
_bad_ids = [m.get("command_id", "") for m in pm.menu_items]
check("非法注册未污染注册表",
      all(("dup" not in c) and ("no_handler" not in c) for c in _bad_ids))

print("=== 负例：回调抛异常不得静默 ===")
before = len(logs)


def _boom(app=None):
    raise RuntimeError("回调故意抛错")


try:
    invoke_plugin_callback(_boom)
    raised = False
except Exception:
    raised = True
new_logs = [m for m, t in logs[before:] if "回调" in m or "err" == t]
check("回调异常被兜住且留痕", (not raised) and len(new_logs) > 0,
      "raised=%s 新日志=%d" % (raised, len(new_logs)))

print("=== 负例：无注册控件不产生任何控件/绑定 ===")
f = tk.Frame(root)
check("空槽位不创建控件", (len(f.winfo_children()) == 0)
      and attach_plugin_context_menu(f, "text") is None)

root.destroy()
shutil.rmtree(PLUGIN_DIR, ignore_errors=True)

print("\n=== 结果 ===")
# 与 run_ci.py / run_functional_probe.py / run_hub_probe.py 同一格式：SKIP 单独计数。
print("PASS %d  FAIL %d  SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
if FAIL:
    print("缺口清单：")
    for f_ in FAIL:
        print("   -", f_)
if SKIP:
    print("跳过清单：")
    for s_ in SKIP:
        print("   -", s_)
sys.exit(1 if FAIL else 0)
