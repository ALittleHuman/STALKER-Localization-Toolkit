# -*- coding: utf-8 -*-
"""文本提取 App (TextExtractApp).

用途: 从 STALKER 模组的 gameplay 配置 XML 与 scripts 脚本 (.script / .ltx) 中
提取可翻译文本, 把源文件里的原文换成 string_table ID 引用, 并把原文汇总成
独立的文本 XML 交给后续流程。

用法 (Hub「文本提取」页):
    源目录   = 模组根目录(含 gameplay/ 和/或 scripts/), 也可直接指向其中某一个
               子目录; 两者都存在时**依次都处理**, 各产出一个 XML。
               两者都不存在才拒绝。
    输出目录 = 必填, 且不能与源目录相同。新文件写入 输出目录/gameplay|scripts,
               文本 XML 写在输出目录根: {prefix}_gameplay_texts.xml /
               {prefix}_scripts_texts.xml —— 源目录里有哪类就产哪类, 某一类
               未提取到文本就不产出该 XML。
               **源目录中的原文件始终只读**: ID 替换后原文不可恢复, 因此不允许
               原地覆盖输出(旧版散装工具同样要求目标目录必填)。
    「提取前清理目标目录」= 先删除 输出目录/gameplay、输出目录/scripts 与同名
               {prefix}_*_texts.xml, 再开始提取(与旧版散装工具语义一致)。

提取逻辑参考 wzyddg/stalker_auto-trans-tool_remake，
作者已在贴吧（https://tieba.baidu.com/p/7900909352）声明开源。"""
from apps._bootstrap import (
    os, re, shutil, time, Path, List, Dict, Set, Tuple, tk, ttk, filedialog, messagebox
)

from toolkit import (
    color, dir_row, tool_header, SplitPane, _make_pump, read_text_file, errbox,
    log_summary, log_detail,
    plugin_slot_bar, TaskRunner, status_style_name, stat_grid, HOST_TEXT,
    DEFAULT_ID_PREFIX, FALLBACK_ID_PREFIX, ID_PREFIX_TEMPLATE, GP_TEXTS_NAME,
    SC_TEXTS_NAME
)

# 注：该常量本应属 toolkit_textio（convert_app 尾部另有一份同名定义）；
# 此处先本地定义，消除"跨 app 隐式依赖"导致的 NameError（scripts/ltx 分支）。
SCRIPT_TRANSLATE_FUNC = "game.translate_string"

# ── 源目录类型与 ID 前缀 ──
# 处理顺序固定 gameplay → scripts（与旧版散装工具一致：两者无条件依次处理）。
# ID 前缀里的类型段必须**显式映射**：旧版是 sgtat_{prefix}_gp_{ts} /
# sgtat_{prefix}_sc_{ts}，重构版一度写成 ftype[:2]（"gameplay"[:2] == "ga"），
# 会让下游按旧 ID 建立的译文表全部失配。
_TYPE_DIRS = ("gameplay", "scripts")
_TYPE_ABBR = {"gameplay": "gp", "scripts": "sc"}

# ── 提取用正则（与 convert_app 保持一致） ──
# 俄文字母表 = U+0410..U+044F（А..Я、а..я）+ Ё(U+0401)/ё(U+0451)。
# 逐字符核对：新版 = 旧版手写串 + 'Ъ'(U+042A)，旧版没有任何新版缺的字符，
# 且旧版收了大写+小写成对，唯独漏掉大写 'Ъ'（小写 'ъ' 在）——属笔误漏字。
# 影响面很窄但方向明确：只有"西里尔字母仅含 'Ъ'"的串（如 "Ъ"、"Ъ!"、带引号的
# "Ъ" 字面量）会从"被当成 ID 跳过"变成"参与翻译"，WORD_PATTERN 也会把 'Ъ'
# 认作词字符。'Ъ' 本就是俄文字母，这是**修正**，故保留（注意：'ОБЪЕКТ' 这类
# 串在旧版也会因 О/Б/Е/К/Т 被判为文本，与本修正无关）。
RUS_LETTERS = "".join(chr(c) for c in range(0x0410, 0x0450)) + "\u0401\u0451"
RUS_LET_CPL = re.compile("[" + RUS_LETTERS + "]")
WORD_PATTERN = re.compile("[" + RUS_LETTERS + "a-zA-Z]")
SCRIPT_LINE_PERMIT_PTN = re.compile(
    r"([Mm]essage|[Tt]ext(?!ure)|(?<![a-z])[Nn]ews(?![a-z]))")
SCRIPT_LINE_SENSITIVE_PTN = re.compile(
    r"(exec|write|parse_names|load|(?<!de)script(?!ion)|call|"
    r"set(?![Tt]ext)|open|sound|effect|abort|print|console|cmd|return)")
