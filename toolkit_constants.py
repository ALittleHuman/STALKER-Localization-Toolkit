# -*- coding: utf-8 -*-
"""STALKER 汉化工具集 — 业务常量表（能力 5）

把原先散在各 App 里的**取值集合与命名约定**集中到一处。这里的常量有两个特征：
    * 属于业务领域（STALKER 的文件布局/编码习惯），不是纯技术参数；
    * 多个工具或同一工具的多处需要同一份取值，写两遍必然漂移。

本模块**纯数据、零依赖**——不 import tkinter，也不 import 工程内其它模块，
因此任何层都可以安全引用它（包括引擎层与未来的插件）。

约定：放在这里的是"同一个事实只写一次"的东西；只在一个函数里用一次的
局部字面量不要搬进来，否则只是把常量堆换个地方。
"""
import os

# ─────────────────────────────────────────────────────────────
# 一、包与格式（fs 工具 + 引擎层共用的文件识别约定）
# ─────────────────────────────────────────────────────────────
# STALKER 的数据包扩展名（.db 家族 + .sq 家族）。引擎按格式名区分内部结构，
# 这里只负责"这个文件看起来是不是一个数据包"。
PKG_EXTS = (".db", ".db0", ".db1", ".db2", ".db3", ".db4",
            ".db5", ".db6", ".db7", ".db8", ".db9",
            ".sq", ".sq_base", ".sqfs")

# 扩展名尾部匹配用的短后缀。判据是"最后一个点起取 3 个字符"，即
# apps/fs_app.py 里 `n[d:d+3] == ".db"` / `.sq` 的同一种宽松匹配 ——
# 它会同时命中 .db0~.db9 与 .sq_base。注意这**不等于** os.path.splitext
# 的精确比较：历史上这里写成 `name.endswith(m)`，于是 gamedata.db0 /
# x.sq_base 被判成"不是数据包"，既与 fs_app 的现行为不一致，也与上面的
# PKG_EXTS 自相矛盾。is_package_name 已按此语义实现。
PKG_EXT_MARKERS = (".db", ".sq")

# 内部格式名 ↔ 输出扩展名
EXT_FOR_FORMAT = {"sqfs": ".sqfs"}
DEFAULT_DB_EXT = ".db"
DEFAULT_PACK_BASENAME = "packed"

# SquashFS 相关：临时文件后缀与外部工具名
SQFS_TMP_SUFFIX = ".sqfs"
SQFS_TOOL_NAMES = ("rdsquashfs.exe", "sqfs2tar.exe", "tar2sqfs.exe")


def is_package_name(path):
    """按名字判断是否像 STALKER 数据包（宽松匹配，与 fs_app 原判定等价）。

    "宽松"的确切含义：取**最后一个点起的前 3 个字符**与标记比较，而不是
    `splitext` 的精确扩展名比较。因此 gamedata.db0（→ ".db"）、
    all.sq_base（→ ".sq"）、z.SQFS（→ ".sq"）都算数据包，
    readme.txt（→ ".tx"）不算。判据必须与 `PKG_EXTS` 的家族口径一致。
    """
    name = os.path.basename(path).lower()
    d = name.rfind(".")
    if d < 0:
        return False
    return name[d:d + 3] in PKG_EXT_MARKERS


def output_ext_for(fmt):
    """格式名 → 输出扩展名（如 sqfs → .sqfs，其余 → .db）。"""
    return EXT_FOR_FORMAT.get(fmt, DEFAULT_DB_EXT)


# ─────────────────────────────────────────────────────────────
# 二、备份约定（convert 工具的 .bak 备份）
# ─────────────────────────────────────────────────────────────
BACKUP_DIRNAME = "backup"       # 备份子目录名（源根下）
BACKUP_SUFFIX = ".bak"          # 备份文件后缀

# ─────────────────────────────────────────────────────────────
# 三、编码（工具链面对的源文件编码习惯）
# ─────────────────────────────────────────────────────────────
# 源/目标编码下拉的取值（顺序即界面顺序）。含 STALKER 原版常见的西里尔编码
# 与本项目实际处理过的东亚编码。
ENCODING_CHOICES = ["auto", "utf-8", "gbk", "gb2312", "big5", "shift_jis", "euc-kr",
                    "windows-1251", "windows-1252", "iso-8859-1", "ascii", "utf-16"]

# STALKER 原版文本最常用的单字节编码（XML 声明缺省时按它兜底）
LEGACY_ENCODING = "windows-1251"

# ─────────────────────────────────────────────────────────────
# 四、文本提取（text_extract 的输出命名与遍历范围）
# ─────────────────────────────────────────────────────────────
XML_EXTS = (".xml",)
SCRIPT_EXTS = (".script", ".ltx")
DEFAULT_ID_PREFIX = "gs"
FALLBACK_ID_PREFIX = "mod"
# 类型段用**缩写**（gameplay→gp / scripts→sc），与 1.0.0 发行版的既有 ID 逐字一致。
# 槽位名从 {ftype} 改成 {abbr}：它收的从来不是 ftype 全名而是缩写，旧名字有歧义
# （曾一度有人按字面把全名塞进来，产出 sgtat_gs_gameplay_123 会让既有译文表全表失配）。
# 名字改准，**取值与产物 ID 完全不变**。
ID_PREFIX_TEMPLATE = "sgtat_{prefix}_{abbr}_{ts}"
GP_TEXTS_NAME = "{prefix}_gameplay_texts.xml"
SC_TEXTS_NAME = "{prefix}_scripts_texts.xml"
