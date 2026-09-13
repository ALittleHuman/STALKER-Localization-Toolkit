# -*- coding: utf-8 -*-
"""插件宿主：扫描 plugins/ 目录并管理扩展点。

toolkit.py 会 re-export PluginManager，调用方无需改动。

日志分级（与方案A 一致）:
    summary(...)  插件加载/注册的成功与失败、插件目录与数量 —— 进 GUI 日志栏 + 落盘
    log(...)      扫描与导入的详细过程 —— 只落盘，导出日志时输出

组件复用: 插件文件可直接 `import toolkit_widgets` / `from toolkit import ...`，
或使用 `api.widgets` 取到 toolkit_widgets 模块，无需自造通用组件。
"""
import os
import re


# ── 组件槽位注册表（唯一事实来源；插件按 (host, location) 精确寻址）──
#   host     : 目标组件，与 apps/ 下各工具声明的 HOST 常量一一对应
#   location : 槽位类型；toolbar = 标题下方一行动作区，context = 主内容控件右键菜单
HOSTS = {
    "fs": "文件系统",
    "convert": "编码转换",
    "text": "文本提取",
    "xml": "XML校对",
    "video": "视频转换",
    "font": "汉化包生成",
}
LOCATIONS = {
    "toolbar": "工具标题下方的一行插件动作区",
    "context": "工具主内容控件的右键菜单",
}

# ── 槽位常量表（唯一事实来源）──────────────────────────────────
# 组件侧一律用这些常量，不写字面量；CI 静态守卫会拦下硬编码的 host/area。
HOST_FS, HOST_CONVERT, HOST_TEXT = "fs", "convert", "text"
HOST_XML, HOST_VIDEO, HOST_FONT = "xml", "video", "font"
LOC_TOOLBAR, LOC_CONTEXT = "toolbar", "context"

AREA_TOP_BAR = "top_bar"
AREA_BOTTOM = "bottom"            # 组件**最下方**的一整条插件面板区（真·底部，pack side="bottom"）
AREA_FORMAT = "format"            # fs: 解包格式下拉
AREA_PACK_FORMAT = "pack_format"  # fs: 封包格式下拉
AREA_SOURCE_ENC = "source_enc"    # convert: 源编码下拉
AREA_GAME = "game"                # font: 游戏版本下拉
AREA_LANG = "lang"                # font: 加载语言下拉
AREA_SIZE = "size"                # font: 尺寸档位下拉
AREA_SUFFIX = "suffix"            # font: 字体后缀下拉
AREA_FILTER = "filter"            # xml: 筛选项下拉

# ── 贡献点：XML 校对的行分类与筛选声明 ───────────────────────
# 行分类（row_kind）：文件级的互斥状态
MODE_ROW_KINDS = ("same", "diff", "only_a", "only_b")
# "有差异"下的子类型：声明为集合，避免筛选规则散落在组件代码里
MODE_DIFF_TYPES = ("only", "text")

# 筛选声明的哨兵：(row_kind 集合, 需要的 differ_types)
# differ_types 为 None 表示"不限制子类型"
FILTER_ANY_TYPE = None

DEFAULT_FILTERS_STATS = [
    ("全部", ("same", "diff", "only_a", "only_b"), FILTER_ANY_TYPE),
    ("不一致", ("diff",), FILTER_ANY_TYPE),
    ("一致", ("same",), FILTER_ANY_TYPE),
    ("仅 A 有", ("only_a",), FILTER_ANY_TYPE),
    ("仅 B 有", ("only_b",), FILTER_ANY_TYPE),
]
DEFAULT_FILTERS_TEXT = [
    ("全部", ("same", "diff", "only_a", "only_b"), FILTER_ANY_TYPE),
    ("有差异", ("diff",), FILTER_ANY_TYPE),
    ("文本不同", ("diff",), ("text",)),          # 子类型筛选
    ("仅 A 有", ("only_a",), FILTER_ANY_TYPE),
    ("仅 B 有", ("only_b",), FILTER_ANY_TYPE),
]