SCRIPT_MATCH_SENSITIVE_PTN = re.compile(r'("[\s]*return)')
CFG_TAG_PTN = re.compile(
    r"<(?:text|bio|title|name)(?:| [ \S]*?[^/]) *?>([^<>]*?)</(?:text|bio|title|name)>")
CFG_ATTR_PTN = re.compile(r'(?:hint|name)\s*=\s*((?:"[^"]*")|' + r"(?:'[^']*'))")

# 本工具**自己的产物**命名：{prefix}_gameplay_texts.xml / {prefix}_scripts_texts.xml。
# 若输出目录落在源目录内部，产物就在源树里，下一次运行会被 rglob("*.xml")
# 重新当成源文件提取一遍（自我投喂：条数与 ID 逐次膨胀）。跳过它们。
# 只在扫描侧排除，不禁止"输出到源目录内"这种用法。
SELF_OUTPUT_PTN = re.compile(r"_(?:gameplay|scripts)_texts\.xml$", re.I)

def _does_text_look_like_id(text: str) -> bool:
    if len(RUS_LET_CPL.findall(text)) > 0:
        return False
    if "_" in text:
        return True
    return " " not in text


def _does_text_look_like_script(text: str) -> bool:
    if len(RUS_LET_CPL.findall(text)) > 0:
        return False
    if '=' in text or '@' in text:
        return True
    for blk in [r":\d", r"load\s+~+"]:
        if re.compile(blk).search(text):
            return True
    return False


def _get_config_xml_texts(text: str) -> Set[str]:
    # 返回 set 是既有契约（调用方按成员判断/遍历）。**遍历时**必须自行
    # 按稳定顺序排序：字符串哈希随进程随机化，直接迭代 set 会让同一份源
    # 两次运行得到不同的 ID 编号。
    candidates = []
    for m in CFG_TAG_PTN.findall(text):
        if m.strip():
            candidates.append(m.strip())
    for m in CFG_ATTR_PTN.findall(text):
        if len(m) > 2:
            candidates.append(m[1:-1])
    return set(candidates)


def _escape_literal_text(text: str, quote: str = '"') -> str:
    escaped = text.replace("\\", '\\\\').replace("\n", '\\n')
    if quote == '"':
        escaped = escaped.replace('"', '\\"')
    elif quote == "'":
        escaped = escaped.replace("'", "\\'")
    return escaped


def _get_script_texts(text: str) -> Set[str]:
    result = set()
    for line in text.split("\n"):
        line = re.sub(r'--[\s\S]*$', '', line).strip()
        is_open, ongoing, is_escape, quote_char = False, '', False, None
        line_matches = set()
        for i, ch in enumerate(line):
            if ch in ('"', "'"):
                if ch == quote_char or quote_char is None:
                    if not is_open:
                        ongoing, quote_char, is_open = ch, ch, True
                        continue
                    if is_escape:
                        ongoing += ch; is_escape = False
                    else:
                        ongoing += ch; is_open = False; quote_char = None
                        if (not SCRIPT_MATCH_SENSITIVE_PTN.search(ongoing)
                                and WORD_PATTERN.search(ongoing)):
                            line_matches.add(ongoing)
                    continue
            if is_open:
                if ch == '\\':
                    is_escape = not is_escape
                    if not is_escape: ongoing += '\\\\'
                    else: ongoing += '\\'
                elif ch == 'n' and is_escape:
                    ongoing += '\n'; is_escape = False
                else:
                    ongoing += ch
        sorted_lm = sorted(line_matches, key=len, reverse=True)
        sac_line = line
        for lm in sorted_lm:
            qc = lm[0]
            sac_line = sac_line.replace(
                qc + _escape_literal_text(lm[1:-1], quote=qc) + qc, "")
        norm = sac_line.lower()
        if SCRIPT_LINE_PERMIT_PTN.search(norm):
            result = set(sorted_lm + list(result))
        elif not SCRIPT_LINE_SENSITIVE_PTN.search(norm):
            result = set(sorted_lm + list(result))
    return result


def _replace_from_text(text: str, replacement: Dict[str, str]) -> str:
    for key in sorted(replacement, key=len, reverse=True):
        text = text.replace(key, replacement[key])
    return text


def _escape_xml_content(text: str) -> str:
    for a, b in [('&', '&amp;'), ('"', '&quot;'), ("'", '&apos;'), ('<', '&lt;')]:
        text = text.replace(a, b)
    text = text.strip()
    return text if text else '\xa0'


