# -*- coding: utf-8 -*-
"""文本 / 文件 IO 工具（从 toolkit.py 拆分）。

包含：字节格式化、多编码文本读取、XML 文本提取、文件递归收集。
toolkit.py 会 re-export 这些名字，调用方无需改动。
"""
import codecs
import os


def fmt_size(sz):
    """字节数格式化: B / KB / MB."""
    if sz >= 1048576:
        return f"{sz / 1048576:.1f} MB"
    if sz >= 1024:
        return f"{sz / 1024:.1f} KB"
    return f"{sz} B"


# ─── 公共功能 (本质相同的逻辑统一实现, 子功能用参数区分) ───
# 顺序不可随意调整，尤其 gb18030 **必须排在 windows-1251 之前**：
# 实测 gb18030 的中文 XML 字节用 windows-1251 能"解码成功"（得到乱码，
# 不抛异常），而 cp1251 的俄文字节用 gb18030 会抛 UnicodeDecodeError。
# 也就是说"gb18030 在前"对俄文无损、对中文必需；反过来则中文源一律乱码。
# 这与重构前 toolkit.py:210 的顺序一致（此处曾把 gb18030 挪到第 5 位，
# 属回归）。
DEFAULT_ENCODINGS = ["utf-8-sig", "utf-8", "gb18030", "windows-1251", "windows-1252", "latin-1"]

# 字节解码的候选顺序（与 read_text_file 的文本模式链分开维护，
# 避免改动既有文本读取语义）。这里统一的是原先散在三个 App 里的四份实现。
BYTE_DECODE_CANDIDATES = ["windows-1251", "windows-1252", "gbk"]
ENCODING_ALIASES = {
    "cp1251": "windows-1251", "cp-1251": "windows-1251", "windows1251": "windows-1251",
    "cp1252": "windows-1252", "cp-1252": "windows-1252", "windows1252": "windows-1252",
    "utf8": "utf-8", "utf-8-sig": "utf-8",
}

# 保底编码：全部候选失败时用它（latin-1 永不失败）并标记 "forced"。
DECODE_FALLBACK = "latin-1"

_XML_DECL_ENC_RE = None

