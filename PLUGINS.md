# 插件说明

工具集支持从 `plugins\` 目录加载 Python 插件。插件可以扩展：新增 Hub 栏目（工具 Tab）、任意加密包解密、新封包/解包格式、新命令与槽位动作、往已有下拉加条目、新建插件下拉、贡献面板、以及为 XML 校对贡献**比较模式**。

插件在 Hub 启动时扫描一次；文件系统工具与 Hub 共用同一份插件实例。修改插件后需重启工具生效。

## 1. 插件目录与加载规则

```
STALKER_Toolkit\
└─ plugins\
   ├─ enabled.txt       # 可选：插件白名单
   └─ nlc_sqfs.py       # 示例：NLC 解密插件（本地保留，仓库不含）
```

插件目录位置：

- 源码运行：`STALKER_Toolkit\plugins`
- 发布版（build 产物）：`STALKER Localization Toolkit\plugins`（exe 同目录，运行时可读写）

加载规则：

- 递归扫描 `plugins\` 下所有 `.py` 文件（含直接子目录）。
- 文件名以 `_` 开头的文件被忽略；`__pycache__` 和 `.git` 目录被忽略。
- 插件按相对路径排序后依次加载。
- 如果 `plugins\enabled.txt` 存在且内容非空，则只加载其中列出的文件。每行一个相对路径（如 `nlc_sqfs.py`），`#` 开头为注释；支持 `*` 和 `?` 通配符（如 `*.py`、`subdir/*.py`）。
- 单个插件加载或注册失败不会影响工具启动，失败信息会写入日志；文件系统工具中会额外弹窗提示。

## 2. 插件结构

每个插件是一个 Python 文件，结构如下：

```python
# my_plugin.py
PLUGIN_INFO = {
    "id": "my_plugin",
    "name": "My Plugin",
    "version": "1.0",
    "author": "you",
    "description": "一句话说明这个插件做什么",
}

def register(api):
    # 在这里调用 api.register_xxx 注册扩展
    ...
```

- `PLUGIN_INFO` 可省略，但建议填写，便于日志与排查。
- `register(api)` 是唯一入口，插件被加载时由宿主调用。

## 3. API 参考

`register(api)` 收到的 `api` 提供 **9 个注册方法**（3.1~3.5、3.9）、**若干通用成员**（3.6：日志分级、组件复用、插件标识）、**后端无关的控件工厂**（3.10：`api.ui` / `api.backend`）、**槽位寻址模型**（3.7：`HOST_*` / `LOC_*` / `AREA_*` 常量与 `PluginSlot.refresh()`）以及 **命令与挂载点分离**（3.8）。

九个注册方法一览（实测 `toolkit_plugins.py` 中 `Api` 的全部 `register_*`）：

| # | 方法 | 一句话 |
|---|---|---|
| 1 | `register_decryptor(check, decrypt)` | 任意加密包解密（3.1） |
| 2 | `register_format(name, handler)` | 新解包/封包格式（3.2） |
| 3 | `register_menu_item(...)` | 把命令挂到槽位（3.3） |
| 4 | `register_option(...)` | 新建插件下拉（3.4） |
| 5 | `register_tool(name, builder, order=0)` | 新增 Hub 栏目（3.5） |
| 6 | `register_command(action_id, label, handler, when=None)` | 注册可被多处引用的命令（3.8） |
| 7 | `register_option_entry(host, area, value, when=None)` | 往已有下拉加条目（3.9） |
| 8 | `register_panel(title, builder, host, area, order, when)` | 贡献面板（3.9） |
| 9 | `register_compare_mode(...)` | XML 校对比较模式（3.9） |

### 3.1 api.register_decryptor(check, decrypt)

注册通用加密包解密器。文件系统工具加载文件时按注册顺序依次询问 `check(path)`，第一个返回 `True` 的解密器被采用；解密得到的字节会重新按 SquashFS（`hsqs`/`sqsh`）或 X-Ray DB 解析。

触发时机有两条，**实测如此**：

- 文件名匹配 `.sq*` 且引擎的 `sqfs_check()` 返回 `encrypted`（即不是明文 SquashFS）——**直接**交给解密器，不再先跑格式识别；
- 其它文件（含未知 `.sq*` 与无法识别的 X-Ray DB）在**标准识别全部失败后**才交给解密器兜底。

所以 `check()` 只会在宿主已经放弃标准识别时被问到；即便如此也**不要匹配未加密的正常文件**。

