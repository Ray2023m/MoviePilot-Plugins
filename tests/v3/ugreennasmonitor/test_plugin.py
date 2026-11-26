"""Lightweight tests for data formatting helpers; no MoviePilot runtime required."""
import importlib.util
import sys
import types
from pathlib import Path

# Stub only the stable host base and logger so helpers can be imported outside MP.
app = types.ModuleType("app")
sdk = types.ModuleType("app.sdk")
plugin = types.ModuleType("app.sdk.plugin")
logging_mod = types.ModuleType("app.sdk.logging")

class PluginBase:
    def __init__(self):
        pass

plugin._PluginBase = PluginBase
logging_mod.logger = types.SimpleNamespace(warning=lambda *args, **kwargs: None)
sys.modules.update({
    "app": app, "app.sdk": sdk, "app.sdk.plugin": plugin,
    "app.sdk.logging": logging_mod,
})

path = Path(__file__).parents[3] / "plugins.v3" / "ugreennasmonitor" / "__init__.py"
spec = importlib.util.spec_from_file_location("ugreen_plugin_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_bytes_formatting():
    assert module._bytes(0) == "0.0 B"
    assert module._bytes(1024) == "1.0 KiB"


def test_numeric_formatting():
    assert module._fmt("12.53") == "12.5"
    assert module._fmt(None) == "0.0"
