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
  E. 契约清单读取返回空元组（= 悄悄降级）→ "契约清单是从 toolkit_plugin_ui.py 读到的 16 个方法…"
  F. 面板『生成』接到 identify     → "实验插件面板的按钮点了真的进对应流程…"
     （这条跑的是 **Tk 侧**探针 `run_ext_probe.py`：结构锁只看 command 非空，接线接错照样绿）
  G. 把差异字节数塞进判定条件     → "AST 锁：判定路径里不得出现“差异字节数”这类代理指标…"
     （行为上什么都不改，**只有** AST 结构锁能抓住 —— 用它证明红线的结构锁不是摆设）

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
FPK = os.path.join(BASE, "font_pack", "font_pack.py")
FPA = os.path.join(BASE, "apps", "font_pack_app.py")
BG = os.path.join(BASE, "build_gui.py")
TW = os.path.join(BASE, "toolkit_widgets.py")
XCA = os.path.join(BASE, "apps", "xml_compare_app.py")
FSA = os.path.join(BASE, "apps", "fs_app.py")
SF = os.path.join(BASE, "file_system", "stalker_fs.py")
TEA = os.path.join(BASE, "apps", "text_extract_app.py")
TARGETS = (QT, QTH, PLUG, FPK, FPA, BG, TW, XCA, SF, FSA, TEA)