参数：

- `check(path: str) -> bool`：识别该插件能处理的文件。不要匹配未加密的正常文件，否则可能抢在标准识别前生效。
- `decrypt(path: str, out_path: str = None) -> bytes | None`：返回解密后的字节；若 `out_path` 非空，应同时写出文件；返回 `None` 表示失败。

工具侧对解密结果是**通用上报**：日志里出现的是插件 `PLUGIN_INFO` 的 `name`，形如
`NLC Improved sq_base decryptor: xdb 12 项, 3 文件`。工具**不硬编码任何模组名**，也不 import 任何具体插件模块；
引擎层的 `sqfs_check()` 只返回 `sqfs` / `encrypted` / `unknown` 三种通用类别。
因此请把 `PLUGIN_INFO.name` 写成能自解释的名字——它就是用户在日志里看到的名字。

三种结果措辞分明：成功、`<插件名>: 解密后数据无法识别`（插件认领了但输出不是可识别容器）、
`未找到可解密该文件的插件`（没有任何插件的 `check()` 认领）。

示例（解密 `.crypt` 文件为 X-Ray DB）：

```python
def register(api):
    api.register_decryptor(
        lambda path: path.lower().endswith(".crypt"),
        decrypt_xdb,
    )

def decrypt_xdb(path, out_path=None):
    raw = open(path, "rb").read()
    dec = my_cipher(raw)
    if out_path:
        with open(out_path, "wb") as f:
            f.write(dec)
    return dec
```

### 3.2 api.register_format(name, handler)

注册新的封包 / 解包格式。注册后，`name` 会出现在文件系统工具的“格式”下拉框中；`auto` 自动检测也会尝试插件格式（在内置格式识别失败后）。

参数：

- `name: str`：格式标识，也作为下拉框选项值。不要与内置格式 `auto`、`xdb`、`2947ru`、`2947ww`、`2945`、`2215`、`11xx`、`sqfs` 重名。
- `handler: dict`：必须包含两个键：
  - `handler["unpack"](raw: bytes) -> list`：解析原始字节，返回条目列表。每个条目结构：
    ```python
    {
        "path": "gamedata/text/eng/ui_st_mm.xml",
        "offset": 123,        # 文件数据在 raw 中的偏移
        "size_real": 456,     # 解压后大小
        "size_comp": 456,     # 压缩后大小
        "crc": 0,             # 校验值，无则填 0
        "is_dir": False,
    }
    ```
  - `handler["pack"](files: list) -> bytes`：把文件列表打包成原始字节。`files` 结构为 `[(path, data_bytes, is_dir), ...]`，路径使用 `/`。

示例：

```python
def my_unpack(raw):
    return [{
        "path": "example.txt",
        "offset": 0,
        "size_real": len(raw),
        "size_comp": len(raw),
        "crc": 0,
        "is_dir": False,
    }]

def my_pack(files):
    return files[0][1] if files else b""

def register(api):
    api.register_format("myfmt", {"unpack": my_unpack, "pack": my_pack})
```

### 3.3 api.register_menu_item(...)

把命令挂到某个槽位。**动作与它出现在哪里是两件事**（详见 3.8）：

```python
api.register_menu_item(label=None, callback=None, location="context",
                       host="fs", command=None, when=None, order=0)
```

新形态引用已注册的命令（推荐）：

```python
api.register_command("export_csv", "导出为 CSV", my_handler)
api.register_menu_item(command="export_csv", host="xml", location="toolbar")
```

旧形态自带回调，宿主自动建一条内部命令：

```python
api.register_menu_item("执行我的操作", my_action, host="fs", location="context")
```

参数：

- `host`：`fs` / `convert` / `text` / `xml` / `video` / `font`，非法值直接拒绝并报错。
- `location`：`toolbar`（工具标题下方一行动作区）或 `context`（主内容控件右键菜单）。
- `command` / `callback`：二选一，都为空的注册被拒绝。
- `when`：`None` 恒显示；`dict` 要求宿主传入的 context 对应键相等；**可调用对象**则调用之。
- `order`：升序，同值保注册顺序。

调用方式：宿主优先以 `callback(app)` 调用（`app` 为对应工具实例），回调不接受参数时回退 `callback()`。
回调抛异常**不会冒到 Tk**：写 `summary/err` 日志后返回 `None`。

