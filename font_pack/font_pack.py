# -*- coding: utf-8 -*-
"""
汉化包生成引擎 — CN_Pack_Generator 的 Python 重写
功能: 从汉化 XML 提取字符集 → 渲染字库纹理(DDS) → 组装 gamedata 汉化包
依赖: Pillow (缺失时自动安装)
"""
import os, sys, struct, unicodedata

# ─── 游戏版本配置 ───
GAMES = {
    "SoC":  {"cfg_dir": "config",  "dds": "8888"},
    "ClS": {"cfg_dir": "configs", "dds": "8888"},
    "CoP":  {"cfg_dir": "configs", "dds": "A8"},
}

# ─── 字号表: (字号, 是否超采样x2) ───
SIZES = [(11, 0), (13, 0), (15, 0), (16, 1), (17, 1), (18, 1),
         (20, 1), (21, 1), (23, 1), (25, 1)]

# 强制方块字符 (EAW 为 A 但中文语境全角, 原版按字号+1)
FORCED_FULLWIDTH = set("\u201c\u201d\u2018\u2019\u2014\u2016")  # “ ” ‘ ’ — ‖


# 原版 FontGen (GDI) 的 cell 高表 (ini height= 值, 与 FreeType metrics 不同)
CELL_HEIGHTS = {11: 20, 13: 22, 15: 23, 16: 25, 17: 26, 18: 29, 20: 31, 21: 32, 23: 33, 25: 35}

# 当前环境原版 FontGen 的方块字符宽 (汉字/全角标点, 查表避免字体 advance 差异)
BLOCK_WIDTHS = {11: 17, 13: 18, 15: 19, 16: 21, 17: 22, 18: 24, 20: 26, 21: 27, 23: 29, 25: 31}

# FontGen 内置字符集中的生僻汉字 (原版 Char.txt 编码 bug 丢失后由内置集补充)
FONTGEN_EXTRA = set("屑懈挟衼袗袘袙袚袛袝袞袟袠袡袣袥袦袧袨袩袪褉褋褌褍褎褏褑褔褕褖褗褘褜褝褞褟褢")

# 原版 CharAdder 编码 bug 丢失的西里尔 (严格兼容模式下剔除, 保证与原版整包一致)
LOST_CYRILLIC = set("ГЙФХЦЧШЩЭЮбвгдежзийклмнопрстуфхцчшщъыьэю")

def _load_adv_tables():
    """从同目录 adv_tables.json 读取各字号的字符宽度表。"""
    import json as _json
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adv_tables.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = _json.load(f)
    except Exception as e:
        raise RuntimeError(f"无法加载字体宽度表 {path}: {e}")
    return {int(size): {int(cp): w for cp, w in table.items()}
            for size, table in raw.items()}


ADV_TABLES = _load_adv_tables()


# ASCII + 俄语基础字符 (对应原 _ascii_char.txt)
ASCII_CHARS = (' !"#$%&\'()*+,-./0123456789:;<=>?@'
               'ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`'
               'abcdefghijklmnopqrstuvwxyz{|}~'
               'АаБбВвГгДдЕеЁёЖжЗзИиЙйКкЛлМмНнОоПпРрСсТтУуФфХхЦцЧчШшЩщъЫыьЭэЮюЯя')

TEX_W = 1024  # 字库纹理宽 (放不下自动 2048)
GAP = 3       # 字符间水平间隙 (原版 FontGen 布局规律)