# ─── BOM ───
# 宽字符 BOM 必须**先长后短**匹配（utf-32 的 BOM 以 utf-16 的 BOM 开头）。
_UTF8_BOM = b"\xef\xbb\xbf"
_BOM_WIDE = ((b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
             (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))

# ─── 统计探测（chardet）───
# 确定性链（手动 / BOM / 严格 UTF-8 / XML 声明）全部落空后，才用统计探测。
# 它恢复的是**旧编码转换工具原有的能力**：GBK / Big5 / Shift-JIS / 无 BOM 的
# UTF-16 这类"外观上不像 cp1251"的文本，确定性链无法区分，只能靠统计。
# 但它在**短样本**上会把 cp1251 俄文判成 MacCyrillic / ISO-8859-5 —— 同样能
# 解码，结果却是乱码。因此"低置信度 + 西里尔家族非 cp1251"的结论一律回到
# windows-1251（本项目原版文件的绝大多数）。
_CHARDET_MIN_CONF = 0.30
# 西里尔家族的其他候选：**任何置信度都不采信**，一律回到 windows-1251。
# 理由是实测出来的：chardet 对本项目的俄文样本极不稳定，而这些编码
# **互相之间没有字节级约束**，全都"解码成功"，错了就是整篇乱码。
#   'Ты должен идти на Янтарь…' → MacCyrillic 0.47（Python 真有 mac_cyrillic 编解码器）
#   'Здравствуй, сталкер!'      → MacCyrillic 0.23
#   'АКМ 5.45 мм'               → cp869 0.04
# 本项目原版文件绝大多数是 windows-1251，真要别的编码由用户手动指定。
_CYRILLIC_ALTS = {
    "maccyrillic", "mac-cyrillic", "iso8859-5", "iso-8859-5",
    "koi8-r", "koi8-u", "cyrillic", "cp855", "cp866", "ibm866", "cp869",
}
# 其余单字节家族不再单独列表：原先有一张 `_AMBIGUOUS_SINGLE_BYTE` 手工清单
# （西欧/希腊等），但**手工清单必然漏**，实测就漏掉了 cp865 —— chardet 对一个
# cp1251 文件给 "cp865, 0.025"，因为 cp865 不在名单里，那条
# `conf >= MIN or guess not in 名单` 就直接放行了，于是整篇按丹麦语 DOS 码页解成乱码。
# 现在改为**程序化判定是不是单字节编解码器**（`_is_single_byte_codec`）：
# 单字节家族对任意字节都"解成功"，低置信度时不予采信；多字节家族（gb18030 /
# big5 / utf-16 …）即便置信度略低也采信 —— 多字节编码能把整段字节严格解开，
# 本身就是很强的证据。实测 gb18030 对短中文样本只有 0.279（低于 0.3 门槛），
# 所以这条豁免是必需的，不能只留门槛。


def bom_encoding(raw):
    """BOM → 编码名；无 BOM 返回 None。

    UTF-8 的 BOM 归一为 `utf-8`：调用方历来按 utf-8 处理并自行剥 BOM，
    返回 `utf-8-sig` 会让"判定出的编码"与"实际用的编码"对不上。
    """
    if raw.startswith(_UTF8_BOM):
        return "utf-8"
    for sig, enc in _BOM_WIDE:
        if raw.startswith(sig):
            return enc
    return None


def _chardet_guess(raw):
    """统计探测 → (编码名, 置信度)。不可用（未装 / 无此编解码器）时返回 (None, 0.0)。"""
    try:
        import chardet
    except ImportError:
        return None, 0.0
    try:
        res = chardet.detect(raw) or {}
    except Exception:
        return None, 0.0
    name = (res.get("encoding") or "").strip().lower()
    if not name:
        return None, 0.0
    name = ENCODING_ALIASES.get(name, name)
    try:
        codecs.lookup(name)          # chardet 会给出 Python 没有的名字（如 MacCyrillic）
    except LookupError:
        return None, 0.0
    try:
        conf = float(res.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return name, conf


def is_multibyte_utf8(raw):
    """能按 UTF-8 解码**且确实含多字节序列**（存在 ≥0x80 的字节）时为 True。

    为什么不能只判"能不能按 UTF-8 解码"：纯 ASCII 也是合法 UTF-8，但它同时是
    任何一种 ASCII 兼容单字节编码 —— 那不是"多字节编码"的证据。1.0.0 只看
    "解码成功即 utf-8"，于是英文 XML（全 ASCII、声明 windows-1251）一律被判成
    utf-8，再撞上"已是目标编码"分支，XML 声明就永远改不掉。
    """
    if not raw or max(raw) < 0x80:
        return False
    try:
        raw.decode("utf-8")
        return True
    except (UnicodeDecodeError, UnicodeError):
        return False


def bytes_fit_encoding(raw, enc):
    """字节是否**可能**是 enc 编码的 —— 严格解码通过才算。

    用来否掉"撒谎的 XML 声明"：声明是**文件自己的声称**，字节能否定它。
    典型：字节是 cp1251 的西里尔文、声明却写 `encoding="utf-8"` —— 严格解必失败，
    这条声明与"多字节检查"已经拿到的事实直接矛盾，无权被采信。
    （编解码器名不存在时同样视为不可信，免得把一个用不了的编码名传下去。）
    """
    if not enc:
        return False
    try:
        raw.decode(enc)
        return True
    except (UnicodeDecodeError, UnicodeError, LookupError):
        return False


def _is_single_byte_codec(enc):
    """该编解码器是否"每个字节各自解成一个字符"（单字节家族）。

    判据：`bytes(range(256))` 容错解码后是否正好得到 256 个字符。
    单字节编码对**任意**字节都能解成功，所以"解成功"不能作为它是正确编码的证据；
    多字节编码若能把整段字节严格解开，本身就是很强的证据。

    为什么不手工列名单：原先那张 `_AMBIGUOUS_SINGLE_BYTE` 就漏掉了 cp865，
    导致置信度 0.025 的瞎猜被采信、整篇乱码。程序化判定是自维护的，
    不依赖谁记得往名单里补编码。
    （utf-8 在此被判为"单字节"，无害：真 UTF-8 在第 2 步就被多字节检查接管；
    而低置信度的 utf-8 猜测本就该被拒 —— 字节既然不是合法 UTF-8，返回 utf-8 必错。）
    """
    try:
        return len(bytes(range(256)).decode(enc, errors="replace")) == 256
    except (LookupError, UnicodeDecodeError, UnicodeError):
        return False


def sniff_encoding(raw, override=None):
    """字节级编码判定（不读文件、不做错误兜底），返回编码名。

    判定顺序（**多/单字节检查优先级最高**，其后才是手动、声明、统计）：
        1. BOM（物理事实：utf-8 / utf-16 / utf-32，含大端）
        2. **多字节检查**：能按 UTF-8 解码且含多字节序列 → utf-8
           （纯 ASCII 不算多字节，会继续往下走）
        3. override 明确指定（非空且非 auto）→ 归一化后的名字
        4. XML 声明里的 encoding="..."（STALKER 原版 XML 走这条）——
           **前提是字节能证实它**（`bytes_fit_encoding`）：声明与字节矛盾时不采信
        5. chardet 统计探测（装了才用；低置信度的西里尔家族误判除外）
        6. 默认 windows-1251（STALKER 原版绝大多数如此）

    "一目录多编码"这件事由**逐文件**跑本函数天然支持：每个文件各自看自己的
    BOM/多字节/声明，所以默认的 override="auto" 就能处理 A 文件 A 编码、
    B 文件 B 编码；override 只在"确定整目录就这一种"时才用，且多字节检查
    仍排在它之上（混在 cp1251 目录里的 UTF-8 文件照样认得出来）。

    为什么第 2 步必须在第 3 步之前：多字节 UTF-8 的字节用任何单字节编码去解都是
    乱码，这是**物理事实**，比"用户选了什么"更硬。反过来，纯 ASCII 在两种编码下
    字节完全相同，没有多字节证据，就该听用户的、再看声明。

    两处历史缺陷（2026-09）：
        * 1.0.0 用"严格 UTF-8 解码成功"当第 2 步判据，未区分纯 ASCII 与真多字节，
          于是英文 XML 全被误判 utf-8 → 声明改不掉；
        * 旧实现没有任何统计探测，GBK / Big5 / UTF-16 一律落到 windows-1251，
          而重构前的 Convert_v0.5.py 用 chardet 能正确识别它们。
    """
    import re
    global _XML_DECL_ENC_RE

    # 1. BOM 是物理事实，优先于任何猜测
    bom = bom_encoding(raw)
    if bom:
        return bom

    # 2. 多字节检查（最高优先的编码判定）
    if is_multibyte_utf8(raw):
        return "utf-8"

    # 3. 手动指定：走到这里说明是多字节证据不足（纯 ASCII 或单字节编码），
    #    此时用户的选择是最终裁决
    enc = (override or "").strip().lower()
    if enc and enc != "auto":
        return ENCODING_ALIASES.get(enc, enc)

    # 4. XML 声明 —— 但**必须能被字节证实**。
    # 声明是文件自己的声称；多字节检查只能证明"不是 UTF-8"，不能证明"是哪种单字节
    # 编码"，于是链条会去问声明。可如果声明写 utf-8 而字节严格解不开 utf-8，
    # 这条声明与已拿到的事实直接矛盾 —— 旧实现照信，于是"字节 cp1251、声明 utf-8"
    # 的文件被判成 utf-8：目标也是 utf-8 时会被当成"已达标"静默跳过，目标不是
    # utf-8 时则被 `errors="replace"` 成片替换掉正文。所以这里先要求字节证实它。
    if _XML_DECL_ENC_RE is None:
        _XML_DECL_ENC_RE = re.compile(
            rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']', re.I | re.S)
    m = _XML_DECL_ENC_RE.search(raw[:500])
    if m:
        decl = m.group(1).decode("ascii", "replace").strip().lower()
        cand = ENCODING_ALIASES.get(decl, decl) if decl else None
        if bytes_fit_encoding(raw, cand):
            return cand

    # 5. 统计探测：西里尔家族的其他候选一律不采信（见 _CYRILLIC_ALTS）。
    #    其余按"置信度达标 **或** 属于多字节家族"采信 —— 单字节家族对任意字节都
    #    解成功，低置信度时毫无信息量（实测 chardet 会对 cp1251 文件给出
    #    "cp865 / 0.025"，采信即整篇乱码）；多字节家族即便置信度略低也可信
    #    （实测短中文样本 gb18030 只有 0.279）。
    guess, conf = _chardet_guess(raw)
    if guess and guess not in _CYRILLIC_ALTS:
        if conf >= _CHARDET_MIN_CONF or not _is_single_byte_codec(guess):
            return guess

    # 6. 默认
    return "windows-1251"


def decode_bytes(raw, override=None, errors="strict"):
    """字节 → (text, used_encoding, forced)。

    用于"不知道文件编码"的原版游戏文件。判定顺序见 sniff_encoding；这里额外
    处理 BOM：**宽字符 BOM（utf-16/utf-32，含大端）在剥之前就先认出来**，
    并把整段字节交给对应 codec（由它自己吃掉 BOM）。

    旧实现无条件先剥 2 字节再用 `utf-16` 解，有两个后果：
        * 大端 BOM（\\xfe\\xff）会被当成小端解 → 乱码；
        * UTF-32 的 BOM 以 UTF-16 的 BOM 开头 → 被误判为 UTF-16。
    同时它也**丢掉了 BOM 这个信号**：剥完再调 sniff_encoding，判定链就看不到它了
    （UTF-16 只剩 BOM 一个判据）。

    该编码解不开时依次试 BYTE_DECODE_CANDIDATES，最后用 latin-1 + 指定 errors
    保底（forced=True）。latin-1 永不抛异常，因此本函数不会因编码失败而中断。
    """
    if isinstance(raw, str):
        return raw, "utf-8", False

    enc_manual = (override or "").strip().lower()
    manual = bool(enc_manual and enc_manual != "auto")
    if not manual:
        for sig, enc in _BOM_WIDE:
            if raw.startswith(sig):
                try:
                    return raw.decode(enc), enc, False
                except (UnicodeDecodeError, UnicodeError, LookupError):
                    break

    had_utf8_bom = raw.startswith(_UTF8_BOM)
    if had_utf8_bom:
        raw = raw[3:]

    first = "utf-8" if had_utf8_bom else sniff_encoding(raw, override)
    tried = []
    for enc in [first] + [e for e in BYTE_DECODE_CANDIDATES if e != first]:
        if enc in tried:
            continue
        tried.append(enc)
        try:
            return raw.decode(enc), enc, False
        except (UnicodeDecodeError, UnicodeError, LookupError):
            continue
    return raw.decode(DECODE_FALLBACK, errors=errors), DECODE_FALLBACK, True


def read_text_bytes(path, override=None, errors="strict"):
    """读文件 → (text, used_encoding, forced)。语义同 decode_bytes，含读盘。"""
    with open(path, "rb") as f:
        return decode_bytes(f.read(), override=override, errors=errors)


def decode_file(filepath, enc_override="auto"):
    """兼容旧签名：(text, used_encoding)。内部走 decode_bytes。"""
    text, enc, _forced = read_text_bytes(filepath, override=enc_override)
    return text, enc


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