渲染位置：`toolbar` 槽渲染为「工具标题 → 插件动作区 → 工具内容」的固定顺序（位置约定见 3.7）；
`context` 槽追加到该工具主内容控件已有的右键菜单，顺序为「原有项 → 分隔符 → 插件项」。
**无注册即无痕迹**：没有任何插件注册该槽时不创建控件、不绑定事件。

当前限制：回调只拿到工具实例，**没有**菜单上下文（如当前右键选中的节点）；如需更细的上下文，
可在回调内通过 `app.db_ctree` 等成员自行获取。

### 3.4 api.register_option(...)

**新建**一个属于插件的下拉（组件本来没有下拉时用它；往已有下拉加条目请用 3.9 的
`register_option_entry`）。

```python
api.register_option(label, choices, callback=None, host="fs",
                    area="top_bar", when=None, order=0)
```

参数：

- `label`：选项名称。
- `choices: list[str]`：可选值列表，第一项为默认值。
- `callback: callable | None`：切换时回调。宿主优先 `callback(value, app)`，旧式回调回退
  `callback(value)` 或 `callback()`。
- `host` / `area`：渲染到哪个组件的哪个区域；实际由组件的 `plugin_options_area(...)` 决定。
  非法 `host` 直接拒绝并报错。

渲染方式：每个选项生成一行 `标签(label) + OptionMenu(choices)`，通过
`StringVar.trace_add("write", ...)` 触发回调。

当前限制：

- 只有调用了 `plugin_options_area(...)` 的组件会渲染插件新建下拉（实测：**`fs` 与 `video`**）。
- `callback` 只能拿到新值与工具实例，拿不到其他宿主上下文。

示例：

```python
def on_mode_changed(value, app=None):
    print("mode =", value)

def register(api):
    api.register_option("NLC 模式", ["自动", "强制", "关闭"], on_mode_changed, host="fs")
```

### 3.5 api.register_tool(name, builder, order=0)

在 Hub 中新增一个栏目（工具 Tab）。

参数：

- `name: str`：Tab 显示名称，不能与内置栏目重名。
- `builder: callable(parent) -> object`：构建函数。Hub 会创建一个 `tk.Frame` 作为 `parent` 传入，插件在 `parent` 上构建自己的 GUI；可返回任意对象（应用实例），Hub 不关心返回值。
- `order: int`：Hub 栏目顺序（升序，同值保注册顺序；内置六个工具固定在前）。

示例：

```python
import tkinter as tk
from tkinter import ttk

def build_tab(parent):
    ttk.Label(parent, text="这是我的插件工具").pack(padx=20, pady=20)
    return None

def register(api):
    api.register_tool("我的工具", build_tab, order=5)
```

插件工具可以自己创建任意下拉框、右键菜单、按钮并挂接真实逻辑，宿主只负责提供 Tab 容器。
`builder` 与六个内置 App 的构造契约一致：**都是一个可调用对象，接收宿主 Tab 返回对象**
（内置侧直接放的是 App 类本身，见第 6 节）。

### 3.6 api.log / api.log_detail / api.widgets

日志采用两级，与宿主完全一致：

| 成员 | 行为 |
|---|---|
| `api.log(msg, tag="info")` | **summary 级**：写本次运行的 `logs/runtime_<启动时刻>.log` + 进 Hub 日志栏（启动期先缓冲，界面就绪后回放） |
| `api.log_detail(msg, tag="info")` | **detail 级**：只写本次运行的 `logs/runtime_<启动时刻>.log`，点"导出"时才随全量日志输出 |

`tag` 可取 `info` / `ok` / `err` / `warn` / `dim` / `hdr`。

组件复用：

- `api.widgets` 返回 `toolkit_widgets` 模块，可直接使用 `dir_row` / `count_label` / `tool_header` / `tool_text` / `LogBox` / `log_section` / `CanvasTree` / `SplitPane` / `vscrollbar` / `drop_zone` / `_make_pump` 等；
- 也可以直接 `from toolkit import ...`（`toolkit.py` 是协调层，re-export 了全部公共 API）；
- 这些组件已统一处理主题切换与高 DPI，不要自造同类控件。

**注意（新插件请优先看 3.10）**：`api.widgets` 与直接 `ttk` 都是 **Tk 专用**的。
宿主已具备 Qt 后端（试点阶段，见 `qt_pilot*.py`），`api.widgets` 在 Qt 宿主里没有对应物；
只用它的插件在 Qt 后端会被**如实上报为 `skip(tk-only)`**（不崩、不影响其它插件），
但也就拿不到 Qt 的性能收益。**新插件请用 `api.ui` 写界面**（同名同参、两个后端都能跑）。