# ─── fonts.ltx 模板 ───
FONTS_LTX = {
"SoC": """[stat_font]
shader 			= font
texture			= ui\\ui_font_hud_01
interval		= 0.75,1

[hud_font_small]:stat_font

[hud_font_medium]
shader 			= font
texture			= ui\\ui_font_hud_02

[hud_font_di]
shader 			= font
texture			= ui\\ui_font_console_02

[ui_font_arial_14]
shader			= font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_13

;not used
[ui_font_arial_21]
shader			= font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_13
texture1600		= ui\\ui_font_17

[ui_font_graffiti19_russian]
shader			= font
texture			= ui\\ui_font_16
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_17

[ui_font_graffiti22_russian]
shader			= font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_16
texture1600		= ui\\ui_font_20

[ui_font_graff_32]
shader			= font
texture			= ui\\ui_font_18
texture800		= ui\\ui_font_17
texture1600		= ui\\ui_font_21

;not used
[ui_font_graff_40]
shader			= font
texture			= ui\\ui_font_21
texture800		= ui\\ui_font_18
texture1600		= ui\\ui_font_23

[ui_font_graff_50]
shader			= font
texture			= ui\\ui_font_23
texture800		= ui\\ui_font_21
texture1600		= ui\\ui_font_25

[ui_font_letterica16_russian]
shader			= font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_15

[ui_font_letterica18_russian]
shader			= font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_16

[ui_font_letter_25]
shader			= font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_20

""",
"ClS": """[stat_font]
shader 			= font
texture			= ui\\ui_font_hud_01
interval		= 0.75,1

[hud_font_small]:stat_font

[hud_font_medium]
shader 			= font
texture		= ui\\ui_font_hud_02

[hud_font_di]
shader 			= font
texture			= ui\\ui_font_console_02

[hud_font_di2]
shader 			= hud\\font2
texture			= ui\\ui_font_console_02

[ui_font_arial_14]
shader			= font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_13

;not used
[ui_font_arial_21]
shader			= font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_13
texture1600		= ui\\ui_font_17

[ui_font_graffiti19_russian]
shader			= font
texture			= ui\\ui_font_16
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_17

[ui_font_graffiti22_russian]
shader		= font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_16
texture1600		= ui\\ui_font_20

[ui_font_graff_32]
shader			= font
texture			= ui\\ui_font_18
texture800		= ui\\ui_font_17
texture1600		= ui\\ui_font_21

;not used
[ui_font_graff_40]
shader			= font
texture			= ui\\ui_font_21
texture800		= ui\\ui_font_18
texture1600		= ui\\ui_font_23

[ui_font_graff_50]
shader			= font
texture			= ui\\ui_font_23
texture800		= ui\\ui_font_21
texture1600		= ui\\ui_font_25

[ui_font_letterica16_russian]
shader			= font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
;texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_15

[ui_font_letterica18_russian]
shader			= font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_16

[ui_font_letter_25]
shader			= font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_20

""",
"CoP": """[stat_font]
shader 			= font
texture			= ui\\ui_font_hud_01
interval		= 0.75,1

[hud_font_small]:stat_font

[hud_font_medium]
shader 			= font
texture			= ui\\ui_font_hud_02

[hud_font_di]
shader 			= hud\\font
texture			= ui\\ui_font_console_02

[hud_font_di2]
shader 			= hud\\font2
texture			= ui\\ui_font_console_02

[ui_font_arial_14]
shader			= hud\\font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_13

;not used
[ui_font_arial_21]
shader			= hud\\font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_13
texture1600		= ui\\ui_font_17

[ui_font_graffiti19_russian]
shader			= hud\\font
texture			= ui\\ui_font_16
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_17

[ui_font_graffiti22_russian]
shader			= hud\\font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_16
texture1600		= ui\\ui_font_20

[ui_font_graff_32]
shader			= hud\\font
texture			= ui\\ui_font_18
texture800		= ui\\ui_font_17
texture1600		= ui\\ui_font_21

;not used
[ui_font_graff_40]
shader			= hud\\font
texture			= ui\\ui_font_21
texture800		= ui\\ui_font_18
texture1600		= ui\\ui_font_23

[ui_font_graff_50]
shader			= hud\\font
texture			= ui\\ui_font_23
texture800		= ui\\ui_font_21
texture1600		= ui\\ui_font_25

[ui_font_letterica16_russian]
shader			= hud\\font
texture			= ui\\ui_font_11
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_15

[ui_font_letterica18_russian]
shader			= hud\\font
texture			= ui\\ui_font_15
texture800		= ui\\ui_font_11
texture1600		= ui\\ui_font_16

[ui_font_letter_25]
shader			= hud\\font
texture			= ui\\ui_font_17
texture800		= ui\\ui_font_15
texture1600		= ui\\ui_font_20
""",
}

