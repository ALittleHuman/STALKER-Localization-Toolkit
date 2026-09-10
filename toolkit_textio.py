# -*- coding: utf-8 -*-
"""文本 / 文件 IO 工具（从 toolkit.py 拆分）。

包含：字节格式化、多编码文本读取、XML 文本提取、文件递归收集。
toolkit.py 会 re-export 这些名字，调用方无需改动。
"""
import os


def fmt_size(sz):
    """字节数格式化: B / KB / MB."""
    if sz >= 1048576:
        return f"{sz / 1048576:.1f} MB"
    if sz >= 1024:
        return f"{sz / 1024:.1f} KB"
    return f"{sz} B"


# ─── 公共功能 (本质相同的逻辑统一实现, 子功能用参数区分) ───
DEFAULT_ENCODINGS = ["utf-8-sig", "utf-8", "windows-1251", "windows-1252", "gb18030", "latin-1"]


def read_text_file(path, encodings=None):
    """多编码读取文本文件: 依次尝试编码, 返回 (内容, 成功编码).
    全部失败时最后一种编码以 ignore 容错读出. 适合原版游戏文件(多编码)."""
    encs = encodings or DEFAULT_ENCODINGS
    for i, enc in enumerate(encs):
        try:
            with open(path, "r", encoding=enc,
                      errors="ignore" if i == len(encs) - 1 else "strict") as f:
                return f.read(), enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码: {path}")


def parse_xml_texts(text):
    """从 XML 文本提取所有文本节点内容 (容错).
    支持：合法 XML、多根 XML、坏实体/非法 XML。
    多根 XML 在 STALKER 模组中非常常见，必须完整提取。"""
    import re
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
        return list(root.itertext())
    except Exception:
        pass
    # 多根 XML：移除声明后包一层根再解析。
    try:
        body = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", text, count=1, flags=re.I | re.S)
        root = ET.fromstring("<toolkit_root>" + body + "</toolkit_root>")
        return list(root.itertext())
    except Exception:
        pass
    # 最后回退：去掉所有标签，提取剩余文本（宁多勿漏，
    # 多提取的字符只会让字库稍大，漏提取会导致游戏显示方块）。
    strip_re = re.compile(r"<[^>]+>")
    plain = strip_re.sub("", text)
    return [plain] if plain.strip() else []


def collect_files(root_dir, exts=None, exclude_dirs=()):
    """递归收集文件: exts 为扩展名集合(小写, 含点)或 None 收全部;
    exclude_dirs 为相对路径前缀元组. 返回排序后的绝对路径列表."""
    out = []
    for dp, dn, fns in os.walk(root_dir):
        rel = os.path.relpath(dp, root_dir).replace("\\", "/")
        if rel != "." and any(rel.startswith(p) for p in exclude_dirs):
            continue
        for fn in fns:
            if exts and os.path.splitext(fn)[1].lower() not in exts:
                continue
            out.append(os.path.join(dp, fn))
    return sorted(out)