插件标识：`api.plugin_file`（相对文件名）、`api.plugin_info`（插件自己的 `PLUGIN_INFO`）。

### 3.7 槽位寻址：host × location

插件动作可以指向**任意组件**，不再局限于文件系统。寻址是精确的二元组：

| 维度 | 取值 | 说明 |
|---|---|---|
| `host` | `HOST_FS` / `HOST_CONVERT` / `HOST_TEXT` / `HOST_XML` / `HOST_VIDEO` / `HOST_FONT`（值即 `fs` / `convert` / `text` / `xml` / `video` / `font`） | 目标组件 |
| `location` | `LOC_TOOLBAR` / `LOC_CONTEXT`（值即 `toolbar` / `context`） | `toolbar` = 工具标题下方的一行动作区；`context` = 工具主内容控件的右键菜单 |
| `area` | `AREA_TOP_BAR` / `AREA_FORMAT` / `AREA_PACK_FORMAT` / `AREA_SOURCE_ENC` / `AREA_GAME` / `AREA_LANG` / `AREA_SIZE` / `AREA_SUFFIX` / `AREA_FILTER` | 面板与下拉的具体区域 |

这些常量由 `toolkit_plugins.py` 定义，可从 `toolkit` 直接导入（`from toolkit import HOST_XML, AREA_FILTER`）。
组件侧一律用常量、不写字面量；`toolkit_guard.py` 会拦下插件调用点里的裸 `host` / `area` 字符串。

```python
api.register_menu_item("导出为 CSV", my_cb, host="xml", location="toolbar")
api.register_menu_item("重新解析",   my_cb, host="fs",  location="context")
api.register_option("我的选项", ["a", "b"], host="fs")
```

- **精确匹配**：组件只取自己 `(host, location)` 的动作，**不做跨槽位回退**——注册给 `xml` 的动作绝不会出现在文件系统工具里。
- **写错就报错**：`host` / `location` 不在上表内时注册被拒绝，并列出可用取值写入日志与 `load_errors`（Hub 启动会弹窗提示）。**不会静默失效**。
- **无注册即无痕迹**：没有任何插件注册该槽时，动作区**不创建控件**、右键菜单**不绑定事件**，视觉与未接插件时完全一致。
- **当前已接线的槽位**：六个工具的 `toolbar` 槽全部接好；`context` 槽目前只接了文件系统工具（DB 列表右键）。其余组件要开 `context` 槽，需由该组件指定"主内容控件"后调用
  `attach_plugin_context_menu(widget, host, app=self)`（helper 已就绪，未列出的位置暂不作为槽位）。

**运行期刷新（`when` 不是死的）**：`plugin_slot_bar(...)` 返回 `PluginSlot` 句柄。构造时只求值
一次 context，之后运行期状态变化（如 fs 的 `loaded` 由空变有、xml 出结果）**不会自动重算**，
必须由组件调用 `slot.refresh()`：

- `refresh()`：复用构造时的 context 重算；
- `refresh({"has_results": True})`：用新 dict 替换 context 后重算。

更进一步，**context 允许传可调用对象**：传 `lambda: {...}` 时每次重算都重新求值，避免
"构造时的快照被冻结、`when` 永远为假"。组件侧的实例：`font_pack_app` 用
`context=lambda: {"has_results": self._has_results}`；`fs_app` 则在状态变化处显式
`slot.refresh({"loaded": bool(self.loaded)})`。

`PluginSlot` 还兼容旧用法：可解包为 frame（`frame = plugin_slot_bar(...)`），并代理
`pack` / `pack_forget` / `winfo_exists`；无可见命令时 `frame is None`，`refresh()` 是空操作。

### 3.8 命令与挂载点分离

**动作**与**它出现在哪里**是两件事。先注册命令，再用命令挂到任意多个槽位：

```python
api.register_command("export_csv", "导出为 CSV", my_handler, when={"loaded": True})
api.register_menu_item(command="export_csv", host="fs", location="toolbar")
api.register_menu_item(command="export_csv", host="fs", location="context")   # 同一个命令，两个位置
```

