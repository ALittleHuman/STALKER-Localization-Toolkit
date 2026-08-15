# 插件使用说明

工具集支持从 `plugins\` 目录加载 Python 插件。插件用于扩展工具集能力，例如特殊加密资源的解密、新增格式、新增菜单项或下拉选项。

## 插件目录

```
STALKER_Toolkit\
├─ plugins\
│  └─ nlc_sqfs.py                         # NLC Improved sq_base 解密插件
└─ deps\
   └─ squashfs-tools-ng-1.3.2-mingw64\    # 第三方依赖（供 FS 引擎调用，不是插件）
```

工具集启动时（文件系统工具初始化）会扫描 `plugins\*.py`，逐个导入并调用插件的 `register(api)`。

## 插件写法

一个最小插件文件：

```python
# my_plugin.py
import os

PLUGIN_INFO = {
    "id": "my_plugin",
    "name": "My Plugin",
    "version": "1.0",
    "author": "you",
    "description": "插件说明",
}

def register(api):
    # 注册一个解密器：check(path) 返回 True 时，decrypt(path) 会被调用
    api.register_decryptor(
        lambda path: os.path.isfile(path) and open(path, "rb").read(4) == b"MYMG",
        my_decrypt,
    )

def my_decrypt(path, out_path=None):
    ...
    return decrypted_bytes
```

不写 `register` 的老式插件，只要暴露 `decrypt_sq(path)`，也会被兼容加载为解密器。

## 可用的扩展点

| 扩展点 | 说明 |
|---|---|
| `api.register_decryptor(check, decrypt)` | 注册特殊加密包解密器。`check(path)` 负责识别文件，`decrypt(path)` 返回解密后的字节。 |
| `api.register_format(name, handler)` | 注册新的封包/解包格式。`handler` 需提供 `unpack(raw)->entries` 和 `pack(files)->bytes`，条目结构与 `stalker_fs` 一致。 |
| `api.register_menu_item(label, callback)` | 在文件系统工具的右键菜单新增一项。 |
| `api.register_option(label, choices)` | 为下拉框新增选项。 |

## 现有插件：NLC Improved sq_base

- 文件：`plugins\nlc_sqfs.py`
- 功能：识别 `ZZZZ` 头部的 NLC Improved `sq_base`，解密为标准 SquashFS。
- 使用：无需任何操作。在文件系统工具中加载 `.sq_base` 时，插件会自动被调用；解密成功后按普通 SquashFS 浏览和提取。

## 插件管理约定

- 插件文件放在 `plugins\` 下，扩展名 `.py`，文件名以下划线 `_` 开头的文件会被忽略。
- 插件加载失败不会影响工具集启动，日志会记录失败原因。
- 插件之间应保持独立，不要互相 import。
- 需要第三方二进制时，放在 `plugins\` 下自己的目录里，并在插件内通过 `__file__` 定位。
