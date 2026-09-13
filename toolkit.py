# -*- coding: utf-8 -*-
"""
STALKER 汉化工具集 — 公共库协调层（re-export）

本模块不再实现功能，只把拆分后的各层重新导出，保证既有导入 100% 兼容：

    toolkit_log      日志管线（最先加载，纯 stdlib，summary/detail 两级）
    toolkit_base     底层基础（常量 / app_dir / 依赖兜底 / 窗口外壳）
    toolkit_theme    主题（单文件：亮暗数据 + apply_theme + 标题栏）
    toolkit_widgets  通用组件（LogBox / CanvasTree / SplitPane / dir_row ...）
    toolkit_textio   文本 / 文件 IO 纯函数
    toolkit_platform 平台与外部程序（应用配置 / locate_exe / 隐藏窗口运行）
    toolkit_constants 业务常量表（包扩展名 / 编码候选 / 输出命名模板）
    toolkit_plugins  插件宿主（PluginManager）

调用方一律 `from toolkit import ...`，无需知道内部分层。
注意：T 是 toolkit_theme 中的同一个 dict 对象，apply_theme 就地更新它；
切勿在本文件或别处 `T = ...` 重新绑定，否则各子工具已绑定的引用会失效。

本文件是**纯 re-export 层**：所有 import 都是对外公开的 API，
在文件内部"未被使用"是设计使然。末尾的 `__all__` 把这份对外契约**显式**写下来
（146 个名字，与上面的 import 逐一对齐）：pyflakes 视 `__all__` 中的名字为"已使用"，
于是本文件不再需要 run_ci 的整文件豁免——将来谁加了一行 import 却忘了进 `__all__`，
或者 `__all__` 里写了个不再存在的名字，静态检查都会立刻报出来。
（`apps/_bootstrap.py` 用的是同一套办法；`stalker_toolkit.py` 是应用入口而非库，
本来就不该有豁免。）
"""

# ═══════════════════════════════════════════════════════════════
# 底层基础 / 日志管线
# ═══════════════════════════════════════════════════════════════
from toolkit_base import (
    APP_NAME, APP_VERSION, APP_PRERELEASE, BUILD_COUNT, PRERELEASE_COUNTS,
    app_dir, ensure_package,
    _BaseTk, _HAS_DND, DND_FILES,
    _ico_to_photoimages, set_app_icon, errbox,
    enable_hidpi, HIDPI_STATUS,
)
from toolkit_log import (
    log_to_file, summary as log_summary, detail as log_detail, set_gui_sink,
    log_path, take_buffer as take_log_buffer, log_write_failed,
)

# ═══════════════════════════════════════════════════════════════
# 主题（单文件；新增主题只往 toolkit_theme.THEMES 加数据）
# ═══════════════════════════════════════════════════════════════
from toolkit_theme import (
    THEMES, _FONTS, palette, T, CURRENT_MODE, color,
    apply_theme, apply_tk_defaults,
    load_user_theme, save_user_theme,
    _hex_to_colorref, apply_titlebar, _BG_ROLES, _role_of,
    ui_scale, set_ui_scale, px, sync_tk_scaling,
)

# ═══════════════════════════════════════════════════════════════
# 通用组件（供六个子工具与插件复用）
# ═══════════════════════════════════════════════════════════════
from toolkit_widgets import (
    refresh_theme, path_row, _make_pump,
    dir_row, count_label, tool_text, tool_header, vscrollbar, AutoScrollbar,
    BusyOverlay, drop_zone,
    LogBox, log_section, CanvasTree, SplitPane, ScrollViewport, ScrollPanel,
    neutralize_input_focus, install_blank_click_unfocus, install_tab_focus_reset,
    plugin_slot_bar, attach_plugin_context_menu, invoke_plugin_callback,
    PluginSlot,
    tool_dropdown, plugin_options_area, tool_panel, refresh_dropdown,
    invoke_plugin_option_callback, plugin_entries,
    TaskRunner, status_style, status_style_name,
    themed_entry, themed_listbox, dialog_window, tool_button, stat_grid, tool_label,
)

# ═══════════════════════════════════════════════════════════════
# 文本 / 文件 IO
# ═══════════════════════════════════════════════════════════════
from toolkit_textio import (
    DEFAULT_ENCODINGS, fmt_size, read_text_file, parse_xml_texts, collect_files,
    sniff_encoding, decode_bytes, read_text_bytes, decode_file,
    is_multibyte_utf8, bytes_fit_encoding,
    BYTE_DECODE_CANDIDATES, DECODE_FALLBACK,
)

# ═══════════════════════════════════════════════════════════════
# 插件宿主
# ═══════════════════════════════════════════════════════════════
from toolkit_plugins import (
    PluginManager,
    HOST_FS, HOST_CONVERT, HOST_TEXT, HOST_XML, HOST_VIDEO, HOST_FONT,
    LOC_TOOLBAR, LOC_CONTEXT,
    AREA_TOP_BAR, AREA_BOTTOM, AREA_FORMAT, AREA_PACK_FORMAT, AREA_SOURCE_ENC,
    AREA_GAME, AREA_LANG, AREA_SIZE, AREA_SUFFIX, AREA_FILTER,
    MODE_ROW_KINDS, MODE_DIFF_TYPES, FILTER_ANY_TYPE,
    DEFAULT_FILTERS_STATS, DEFAULT_FILTERS_TEXT, row_matches_filter,
)