- **命令 id = `<插件文件>:<动作名>`**：你只写动作名（`export_csv`），**前缀由宿主加**，插件无法冒用别人的命名空间。
  动作名限 `字母 / 数字 / _ . -`，1~64 字符；重复注册、非法动作名、挂载点引用未注册命令 **一律拒绝并报错**（写入 `load_errors`，启动弹窗可见）。
- **`when` 条件可见性**：`when=None` 恒显示；`when={"loaded": True}` 表示宿主传入的 context 需匹配（缺键即不满足）；
  也可传可调用对象 `lambda ctx: ...`。组件渲染时通过 `plugin_slot_bar(..., context={...})` /
  `attach_plugin_context_menu(..., context={...})` 传入当前状态，条件由此判定——**条件写在你这边，不用改组件源码**。
- **旧式写法仍可用**：`api.register_menu_item("标签", callback, host="fs", location="toolbar")` 会自动建一个内部命令。

### 3.9 其余三个注册点

#### api.register_option_entry(host, area, value, when=None)

往**组件已有**的下拉菜单里加一个条目值（如 fs 的“格式”下拉）。组件没有对应下拉时加不进去
——那种情况请用 `register_option` 新建一个。

```python
api.register_option_entry("fs", "format", "我的格式")   # area 常量见 3.7 表
api.register_option_entry("font", "game", "我的版本")
```

`area` 用 `toolkit_plugins` 的 `AREA_*` 常量（`format` / `pack_format` / `source_enc` /
`game` / `lang` / `size` / `suffix` / `filter` / `top_bar`），**不要写裸字符串**——
`toolkit_guard.py` 会在 CI 里拦下硬编码槽位。同名条目保序去重。

#### api.register_panel(title, builder, host="fs", area="top_bar", order=0, when=None)

往组件的某个区域贡献一个子栏目/面板。`builder(parent)` 建 UI，`parent` 是宿主给的容器；
`builder` 不可调用时注册被拒绝。实测渲染该区域的组件：`fs` 与 `xml`（`tool_panel(...)`）。

```python
# 新写法（推荐）：界面走 api.ui，两个后端都能跑
def build_panel(parent, ui):
    row = ui.row(parent)                      # 竖直容器（等价 Tk 的 Frame + 默认 pack）
    ui.pack(ui.button(row, "解包", on_click=do_unpack), side="left")
    ui.pack(ui.label(row, "格式："), side="left")
    view = ui.text_view(parent, height=10)    # 只读多行文本
    ui.pack(view.widget, fill="x")
    return getattr(parent, "widget", parent)  # 返回值可选：宿主按 parent 容器排布

api.register_panel("我的面板", lambda parent: build_panel(parent, api.ui),
                   host="fs", area="top_bar")
```

`builder` 也可以直接写成两参形式 `builder(parent, ui)`，宿主会按签名判断是否传入 `ui`
（见 3.10）。旧写法 `lambda parent: ttk.Label(parent, text="hi").pack()` 仍能用，
但它在 Qt 后端会被判为 `tk-only` 并跳过。

#### api.register_compare_mode(...)

为 **XML 校对**贡献一种比较模式。这是**贡献点**而非挂载点：新模式会同时体现在模式下拉、
表格列、筛选项与行取值/比较算法上，组件源码不用改一行。

```python
api.register_compare_mode(
    name, columns, compare, row_builder=None,
    filters=None, order=0, detail_builder=None)
```

| 参数 | 说明 |
|---|---|
| `name` | 模式显示名（同时是模式下拉的取值）；与已有模式重名会被拒绝 |
| `columns` | `[(key, heading, width), ...]`。`key` 为 `rel` / `status` / `detail` 时由组件通用渲染，其余按同名列取值 |
| `compare` | `compare(ctx, path_a, path_b, rel) -> dict`；`ctx` 由组件提供（含 `name_a` / `name_b` / 编码等） |
| `row_builder` | 可选：`result -> (row_kind, differ_types)`。`row_kind ∈ {"same","diff","only_a","only_b"}`；`differ_types` 用于“有差异”下的子类型（如 `{"text"}`）。传 `None` 时由组件按 `consistent` / `only_side` 推断 |
| `filters` | 可选：`[(标签, {row_kind}, 需要的 differ_types), ...]`；传 `None` 用组件的默认筛选集 |
| `order` | 模式下拉中的顺序（升序，同值保注册顺序） |
| `detail_builder` | 可选：`(result, name_a, name_b) -> 明细文本`。不提供时详情退化为通用摘要 |

