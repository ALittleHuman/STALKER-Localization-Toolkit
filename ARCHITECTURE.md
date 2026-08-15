# STALKER Toolkit 架构说明

## 当前目录

```
STALKER_Toolkit\
├─ stalker_toolkit.py            # 主入口（单文件整合版 GUI，仍内嵌部分公共组件）
├─ toolkit.py                    # 公共组件库（主题 / 文本 / 日志 / 文件树 / 分隔条 / 插件管理器）
├─ file_system\                  # FS 引擎与独立 GUI
├─ font_pack\                    # 汉化包生成
├─ xml_compare\                  # XML 校对
├─ convert\                      # 编码转换
├─ video_ogm\                    # 视频 OGM
├─ text_extract\                 # 文本提取
├─ plugins\                      # Python 插件
├─ deps\                         # 第三方依赖（squashfs-tools-ng）
├─ logs\
└─ ARCHITECTURE.md / PLUGINS.md / README.md
```

## 模块化现状

### 公共组件库 `toolkit.py`
统一提供：
- `THEMES` / `palette()` / `apply_theme()` / `apply_tk_defaults()` / `color()`
- `tool_text(parent, text, kind=...)`：大标题、小标题、正文、说明、统计、语义文本统一组件
- `tool_header(parent, text, ...)`：`tool_text` 的 title 别名
- `LogBox` / `log_section`
- `CanvasTree`（自绘文件树，勾选/框选/目录状态）
- `_Node`（内存树模型）
- `dir_row` / `count_label` / `vscrollbar` / `drop_zone`
- `SplitPane`（统一可拖拽分隔条，拖动后刷新自绘子控件）
- `PluginManager`（插件扫描/注册/查找）

### 插件系统
- 目录：`plugins\*.py`（`_` 开头忽略）
- 插件文件定义 `PLUGIN_INFO` 和 `register(api)`
- 扩展点：
  - `api.register_decryptor(check, decrypt)`
  - `api.register_format(name, handler)`，handler 需有 `unpack(raw)->entries` 与 `pack(files)->bytes`
  - `api.register_menu_item(label, callback)`
  - `api.register_option(label, choices)`
- 现有插件：`nlc_sqfs.py`（NLC Improved sq_base 解密）
- 第三方依赖放 `deps\`，不放 `plugins\`

### 主入口 `stalker_toolkit.py`
- 单文件整合版，包含 6 个工具 GUI + hub
- 当前仍内嵌部分公共组件（主题、tool_text、CanvasTree 等），下一步要去重改为从 `toolkit` 导入
- FS 工具已接入 `PluginManager`：
  - 解密器优先走插件管理器，回退 `nlc_sqfs`
  - 格式下拉框 / 封包格式下拉框包含插件注册格式
  - DB 列表右键菜单包含插件菜单项

## 已知待办

1. 主入口去重：删除 `stalker_toolkit.py` 内嵌的公共组件副本，改为 `from toolkit import ...`
2. `register_option` 的 UI 接入
3. `_build_db_panel` 中插件菜单项当前在 `if _HAS_DND:` 块内，需移到块外
4. 各工具内硬编码 Label 逐步替换为 `tool_text`
5. 视频 OGM 音频编码器目前固定 `libvorbis`，若要严格匹配参考 OGM 需按参考音频 codec 选择
6. 多行代码修改受 CRLF 限制，目前用 `fix_*.py` 脚本补丁方式处理

## 修复脚本说明

- `fix_load_nlc.py`：修复 `_load_nlc` 缩进
- `fix_paned.py`：把 `ttk.Panedwindow` 统一替换为 `SplitPane`
- `fix_fonts.py`：清除硬编码 `Microsoft YaHei UI` 字体
- `fix_pack_plugin.py`：修复 `_pack` 插件格式分支缩进
- `move_deps.py`：移动 squashfs-tools-ng 到 deps
- `rename_tools.py`：重命名 `Convert_v0.5.py` → `encoding_converter.py`
- `backup_toolkit.py`：整体备份
- `cross_validate.py`：11xx/2215/2945 与 cv 的交叉验证
