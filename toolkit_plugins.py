# -*- coding: utf-8 -*-
"""插件宿主：扫描 plugins/ 目录并管理扩展点（从 toolkit.py 拆分）。

toolkit.py 会 re-export PluginManager，调用方无需改动。
"""
import os
import re


class PluginManager:
    """Scan a plugins/ directory and host extension points.

    A plugin is a Python file in the plugin directory (or a direct
    subdirectory) that defines PLUGIN_INFO and register(api). It may
    also expose plain functions for backward compatibility.

    Optional allow-list: plugins/enabled.txt
        One plugin file name per line (# comments ignored). If the file
        exists and is non-empty, only the listed plugins are loaded.

    Extension points:
      * decryptor(check, decrypt)
      * format(name, handler)
      * menu_item(label, callback, location="context")
      * option(label, choices, callback=None)
      * tool(name, builder)
    """

    def __init__(self, plugins_dir, log=None):
        self.plugins_dir = plugins_dir
        self.log = log or (lambda msg, tag="info": None)
        self.plugins = []
        self.decryptors = []
        self.formats = []
        self.menu_items = []
        self.options = []
        self.tools = []
        self.load_errors = []

    def _enabled_allowlist(self):
        path = os.path.join(self.plugins_dir, "enabled.txt")
        if not os.path.isfile(path):
            return None
        names = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        names.append(line)
        except Exception:
            return None
        return names if names else None

    @staticmethod
    def _match_allow(name, allow):
        """Match allow-list entries; '*' and '?' wildcards are supported."""
        import fnmatch
        return any(fnmatch.fnmatch(name, pat) for pat in allow)

    def _iter_plugin_files(self):
        """Yield (relative_name, absolute_path) for all loadable plugins."""
        allow = self._enabled_allowlist()
        files = []
        for dp, dn, fn in os.walk(self.plugins_dir):
            dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
            for f in fn:
                if not f.endswith(".py") or f.startswith("_"):
                    continue
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, self.plugins_dir).replace("\\", "/")
                files.append((rel, full))
        files.sort(key=lambda x: x[0])
        if allow is None:
            return files
        return [(rel, full) for rel, full in files if self._match_allow(rel, allow)]

    def scan(self):
        """Import all plugin files and call their register()."""
        self.plugins = []
        self.decryptors = []
        self.formats = []
        self.menu_items = []
        self.options = []
        self.tools = []
        self.load_errors = []
        if not os.path.isdir(self.plugins_dir):
            return self.plugins

        for rel, path in self._iter_plugin_files():
            modname = "toolkit_plugin_" + re.sub(r"[^0-9A-Za-z_]", "_", rel[:-3])
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(modname, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                msg = f"plugin load failed: {rel}: {e}"
                self.load_errors.append(msg)
                self.log(msg, "err")
                continue
            info = getattr(mod, "PLUGIN_INFO", {})
            api = self._make_api(rel, info)
            registered = False
            if hasattr(mod, "register"):
                try:
                    mod.register(api)
                    registered = True
                except Exception as e:
                    msg = f"plugin register failed: {rel}: {e}"
                    self.load_errors.append(msg)
                    self.log(msg, "err")
            if not registered:
                # backward compatibility: bare functions in the plugin
                if hasattr(mod, "decrypt_sq"):
                    api.register_decryptor(
                        lambda p, m=mod: getattr(m, "open_sq")(p) is not None,
                        mod.decrypt_sq,
                    )
                    registered = True
            self.plugins.append({"file": rel, "info": info, "module": mod,
                                 "registered": registered})
            self.log(f"plugin loaded: {rel}", "ok")
        return self.plugins

    def _make_api(self, filename, info):
        pm = self

        class Api:
            def register_decryptor(self, check, decrypt):
                pm.decryptors.append({
                    "plugin": filename,
                    "info": info,
                    "check": check,
                    "decrypt": decrypt,
                })

            def register_format(self, name, handler):
                pm.formats.append({
                    "plugin": filename,
                    "info": info,
                    "name": name,
                    "handler": handler,
                })

            def register_menu_item(self, label, callback, location="context"):
                pm.menu_items.append({
                    "plugin": filename,
                    "info": info,
                    "label": label,
                    "callback": callback,
                    "location": location,
                })

            def register_option(self, label, choices, callback=None):
                pm.options.append({
                    "plugin": filename,
                    "info": info,
                    "label": label,
                    "choices": choices,
                    "callback": callback,
                })

            def register_tool(self, name, builder):
                """Register a new Hub tab. builder(parent) builds the tab UI."""
                pm.tools.append({
                    "plugin": filename,
                    "info": info,
                    "name": name,
                    "builder": builder,
                })

        return Api()

    def find_decryptor(self, path):
        """Return the first registered decryptor that accepts path, else None."""
        for d in self.decryptors:
            try:
                if d["check"](path):
                    return d
            except Exception:
                continue
        return None