# ═══════════════════════════════════════════════════════════════
# 平台与外部程序
# ═══════════════════════════════════════════════════════════════
from toolkit_platform import (
    app_config_path, load_app_config, save_app_config,
    user_config_path, load_user_config, load_user_value,
    save_user_value, save_user_values,
    run_hidden, locate_exe, system_font_dirs, open_in_explorer, hidden_kwargs,
)

# ═══════════════════════════════════════════════════════════════
# 业务常量表
# ═══════════════════════════════════════════════════════════════
from toolkit_constants import (
    PKG_EXTS, PKG_EXT_MARKERS, EXT_FOR_FORMAT, DEFAULT_DB_EXT, DEFAULT_PACK_BASENAME,
    SQFS_TMP_SUFFIX, SQFS_TOOL_NAMES, is_package_name, output_ext_for,
    BACKUP_DIRNAME, BACKUP_SUFFIX,
    ENCODING_CHOICES, LEGACY_ENCODING,
    XML_EXTS, SCRIPT_EXTS, DEFAULT_ID_PREFIX, FALLBACK_ID_PREFIX,
    ID_PREFIX_TEMPLATE, GP_TEXTS_NAME, SC_TEXTS_NAME,
)

# ═══════════════════════════════════════════════════════════════
# 对外契约（= 本层全部 re-export，146 名，逐一对齐上面的 import）
# ═══════════════════════════════════════════════════════════════
__all__ = [
    "APP_NAME", "APP_VERSION", "APP_PRERELEASE", "BUILD_COUNT",
    "PRERELEASE_COUNTS", "app_dir", "ensure_package", "_BaseTk", "_HAS_DND",
    "DND_FILES", "_ico_to_photoimages", "set_app_icon", "errbox",
    "enable_hidpi", "HIDPI_STATUS", "log_to_file", "log_summary",
    "log_detail", "set_gui_sink", "log_path", "take_log_buffer",
    "log_write_failed", "THEMES",
    "_FONTS", "palette", "T", "CURRENT_MODE", "color", "apply_theme",
    "apply_tk_defaults", "load_user_theme", "save_user_theme",
    "_hex_to_colorref", "apply_titlebar", "_BG_ROLES", "_role_of", "ui_scale",
    "set_ui_scale", "px", "sync_tk_scaling", "refresh_theme", "path_row",
    "_make_pump", "dir_row", "count_label", "tool_text", "tool_header",
    "vscrollbar", "AutoScrollbar", "ScrollViewport", "ScrollPanel", "BusyOverlay", "drop_zone", "LogBox", "log_section", "CanvasTree",
    "SplitPane", "plugin_slot_bar", "attach_plugin_context_menu",
    "neutralize_input_focus", "install_blank_click_unfocus", "install_tab_focus_reset",
    "invoke_plugin_callback", "PluginSlot", "tool_dropdown",
    "plugin_options_area", "tool_panel", "refresh_dropdown",
    "invoke_plugin_option_callback", "plugin_entries", "TaskRunner",
    "status_style", "status_style_name", "themed_entry", "themed_listbox",
    "dialog_window", "tool_button", "stat_grid", "tool_label",
    "DEFAULT_ENCODINGS", "fmt_size", "read_text_file", "parse_xml_texts",
    "collect_files", "sniff_encoding", "decode_bytes", "read_text_bytes",
    "decode_file", "is_multibyte_utf8", "bytes_fit_encoding",
    "BYTE_DECODE_CANDIDATES", "DECODE_FALLBACK", "PluginManager", "HOST_FS",
    "HOST_CONVERT", "HOST_TEXT", "HOST_XML", "HOST_VIDEO", "HOST_FONT",
    "LOC_TOOLBAR", "LOC_CONTEXT", "AREA_TOP_BAR", "AREA_BOTTOM",
    "AREA_FORMAT", "AREA_PACK_FORMAT", "AREA_SOURCE_ENC", "AREA_GAME",
    "AREA_LANG", "AREA_SIZE", "AREA_SUFFIX", "AREA_FILTER", "MODE_ROW_KINDS",
    "MODE_DIFF_TYPES", "FILTER_ANY_TYPE", "DEFAULT_FILTERS_STATS",
    "DEFAULT_FILTERS_TEXT", "row_matches_filter", "app_config_path",
    "load_app_config", "save_app_config", "user_config_path",
    "load_user_config", "load_user_value", "save_user_value",
    "save_user_values", "run_hidden", "locate_exe", "system_font_dirs",
    "open_in_explorer", "hidden_kwargs", "PKG_EXTS", "PKG_EXT_MARKERS",
    "EXT_FOR_FORMAT", "DEFAULT_DB_EXT", "DEFAULT_PACK_BASENAME",
    "SQFS_TMP_SUFFIX", "SQFS_TOOL_NAMES", "is_package_name", "output_ext_for",
    "BACKUP_DIRNAME", "BACKUP_SUFFIX", "ENCODING_CHOICES", "LEGACY_ENCODING",
    "XML_EXTS", "SCRIPT_EXTS", "DEFAULT_ID_PREFIX", "FALLBACK_ID_PREFIX",
    "ID_PREFIX_TEMPLATE", "GP_TEXTS_NAME", "SC_TEXTS_NAME",
]
