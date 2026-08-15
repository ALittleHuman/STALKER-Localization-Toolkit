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
CELL_HEIGHTS = {11: 15, 13: 16, 15: 19, 16: 20, 17: 22, 18: 23,
                20: 25, 21: 26, 23: 29, 25: 31}

# 当前环境原版 FontGen 的方块字符宽 (汉字/全角标点, 查表避免字体 advance 差异)
BLOCK_WIDTHS = {11: 13, 13: 15, 15: 18, 16: 19, 17: 20, 18: 21,
                20: 23, 21: 24, 23: 26, 25: 29}

# FontGen 内置字符集中的生僻汉字 (原版 Char.txt 编码 bug 丢失后由内置集补充)
FONTGEN_EXTRA = set("屑懈挟衼袗袘袙袚袛袝袞袟袠袡袣袥袦袧袨袩袪褉褋褌褍褎褏褑褔褕褖褗褘褜褝褞褟褢")

# 原版 CharAdder 编码 bug 丢失的西里尔 (严格兼容模式下剔除, 保证与原版整包一致)
LOST_CYRILLIC = set("ГЙФХЦЧШЩЭЮбвгдежзийклмнопрстуфхцчшщъыьэю")

ADV_TABLES = {
    11: {9:0, 32:3, 33:3, 34:4, 35:7, 36:7, 37:10, 38:8, 39:2, 40:4, 41:4, 42:5, 43:7, 44:3, 45:4, 46:3, 47:3, 48:7, 49:7, 50:7, 51:7, 52:7, 53:7, 54:7, 55:7, 56:7, 57:7, 58:3, 59:3, 60:7, 61:7, 62:7, 63:7, 64:12, 65:8, 66:8, 67:8, 68:8, 69:8, 70:7, 71:9, 72:8, 73:3, 74:6, 75:8, 76:7, 77:10, 78:8, 79:9, 80:8, 81:9, 82:8, 83:8, 84:7, 85:8, 86:8, 87:11, 88:8, 89:8, 90:7, 91:3, 92:3, 93:3, 94:6, 95:7, 96:4, 97:7, 98:7, 99:6, 100:7, 101:7, 102:3, 103:7, 104:7, 105:3, 106:3, 107:6, 108:3, 109:10, 110:7, 111:7, 112:7, 113:7, 114:4, 115:6, 116:3, 117:7, 118:6, 119:8, 120:6, 121:6, 122:6, 123:4, 124:3, 125:4, 126:7, 171:7, 173:0, 177:7, 183:3, 187:7, 215:7, 1025:8, 1040:8, 1041:8, 1042:8, 1044:9, 1045:8, 1046:11, 1047:7, 1048:8, 1050:8, 1051:8, 1052:10, 1053:8, 1054:9, 1055:8, 1056:8, 1057:8, 1058:7, 1059:8, 1066:9, 1067:10, 1071:8, 1072:7, 1103:6, 1105:7, 8212:6, 8220:4, 8221:4, 8226:4, 8230:7, 8470:12},
    13: {9:0, 32:4, 33:4, 34:5, 35:8, 36:8, 37:13, 38:10, 39:3, 40:5, 41:5, 42:6, 43:8, 44:4, 45:5, 46:4, 47:4, 48:8, 49:8, 50:8, 51:8, 52:8, 53:8, 54:8, 55:8, 56:8, 57:8, 58:4, 59:4, 60:8, 61:8, 62:8, 63:8, 64:14, 65:10, 66:10, 67:10, 68:10, 69:10, 70:9, 71:11, 72:10, 73:4, 74:7, 75:10, 76:8, 77:12, 78:10, 79:11, 80:10, 81:11, 82:10, 83:10, 84:9, 85:10, 86:10, 87:13, 88:10, 89:10, 90:9, 91:4, 92:4, 93:4, 94:7, 95:8, 96:5, 97:8, 98:8, 99:7, 100:8, 101:8, 102:4, 103:8, 104:8, 105:4, 106:4, 107:7, 108:4, 109:12, 110:8, 111:8, 112:8, 113:8, 114:5, 115:7, 116:4, 117:8, 118:7, 119:10, 120:7, 121:7, 122:7, 123:5, 124:4, 125:5, 126:8, 171:8, 173:0, 177:8, 183:4, 187:8, 215:8, 1025:10, 1040:10, 1041:9, 1042:10, 1044:11, 1045:10, 1046:13, 1047:9, 1048:10, 1050:10, 1051:10, 1052:12, 1053:10, 1054:11, 1055:10, 1056:10, 1057:10, 1058:9, 1059:9, 1066:11, 1067:12, 1071:10, 1072:8, 1103:8, 1105:8, 8212:8, 8220:5, 8221:5, 8226:5, 8230:8, 8470:14},
    15: {9:1, 32:5, 33:5, 34:6, 35:10, 36:10, 37:15, 38:11, 39:4, 40:6, 41:6, 42:7, 43:10, 44:5, 45:6, 46:5, 47:5, 48:10, 49:10, 50:10, 51:10, 52:10, 53:10, 54:10, 55:10, 56:10, 57:10, 58:5, 59:5, 60:10, 61:10, 62:10, 63:10, 64:17, 65:11, 66:11, 67:12, 68:12, 69:11, 70:10, 71:13, 72:12, 73:5, 74:9, 75:11, 76:10, 77:14, 78:12, 79:13, 80:11, 81:13, 82:12, 83:11, 84:10, 85:12, 86:11, 87:16, 88:11, 89:11, 90:10, 91:5, 92:5, 93:5, 94:8, 95:9, 96:6, 97:10, 98:10, 99:9, 100:10, 101:10, 102:5, 103:10, 104:10, 105:4, 106:4, 107:9, 108:4, 109:14, 110:10, 111:10, 112:10, 113:10, 114:6, 115:9, 116:5, 117:10, 118:9, 119:12, 120:9, 121:9, 122:9, 123:6, 124:5, 125:6, 126:10, 171:10, 173:0, 177:10, 183:5, 187:10, 215:10, 1025:11, 1040:11, 1041:11, 1042:11, 1044:13, 1045:11, 1046:15, 1047:11, 1048:12, 1050:11, 1051:12, 1052:14, 1053:12, 1054:13, 1055:12, 1056:11, 1057:12, 1058:10, 1059:11, 1066:13, 1067:15, 1071:12, 1072:10, 1103:9, 1105:10, 8212:10, 8220:6, 8221:6, 8226:6, 8230:10, 8470:16},
    16: {9:0, 32:5, 33:5, 34:7, 35:10, 36:10, 37:15, 38:12, 39:4, 40:6, 41:6, 42:7, 43:10, 44:5, 45:6, 46:5, 47:5, 48:10, 49:10, 50:10, 51:10, 52:10, 53:10, 54:10, 55:10, 56:10, 57:10, 58:5, 59:5, 60:10, 61:10, 62:10, 63:10, 64:17, 65:12, 66:12, 67:13, 68:13, 69:12, 70:11, 71:13, 72:13, 73:5, 74:9, 75:12, 76:10, 77:14, 78:13, 79:13, 80:12, 81:13, 82:13, 83:12, 84:11, 85:13, 86:12, 87:16, 88:12, 89:12, 90:11, 91:5, 92:5, 93:5, 94:8, 95:10, 96:6, 97:10, 98:10, 99:9, 100:10, 101:10, 102:5, 103:10, 104:10, 105:4, 106:4, 107:9, 108:4, 109:14, 110:10, 111:10, 112:10, 113:10, 114:6, 115:9, 116:5, 117:10, 118:9, 119:13, 120:9, 121:9, 122:9, 123:6, 124:5, 125:6, 126:10, 171:10, 173:0, 177:10, 183:5, 187:10, 215:10, 1025:12, 1040:12, 1041:11, 1042:12, 1044:13, 1045:12, 1046:15, 1047:11, 1048:13, 1050:12, 1051:12, 1052:14, 1053:13, 1054:13, 1055:13, 1056:12, 1057:13, 1058:11, 1059:11, 1066:14, 1067:15, 1071:13, 1072:10, 1103:10, 1105:10, 8212:10, 8220:6, 8221:6, 8226:6, 8230:10, 8470:17},
    17: {9:0, 32:5, 33:5, 34:7, 35:10, 36:10, 37:16, 38:12, 39:4, 40:6, 41:6, 42:7, 43:11, 44:5, 45:6, 46:5, 47:5, 48:10, 49:10, 50:10, 51:10, 52:10, 53:10, 54:10, 55:10, 56:10, 57:10, 58:5, 59:5, 60:11, 61:11, 62:11, 63:10, 64:18, 65:12, 66:12, 67:13, 68:13, 69:12, 70:11, 71:14, 72:13, 73:5, 74:9, 75:12, 76:10, 77:15, 78:13, 79:14, 80:12, 81:14, 82:13, 83:12, 84:11, 85:13, 86:12, 87:17, 88:12, 89:12, 90:11, 91:5, 92:5, 93:5, 94:9, 95:10, 96:6, 97:10, 98:10, 99:9, 100:10, 101:10, 102:5, 103:10, 104:10, 105:4, 106:4, 107:9, 108:4, 109:15, 110:10, 111:10, 112:10, 113:10, 114:6, 115:9, 116:5, 117:10, 118:9, 119:13, 120:9, 121:9, 122:9, 123:6, 124:5, 125:6, 126:11, 171:10, 173:0, 177:11, 183:5, 187:10, 215:11, 1025:12, 1040:12, 1041:12, 1042:12, 1044:14, 1045:12, 1046:16, 1047:11, 1048:13, 1050:12, 1051:13, 1052:15, 1053:13, 1054:14, 1055:13, 1056:12, 1057:13, 1058:11, 1059:12, 1066:14, 1067:16, 1071:13, 1072:10, 1103:10, 1105:10, 8212:10, 8220:6, 8221:6, 8226:6, 8230:10, 8470:18},
    18: {9:0, 32:5, 33:5, 34:7, 35:11, 36:11, 37:17, 38:13, 39:4, 40:6, 41:6, 42:7, 43:11, 44:5, 45:6, 46:5, 47:5, 48:11, 49:11, 50:11, 51:11, 52:11, 53:11, 54:11, 55:11, 56:11, 57:11, 58:5, 59:5, 60:11, 61:11, 62:11, 63:11, 64:19, 65:13, 66:13, 67:14, 68:14, 69:13, 70:12, 71:15, 72:14, 73:5, 74:10, 75:13, 76:11, 77:16, 78:14, 79:15, 80:13, 81:15, 82:14, 83:13, 84:12, 85:14, 86:13, 87:18, 88:13, 89:13, 90:12, 91:5, 92:5, 93:5, 94:9, 95:10, 96:6, 97:11, 98:11, 99:10, 100:11, 101:11, 102:5, 103:11, 104:11, 105:4, 106:4, 107:10, 108:4, 109:16, 110:11, 111:11, 112:11, 113:11, 114:6, 115:10, 116:5, 117:11, 118:10, 119:14, 120:10, 121:10, 122:10, 123:6, 124:5, 125:6, 126:11, 171:11, 173:0, 177:11, 183:5, 187:11, 215:11, 1025:13, 1040:13, 1041:12, 1042:13, 1044:15, 1045:13, 1046:17, 1047:12, 1048:14, 1050:13, 1051:13, 1052:16, 1053:14, 1054:15, 1055:14, 1056:13, 1057:14, 1058:12, 1059:12, 1066:15, 1067:17, 1071:14, 1072:11, 1103:10, 1105:11, 8212:11, 8220:6, 8221:6, 8226:7, 8230:11, 8470:19},
    20: {9:0, 32:6, 33:6, 34:8, 35:12, 36:12, 37:19, 38:14, 39:4, 40:7, 41:7, 42:8, 43:12, 44:6, 45:7, 46:6, 47:6, 48:12, 49:12, 50:12, 51:12, 52:12, 53:12, 54:12, 55:12, 56:12, 57:12, 58:6, 59:6, 60:12, 61:12, 62:12, 63:12, 64:21, 65:14, 66:14, 67:15, 68:15, 69:14, 70:13, 71:16, 72:15, 73:6, 74:11, 75:14, 76:12, 77:17, 78:15, 79:16, 80:14, 81:16, 82:15, 83:14, 84:13, 85:15, 86:14, 87:20, 88:14, 89:14, 90:13, 91:6, 92:6, 93:6, 94:10, 95:12, 96:7, 97:12, 98:12, 99:11, 100:12, 101:12, 102:6, 103:12, 104:12, 105:5, 106:5, 107:11, 108:5, 109:17, 110:12, 111:12, 112:12, 113:12, 114:7, 115:11, 116:6, 117:12, 118:11, 119:15, 120:11, 121:11, 122:11, 123:7, 124:6, 125:7, 126:12, 171:12, 173:0, 177:12, 183:6, 187:12, 215:12, 1025:14, 1040:14, 1041:14, 1042:14, 1044:16, 1045:14, 1046:19, 1047:13, 1048:15, 1050:14, 1051:15, 1052:17, 1053:15, 1054:16, 1055:15, 1056:14, 1057:15, 1058:13, 1059:13, 1066:16, 1067:18, 1071:15, 1072:12, 1103:11, 1105:12, 8212:12, 8220:7, 8221:7, 8226:8, 8230:12, 8470:21},
    21: {9:0, 32:6, 33:6, 34:8, 35:12, 36:12, 37:19, 38:15, 39:4, 40:7, 41:7, 42:9, 43:13, 44:6, 45:7, 46:6, 47:6, 48:12, 49:12, 50:12, 51:12, 52:12, 53:12, 54:12, 55:12, 56:12, 57:12, 58:6, 59:6, 60:13, 61:13, 62:13, 63:12, 64:22, 65:15, 66:15, 67:16, 68:16, 69:15, 70:13, 71:17, 72:16, 73:6, 74:11, 75:15, 76:12, 77:18, 78:16, 79:17, 80:15, 81:17, 82:16, 83:15, 84:13, 85:16, 86:15, 87:21, 88:15, 89:15, 90:13, 91:6, 92:6, 93:6, 94:10, 95:12, 96:7, 97:12, 98:12, 99:11, 100:12, 101:12, 102:6, 103:12, 104:12, 105:5, 106:5, 107:11, 108:5, 109:18, 110:12, 111:12, 112:12, 113:12, 114:7, 115:11, 116:6, 117:12, 118:11, 119:16, 120:11, 121:11, 122:11, 123:7, 124:6, 125:7, 126:13, 171:12, 173:0, 177:13, 183:6, 187:12, 215:13, 1025:15, 1040:15, 1041:14, 1042:15, 1044:17, 1045:15, 1046:20, 1047:14, 1048:16, 1050:15, 1051:15, 1052:18, 1053:16, 1054:17, 1055:16, 1056:15, 1057:16, 1058:13, 1059:14, 1066:17, 1067:19, 1071:16, 1072:12, 1103:12, 1105:12, 8212:13, 8220:7, 8221:7, 8226:8, 8230:12, 8470:22},
    23: {9:0, 32:7, 33:7, 34:9, 35:13, 36:13, 37:21, 38:16, 39:5, 40:8, 41:8, 42:10, 43:14, 44:7, 45:8, 46:7, 47:7, 48:13, 49:13, 50:13, 51:13, 52:13, 53:13, 54:13, 55:13, 56:13, 57:13, 58:7, 59:7, 60:14, 61:14, 62:14, 63:13, 64:24, 65:16, 66:16, 67:17, 68:17, 69:16, 70:15, 71:19, 72:17, 73:7, 74:12, 75:16, 76:13, 77:20, 78:17, 79:19, 80:16, 81:19, 82:17, 83:16, 84:15, 85:17, 86:16, 87:23, 88:16, 89:16, 90:15, 91:7, 92:7, 93:7, 94:11, 95:13, 96:8, 97:13, 98:13, 99:12, 100:13, 101:13, 102:7, 103:13, 104:13, 105:6, 106:6, 107:12, 108:6, 109:20, 110:13, 111:13, 112:13, 113:13, 114:8, 115:12, 116:7, 117:13, 118:12, 119:17, 120:12, 121:12, 122:12, 123:8, 124:6, 125:8, 126:14, 171:13, 173:0, 177:14, 183:7, 187:13, 215:14, 1025:16, 1040:16, 1041:16, 1042:16, 1044:19, 1045:16, 1046:22, 1047:15, 1048:17, 1050:16, 1051:17, 1052:20, 1053:17, 1054:19, 1055:17, 1056:16, 1057:17, 1058:15, 1059:15, 1066:19, 1067:21, 1071:17, 1072:13, 1103:13, 1105:13, 8212:14, 8220:8, 8221:8, 8226:9, 8230:14, 8470:24},
    25: {9:0, 32:7, 33:8, 34:10, 35:15, 36:15, 37:24, 38:18, 39:6, 40:9, 41:9, 42:11, 43:16, 44:8, 45:9, 46:8, 47:8, 48:15, 49:15, 50:15, 51:15, 52:15, 53:15, 54:15, 55:15, 56:15, 57:15, 58:8, 59:8, 60:16, 61:16, 62:16, 63:15, 64:27, 65:18, 66:18, 67:19, 68:19, 69:18, 70:16, 71:21, 72:19, 73:8, 74:14, 75:18, 76:15, 77:22, 78:19, 79:21, 80:18, 81:21, 82:19, 83:18, 84:16, 85:19, 86:18, 87:25, 88:18, 89:18, 90:16, 91:8, 92:8, 93:8, 94:13, 95:15, 96:9, 97:15, 98:15, 99:14, 100:15, 101:15, 102:8, 103:15, 104:15, 105:7, 106:7, 107:14, 108:7, 109:22, 110:15, 111:15, 112:15, 113:15, 114:9, 115:14, 116:8, 117:15, 118:14, 119:19, 120:14, 121:14, 122:14, 123:9, 124:7, 125:9, 126:16, 171:15, 173:0, 177:16, 183:8, 187:15, 215:16, 1025:18, 1040:18, 1041:18, 1042:18, 1044:21, 1045:18, 1046:24, 1047:17, 1048:19, 1050:18, 1051:19, 1052:22, 1053:19, 1054:21, 1055:19, 1056:18, 1057:19, 1058:16, 1059:17, 1066:21, 1067:23, 1071:19, 1072:15, 1103:15, 1105:15, 8212:16, 8220:9, 8221:9, 8226:10, 8230:15, 8470:26},
}

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
                           capture_output=True, timeout=180)
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

    # 先确定纹理宽: 1024 行数*cell ≤ 1024 则用, 否则 2048
    tex_w = 1024
    slots = tex_w // cell_h
    rows_n = (len(chars) + slots - 1) // slots
    if rows_n * cell_h - 1 > 1024:
        tex_w = 2048
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
            top = bbox[1] // S
            left = bbox[0] // S
            gw = (mb[2] - mb[0]) // S
            gh = (mb[3] - mb[1]) // S
            if gw >= 1 and gh >= 1:
                glyph = Image.frombytes("L", mask.size, bytes(mask)).crop(mb)
                if S > 1:
                    glyph = glyph.resize((gw, gh), Image.LANCZOS)
                canvas.paste(glyph, (x + left, y + top))
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

    # XML
    n = 0
    for fn in sorted(os.listdir(xml_dir)):
        if fn.lower().endswith(".xml"):
            import shutil
            shutil.copy2(os.path.join(xml_dir, fn), os.path.join(text_dir, fn))
            n += 1
    L(f"XML: 复制 {n} 个文件 → {cfg_dir}/text/{lang}/")

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