边界（务必知道）：组件的**列、筛选项、行取值、详情渲染**都由声明驱动，但**想让详情好看
就应提供 `detail_builder`**；结果里的 `mode` 字段内置比较函数写内部键、插件应写注册的显示名，
列渲染不再依赖它（只用于导出表头等展示）。

### 3.10 api.ui / api.backend —— 后端无关的控件工厂

**为什么有它**：插件契约里原本只有三处与工具包具体的 UI 技术耦合 —— `api.widgets`、
`register_panel(...)` 与 `register_tool(...)` 的 `builder(parent)`。后两者自己造控件，
于是"同一份插件代码无法在另一个后端上跑"。`api.ui` 给出**同一套极小接口**的两个实现：

| 成员 | 说明 |
|---|---|
| `api.backend` | `"tk"`（当前发行版）或 `"qt"`（试点）。**通常不需要分支** —— 用 `api.ui` 写的插件两边通用 |
| `api.ui` | 控件工厂，方法面固定 **14 个**（下表） |

| 类别 | 方法 |
|---|---|
| 造控件（8） | `label(parent, text, style=None)`、`button(parent, text, on_click=None, width=None, style=None, state=None)`、`row(parent, …)`（竖直容器）、`checkbox(parent, text, variable=None, on_toggle=None)`、`entry(parent, textvariable=None, width=None, show=None)`、`text(parent, height=6, width=None, wrap="word")`、`combo(parent, values=(), variable=None, width=None, on_change=None)`、`pack(widget, side="top", fill="x", expand=False, padx=0, pady=0, anchor=None)` |
| 改控件 / 取用户输入（6） | `set_text(widget, text)`、`text_view(parent, height=12, mono=True)`（返回带 `set_text/clear/alive/get_text` 与 `.widget` 的**只读**视图）、`alive(widget)`、`ask_yes_no(parent, title, message)`、`ask_open_file(parent, title, filetypes=None, initialdir="")`、`ask_save_file(parent, title, initialdir="", initialfile="", filetypes=None)` |

**两条必须知道的语义**（两条都写进了注入验证过的锁）：

1. **`pack()` 与 Tk 同义**：`side="top"`（默认，竖直序列）/ `"left"`、`"right"`（同一水平行）。
   `row(parent)` 造出来的是**竖直容器**；想要一行按钮就 `ui.pack(btn, side="left")`。
   Qt 后端内部用"创建即入布局 + `side` 归位"实现，所以插件**不需要**写
   `if api.backend == "qt"` 分支。
2. **控件创建后要 `pack`**（Tk 语义如此）。Qt 侧创建时已进布局，再 `pack` 只是归位/对齐提示，
   不会重复添加。

```python
def register(api):
    api.register_panel("引擎补丁", lambda parent: build(api, parent), host="font", area="bottom")

def build(api, parent):
    ui = api.ui
    wrap = ui.row(parent)
    row = ui.row(wrap)
    for text, op in (("识别", "identify"), ("校验", "verify")):
        ui.pack(ui.button(row, text, on_click=lambda o=op: run(o)), side="left", padx=(0, 6))
    path_label = ui.label(wrap, "未选择文件")
    ui.pack(path_label, fill="none", anchor="w", pady=(4, 0))
    view = ui.text_view(wrap, height=12)
    ui.pack(view.widget, fill="x", pady=(4, 0))
    # 之后随时：ui.set_text(path_label, p) / view.set_text(报告) / view.clear() / view.alive()
    return getattr(wrap, "widget", wrap)
```

`text_view` 返回值是**小对象**而不是裸控件：只读视图的写入通道就是 `set_text/clear`，
别去 `configure(state=...)`（Qt 侧没有这个 API）。`alive()` 用于判断面板是否已被销毁
（Hub 重建界面会留下旧句柄）。

**实测迁移成本**（`plugins/engine_utf8_patch.py`，基线是迁移前的发行副本）：
1470 → 1452 行，9 处 Tk 控件构造 + 25 处布局/改控件调用 + 3 处对话框调用 + 1 个 Tk 专有辅助函数
→ **16 处 `api.ui` 调用**；面板结构与注册点一个都没动（`run_ext_probe` 的 10 条锁前后同一条不变）。

## 4. 兼容旧式插件