L_OK = "真实插件面板在 Qt 后端建出来了（panel/ok，而不是 skip）"
L_SRC = "engine_utf8_patch 里已无 Tk 构造/对话框（迁移真的落到 api.ui）"
L_ROW = "三个动作按钮落在同一个水平行容器里（pack(side='left') 语义）"
L_COL = "外层容器是竖直堆叠（Tk 默认 pack 方向），顺序 = 按钮行 → 提示行 → 结果框"

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
     "契约清单是从 toolkit_plugin_ui.py 读到的 16 个方法（没降级成空/旧清单）"),
    # ⑧ 接线接错：面板的『生成』也去 identify。结构锁（command 非空）抓不到，必须真 invoke()。
    #    这条同时跑 **Tk 侧**探针（run_ext_probe），因为"两个后端行为一致"才是迁移的验收点。
    (PLUG, "run_ext_probe.py", "面板『生成』接到 identify（接线接错）",
     'on_click=lambda: _gui_run("apply", wrap)',
     'on_click=lambda: _gui_run("identify", wrap)',
     "实验插件面板的按钮点了真的进对应流程（不只是 command 非空）"),
    # ⑨ 代理指标：把"差了多少字节"塞进**判定**（这里是一句空转的 if）。
    #    行为上什么都没改，所以只有 AST 结构锁能抓住它 —— 这条注入就是在证明
    #    "红线的结构锁不是摆设"。
    (PLUG, "run_ext_probe.py", "把差异字节数塞进判定条件（代理指标复活）",
     '    fp["changed_bytes"] = _changed_bytes(data)\n',
     '    fp["changed_bytes"] = _changed_bytes(data)\n'
     '    if fp["changed_bytes"] == 88:            # 注入：拿代理指标当判据\n'
     '        fp["cave_zeros"] = fp["cave_zeros"]\n',
     "AST 锁：判定路径里不得出现“差异字节数”这类代理指标（比较/条件/常量名）"),
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
    # ⑭⑮⑯⑰ 汉化包几何（2026-09-14 三修：①字比格子小 ②底边被吞 ③框伸进邻格）。
    #   三条都是"看着对、其实量得出来不对"的错法，所以每条都必须由 run_functional_probe.py
    #   的对应锁抓红；抓不住就说明那条锁是摆设。expect 允许给多个候选锁名 —— 几何是连锁的，
    #   例如"不封顶"会先撞 .ini 布局锁（同一批像素的另一条不变量），那也是被抓住了。
    (FPK, "run_functional_probe.py", "定标退化成按槽位名渲染（字又小 30%）",
     "    for cand in range(size, size + 14):",
     "    for cand in range(size, size + 1):   # 注入：不放大，退回按槽位名",
     ("汉化包：墨迹按格子定标", "汉化包：.ini 布局满足原版不变量")),
    (FPK, "run_functional_probe.py", "定标上限被拆掉（一路放大到越界）",
     "            if ih > cell_h - 4 or (rw is not None and iw > rw):",
     "            if False:                      # 注入：上限判据失效",
     ("汉化包：墨迹按格子定标", "汉化包：.ini 布局满足原版不变量",
      "汉化包：墨迹不出自己的行带下边界")),
    (FPK, "run_functional_probe.py", "贴图画布少一行（最后一行像素被 paste 静默丢）",
     "    need = max(1, max_y)",
     "    need = max(1, max_y - 1)   # 注入：旧写法",
     "汉化包：字库画布高 ≥ 行带总高"),
    (FPK, "run_functional_probe.py", "框宽不再封顶到 cell（伸进邻格采样框）",
     "        return min(rw, cell_h)",
     "        return rw              # 注入：不封顶",
     ("汉化包：.ini 布局满足原版不变量", "汉化包：DDS 逐字复核墨迹矩形 == 解析模型")),
    # ⑱⑲⑳ 简繁替换（用户口径 2026-09-14："日语的…那些缺简体的就上繁体"）。
    #   三条分别对应：表坏了 / 替换条件不存在（无条件替换）/ 界面退回过标签。
    (FPK, "run_functional_probe.py", "简繁替换表被清空（缺简体又变回空白）",
     "ST_FALLBACK = _load_st_fallback()",
     "ST_FALLBACK = {}   # 注入：替换表空",
     ("汉化包：简繁替换表只收", "汉化包：字体缺简体字形时用繁体字形补")),
    (FPK, "run_functional_probe.py", "无条件替换（字体本来有该字形也换成繁体）",
     # 注：font_pack.py 是 **CRLF** 文件，多行注入点里的 `\n` 匹配不上（本条第一版就栽在这，
     # 报"注入点出现 0 次"）。用带换行的单行锚点即可，两侧行尾都能匹配。
     "\n        if mb is None:",
     "\n        if True:                       # 注入：无条件替换",
     ("汉化包：字体缺简体字形时用繁体字形补", "汉化包：.ini 布局满足原版不变量",
      "汉化包：DDS 逐字复核墨迹矩形 == 解析模型")),
    (FPA, "run_app_probe.py", "字体选择器退回旧标签（不标日语、不说用繁体）",
     '                        return "japanese" if sample_fallback(path) else "missing"',
     '                        return "missing"   # 注入：退回旧行为',
     "字体选择器"),
    (FPK, "run_functional_probe.py", "墨迹不再压进框（框封顶后墨迹越框）",
     "        gw = ink_draw_w(gw, rw, pl)",
     "        pass                           # 注入：不压进框",
     ("汉化包：DDS 逐字复核墨迹矩形 == 解析模型", "汉化包：.ini 布局满足原版不变量")),
    # ㉒㉓㉔ 构建器（2026-09-14 用户口径："构建器，在切换标记的时候，序号也要自动改。还有，滚动条呢？"）
    (BG, "run_build_probe.py", "切标记不再同步序号（退回上一个标记的号）",
     "        self.var_marker_manual = True\n        self._sync_seq_to_channel()",
     "        self.var_marker_manual = True",
     "GUI：切换标记时序号跟着这个标记走"),
    (BG, "run_build_probe.py", "去掉版本号的 trace（改版本不再重算序号）",
     '        self.var_version.trace_add("write", lambda *a: self._on_version_edit())',
     '        pass   # 注入：去掉版本号 trace',
     "GUI：改版本号（新键）时序号按新键重算"),
    (BG, "run_build_probe.py", "构建输出退回只有竖条（wrap=none 的长行尾巴拖不到）",
     'LogBox(log_lf, height=16, wrap="none", hbar=True)',
     'LogBox(log_lf, height=16, wrap="none")',
     "GUI：构建输出（wrap=none）的横/竖滚动条该收就收"),
    # ㉕㉖ 树行内对齐（2026-09-14 用户口径："勾选框和三角、文字是错位的，统一以勾选框为准"）
    #   两条分别打"各元素各写各的 y+12"与"不给三角留槽（左半边画到画布外）"。
    (TW, "run_app_probe.py", "三角/文字退回写死的 y+12（与勾选框错位）",
     "\n            cy = self._row_center(i)",
     "\n            cy = y + 12",
     "HiDPI：树行内三角/文件名与勾选框对齐"),
    (TW, "run_app_probe.py", "不给三角留槽（CHK_PAD 不含 ARROW_W+GAP）",
     "        self.CHK_PAD = max(px(6), 2) + self.ARROW_W + self.ARROW_GAP",
     "        self.CHK_PAD = max(px(6), 2)",
     "HiDPI：树行内三角/文件名与勾选框对齐"),
    # ㉗㉘ 滚轮统一（2026-09-14 用户问"滚动条真的都统一了吗"→ 查出 id 画布没走统一规则）
    (XCA, "run_app_probe.py", "id 画布不再声明滚轮独占（同一次事件动两个滚动条）",
     "        if not wheel_claim(e):",
     "        if False:                      # 注入：不声明独占",
     "滚轮：id 差异画布与全局规则一致"),
    # ★ 2026-09-15：这条注入原来只拆 `if after == before:`（滚不动也吃）。加了"没条子
    #   不许滚"的闸之后，它**不再复现机制**了 —— 闸在更前面就返回 None，注入点根本走不到
    #   （实测注入后探针全绿）。改成一次拆掉两处：不看条子 + 滚不动也吃。
    (XCA, "run_app_probe.py", "id 画布不看条子 + 滚不动也吃事件",
     '        if not bar_shown(getattr(self, "_id_sb", None)):\n'
     '            return None                      # 没有滚动条的地方不许滚（用户规则 2026-09-15）\n'
     '        before = cv.yview()\n'
     '        cv.yview_scroll(-1 if e.delta > 0 else 1, "units")\n'
     '        after = cv.yview()\n'
     '        if after == before:\n'
     '            return None                      # 滚不动 → 这里没有可用的滚动条\n',
     '        if False:                            # 注入：不看条子（没条子也照样滚）\n'
     '            return None\n'
     '        before = cv.yview()\n'
     '        cv.yview_scroll(-1 if e.delta > 0 else 1, "units")\n'
     '        after = cv.yview()\n'
     '        if False:                            # 注入：滚不动也吃事件\n'
     '            return None\n',
     "装得下时不该吃滚轮"),
    # ㉙ 外部工具输出按平台默认编码解（2026-09-14：真实镜像上抓到 sq_meshes 整包被藏）
    (SF, "run_functional_probe.py", "rdsquashfs 输出退回平台默认编码（非 GBK 路径整包判损坏）",
     '        r = subprocess.run([tool, "--describe", path], capture_output=True, text=True,\n'
     '                           encoding="utf-8", errors="replace", timeout=30,',
     '        r = subprocess.run([tool, "--describe", path], capture_output=True, text=True,\n'
     '                           timeout=30,',
     ("引擎：外部工具输出显式指定 utf-8", "引擎：SquashFS 真实往返")),
    # ㉚㉛ 树的横向滚动条（2026-09-15 用户问"fs 的滚动条呢？"）
    (TW, "run_app_probe.py", "树退回只有竖条（长路径的尾巴看不到）",
     "                 hbar=True):",
     "                 hbar=False):",
     ("fs：三棵树都有横向滚动条", "HiDPI：树的横/竖滚动条撑满")),
    (TW, "run_app_probe.py", "scrollregion 的 x 范围退回 0（横向滚不动）",
     "        self._content_w = self._measure_content_w()",
     "        self._content_w = 0   # 注入：关掉横向滚动",
     "HiDPI：树的横/竖滚动条撑满"),
    # ㉜ 把 pack 顺序打回"画布先占（expand）"——2026-09-15 真实踩过的那一版：
    #     横条只能分残渣（恒 44x15）且**常驻可见**，还会顶得面板自己的竖条冒出来。
    #     注意 toolkit_widgets.py 是 **CRLF**，多行锚点里的 `\n` 匹配不上 →
    #     这里显式写 `\r\n`（先例见 ARCHITECTURE §7.3 的注入行尾说明）。
    (TW, "run_app_probe.py", "树的两条滚动条 pack 顺序打回错的那版（横条分残渣）",
     '        self.vbar.pack(side="right", fill="y")\r\n'
     '        if self.hbar is not None:\r\n'
     '            self.hbar.pack(side="bottom", fill="x")\r\n'
     '        self.canvas.pack(side="left", fill="both", expand=True)',
     '        self.canvas.pack(side="left", fill="both", expand=True)\r\n'
     '        self.vbar.pack(side="right", fill="y")\r\n'
     '        if self.hbar is not None:\r\n'
     '            self.hbar.pack(side="bottom", fill="x")',
     "HiDPI：树的横/竖滚动条撑满"),
    # ㉝ 操作栏被切（2026-09-15 用户："下面按钮没显示，但是没有滚动条"）：
    #     等价于**旧顺序** —— 先有一个"请求高很大且 expand"的兄弟把空间吃光，
    #     最后 pack 的操作栏就分不到（unmap）。★ 第一版注入插了个**空 SplitPane**：
    #     它请求高很小 → 根本没挤到操作栏 → 探针全绿，注入器当场报"锁没抓住这个错"
    #     （注入本身写错也是要记的：判据是"注入必须真的复现那个机制"）。
    (BG, "run_build_probe.py", "操作栏被切（大请求高的兄弟先占、操作栏最后 pack）",
     '        bar = ttk.Frame(self.root)\n'
     '        bar.pack(side="bottom", fill="x", padx=14, pady=(0, 12))',
     '        _pin = tk.Frame(self.root, height=px(900), width=px(1))  # 注入：先占高度\n'
     '        _pin.pack(fill="both", expand=True)\n'
     '        bar = ttk.Frame(self.root)\n'
     '        bar.pack(side="bottom", fill="x", padx=14, pady=(0, 12))',
     "GUI：操作栏（开始构建…）在最小窗口下也不被切"),
    # ㉞ 面板"不该滚的时候也滚"（2026-09-15 用户原话）：
    #     把弹性内容的面板退回默认 fit="content" → 1 行的列表也能上下滚 → 锁变红。
    #     ★ 这条规则有**两份**锁（行为锁在 run_app_probe，用法核对在 run_scroll_audit），
    #       两个探针都要抓到才算数。
    (FSA, ("run_app_probe.py", "run_scroll_audit.py"),
     "弹性树的面板退回 fit=content（1 行也能上下滚）",
     'panel = ScrollPanel(pan, "数据包列表（.db / .sq）", fit="viewport")',
     'panel = ScrollPanel(pan, "数据包列表（.db / .sq）")',
     ("fs：弹性树的面板在没有可滚内容时", "面板用法核对：db_panel",
      "面板用法核对（全页面）")),
    # ㉟ 两向不变量的**反方向**：能滚却看不到条（= 用户报的"没有滚动条却自己滚起来"）。
    #     把竖条的 pack 打断（条子永远藏起来）→ 页面/面板/树只要有一处能滚就必红。
    (TW, "run_scroll_audit.py", "竖条永不 pack（能滚却看不到条）",
     '        if vbar is not None and vbar.visible():\r\n'
     '            vbar.pack(side="right", fill="y")',
     '        if False:                      # 注入：竖条永不 pack（藏着的滚动）\r\n'
     '            vbar.pack(side="right", fill="y")',
     "能滚却看不到条"),
    # ㊱ 用户规则（2026-09-15）："没有滚动条就不应该滚动。滚动代码只在有滚动条的地方有。"
    #     把"条子是否真的看得见"判据拆掉（永远认为可见）→ 没条子的地方照样滚 → 锁变红。
    (TW, "run_app_probe.py", "条子没显示也照样滚（bar_shown 恒为真）",
     '    if sb is None:\r\n'
     '        return False\r\n',
     '    if True:                      # 注入：永远认为条子可见（没条子也照样滚）\r\n'
     '        return True\r\n',
     "没有滚动条的地方一律不许滚"),
    # ㊲ 用户 2026-09-17："加载上DB之后也显示'加载中'"。
    #     把"没人写收尾就恢复前置状态"这条拆掉 → 状态栏永远停在"…中" → 锁变红。
    (TW, "run_app_probe.py", "任务收尾不恢复前置状态（永远停在「…中」）",
     '        elif (self._error_status is None and self._running_status is not None\r\n'
     '              and self._status_text == self._running_status\r\n'
     '              and self._prev_status is not None):\r\n',
     '        elif False:                      # 注入：不恢复前置状态（停在"…中"）\r\n',
     "任务壳：收尾后"),
    # ㊳㊴ 用户拍板的"选项 B"（不再依赖 sqfs2tar）：大小改由**纯 Python 读元数据**给出。
    #     ① 读取器返回空 → 大小全 0（旧行为）→ 往返锁的大小断言必须红；
    #     ② 失败分支不写 sqfs_last_error → "失败可见"锁必须红。
    (SF, "run_functional_probe.py", "SquashFS 读取器返回空（大小退回静默 0 B）",
     '        return _sqfs_walk_sizes(fh, sb)',
     '        return {}                          # 注入：取不到大小（静默 0 B）',
     "SquashFS 真实往返"),
    (SF, "run_functional_probe.py", "取大小失败静默（不写 sqfs_last_error）",
     '            sqfs_last_error = "%s: %s" % (type(e).__name__, e)',
     '            sqfs_last_error = None        # 注入：失败静默（用户只看到 0 B）',
     "取大小失败**要可见**"),
    # ㊵㊶㊷ 2026-09-17「解包失败（返回 0）」这一族：批量分支弃用 sqfs2tar、逐条 --cat、
    #     失败必须说出原因。三条注入分别钉住：① 批量静默丢件；② 活代码里又出现被删掉的
    #     工具名（会整包收进内存 / 被 360 拦）；③ 失败静默（界面只剩"返回 0"）。
    (SF, "run_functional_probe.py", "批量提取只解前 8 项（静默丢件）",
     '    count, failed = 0, []',
     '    count, failed = 0, []\n'
     '    files = files[:8]                 # 注入：批量只解前 8 项（静默丢件）',
     "SquashFS 批量提取"),
    (SF, "run_functional_probe.py", "活代码里又出现 sqfs2tar（整包收进内存/被 360 拦）",
     '_SQFS_CAT_TIMEOUT = 300      # 单个文件的 --cat 上限（秒）：只读一个文件，不该久等',
     '_SQFS_CAT_TIMEOUT = 300\n'
     '_SQFS_LEGACY_T2T = "sqfs2tar.exe"     # 注入：把删掉的工具名塞回活代码',
     "不再依赖 sqfs2tar"),
    (SF, "run_functional_probe.py", "解包失败静默（不写 sqfs_extract_last_error）",
     '        sqfs_extract_last_error = _sqfs_failure_note(failed, count)',
     '        sqfs_extract_last_error = None    # 注入：失败静默（界面只剩"返回 0"）',
     "解包失败要说出原因"),
    # ㊸ 用户口径 2026-09-17："拖入的直接是 script(s) 或 gameplay，不要像之前那样找。"
    #     把"看文件夹自己的名字"拆掉（恒当 gameplay）→ 选上层目录也不再被拒绝 →
    #     "源目录必须是 gameplay/scripts 文件夹本身" 那条锁必须红。
    (TEA, "run_functional_probe.py", "源目录类型不看文件夹名（旧的往下找语义）",
     '    base = os.path.basename(os.path.normpath(source)).lower()',
     '    base = "gameplay"                      # 注入：不看文件夹名（旧的"往下找"语义）',
     "源目录必须是 gameplay/scripts 文件夹本身"),
]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    # 可选：命令行给若干个"名字子串"→ 只跑命中的注入。全跑一遍要十几分钟（每条都跑整份探针），
    # 改一条锁时只跑自己那几条就够；**不带参数 = 全跑**（提交前/大改后照旧全跑）。
    only = [a for a in sys.argv[1:] if a.strip()]
    for p in TARGETS:
        if not os.path.isfile(p):
            print("[SKIP] 缺文件（闭源/未在工作区）：%s" % p)
            return 0
    orig = {p: io.open(p, "rb").read() for p in TARGETS}
    orig_sha = {p: sha(b) for p, b in orig.items()}
    # ★ 启动自检：上一轮若被**强杀**（工具超时 / KILL），`finally` 没跑到 ——
    #   注入文本会留在树里。此时若直接跑，会把"被注入的版本"当成基线，于是那条
    #   注入点找不到（[SKIP]）、洞被静默带过去。2026-09-15 实测踩到一次
    #   （`font_pack.py` 里留着 `if False:  # 注入：上限判据失效`）。
    dirty = []
    for p in TARGETS:
        try:
            txt = io.open(p, encoding="utf-8").read()
        except Exception:
            continue
        if "# 注入" in txt or "注入：" in txt:
            dirty.append(os.path.basename(p))
    if dirty:
        print("[拒绝启动] 这些目标文件里还留着**注入文本**（上一次运行被强杀，finally 没跑到）：")
        for n in dirty:
            print("    " + n)
        print("    先还原（git checkout -- <文件>）再重跑本脚本 —— 否则会把脏版本当基线。")
        return 2
    for p in TARGETS:
        print("%s sha256=%s bytes=%d" % (os.path.basename(p), orig_sha[p], len(orig[p])))
    bad = 0
    ran = 0
    try:
        for target, probe, name, old, new, expect in INJECTIONS:
            if only and not any(a in name for a in only):
                continue
            ran += 1
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
            # 一条注入可以让**多个**探针各跑一遍（例如"弹性树的面板退回 fit=content"
            # 同时钉在 run_app_probe 的行为锁与 run_scroll_audit 的用法核对上）：
            # 每个探针都要抓到才算这条注入成立。
            for probe in (probe if isinstance(probe, (tuple, list)) else (probe,)):
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
                exprs = expect if isinstance(expect, (tuple, list)) else (expect,)
                hit = any(e in ln for ln in fails for e in exprs)
                print("    %s 目标锁变红: %s" % ("[OK]" if hit else "[!!]", " | ".join(exprs)))
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
    print("\n注入验证结果: %s（跑了 %d/%d 条）"
          % ("全部符合预期" if bad == 0 else "%d 处不符合预期" % bad,
             ran, len(INJECTIONS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