LOCALIZATION_LTX = {
"SoC": """[string_table]
language\t= #LANG#
font_prefix\t= _#LANG#
files = ui_st_pda, ui_st_mm_mp, ui_st_inventory, string_table_tutorial, string_table_general, string_table_includes, stable_dialog_manager, stable_dialog_manager_uni, stable_task_manager, stable_treasure_manager, string_table_level_tips, string_table_items, string_table_ui, string_table_enc_zone, string_table_outfit, stable_dialogs, stable_dialogs_escape, stable_dialogs_garbage, stable_dialogs_agroprom, stable_dialogs_deadcity, stable_dialogs_darkvalley, stable_dialogs_pripyat, stable_dialogs_labx18, stable_dialogs_bar, stable_dialogs_military, stable_dialogs_yantar, stable_dialogs_radar, stable_dialogs_aes, mp_st_speechmenu, ui_st_keybinding, ui_mp_teamdesc, ui_st_mm, stable_stories, ui_st_mapdesc, string_table_enc_social, string_table_enc_mutants, string_table_enc_weapons, string_table_enc_equipment, ui_st_mp, ui_st_other, stable_game_credits
""",
"ClS": """[string_table]
language        = #LANG#
font_prefix     = _#LANG#
""",
"CoP": """[string_table]
language        = #LANG#
font_prefix     = _#LANG#
""",
}


def ensure_pillow():
    """Pillow 缺失时自动安装."""
    try:
        from PIL import Image  # noqa
        return True
    except ImportError:
        try:
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "pillow"],
                           capture_output=True, timeout=180,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            from PIL import Image  # noqa
            return True
        except Exception:
            return False


def extract_chars(xml_dir, full_cyrillic=True):
    """扫描 xmlfiles 目录, 提取所有文本字符, 返回去重字符表.
    full_cyrillic=False 时剔除原版丢失的西里尔 (严格兼容原版).
    文本解析复用 toolkit.parse_xml_texts (无 toolkit 时自包含回退)."""
    import re
    try:
        import toolkit
        _parse_xml = toolkit.parse_xml_texts
    except ImportError:
        _parse_xml = _local_parse_xml_texts
    chars = set(ASCII_CHARS)
    if not os.path.isdir(xml_dir):
        return None
    for fn in sorted(os.listdir(xml_dir)):
        if not fn.lower().endswith(".xml"):
            continue
        fp = os.path.join(xml_dir, fn)
        try:
            raw = open(fp, "rb").read().decode("utf-8-sig", "ignore")
            texts = _parse_xml(raw)
        except Exception:
            continue
        for t in texts:
            for ch in t:
                if ch in "\r\n":
                    continue
                cp = ord(ch)
                if cp < 0x20 and ch != "\t":
                    continue
                if 0xD800 <= cp <= 0xDFFF:
                    continue
                chars.add(ch)
    chars |= FONTGEN_EXTRA
    if not full_cyrillic:
        chars -= LOST_CYRILLIC
    return "".join(sorted(chars))


def _local_parse_xml_texts(text):
    """自包含回退: ET 优先, 正则回退 (与 toolkit.parse_xml_texts 相同)."""
    import re as _re
    import xml.etree.ElementTree as ET
    try:
        return list(ET.fromstring(text).itertext())
    except Exception:
        strip = _re.compile(r"<[^>]+>")
        out = []
        for m in _re.finditer(r"<text[^>]*>(.*?)</text>", text, _re.S):
            out.append(strip.sub("", m.group(1)))
        for m in _re.finditer(r"<string[^>]*>(.*?)</string>", text, _re.S):
            out.append(strip.sub("", m.group(1)))
        return out


