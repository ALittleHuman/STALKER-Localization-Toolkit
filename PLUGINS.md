# 插件说明

文件系统工具支持从 `plugins\` 目录加载 Python 插件，用于扩展：加密包解密、新封包/解包格式、右键菜单项、下拉选项。插件只在文件系统工具初始化时扫描一次，修改后需重启工具生效。

## 1. 插件目录与加载规则

```
STALKER_Toolkit\
└─ plugins\
   ├─ enabled.txt       # 可选：插件白名单
   └─ nlc_sqfs.py       # 示例：NLC 解密插件（本地保留，仓库不含）
```

加载规则：

- 递归扫描 `plugins\` 下所有 `.py` 文件（含直接子目录）。
- 文件名以 `_` 开头的文件被忽略；`__pycache__` 和 `.git` 目录被忽略。
- 插件按相对路径排序后依次加载。
- 如果 `plugins\enabled.txt` 存在且内容非空，则只加载其中列出的文件。每行一个相对路径（如 `nlc_sqfs.py`），`#` 开头为注释。
- 单个插件加载或注册失败不会影响工具启动，失败信息会写入日志，并在文件系统工具中弹窗提示。

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

`register(api)` 收到的 `api` 提供四个注册方法。

### 3.1 api.register_decryptor(check, decrypt)

注册加密包解密器。当文件系统工具加载 `.sq*` 文件且其头部魔数为 `ZZZZ`（即 NLC 类型）时，会按注册顺序依次询问 `check(path)`；第一个返回 `True` 的解密器被采用。如果没有注册解密器接受该文件，工具会回退到 `plugins\nlc_sqfs.py` 模块。

参数：

- `check(path: str) -> bool`：识别该插件能处理的文件。
- `decrypt(path: str, out_path: str = None) -> bytes | None`：返回解密后的字节；若 `out_path` 非空，应同时写出文件；返回 `None` 表示失败。

示例（NLC sq_base）：

```python
def register(api):
    api.register_decryptor(
        lambda path: os.path.isfile(path) and open_sq(path) is not None,
        decrypt_sq,
    )
```

### 3.2 api.register_format(name, handler)

注册新的封包 / 解包格式。注册后，`name` 会出现在文件系统工具的“格式”下拉框中。用户手动选择该格式时，解包 / 打包会调用对应的 handler；`auto` 自动检测不会检测插件格式。

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

### 3.3 api.register_menu_item(label, callback, location="context")

在文件系统工具“DB 文件列表”的右键菜单中新增一项。

参数：

- `label: str`：菜单文字。
- `callback: callable`：点击时调用，无参数。
- `location: str`：目前只支持 `"context"`（右键菜单）。

示例：

```python
def my_action():
    print("menu clicked")

def register(api):
    api.register_menu_item("执行我的操作", my_action)
```

### 3.4 api.register_option(label, choices, callback=None)

在文件系统工具顶部新增一个下拉选项。

参数：

- `label: str`：选项名称，同时作为读取当前值的键。
- `choices: list[str]`：可选值列表，第一项为默认值。
- `callback: callable | None`：切换时回调，参数为新值字符串；可选。

示例：

```python
def on_mode_changed(value):
    print("mode =", value)

def register(api):
    api.register_option("NLC 模式", ["自动", "强制", "关闭"], on_mode_changed)
```

## 4. 兼容旧式插件

不写 `register(api)`、但暴露 `decrypt_sq(path, out_path=None)` 的插件会被自动注册为解密器，识别函数固定为 `open_sq(path) is not None`（即插件还需提供 `open_sq`）。新插件请使用 `register(api)`。

## 5. NLC Improved sq_base 解密插件（闭源）

- NLC 解密插件 `nlc_sqfs.py` 为闭源组件：本地 `plugins\` 保留，仓库不包含、不发布源码。
- 持有该插件时，将其放入 `plugins\`，文件系统工具加载 `.sq_base` 时自动调用。
- 没有该插件时工具照常启动，只是无法解密 NLC `sq_base`。
- 该插件也可独立运行：`python plugins\nlc_sqfs.py <file.sq_base> [out.sqfs]`。

## 6. 插件开发约定

- 插件文件放在 `plugins\` 下，扩展名 `.py`；文件名以 `_` 开头的文件不会被加载。
- 插件之间保持独立，不要互相 import。
- 需要第三方二进制时，放在 `plugins\` 下自己的目录里，并用 `os.path.join(os.path.dirname(__file__), ...)` 定位。
- 加载失败不会阻断工具启动，但会在日志中记录 `plugin load failed` 并弹窗提示。
- 插件只在文件系统工具初始化时加载，修改插件后请重启工具。
