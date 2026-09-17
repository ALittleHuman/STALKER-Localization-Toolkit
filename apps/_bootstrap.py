# -*- coding: utf-8 -*-
"""
App 公共引导模块。

统一提供：
    * 标准库 / tkinter 的常用导入（避免每个 App 重复 15 行 import）
    * file_system / font_pack / plugins 子目录的 sys.path 注入

各 App 用法：
    from apps._bootstrap import (
        os, sys, re, threading, struct, shutil, subprocess, tempfile, time, json, glob,
        atexit, datetime, dataclass, field, Path, Counter,
        Optional, List, Dict, Set, Tuple, Union, Any, Callable,
        ET, tk, ttk, filedialog, messagebox, scrolledtext,
    )
"""
import os
import sys
import re
import atexit
import threading
import struct
import shutil
import subprocess
import tempfile
import time
import json
import glob
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter
from typing import Optional, List, Dict, Set, Tuple, Union, Any, Callable
import xml.etree.ElementTree as ET

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# 引擎库路径注入（stalker_fs / font_pack / 插件）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("file_system", "font_pack", "plugins"):
    _p = os.path.join(_BASE_DIR, _sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# 本模块是**转发层**：下面的名字是给各 App `from apps._bootstrap import ...` 用的，
# 在本文件内"未使用"属设计使然。显式声明 __all__ 有两个好处：
#   1. 静态检查（pyflakes 视 __all__ 里的名字为已使用）不再对整文件报"未用导入"，
#      于是"有没有真的漏掉一个名字"这件事才看得清；
#   2. 转发清单从"散在 comments 里"变成可机读的对外接口。
__all__ = [
    "os", "sys", "re", "atexit", "threading", "struct", "shutil", "subprocess",
    "tempfile", "time", "json", "glob",
    "datetime", "dataclass", "field", "Path", "Counter",
    "Optional", "List", "Dict", "Set", "Tuple", "Union", "Any", "Callable",
    "ET", "tk", "ttk", "filedialog", "messagebox", "scrolledtext",
]
