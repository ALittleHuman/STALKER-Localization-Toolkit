# -*- coding: utf-8 -*-
"""
App 公共引导模块。

统一提供：
    * 标准库 / tkinter 的常用导入（避免每个 App 重复 15 行 import）
    * file_system / font_pack / plugins 子目录的 sys.path 注入

各 App 用法：
    from apps._bootstrap import (
        os, sys, re, threading, struct, shutil, subprocess, tempfile, time, json, glob,
        datetime, dataclass, field, Path, Counter,
        Optional, List, Dict, Set, Tuple, Union, Any, Callable,
        ET, tk, ttk, filedialog, messagebox, scrolledtext,
    )
"""
import os
import sys
import re
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