不写 `register(api)`、但暴露 `decrypt_sq(path, out_path=None)` 的插件会被自动注册为解密器，识别函数固定为 `open_sq(path) is not None`（即插件还需提供 `open_sq`）。新插件请使用 `register(api)`。

## 5. NLC Improved sq_base 解密插件（闭源）

- NLC 解密插件 `nlc_sqfs.py` 为闭源组件：本地 `plugins\` 保留，仓库不包含、不发布源码。
- 持有该插件时，将其放入 `plugins\`，文件系统工具加载 `.sq_base` 时自动调用。
- 没有该插件时工具照常启动，只是无法解密 NLC `sq_base`。
- **本地版本（v2.0）已改用 §2 的标准协议**：提供 `PLUGIN_INFO` + `register(api)`，
  内部调 `api.register_decryptor(check_sq_base, decrypt_sq)`，详细日志走 `api.log_detail`；
  它不是 §4 描述的旧式自动注册插件。日志里的上报名取自 `PLUGIN_INFO.name`，
  形如 `NLC Improved sq_base decryptor: SquashFS 9 项, 5 文件`。
- `check_sq_base(path)` 只认 `ZZZZ` 头且**从不抛异常**：明文 SquashFS（`hsqs`/`sqsh`）、
  X-Ray DB、空文件、截断文件、目录、不存在的路径一律返回 `False`，不会抢在其他识别之前生效。
- 该插件也可独立运行：
  - `python plugins\nlc_sqfs.py <file.sq_base> [out.sqfs]`
  - `python plugins\nlc_sqfs.py --selftest` —— 12 个长度 × 3 个密钥的往返 + 与逐字节
    参照实现的字节比对，用于换机后确认密码学部分没被改坏。

## 6. 插件开发约定

- 插件文件放在 `plugins\` 下，扩展名 `.py`；文件名以 `_` 开头的文件不会被加载。
- 插件之间保持独立，不要互相 import。
- 需要第三方二进制时，放在 `plugins\` 下自己的目录里，并用 `os.path.join(os.path.dirname(__file__), ...)` 定位。
- 加载失败不会阻断工具启动，但会在日志中记录 `plugin load failed` 并弹窗提示。
- 插件只在 Hub 启动时加载一次，修改插件后请重启工具。
- **界面一律用 `api.ui`（见 3.10）**：同名同参、Tk/Qt 两个后端都跑，插件不必写后端分支。
  `api.widgets` 与裸 `ttk`/`tk` 是 **Tk 专用**的：在 Qt 宿主里会被如实上报为 `skip(tk-only)`
  （不崩、不影响别的插件），但那条路将来会越来越窄。
- `register_tool` 构建的界面建议使用 `ttk` 控件和公共色板（`toolkit.color()` / `toolkit.T`），这样 Hub 切换亮/暗主题时宿主会通过 `refresh_theme()` 自动刷新；使用 tk 原生控件并硬编码颜色的界面需自行处理主题切换。
- 插件工具对象（`builder` 的返回值）**不需要**再提供 `_log` / `log` 方法：Hub 不会去改写它，
  日志走全局两级通道（`api.log` / `api.log_detail`）。这与六个内置 App 的约定完全相同。
- 插件自身上报进度请用 `api.log`（用户可见）/ `api.log_detail`（只落盘），不要自己写日志文件；宿主的分级会保证 GUI 简洁、导出时又不丢细节。
- 需要通用控件时优先复用 `api.ui`（后端无关）/ `api.widgets` / `toolkit`，避免各插件重复实现同一类组件。
- **契约一致**：六个内置 App 与插件通过 `register_tool` 注册的栏目使用**同一个契约**——
  宿主执行 `apps[label] = factory(tab)`，其中 `tab` 是 Hub 在 Notebook 里创建的 `tk.Frame`，
  `factory` 对内置栏目就是 **App 类本身**（`BUILTIN_TOOLS` 里放的是类），对插件栏目就是
  `builder`。形式化写作 **`callable(parent) -> object`**，也即内置侧的 **`App(parent)`**。
  只接收宿主 Tab，不自建根窗口、不应用主题、不自建日志面板，日志统一走全局两级通道
  （`log_summary` / `log_detail`）。插件栏目无需任何额外适配。
  **注意：不存在 `build(parent)` 这个符号**——全仓库没有任何模块级 `def build(...)`
  充当 App 契约（`build.py` 的 `build(out_dir, prerelease)` 是构建函数，与此无关）。
