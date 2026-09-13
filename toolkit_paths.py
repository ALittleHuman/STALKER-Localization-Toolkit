# -*- coding: utf-8 -*-
"""应用路径 —— **不依赖任何 UI 技术**的最小模块。

## 为什么单独一个文件

`app_dir()` 是"可写应用目录"的**唯一规则**，消费方是日志管线、平台层（`user.ltx` /
app 配置）与主题 —— 这些消费方**没有一个是 UI 层的**。但这条规则原先住在
`toolkit_base`，而 `toolkit_base` 顶层就 `import tkinter`、选 `TkinterDnD.Tk`，
还带一句 import 期的 `ensure_package("tkinterdnd2")`（会尝试 pip 安装）。

后果很具体：任何想读写 `user.ltx` 的非 Tk 后端（Qt 试点）都必须先把 Tk 拉进进程，
而冻结的 Qt 包里根本没有 Tcl/Tk。把**这一条规则**搬出来，那条依赖就断了。

## 接口面一个不变

* `toolkit_base.app_dir()` 仍可用（本模块在那边 re-export）；
* `toolkit_platform.app_dir` 仍是**模块级名字** —— 既有探针就是靠
  `toolkit_platform.app_dir = lambda: 临时目录` 把落盘重定向到临时目录的，
  所以本模块不能改成"包一层函数再在内部 import"的写法。

（同理不要在这里加任何 `import tkinter`：加了就等于把刚断开的依赖接回去。
`run_app_probe` 有一条锁盯着这个模块的 Tk 无关性。）
"""
import os
import sys


def app_dir():
    """可写应用目录：PyInstaller onedir 中为 exe 所在目录，开发环境为项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