def write_dds(path, w, h, fmt, data):
    """写 DDS. fmt: '8888' = 32bpp BGRA, 'A8' = 8bpp alpha."""
    if fmt == "8888":
        pitch = w * 4
        pf = struct.pack("<8I", 32, 0x41, 0, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
        flags = 0x1007
    else:
        pitch = w
        pf = struct.pack("<8I", 32, 0x2, 0, 8, 0, 0, 0, 0xFF)
        flags = 0x1007
    hdr = (b"DDS " + struct.pack("<7I", 124, flags, h, w, pitch, 0, 0) +
           b"\0" * 44 + pf + struct.pack("<I", 0x1000) + b"\0" * 16)
    with open(path, "wb") as f:
        f.write(hdr + data)


def render_font(chars, font_path, size, x2, fmt):
    """渲染一个字库: 返回 (dds_bytes, ini_text, tex_w, tex_h, max_y).
    布局 = 原版 FontGen 网格: 槽宽=cell高, 每行槽数=tex_w//槽宽,
    字符在槽内水平居中 (x1 = col*槽宽 + (槽宽-字符宽)//2).
    宽: 1024 若行数*cell 放得下, 否则 2048. 高: 2 幂 ≥ (max_y-1)."""
    from PIL import Image, ImageFont
    S = 2 if x2 else 1
    font = ImageFont.truetype(font_path, size * S)
    cell_h = CELL_HEIGHTS.get(size, size + 4)  # 槽宽 = cell 高
    adv_table = ADV_TABLES.get(size, {})

    def widths_of(ch):
        cp = ord(ch)
        if cp in adv_table:
            return adv_table[cp]
        if unicodedata.east_asian_width(ch) in "FW" or ch in FORCED_FULLWIDTH:
            return BLOCK_WIDTHS.get(size, size + 2)
        adv = font.getlength(ch) / S
        return max(1, round(adv) + 1)

    # 先确定画布宽: 1024 → 2048 → 4096，保证大字号/大字符集放得下
    tex_w = 1024
    slots = tex_w // cell_h
    rows_n = (len(chars) + slots - 1) // slots
    for candidate in (2048, 4096):
        if rows_n * cell_h - 1 <= tex_w:
            break
        tex_w = candidate
        slots = tex_w // cell_h
        rows_n = (len(chars) + slots - 1) // slots
    if rows_n * cell_h - 1 > tex_w:
        raise RuntimeError(f"字库 {tex_w} 宽放不下 {len(chars)} 字符")

    # 布局 + 渲染
    max_y = rows_n * cell_h
    need = max(1, max_y - 1)
    tex_h = 16
    while tex_h < need:
        tex_h *= 2
    canvas = Image.new("L", (tex_w, tex_h), 0)
    ini = []
    for i, ch in enumerate(chars):
        rw = widths_of(ch)
        col = i % slots
        row = i // slots
        x = col * cell_h + (cell_h - rw) // 2
        y = row * cell_h
        bbox = font.getbbox(ch)
        mask = font.getmask(ch, mode="L")
        mb = mask.getbbox()
        if mb is not None:
            gw = (mb[2] - mb[0]) // S
            gh = (mb[3] - mb[1]) // S
            if gw >= 1 and gh >= 1:
                glyph = Image.frombytes("L", mask.size, bytes(mask)).crop(mb)
                if S > 1:
                    glyph = glyph.resize((gw, gh), Image.LANCZOS)
                top = bbox[1] // S
                left = bbox[0] // S
                # 全部使用字体自然位置（与最初一致），整体略微下移，
                # 避免采样框顶部扫到上一行字形的底边。
                draw_x = x + left
                draw_y = y + top - 2
                canvas.paste(glyph, (draw_x, draw_y))
        ini.append(f"{ord(ch):05d}= {x}, {y}, {x + rw}, {y + cell_h}")

    # 转像素
    px = canvas.tobytes()  # L 8bit
    if fmt == "8888":
        out = bytearray()
        for v in px:
            out += bytes((v, v, v, v))
        data = bytes(out)
    else:
        data = px
    ini = "[mb_symbol_coords]\nheight={}\n".format(cell_h) + "\n".join(ini) + "\n"
    return data, ini, tex_w, tex_h, max_y


def build_package(game, lang, xml_dir, font_path, out_dir,
                  offset=0, suffix="", full_cyrillic=True, log=None):
    """生成完整汉化包 gamedata/.
    lang: 加载语言, 决定 config(s)/text/{lang}/ 目录与 localization.ltx language.
    suffix: 字体文件后缀 (如 _chs), 默认空 = ui_font_11.dds; 同步到 font_prefix.
    offset: 尺寸档位, 渲染字号 = 标准字号 + offset (文件名/ltx 保持标准名).
    full_cyrillic: 保留完整西里尔 (默认 False = 严格兼容原版)."""
    def L(msg):
        if log: log(msg)

    if game not in GAMES:
        raise RuntimeError(f"未知游戏版本: {game}")
    if not ensure_pillow():
        raise RuntimeError("Pillow 安装失败, 无法渲染字体")
    chars = extract_chars(xml_dir, full_cyrillic=full_cyrillic)
    if not chars:
        raise RuntimeError("xmlfiles 目录为空或没有 XML 文件")
    L(f"字符集: {len(chars)} 字符 (含 ASCII/俄语基础)" + ("" if full_cyrillic else ", 严格兼容原版"))

    cfg_dir = GAMES[game]["cfg_dir"]
    fmt = GAMES[game]["dds"]

    # 目标目录
    out_gd = os.path.join(out_dir, "gamedata")
    tex_dir = os.path.join(out_gd, "textures", "ui")
    text_dir = os.path.join(out_gd, cfg_dir, "text", lang)
    os.makedirs(tex_dir, exist_ok=True)
    os.makedirs(text_dir, exist_ok=True)

    # 字库 (整套 10 字号)
    for size, x2 in SIZES:
        rsize = size + offset  # 实际渲染字号
        L(f"渲染字号 {rsize} ({'x2' if x2 else '原生'})...")
        data, ini, tex_w, tex_h, max_y = render_font(chars, font_path, rsize, x2, fmt)
        base = os.path.join(tex_dir, f"ui_font_{size}{suffix}")
        write_dds(base + ".dds", tex_w, tex_h, fmt, data)
        with open(base + ".ini", "w", encoding="ascii") as f:
            f.write(ini)
        L(f"  ui_font_{size}{suffix}.dds ({tex_w}x{tex_h}, 占用 {max_y}px 高)")

    # XML: 统一转为无 BOM UTF-8（汉化包内 XML 一律 utf-8）
    import re as _re
    n = 0
    for fn in sorted(os.listdir(xml_dir)):
        if fn.lower().endswith(".xml"):
            src = os.path.join(xml_dir, fn)
            dst = os.path.join(text_dir, fn)
            with open(src, "rb") as f:
                raw = f.read()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("windows-1251", errors="replace")
            # 更新 XML 声明为 utf-8（无 BOM）
            text = _re.sub(r"<\?xml[^>]*\?>",
                           lambda m: _re.sub(r'(encoding\s*=\s*["\'])[^"\']*(["\'])',
                                             r"\1utf-8\2", m.group(0), flags=_re.I),
                           text, count=1, flags=_re.I)
            with open(dst, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            n += 1
    L(f"XML: 写入 {n} 个文件 → {cfg_dir}/text/{lang}/ (无 BOM UTF-8)")

    # fonts.ltx + localization.ltx
    with open(os.path.join(out_gd, cfg_dir, "fonts.ltx"), "w", encoding="utf-8") as f:
        f.write(FONTS_LTX[game])
    loc = (LOCALIZATION_LTX[game]
           .replace("_#LANG#", suffix)   # font_prefix ← 字体后缀 (可为空)
           .replace("#LANG#", lang))      # language ← 加载语言
    with open(os.path.join(out_gd, cfg_dir, "localization.ltx"), "w", encoding="utf-8") as f:
        f.write(loc)
    L("fonts.ltx + localization.ltx 已生成")
    L(f"完成: {out_gd}")
    return out_gd


if __name__ == "__main__":
    # CLI: python font_pack.py <xml_dir> <font.ttf> <out_dir> [game] [lang] [suffix]
    a = sys.argv
    if len(a) < 4:
        print("用法: python font_pack.py <xml目录> <字体文件> <输出目录> [GAME=SoC] [LANG=chs] [后缀=_chs]")
        sys.exit(1)
    game = a[4] if len(a) > 4 else "SoC"
    lang = a[5] if len(a) > 5 else "chs"
    suffix = a[6] if len(a) > 6 else ""
    build_package(game, lang, a[1], a[2], a[3], suffix=suffix, log=print)
