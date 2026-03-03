"""Smoke test for PluginConfig."""
from saki_plugin_sdk import PluginConfig
from saki_plugin_sdk.config import ConfigSchema, _coerce
from saki_plugin_sdk.exceptions import PluginValidationError

# Test resolve with coercion
schema = ConfigSchema.model_validate(
    {
        "fields": [
            {"key": "epochs", "label": "Epochs", "type": "integer", "required": True, "min": 1, "max": 5000, "default": 30},
            {"key": "batch", "label": "Batch", "type": "integer", "required": True, "min": 1, "default": 16},
            {"key": "yolo_task", "label": "Task", "type": "select", "default": "obb"},
        ]
    }
)
cfg = PluginConfig.resolve(
    schema=schema,
    raw_config={"epochs": "50"},
)
assert cfg.epochs == 50 and type(cfg.epochs) is int, f"got {cfg.epochs!r}"
assert cfg.batch == 16
assert cfg.yolo_task == "obb"

# Test model_copy update
cfg2 = cfg.model_copy(update={"epochs": 100})
assert cfg2.epochs == 100 and cfg.epochs == 50

# Test to_dict
d = cfg.to_dict()
assert isinstance(d, dict) and d["epochs"] == 50

# Test model_validate
cfg3 = PluginConfig.model_validate({"a": 1, "b": 2})
assert cfg3.a == 1 and cfg3.b == 2

# Test coerce
assert _coerce("30", "integer") == 30
assert _coerce("0.5", "number") == 0.5
assert _coerce("true", "boolean") is True
assert _coerce("false", "boolean") is False

# Test validation error: required
try:
    PluginConfig.resolve(
        schema=ConfigSchema.model_validate(
            {"fields": [{"key": "x", "label": "x", "type": "integer", "required": True}]}
        ),
    )
    assert False, "should raise"
except ValueError as e:
    assert "required" in str(e)
except PluginValidationError as e:
    assert "required" in str(e)

# Test min validation
try:
    PluginConfig.resolve(
        schema=ConfigSchema.model_validate(
            {"fields": [{"key": "x", "label": "x", "type": "integer", "min": 1, "default": 0}]}
        ),
    )
    assert False, "should raise"
except ValueError as e:
    assert "minimum" in str(e)
except PluginValidationError as e:
    assert "minimum" in str(e)

# Test dict-like access
assert "epochs" in cfg.to_dict()
assert cfg.get("missing", 42) == 42

print("ALL PASS")
