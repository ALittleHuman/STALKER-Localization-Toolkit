# -*- coding: utf-8 -*-
"""
UI / core smoke tests that can run on a Windows desktop session.

Covers:
    * every built-in App can construct its GUI inside the Hub
    * plugin tools registered in plugins/ are built too
    * encoding auto-detection (utf-8 / windows-1251)
    * XML compare core parsing (line/id stats)
    * text extraction cfgxml parsing
    * video tool ffmpeg/ffprobe discovery

Usage:
    python run_ui_smoke.py
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
for sub in ('file_system', 'font_pack', 'plugins'):
    p = os.path.join(BASE, sub)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

from tkinterdnd2 import TkinterDnD
import tkinter as tk
from tkinter import ttk

from toolkit import (
    T, color, apply_theme, apply_tk_defaults, PluginManager,
    log_to_file, _BaseTk, load_user_theme,
)
from apps.font_pack_app import FontPackApp
from apps.convert_app import ConvertApp
from apps.text_extract_app import TextExtractApp
from apps.xml_compare_app import XMLCompareApp
from apps.video_ogm_app import VideoOGMApp
from apps.fs_app import FSToolApp

PASS = []
FAIL = []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f'  PASS  {name}')
    else:
        FAIL.append(name)
        print(f'  FAIL  {name}  {detail}')


def build_hub_tools(root):
    shared_plugins = PluginManager(
        os.path.join(BASE, 'plugins'),
        log=lambda msg, tag='info': log_to_file(msg, tag),
    )
    shared_plugins.scan()
    tools = [
        ('文件系统', lambda tab: FSToolApp(tab, plugins=shared_plugins)),
        ('编码转换', ConvertApp),
        ('文本提取', TextExtractApp),
        ('XML校对', XMLCompareApp),
        ('视频转换', VideoOGMApp),
        ('汉化包生成', FontPackApp),
    ]
    for tool in shared_plugins.tools:
        name = tool.get('name') or tool.get('info', {}).get('name', '插件')
        tools.append((name, tool.get('builder')))
    nb = ttk.Notebook(root)
    nb.pack(fill='both', expand=True)
    apps = {}
    for label, factory in tools:
        tab = tk.Frame(nb, bg=color('bg'))
        nb.add(tab, text=label)
        apps[label] = factory(tab)
        print(f'  built  {label}')
    return apps


def main():
    print('=== UI smoke: build Hub tools ===')
    root = _BaseTk()
    root.withdraw()
    root.configure(bg=T['bg'])
    apply_theme()
    apply_tk_defaults(root)
    apps = build_hub_tools(root)
    check('all six built-in tools constructed', all(k in apps for k in (
        '文件系统', '编码转换', '文本提取', 'XML校对', '视频转换', '汉化包生成'
    )))
    root.update_idletasks()

    print('=== Core: encoding auto-detect ===')
    conv = apps.get('编码转换')
    if conv is not None:
        conv.source_enc.set('auto')
        conv._ensure_snap()
        check('utf-8 detected as utf-8',
              conv._get_source_encoding('中文测试'.encode('utf-8')) == 'utf-8')
        check('cp1251 text falls back to windows-1251',
              conv._get_source_encoding('Привет'.encode('cp1251')) == 'windows-1251')
        check('cp1252 text falls back to windows-1251',
              conv._get_source_encoding('café'.encode('cp1252')) == 'windows-1251')
    else:
        check('ConvertApp exists', False)

    print('=== Core: XML compare parse_file ===')
    from apps.xml_compare_app import parse_file, collect_xml_files
    tmpdir = tempfile.mkdtemp(prefix='toolkit_smoke_xml_')
    xml_a = os.path.join(tmpdir, 'a.xml')
    xml_b = os.path.join(tmpdir, 'b.xml')
    with open(xml_a, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<root><string id="a"><text>hello</text></string></root>')
    with open(xml_b, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<root><string id="a"><text>world</text></string></root>')
    files = collect_xml_files(Path(tmpdir))
    check('collect_xml_files finds two xml', len(files) == 2)
    count_a, ids_a, enc_a = parse_file(Path(xml_a))
    count_b, ids_b, enc_b = parse_file(Path(xml_b))
    check('parse_file id count', ids_a['a'] == 1 and count_a >= 2)
    check('parse_file utf-8 detected', enc_a == 'utf-8' and enc_b == 'utf-8')

    print('=== Core: text extract cfgxml ===')
    from apps.text_extract_app import _parse_cfgxml
    cfg = os.path.join(tmpdir, 'ui_cfg.xml')
    with open(cfg, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<root><string id="ui_mm_test"><text>Main menu</text></string></root>')
    text, texts, enc = _parse_cfgxml(cfg)
    check('_parse_cfgxml extracts text', 'Main menu' in text)
    check('_parse_cfgxml returns text set', 'Main menu' in texts)

    print('=== Core: video tool discovery ===')
    from apps.video_ogm_app import find_ffmpeg
    ff, fp = find_ffmpeg()
    check('ffmpeg discovered', bool(ff) and os.path.isfile(ff), str(ff))
    check('ffprobe discovered', bool(fp) and os.path.isfile(fp), str(fp))

    root.destroy()
    print('=== RESULT ===')
    print(f'PASS {len(PASS)}  FAIL {len(FAIL)}')
    if FAIL:
        print('Failed:')
        for name in FAIL:
            print(' -', name)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