def row_matches_filter(row_kind, differ_types, spec):
    """判断一行是否通过筛选声明 spec=(标签, row_kinds, differ_types)。

    这是筛选语义的**唯一实现**：内置筛选与插件贡献的筛选走同一段代码，
    组件侧不再有 `if filt == "文本不同"` 这类分支。
    """
    _label, kinds, need_types = spec
    if row_kind not in kinds:
        return False
    if need_types is FILTER_ANY_TYPE or need_types is None:
        return True
    return bool(set(differ_types or ()) & set(need_types))


class PluginManager:
    """Scan a plugins/ directory and host extension points.

    A plugin is a Python file in the plugin directory (or a direct
    subdirectory) that defines PLUGIN_INFO and register(api). It may
    also expose plain functions for backward compatibility.

    Optional allow-list: plugins/enabled.txt
        One plugin file name per line (# comments ignored). If the file
        exists and is non-empty, only the listed plugins are loaded.

    Extension points:
      * decryptor(check, decrypt)
      * format(name, handler)
      * menu_item(label, callback, location="context")
      * option(label, choices, callback=None)
      * tool(name, builder)     builder(parent) 建一个与内置六工具同级的 Hub 栏目

    api 另外提供:
      * api.log(msg, tag)            summary 级（用户可见）
      * api.log_detail(msg, tag)     detail 级（只落盘）
      * api.widgets                  toolkit_widgets 模块（通用组件复用）
      * api.plugin_file / api.plugin_info
    """

    # 进程级共享实例（见 shared()）
    _shared = None

    @classmethod
    def shared(cls, plugins_dir=None, log=None, summary=None, ui_factory=None):
        """进程级共享实例：Hub 启动时初始化并 scan 一次；其余工具与插件栏目
        通过 `PluginManager.shared()` 取到同一份，避免重复扫描与多实例。

        约定：首次调用必须提供 plugins_dir；之后再调用只返回已有实例。
        `ui_factory` 是**宿主后端**的控件工厂（缺省 Tk）；只在首次初始化时生效，
        因为插件是在 scan 期通过 `api.ui` 拿到它并注册的。
        """
        if cls._shared is None:
            if plugins_dir is None:
                # 未显式初始化时按约定路径自建（便于单独构造工具 / 测试），
                # 进程内仍只有这一份实例。
                plugins_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "plugins")
            cls._shared = cls(plugins_dir, log=log, summary=summary,
                              ui_factory=ui_factory)
            cls._shared.scan()
        return cls._shared

    def __init__(self, plugins_dir, log=None, summary=None, ui_factory=None):
        self.plugins_dir = plugins_dir
        self.log = log or (lambda msg, tag="info": None)
        self.summary = summary or (lambda msg, tag="info": None)
        # 宿主后端工厂（None = 用缺省 Tk 实现，见 _make_api）。按**实例**保存而不是
        # 模块级全局：同一个进程里 Tk 宿主与 Qt 宿主可能各持一个实例，不能互相污染。
        self.ui_factory = ui_factory
        self.plugins = []
        self.compare_modes = []          # 贡献点：比较模式（内置与插件同一张表）
        self.decryptors = []
        self.formats = []
        self.menu_items = []
        self.options = []
        self.tools = []
        self.commands = {}
        self.option_entries = []
        self.panels = []
        self.load_errors = []
        self.registration_errors = []

    def _enabled_allowlist(self):
        path = os.path.join(self.plugins_dir, "enabled.txt")
        if not os.path.isfile(path):
            return None
        names = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        names.append(line)
        except Exception:
            return None
        return names if names else None

    @staticmethod
    def _match_allow(name, allow):
        """Match allow-list entries; '*' and '?' wildcards are supported."""
        import fnmatch
        return any(fnmatch.fnmatch(name, pat) for pat in allow)

    def _iter_plugin_files(self):
        """Yield (relative_name, absolute_path) for all loadable plugins."""
        allow = self._enabled_allowlist()
        files = []
        for dp, dn, fn in os.walk(self.plugins_dir):
            dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
            for f in fn:
                if not f.endswith(".py") or f.startswith("_"):
                    continue
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, self.plugins_dir).replace("\\", "/")
                files.append((rel, full))
        files.sort(key=lambda x: x[0])
        if allow is None:
            return files
        return [(rel, full) for rel, full in files if self._match_allow(rel, allow)]

    def scan(self):
        """Import all plugin files and call their register()."""
        self.plugins = []
        self.decryptors = []
        self.formats = []
        self.menu_items = []
        # 注意：compare_modes **不在这里清空** —— 内置模式在组件导入时注册，
        # scan() 只负责加载插件，清掉会把内置模式一起丢掉。
        self.options = []
        self.tools = []
        self.commands = {}
        self.option_entries = []
        self.panels = []
        self.load_errors = []
        self.registration_errors = []
        self.summary(f"插件目录: {self.plugins_dir}", "dim")
        if not os.path.isdir(self.plugins_dir):
            self.summary(f"插件目录不存在: {self.plugins_dir}", "warn")
            return self.plugins

        files = self._iter_plugin_files()
        if not files:
            self.summary("未发现插件", "dim")

        for rel, path in files:
            modname = "toolkit_plugin_" + re.sub(r"[^0-9A-Za-z_]", "_", rel[:-3])
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(modname, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                msg = f"plugin load failed: {rel}: {e}"
                self.load_errors.append(msg)
                self.log(msg, "err")
                self.summary(msg, "err")
                continue
            info = getattr(mod, "PLUGIN_INFO", {})
            api = self._make_api(rel, info)
            registered = False
            if hasattr(mod, "register"):
                try:
                    mod.register(api)
                    registered = True
                except Exception as e:
                    msg = f"plugin register failed: {rel}: {e}"
                    self.load_errors.append(msg)
                    self.log(msg, "err")
                    self.summary(msg, "err")
            if not registered:
                # backward compatibility: bare functions in the plugin
                if hasattr(mod, "decrypt_sq"):
                    api.register_decryptor(
                        lambda p, m=mod: getattr(m, "open_sq")(p) is not None,
                        mod.decrypt_sq,
                    )
                    registered = True
            self.plugins.append({"file": rel, "info": info, "module": mod,
                                 "registered": registered})
            self.log(f"plugin loaded: {rel}", "ok")
            name = (info or {}).get("name") or rel
            if registered:
                self.summary(f"插件已加载: {name} ({rel})", "ok")
            else:
                self.summary(f"插件注册失败: {rel}", "err")
        # 槽位寻址错误并入 load_errors：Hub 启动告警会一并显示，避免"注册了却不生效"被忽略
        if self.registration_errors:
            self.load_errors.extend(self.registration_errors)
        return self.plugins

    def _make_api(self, filename, info):
        pm = self
        # 后端无关的控件工厂：默认 Tk 实现；宿主可注入别的后端（见 toolkit_plugin_ui）。
        # 这是**纯新增字段**：既有插件不读它，行为不变；新插件写 `api.ui.button(...)` 即可
        # 只写一遍就跑在两个后端上。
        _ui_factory = pm.ui_factory
        if _ui_factory is None:
            try:
                from toolkit_plugin_ui import TkUiFactory
                _ui_factory = TkUiFactory()
            except Exception:
                _ui_factory = None

        class Api:
            # ── 标识 ──
            plugin_file = filename
            plugin_info = info
            # ── 后端契约（新增，插件可用它分支或直接用 ui 工厂）──
            backend = (_ui_factory.backend if _ui_factory is not None else "tk")
            ui = _ui_factory

            # ── 日志（与宿主同一套分级） ──
            def log(self, msg, tag="info"):
                """summary 级：进 GUI 日志栏 + 落盘。"""
                pm.summary(msg, tag)

            def log_detail(self, msg, tag="info"):
                """detail 级：只落盘，导出日志时输出。"""
                pm.log(msg, tag)

            # ── 通用组件复用 ──
            @property
            def widgets(self):
                """toolkit_widgets 模块，插件直接复用通用组件。"""
                import toolkit_widgets
                return toolkit_widgets

            def register_decryptor(self, check, decrypt):
                pm.decryptors.append({
                    "plugin": filename,
                    "info": info,
                    "check": check,
                    "decrypt": decrypt,
                })

            def register_format(self, name, handler):
                pm.formats.append({
                    "plugin": filename,
                    "info": info,
                    "name": name,
                    "handler": handler,
                })

            def _bad_slot(self, what, host, location=None):
                """记录并上报非法的槽位寻址——绝不静默丢弃（否则表现为"注册了却不生效"）。"""
                if host not in HOSTS:
                    msg = (f"{filename}: {what} 的 host={host!r} 不是已知组件"
                           f"（可用: {', '.join(HOSTS)}）")
                else:
                    msg = (f"{filename}: {what} 的 location={location!r} 不是已知槽位"
                           f"（可用: {', '.join(LOCATIONS)}）")
                pm.registration_errors.append(msg)
                pm.summary(msg, "err")
                pm.log(msg, "err")

            def _reject(self, msg):
                """拒绝一次非法注册并留痕（日志 + load_errors），绝不静默丢弃。"""
                pm.registration_errors.append(msg)
                pm.summary(msg, "err")
                pm.log(msg, "err")

            # ── 命令：id = <插件文件>:<动作名>，前缀由宿主加，插件只写动作名 ──
            def register_command(self, action_id, label, handler, when=None):
                """注册一个可被任意挂载点引用的命令。

                when: None=恒显示；dict=要求宿主传入的 context 中对应键相等；
                      可调用对象=收到 context 返回真假。用于"仅在该模式/已加载时才出现"。
                返回完整命令 id（<插件文件>:<动作名>），失败返回 None。
                """
                if not isinstance(action_id, str) or not re.fullmatch(r"[A-Za-z0-9_.\-]{1,64}", action_id):
                    self._reject(f"{filename}: register_command 的动作名 {action_id!r} 非法"
                                 f"（只允许字母/数字/_.-，1~64 字符）")
                    return None
                if not callable(handler):
                    self._reject(f"{filename}: register_command({action_id!r}) 的 handler 不可调用")
                    return None
                cid = f"{filename}:{action_id}"
                if cid in pm.commands:
                    self._reject(f"{filename}: 命令 {cid} 重复注册")
                    return None
                pm.commands[cid] = {"id": cid, "action": action_id, "label": label,
                                    "handler": handler, "when": when,
                                    "plugin": filename, "info": info}
                return cid

            def register_menu_item(self, label=None, callback=None, location="context",
                                   host="fs", command=None, when=None, order=0):
                """把命令挂到某个槽位（命令与挂载点分离）。

                新形态：register_menu_item(command="export_csv", host="fs", location="toolbar")
                旧形态：register_menu_item("标签", callback, location=..., host=...)  ← 自动建内部命令
                """
                if host not in HOSTS or location not in LOCATIONS:
                    self._bad_slot("register_menu_item", host, location)
                    return
                if command is None:
                    if callback is None:
                        self._reject(f"{filename}: register_menu_item 需要 command= 或 callback=")
                        return
                    cid = self.register_command(
                        f"inline{len(pm.commands) + 1}", label or "动作", callback, when)
                    if cid is None:
                        return
                else:
                    cid = str(command) if ":" in str(command) else f"{filename}:{command}"
                    if cid not in pm.commands:
                        self._reject(f"{filename}: 挂载点引用了未注册的命令 {cid}")
                        return
                pm.menu_items.append({"plugin": filename, "info": info,
                                      "command_id": cid, "location": location, "host": host,
                                      "order": order})

            def register_option_entry(self, host, area, value, when=None):
                """往**组件已有**的下拉菜单里加一个条目（如 fs 的"格式"下拉）。

                组件没有对应下拉时加不进去——那种情况请用 register_option 新建一个。
                """
                if host not in HOSTS:
                    self._bad_slot("register_option_entry", host)
                    return
                pm.option_entries.append({"plugin": filename, "info": info, "host": host,
                                          "area": area, "value": value, "when": when})

            def register_option(self, label, choices, callback=None, host="fs",
                                area="top_bar", when=None, order=0):
                """**新建**一个属于插件的下拉菜单（组件本来没有下拉时用它新建）。

                area 表示渲染到该组件的哪个区域；具体由组件的 plugin_options_area 决定。
                order 与 register_menu_item / register_panel 同义：升序，同值保注册顺序。
                """
                if host not in HOSTS:
                    self._bad_slot("register_option", host)
                    return
                pm.options.append({
                    "plugin": filename,
                    "info": info,
                    "label": label,
                    "choices": choices,
                    "callback": callback,
                    "host": host,
                    "area": area,
                    "when": when,
                    "order": order,
                })

            def register_panel(self, title, builder, host="fs", area="top_bar",
                               order=0, when=None):
                """贡献一个子栏目/面板。builder(parent) 建 UI，parent 是宿主给的容器。"""
                if host not in HOSTS:
                    self._bad_slot("register_panel", host)
                    return
                if not callable(builder):
                    self._reject(f"{filename}: register_panel({title!r}) 的 builder 不可调用")
                    return
                pm.panels.append({"plugin": filename, "info": info, "title": title,
                                  "builder": builder, "host": host, "area": area,
                                  "order": order, "when": when})

            def register_tool(self, name, builder, order=0):
                """Register a new Hub tab. builder(parent) builds the tab UI.
                order: Hub 栏目顺序（升序，同值保注册顺序）。"""
                pm.tools.append({
                    "plugin": filename,
                    "info": info,
                    "name": name,
                    "builder": builder,
                    "order": order,
                })

            def register_compare_mode(self, name, columns, compare, row_builder,
                                      filters=None, order=0, detail_builder=None):
                """为 XML 校对贡献一种**比较模式**（host="xml"）。

                这是"贡献点"而非"挂载点"：插件不只往某个位置塞一个控件，而是给组件
                增加一类能力——新增的模式会同时体现在模式下拉、表格列、筛选项与
                行取值/比较算法上，**组件源码不用改一行**。

                参数：
                    name        模式显示名（同时是模式下拉的取值）
                    columns     列定义 [(key, heading, width), ...]
                                key 为 "rel"/"status" 时取默认行取值，其余按同名列取值
                    compare     比较函数 compare(ctx, path_a, path_b, rel) -> dict
                                ctx 由组件提供（含 name_a/name_b/编码等）
                    row_builder 可选：row_builder(result) -> (row_kind, differ_types)
                                row_kind ∈ {"same","only_a","only_b","diff"}
                                differ_types 用于"有差异"下的子类型（如 {"text"}）
                                传 None 时由组件按 consistent/only_side 推断
                    filters     筛选项声明 [(标签, {row_kind}, 需要的 differ_types), ...]
                                传 None 时用组件的默认筛选集
                    order       模式下拉中的顺序（升序，同值保注册顺序）
                """
                if not isinstance(name, str) or not name.strip():
                    self._reject(f"{filename}: register_compare_mode 的 name 非法")
                    return
                # compare_modes 是「一份一份模式字典的列表」，`name in list`
                # 永远为假 —— 这个检查曾经是死代码，于是第二个插件可以静默
                # 注册同名模式，而 compare_modes_for 用 setdefault 保留先注册者，
                # 后者的 compare 永远不会被调用。
                #
                # 同一插件再次注册**同名**模式不是"重名 bug"，而是**重新扫描**的
                # 正常结果：scan() 会清空 plugins/tools/options/... 等全部插件注册表，
                # 但 compare_modes 里内置与插件共用一张表、不能整表清空，于是插件每次
                # scan() 都会重新跑一遍 register()。此前这条会被判成"比较模式已存在"
                # 并写进 load_errors —— Hub 启动弹窗据此提示"插件加载失败"，而模式
                # 其实好好地还在表里，是**误报**。
                # 因此同名同插件时按"后注册者胜"覆盖旧条目（表里不会多出第二条），
                # 只有**别的**插件重名才继续拒绝。
                # 注意顺序：先做参数校验，只有校验全过才动旧条目 —— 否则一次非法
                # 的重复注册会把已经生效的那条模式删掉。
                if not callable(compare):
                    self._reject(f"{filename}: 比较模式 {name!r} 的 compare 不可调用")
                    return
                cols = list(columns or [])
                if not cols or not all(isinstance(c, (list, tuple)) and len(c) >= 2 for c in cols):
                    self._reject(f"{filename}: 比较模式 {name!r} 的 columns 非法"
                                 f"（需要 [(key, heading[, width]), ...]）")
                    return
                if row_builder is not None and not callable(row_builder):
                    self._reject(f"{filename}: 比较模式 {name!r} 的 row_builder 不可调用")
                    return
                if any(m.get("name") == name and m.get("plugin") != filename
                       for m in pm.compare_modes):
                    self._reject(f"{filename}: 比较模式 {name!r} 已存在")
                    return
                pm.compare_modes = [m for m in pm.compare_modes
                                    if not (m.get("name") == name
                                            and m.get("plugin") == filename)]
                pm.compare_modes.append({
                    "plugin": filename, "info": info, "name": name,
                    "columns": [tuple(c) for c in cols],
                    "compare": compare, "row_builder": row_builder,
                    "filters": list(filters) if filters else None,
                    "detail_builder": detail_builder if callable(detail_builder) else None,
                    "order": order,
                })

        return Api()

    def register_compare_mode(self, name, columns, compare, row_builder=None,
                              filters=None, order=0, detail_builder=None,
                              plugin="<builtin>"):
        """注册一条内置比较模式（组件自身用，与插件走同一张表）。

        契约要点（都与"Hub 先扫插件、后建 App"这个真实顺序有关）：
            * **内置模式随 App 构造才注册**（`apps/xml_compare_app.py` 的
              `__init__` 需要先拿到 PluginManager 实例），因此插件往往先占名字；
            * 所以这里**不能**因为"名字已存在"就把内置挡回去 —— 那样内置永远
              进不了表，插件反而独占该名字。内置照常登记，由 `compare_modes_for`
              保证同名时**内置优先**；
            * 同一个内置名字重复登记（Hub 重建界面会多次构造 App）会被跳过，
              免得注册表随重建次数无限增长；
            * 非内置（插件）想用已被内置占用的名字 → 返回 False 拒绝。
        """
        is_builtin = (plugin == "<builtin>")
        existing = [m for m in self.compare_modes if m["name"] == name]
        if existing:
            if not is_builtin:
                return False
            if any(m.get("plugin") == "<builtin>" for m in existing):
                return False                      # 内置已登记过，不重复追加
        self.compare_modes.append({
            "plugin": plugin, "info": {}, "name": name,
            "columns": [tuple(c) for c in (columns or [])],
            "compare": compare, "row_builder": row_builder,
            "filters": list(filters) if filters else None,
            "detail_builder": detail_builder if callable(detail_builder) else None,
            "order": order,
        })
        return True

    def compare_modes_for(self):
        """全部比较模式，按 order 升序稳定排序（name → 完整记录）。

        同名冲突时**内置模式优先**，与注册顺序无关。
        为什么不能只靠"内置先注册"：内置模式需要拿到 PluginManager 实例才能
        注册，因此是**随 App 构造**才注册的（`apps/xml_compare_app.py`），而
        Hub 的顺序是"先扫插件、后建 App"——插件注册时判重表里还没有内置项，
        它会抢占该名字，随后内置注册被 `return False` 静默丢掉，于是插件
        （可能只是无意重名）就把内置模式顶掉了。这里显式让内置赢。
        """
        seen = {}
        for idx, m in enumerate(self.compare_modes):
            cur = seen.get(m["name"])
            if cur is None:
                seen[m["name"]] = (m.get("order", 0), idx, m)
            elif cur[2].get("plugin") == "<builtin>":
                continue                       # 已存的是内置 → 内置优先，保持
            elif m.get("plugin") == "<builtin>":
                seen[m["name"]] = (m.get("order", 0), idx, m)   # 内置后到也赢
        return {name: v[2] for name, v in sorted(seen.items(), key=lambda kv: (kv[1][0], kv[1][1]))}

    def compare_mode(self, name):
        """取单个模式记录；不存在返回 None。"""
        for m in self.compare_modes:
            if m["name"] == name:
                return m
        return None

    def find_decryptor(self, path):
        """Return the first registered decryptor that accepts path, else None."""
        for d in self.decryptors:
            try:
                if d["check"](path):
                    return d
            except Exception:
                continue
        return None

    def menu_items_for(self, host, location="context", context=None):
        """精确匹配 (host, location) 的挂载点，解析出命令并按 when 过滤。

        context: 宿主当前状态（如 {"mode": "文本", "loaded": True}），供 when 判断。
        按 order 升序稳定排序；未指定 order（默认 0）者保持注册顺序。
        """
        out = []
        for idx, m in enumerate(self.menu_items):
            if m.get("host") != host or m.get("location") != location:
                continue
            cmd = self.commands.get(m.get("command_id"))
            if not cmd:
                continue
            if not _when_ok(cmd.get("when"), context):
                continue
            out.append((m.get("order", 0), idx, {**cmd, "host": host, "location": location}))
        return [x[2] for x in sorted(out, key=lambda t: (t[0], t[1]))]

    def options_for(self, host, area=None, context=None):
        """插件**新建**的下拉（register_option）。area=None 表示不限区域（旧签名兼容）。
        按 order 升序稳定排序。"""
        out = []
        for idx, o in enumerate(self.options):
            if o.get("host") != host:
                continue
            if area is not None and o.get("area") != area:
                continue
            if not _when_ok(o.get("when"), context):
                continue
            out.append((o.get("order", 0), idx, o))
        return [x[2] for x in sorted(out, key=lambda t: (t[0], t[1]))]

    def option_entries_for(self, host, area=None, context=None):
        """加进**已有**下拉里的条目值（register_option_entry），保序去重。"""
        out = []
        for e in self.option_entries:
            if e.get("host") != host:
                continue
            if area is not None and e.get("area") != area:
                continue
            if not _when_ok(e.get("when"), context):
                continue
            if e.get("value") not in out:
                out.append(e.get("value"))
        return out

    def panels_for(self, host, area=None, context=None):
        """该组件该区域的面板贡献（register_panel），按 order 稳定排序。"""
        out = []
        for p in self.panels:
            if p.get("host") != host:
                continue
            if area is not None and p.get("area") != area:
                continue
            if not _when_ok(p.get("when"), context):
                continue
            out.append(p)
        return sorted(out, key=lambda p: p.get("order", 0))


def _when_ok(when, context):
    """when=None 恒真；dict 形式要求 context 对应键相等（缺键即不满足）；可调用则调用之。"""
    if not when:
        return True
    if isinstance(when, dict):
        ctx = context or {}
        return all(ctx.get(k) == v for k, v in when.items())
    if callable(when):
        try:
            return bool(when(context or {}))
        except Exception:
            return False
    return True