def _split_text_at_length(text: str, n: int) -> List[str]:
    if not text: return [""]
    return [text[i*n:(i+1)*n] for i in range(len(text)//n)] + [text[(len(text)//n)*n:]]


def _normalize_xml_string(xml_str: str, need_fix_st: bool = True,
                          delete_header: bool = True) -> str:
    if need_fix_st: delete_header = True
    if "</" in xml_str:
        while xml_str and not xml_str.startswith("<"):
            xml_str = xml_str[1:]
    xml_str = re.sub(r'&[\s]+amp;', '&amp;', xml_str)
    xml_str = re.sub(r'&[\s]+lt;', '&lt;', xml_str)
    xml_str = re.sub(
        '&(?!ensp;|emsp;|nbsp;|lt;|gt;|amp;|quot;|copy;|reg;|trade;|times;|divide;)',
        '&amp;', xml_str)
    xml_str = re.sub(r'<!--[\s\S]*?-->', '', xml_str)
    if delete_header:
        xml_str = re.sub(r'<\?[^>]+\?>', '', xml_str)
    tc = (r'A-Z_a-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF'
          r'\u0370-\u037D\u037F-\u1FFF\u200C-\u200D\u2070-\u218F'
          r'\u2C00-\u2FEF\u3001-\uD7FF\uF900-\uFDCF\uFDF0-\uFFFD')
    xml_str = re.sub(r'<(?![%s/])' % tc, '&lt;', xml_str).strip()
    if xml_str.startswith("&lt;?xml"): xml_str = "<" + xml_str[4:]
    if need_fix_st:
        if not xml_str.strip().startswith("<string_table>"):
            xml_str = "<string_table>" + xml_str + "</string_table>"
        xml_str = re.sub(r"</string_table>[\s\S]+", "</string_table>", xml_str)
    return xml_str


def _generate_text_xml(filepath: str, texts: Dict[str, str]):
    lines = ['<?xml version="1.0" encoding="utf-8"?>', '<string_table>']
    for tid, tcontent in texts.items():
        safe_id = _escape_xml_content(tid)
        safe_text = '\n'.join(
            _split_text_at_length(_escape_xml_content(tcontent), 1000))
        lines.append(f'\t<string id="{safe_id}">')
        lines.append(f'\t\t<text>{safe_text}</text>')
        lines.append('\t</string>')
    lines.append('</string_table>')
    with open(filepath, "w", encoding="utf-8") as f:
        f.write('\n'.join(lines) + '\n')


def _generate_output_file(filepath: str, text: str, encoding: str = "utf-8"):
    """按指定编码写出提取结果。**绝不自行添加 XML 声明**。

    原先这里有一个 `add_xml_header=False` 参数，能在文本开头没有 `<?xml` 时补一条
    声明。它没有任何调用点传 True（= 不可达），而且与"原先无声明的一定不能自己加
    声明"直接冲突，所以整段删掉 —— 文件有没有声明由源文件决定，工具不改这个。
    """
    with open(filepath, "w", encoding=encoding) as f:
        f.write(text)


def _parse_cfgxml(filepath: str, quiet: bool = False) -> Tuple[str, Set[str], str]:
    whole_text, success_enc = read_text_file(filepath)
    whole_text = _normalize_xml_string(whole_text, need_fix_st=False, delete_header=False)
    if not quiet:
        # 与 _parse_script / _parse_ltx 保持一致：非 quiet 时打印实际用的编码。
        # 原先漏了这一行，于是 cfg/xml 分支在输出里看不到编码，而 quiet 形参成了死参数。
        print(f"  [{success_enc}] {filepath}")
    return (whole_text, _get_config_xml_texts(whole_text), success_enc)


def _parse_script(filepath: str, quiet: bool = False) -> Tuple[str, Set[str]]:
    # 解码统一走 toolkit_textio.read_text_file（多编码尝试 + 末位 ignore 兜底）
    whole_text, enc = read_text_file(filepath)
    if not quiet:
        print(f"  [{enc}] {filepath}")
    return (whole_text, _get_script_texts(whole_text))


# ============================================================================
#  提取核心
# ============================================================================

def _parse_ltx(filepath: str, quiet: bool = False) -> Tuple[str, Set[str]]:
    """从 .ltx 脚本配置中提取可翻译文本。

    候选一律是**裸文本**（去掉外层引号后的内容），与 .script 分支的
    "带引号字面量"形态不同；替换时由 _ltx_source_literal 按 .ltx 的语法
    重建/定位要替掉的源片段（调用方负责保证产出仍是合法行）。
    """
    whole_text, enc = read_text_file(filepath)
    if not quiet:
        print(f"  [{enc}] {filepath}")
    cands = set()
    for line in whole_text.splitlines():
        line = line.split(";", 1)[0].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if not val:
            continue
        if key.startswith("inv_name") or key == "description":
            cands.add(val.strip('"\''))
        elif key in ("title", "descr"):
            # {=...} 是 "原样显示" 标记，不参与翻译
            plain = re.sub(r"\{[^}]*\}", "", val)
            for piece in plain.split(","):
                piece = piece.strip().strip('"\'')
                if piece:
                    cands.add(piece)
    return (whole_text, cands)


def _ltx_source_literal(text: str, value: str):
    """在 .ltx 源文本里定位 value，返回替换时应被**整体替掉**的源片段。

    找不到（或无法安全定位）时返回 None。
    .ltx 的值可以带引号（inv_name = "名字"）也可以裸写（inv_name = 名字），
    而替换目标是表达式 game.translate_string("<id>")——它本身不带引号，
    因此必须把**连同引号在内的整段字面量**换掉；只换中间文本会产出
    `inv_name = "game.translate_string("sgtat_x_1")"` 这种引号嵌套的坏语法。
    引号内内容与解析出的值对不上（含转义等）时不冒险替换。
    """
    for qc in ('"', "'"):
        if qc + value + qc in text:
            return qc + value + qc
    idx = text.find(value)
    if idx < 0:
        return None
    before = text[idx - 1] if idx > 0 else ""
    after = text[idx + len(value)] if idx + len(value) < len(text) else ""
    if before in ("'", '"') or after in ("'", '"'):
        return None
    return value


def _extract_gameplay(src: str, dst: str, id_prefix: str, verbose: bool = True,
                      counts_out: dict = None) -> dict:
    """提取 gameplay XML 文本 → {id: 原文}。

    counts_out: 可选的出参 dict，写入实际处理计数 {"files": 成功处理文件数,
    "chars": 提取字符数}。统计面板用它，而不是事后重扫目录——重扫会把
    解码失败被跳过的文件、以及 translated_*/text/ 排除项一起算进去。
    """
    extracted, counter, fc, cc = {}, 0, 0, 0
    sp, tp = Path(src), Path(dst)
    for f in sorted(sp.rglob("*.xml")):
        rel = f.relative_to(sp)
        if any(p.startswith("translated_") or p == "text" for p in rel.parts):
            continue
        if SELF_OUTPUT_PTN.search(f.name):
            log_detail(f"SKIP [gameplay] {rel}: 本工具自己的产物，不重复提取", "dim")
            continue
        try:
            wt, cands, enc = _parse_cfgxml(str(f), quiet=not verbose)
        except Exception as e:
            # 不静默：GUI 走 verbose=False，原先这里什么都不留，用户无从得知
            # 有文件被跳过。落「详细日志」（只落盘，不刷 GUI 日志栏）。
            log_detail(f"SKIP [gameplay] {rel}: {type(e).__name__}: {e}", "warn")
            continue
        fc += 1; repls = {}
        # 候选是 set：按稳定顺序遍历，保证同一份源两次运行得到同一套 _N 编号
        # （字符串哈希随进程随机化，直接迭代 set 会让译文与 ID 的对应漂移）。
        for c in sorted(cands):
            if not c.strip() or _does_text_look_like_id(c): continue
            eid = f"{id_prefix}_{counter}"; counter += 1; cc += len(c)
            extracted[eid] = c; repls[c] = eid
            if verbose: print(".", end="", flush=True)
        out = tp / rel; out.parent.mkdir(parents=True, exist_ok=True)
        _generate_output_file(str(out),
                              _replace_from_text(wt, repls) if repls else wt,
                              encoding=enc)
        # 逐文件过程写「详细日志」（只落盘，不刷 GUI 日志栏）——几千个文件时
        # GUI 只保留开始/完成/错误，细节在 runtime 日志里可查。
        log_detail(f"  [gameplay] {rel} | {len(repls)} 条 | {enc}")
    if counts_out is not None:
        counts_out["files"] = fc; counts_out["chars"] = cc
    return extracted


def _extract_scripts(src: str, dst: str, id_prefix: str, verbose: bool = True,
                     counts_out: dict = None) -> dict:
    """提取 .script/.ltx 文本 → {id: 原文}；counts_out 语义同 _extract_gameplay。"""
    extracted, counter, fc, cc = {}, 0, 0, 0
    sp, tp = Path(src), Path(dst)
    files = sorted(list(sp.rglob("*.script")) + list(sp.rglob("*.ltx")))
    for f in files:
        rel = f.relative_to(sp)
        if any(p.startswith("translated_") for p in rel.parts): continue
        is_ltx = f.suffix.lower() == ".ltx"
        try:
            if is_ltx:
                wt, cands = _parse_ltx(str(f), quiet=not verbose)
            else:
                wt, cands = _parse_script(str(f), quiet=not verbose)
        except Exception as e:
            log_detail(f"SKIP [scripts] {rel}: {type(e).__name__}: {e}", "warn")
            continue
        fc += 1; repls = {}
        if is_ltx:
            # .ltx 候选是裸文本：按 .ltx 语法定位整段（含引号）字面量再替换，
            # 保证产出仍是合法行（见 _ltx_source_literal）。
            for c in sorted(cands):
                if not c.strip() or _does_text_look_like_id(c) or _does_text_look_like_script(c): continue
                old = _ltx_source_literal(wt, c)
                if old is None:
                    log_detail(f"SKIP [ltx] {rel}: 无法安全定位字面量 {c!r}", "warn")
                    continue
                eid = f"{id_prefix}_{counter}"; counter += 1; cc += len(c)
                extracted[eid] = c
                repls[old] = f'{SCRIPT_TRANSLATE_FUNC}("{eid}")'
                if verbose: print(".", end="", flush=True)
        else:
            # .script 候选本身就是带引号的字面量，key 用同一种形态。
            for cq in sorted(cands):
                qc = cq[0]; c = cq[1:-1]
                if _does_text_look_like_id(c) or _does_text_look_like_script(c): continue
                eid = f"{id_prefix}_{counter}"; counter += 1; cc += len(c)
                extracted[eid] = c
                old = qc + _escape_literal_text(c, quote=qc) + qc
                repls[old] = f'{SCRIPT_TRANSLATE_FUNC}("{eid}")'
                if verbose: print(".", end="", flush=True)
        out = tp / rel; out.parent.mkdir(parents=True, exist_ok=True)
        _generate_output_file(str(out),
                              _replace_from_text(wt, repls) if repls else wt)
        log_detail(f"  [scripts] {rel} | {len(repls)} 条")
    if counts_out is not None:
        counts_out["files"] = fc; counts_out["chars"] = cc
    return extracted


def _resolve_source_types(source: str) -> List[str]:
    """源目录 → 待处理的类型列表（顺序固定 gameplay → scripts）。

    源目录本身是 gameplay/scripts 时只处理该类型；否则处理其中存在的**所有**
    类型——完整模组源目录同时含 gameplay/ 与 scripts/ 是常态，旧版散装工具就是
    无条件依次处理两者、一次产出两个 XML（重构版曾误改成二选一，且两者都在时
    直接拒绝，属功能回归）。两者都不存在才拒绝。
    """
    base = os.path.basename(source).lower()
    if base in _TYPE_DIRS:
        return [base]
    subs = [t for t in _TYPE_DIRS if os.path.isdir(os.path.join(source, t))]
    if not subs:
        raise ValueError("源目录中未找到 gameplay 或 scripts 子目录")
    return subs


def _plan_output_dirs(source: str, target: str, types: List[str]) -> List[Tuple[str, str, str]]:
    """→ [(类型, 源子目录, 目标子目录)]；目标子目录撞上源子目录时拒绝。

    数据安全：撞上就是原地覆盖源文件（ID 替换后原文不可恢复）。
    空输出目录（由调用方拦下）与"输出目录 = 源目录"、"源目录是一个
    gameplay/scripts 子目录而输出目录是它的父目录"两条路径都由此兜住。
    """
    source = os.path.abspath(source)
    target = os.path.abspath(target)
    base = os.path.basename(source).lower()
    plan = []
    for t in types:
        src_sub = source if base == t else os.path.join(source, t)
        dst_sub = os.path.join(target, t)
        if os.path.normcase(os.path.abspath(src_sub)) == \
                os.path.normcase(os.path.abspath(dst_sub)):
            raise ValueError(
                "输出目录会覆盖源目录中的原文件（且不可恢复），请另选输出目录")
        plan.append((t, src_sub, dst_sub))
    return plan


def _split_drop_paths(root, event) -> List[str]:
    """tkdnd 的 event.data → 路径列表。

    数据形如 `{C:\\a b} {C:\\c}`（含空格时带花括号）或裸路径；tk 的 splitlist
    是官方解析方式，它不可用时退回朴素的去括号切分。
    """
    data = str(getattr(event, "data", "") or "").strip()
    if not data:
        return []
    try:
        items = list(root.tk.splitlist(data))
    except Exception:
        items = [data.strip("{}")]
    return [p for p in (str(i).strip().strip("{}").strip() for i in items) if p]


def run_extraction(source: str, target: str = "", prefix: str = FALLBACK_ID_PREFIX,
                   clean: bool = False, log_callback=None) -> dict:
    """提取文本，产出处理后的源文件 + 独立的文本 XML。

    源目录里 gameplay/ 与 scripts/ **有哪类就处理哪类**（都有就都处理），
    两者都没有才拒绝。target 必填且不能与源目录相同：新文件写入
    target/gameplay|scripts，文本 XML 写在 target 根；源目录始终只读。
    clean=True 时先删除 target 下的 gameplay/scripts 与 {prefix}_*_texts.xml。
    """
    def log(msg):
        if log_callback: log_callback(msg)

    source = os.path.abspath(source)
    if not os.path.isdir(source):
        raise FileNotFoundError(f"Source not found: {source}")
    if not target:
        raise ValueError(
            "请指定输出目录：改写后的源文件与文本 XML 都写入输出目录，"
            "源目录中的原文件不会被覆盖（原地覆盖后原文不可恢复，故不支持）")
    target = os.path.abspath(target)
    plan = _plan_output_dirs(source, target, _resolve_source_types(source))

    if clean:
        # 旧版语义：先清掉目标目录里的旧输出再提取（目标目录已确认不是源目录，
        # 所以这里不会删到源文件）。
        for t in _TYPE_DIRS:
            p = os.path.join(target, t)
            if os.path.isdir(p):
                shutil.rmtree(p)
            elif os.path.exists(p):
                os.remove(p)
        for name in (GP_TEXTS_NAME.format(prefix=prefix),
                     SC_TEXTS_NAME.format(prefix=prefix)):
            p = os.path.join(target, name)
            if os.path.exists(p):
                os.remove(p)
        log("已清理目标目录中的旧输出。")
    os.makedirs(target, exist_ok=True)

    ts = int(time.time())
    stats = {"gp_files": 0, "gp_strings": 0, "gp_chars": 0,
             "sc_files": 0, "sc_strings": 0, "sc_chars": 0,
             "outputs": []}

    for ftype, src_sub, dst_sub in plan:
        # 槽位名是 {abbr}：传进去的是**缩写**（gp/sc），不是 ftype 全名。
        # 产出形状与 1.0.0 发行版一致：sgtat_gs_gp_1234。
        id_pre = ID_PREFIX_TEMPLATE.format(
            prefix=prefix, abbr=_TYPE_ABBR[ftype], ts=ts)
        log(f"ID 前缀 ({ftype}): {id_pre}")
        counts = {}
        if ftype == "gameplay":
            log("提取 gameplay 配置文本...")
            texts = _extract_gameplay(src_sub, dst_sub, id_pre,
                                      verbose=False, counts_out=counts)
            stats["gp_files"] = counts.get("files", 0)
            stats["gp_strings"] = len(texts)
            stats["gp_chars"] = counts.get("chars", 0)
            name = GP_TEXTS_NAME.format(prefix=prefix)
        else:
            log("提取 scripts 脚本文本...")
            texts = _extract_scripts(src_sub, dst_sub, id_pre,
                                     verbose=False, counts_out=counts)
            stats["sc_files"] = counts.get("files", 0)
            stats["sc_strings"] = len(texts)
            stats["sc_chars"] = counts.get("chars", 0)
            name = SC_TEXTS_NAME.format(prefix=prefix)
        if texts:
            _generate_text_xml(os.path.join(target, name), texts)
            stats["outputs"].append(name)
            log(f"  {ftype}: {len(texts)} 条 → {name}")
        else:
            log(f"  {ftype}: 未提取到可翻译文本（未产出 {name}）")

    stats["total"] = stats["gp_strings"] + stats["sc_strings"]
    stats["total_chars"] = stats["gp_chars"] + stats["sc_chars"]
    stats["target"] = target
    log(f"完成。总计 {stats['total']} 条文本（{stats['total_chars']:,} 字符）。")
    return stats


# ============================================================================
#  GUI — VS Code Dark+ 风格
# ============================================================================



class TextExtractApp:
    """文本提取。

    统一契约：只接收宿主 Tab（parent）——不自建根窗口、不应用主题、不自建日志面板；
    日志走全局两级通道（log_summary / log_detail）。
    """

    def __init__(self, parent):
        self.root = parent
        self.root.configure(bg=color("bg"))
        self.source_path = tk.StringVar()
        self.target_path = tk.StringVar()
        self.prefix_var = tk.StringVar(value=DEFAULT_ID_PREFIX)
        # 提取前清理目标目录（旧版散装工具有此复选框，与 extract 的 clean 参数对应）
        self.clean_var = tk.BooleanVar(value=True)
        self._ui = _make_pump(self.root)
        self._build_ui()
        # 统一任务壳（忙碌标志 / 进度 / 状态文案 / 线程）
        self.task = TaskRunner(
            self.root, self._ui,
            on_busy=lambda busy: self.extract_btn.config(
                state=tk.DISABLED if busy else tk.NORMAL,
                text="提取中..." if busy else "▶  提取文本"),
            status_setter=lambda text, kind="idle": self.status_lbl.config(
                text=text, style=status_style_name(kind)),
            progress_started=self.progress.start,
            progress_stopped=self.progress.stop,
        )
        # 拖拽由 dir_row 的 drop 回调承载（_on_drop_source / _on_drop_target）。
        # 原先这里还有 self._setup_drag_drop()，但它 `import tkinterDnD`（模块名
        # 拼错，正确名为 tkinterdnd2）必然 ImportError 且被吞掉，root 级拖拽
        # 从未生效——已删除该死分支。

    def _drop_dir(self, event, var, field: str):
        """拖拽文件夹到目录框；不是文件夹/一次拖了多个时给提示，不静默忽略。"""
        paths = _split_drop_paths(self.root, event)
        if not paths:
            return
        if len(paths) > 1:
            log_summary(f"一次只能拖入一个文件夹（收到 {len(paths)} 个），已忽略。", "warn")
            return
        p = paths[0]
        if os.path.isdir(p):
            var.set(os.path.normpath(p))
        else:
            log_summary(f"拖入的“{os.path.basename(p) or p}”不是文件夹，{field}未改变。", "warn")

    def _on_drop_source(self, event):
        """拖拽文件夹到源目录框."""
        self._drop_dir(event, self.source_path, "源目录")

    def _on_drop_target(self, event):
        """拖拽文件夹到输出目录框."""
        self._drop_dir(event, self.target_path, "输出目录")

    def _build_dir_row(self, parent, label_text, var, browse_cmd, drop_cmd=None):
        """统一目录行 (toolkit.dir_row): 标签 + 输入框(边框) + 浏览 + 拖拽."""
        ttk.Label(parent, text=label_text).pack(anchor=tk.W)
        dir_row(parent, "", var, browse=browse_cmd, width=0, drop=drop_cmd)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        # ═══ 可调分区: 上部操作区 / 下部日志统计区 ═══
        self._paned = SplitPane(main, orient=tk.VERTICAL)
        self._paned.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        upper = ttk.Frame(self._paned)
        lower = ttk.Frame(self._paned)
        self._paned.add(upper, weight=3)
        self._paned.add(lower, weight=1)

        tr = ttk.Frame(upper); tr.pack(fill=tk.X, pady=(0, 10))
        tool_header(tr, "STALKER 文本提取", side=tk.LEFT, padx=0, pady=0)
        # 插件动作区（toolbar 槽；无插件注册时不创建任何控件）
        self._slot_bar = plugin_slot_bar(upper, HOST_TEXT, app=self,
                                         context={"has_results": False})
        ttk.Label(tr, text="cfgxml + script + ltx  ·  纯提取",
                  style="Dim.TLabel").pack(side=tk.RIGHT)

        self._build_dir_row(upper, "源目录（含 gameplay/ 和/或 scripts/，两者都有则都处理）",
                            self.source_path, lambda: self._browse(self.source_path),
                            self._on_drop_source)
        self._build_dir_row(upper, "输出目录（必填，不能与源目录相同；源目录只读不修改）",
                            self.target_path, lambda: self._browse(self.target_path),
                            self._on_drop_target)

        or_ = ttk.Frame(upper); or_.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(or_, text="前缀").pack(side=tk.LEFT)
        ttk.Entry(or_, textvariable=self.prefix_var, width=8).pack(side=tk.LEFT, padx=(4, 16))
        tk.Checkbutton(or_, text="提取前清理目标目录",
                       variable=self.clean_var).pack(side=tk.LEFT, padx=(0, 16))
        # 原有一行输出文件名说明（"{prefix}_gameplay_texts.xml / ...（有哪类产哪类）"），
        # 按用户要求删除：文件名在提取完成后会写进日志与统计，界面上不必常驻。

        br = ttk.Frame(upper); br.pack(fill=tk.X, pady=(0, 4))
        self.extract_btn = ttk.Button(br, text="▶  提取文本", style="Accent.TButton",
                                       command=self._start)
        self.extract_btn.pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(upper, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(0, 8))

        ttk.Separator(lower, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        # 日志面板由 Hub 统一提供，工具内不再自建（tag 直接用 Hub 原生标签）

        self.stats_frame = ttk.LabelFrame(lower, text=" 统计 ", padding=12)
        self.stats_frame.pack(fill=tk.X, pady=(8, 0))
        # 统一统计网格（原先这里是手搭的 for + setattr）
        _stats = stat_grid(self.stats_frame, [
            ("gameplay", "gp_stat", "gp_detail"),
            ("scripts", "sc_stat", "sc_detail"),
            ("总计", "total_stat", "total_detail"),
        ])
        for _attr, _lbl in _stats.items():
            setattr(self, _attr, _lbl)

        st = ttk.Frame(main); st.pack(fill=tk.X, pady=(6, 0))
        self.status_lbl = ttk.Label(st, text="就绪", style=status_style_name("idle"))
        self.status_lbl.pack(side=tk.LEFT)
        ttk.Label(st, text="提取后交由「汉化包生成」打包，或导入翻译工具",
                  style="Dim.TLabel").pack(side=tk.RIGHT)

    def _browse(self, var):
        p = filedialog.askdirectory()
        if p: var.set(os.path.normpath(p))

    def _set_stats(self, placeholder: str, detail: str = ""):
        """统计栏统一写入（开始置 '…'，失败复位回 '—'）。"""
        for attr in ("gp_stat", "sc_stat", "total_stat"):
            getattr(self, attr).config(text=placeholder)
        for attr in ("gp_detail", "sc_detail", "total_detail"):
            getattr(self, attr).config(text=detail)

    def _start(self):
        src = self.source_path.get().strip()
        dst = self.target_path.get().strip()
        pfx = self.prefix_var.get().strip() or FALLBACK_ID_PREFIX
        # 变量一律在主线程读好再交给工作线程（工作线程不碰 Tk）
        clean = bool(self.clean_var.get())
        if not src: messagebox.showwarning("提示", "请指定源目录"); return
        if not os.path.isdir(src):
            errbox("错误", f"源目录不存在：\n{src}"); return
        if not dst:
            # 长解释已按用户要求删除，只留与上面"请指定源目录"一致的短提示 ——
            # **不能整条删掉**：那样点「提取文本」会静默无反应，用户会以为程序坏了。
            messagebox.showwarning("提示", "请指定输出目录")
            return
        try:
            types = _resolve_source_types(src)
        except ValueError as e:
            messagebox.showwarning("提示", f"{e}。"); return
        try:
            _plan_output_dirs(src, dst, types)
        except ValueError as e:
            errbox("错误", str(e)); return
        if self.task.running: return
        self._set_stats("...")
        log_summary("═══ 开始提取 ═══", "dim")
        log_summary(f"源: {src}")
        log_summary(f"输出: {dst}")
        log_summary(f"处理类型: {' + '.join(types)}")
        log_summary(f"前缀: {pfx}　清理目标目录: {'是' if clean else '否'}")
        log_summary("")

        def work():
            # 异常交给 TaskRunner 的 on_error 处理（写日志 + 置失败状态），不在此吞掉
            sts = run_extraction(src, dst, pfx, clean, log_callback=log_summary)
            self._ui(self._on_stats, sts)

        # 状态只由一个主线程回调写入（业务回调 _on_stats / 失败回调 _on_extract_error），
        # 不传 final_status，避免两个回调对同一状态重复写入。
        self.task.run(work, status="正在提取...",
                      on_error=self._on_extract_error)

    def _on_extract_error(self, e):
        log_summary(f"✕ 错误: {e}", "err")
        # 失败也要复位统计栏：否则它永远停在开始时的 "…"，与「提取失败」自相矛盾。
        self._set_stats("—")
        self.task.set_status("提取失败", "err")

    def _on_stats(self, stats):
        """业务结果回显（统计与产物路径）；任务壳状态由 TaskRunner 负责。"""
        log_summary("", "dim"); log_summary("═══ 完成 ═══", "ok")
        self.gp_stat.config(text=str(stats["gp_strings"]))
        self.gp_detail.config(text=f"{stats['gp_files']} 文件 · {stats['gp_chars']:,} 字符")
        self.sc_stat.config(text=str(stats["sc_strings"]))
        self.sc_detail.config(text=f"{stats['sc_files']} 文件 · {stats['sc_chars']:,} 字符")
        self.total_stat.config(text=str(stats["total"]))
        self.total_detail.config(text=f"{stats['total_chars']:,} 字符")
        log_summary(f"产物目录: {stats['target']}", "ok")
        outputs = stats.get("outputs") or []
        if outputs:
            # 只列实际写出的文件（原先无条件列两个名字，而实际可能只产出一个）
            for name in outputs:
                log_summary(f"  {name}", "ok")
        else:
            log_summary("  未提取到可翻译文本，没有产出文本 XML", "warn")
        self.task.set_status(f"完成 · {stats['total']} 条文本", "ok")
        # 出结果后重算 toolbar 槽位：带 when 的插件命令据此出现
        slot = getattr(self, "_slot_bar", None)
        if slot is not None:
            slot._context = {"has_results": True}
            slot.refresh()
