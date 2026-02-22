"""Smoke test for PluginConfig."""
from saki_plugin_sdk import PluginConfig
from saki_plugin_sdk.config import _coerce

# Test resolve with coercion
cfg = PluginConfig.resolve(
    default_config={"epochs": 30, "batch": 16, "yolo_task": "obb"},
    config_schema={"fields": [
        {"key": "epochs", "type": "integer", "required": True, "min": 1, "max": 5000},
        {"key": "batch", "type": "integer", "required": True, "min": 1},
    ]},
    raw_config={"epochs": "50"},
)
assert cfg.epochs == 50 and type(cfg.epochs) is int, f"got {cfg.epochs!r}"
assert cfg.batch == 16
assert cfg.yolo_task == "obb"

# Test immutability
try:
    cfg.epochs = 99
    assert False, "should raise"
except AttributeError:
    pass

# Test with_updates
cfg2 = cfg.with_updates(epochs=100)
assert cfg2.epochs == 100 and cfg.epochs == 50

# Test to_dict
d = cfg.to_dict()
assert isinstance(d, dict) and d["epochs"] == 50

# Test from_dict
cfg3 = PluginConfig.from_dict({"a": 1, "b": 2})
assert cfg3.a == 1 and cfg3.b == 2

# Test coerce
assert _coerce("30", "integer") == 30
assert _coerce("0.5", "number") == 0.5
assert _coerce("true", "boolean") is True
assert _coerce("false", "boolean") is False

# Test validation error: required
try:
    PluginConfig.resolve(
        default_config={},
        config_schema={"fields": [{"key": "x", "type": "integer", "required": True}]},
    )
    assert False, "should raise"
except ValueError as e:
    assert "required" in str(e)

# Test min validation
try:
    PluginConfig.resolve(
        default_config={"x": 0},
        config_schema={"fields": [{"key": "x", "type": "integer", "min": 1}]},
    )
    assert False, "should raise"
except ValueError as e:
    assert "minimum" in str(e)

# Test dict-like access
assert "epochs" in cfg
assert cfg["epochs"] == 50
assert cfg.get("missing", 42) == 42

print("ALL PASS")
