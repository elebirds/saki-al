# Plugin Configuration Guide

## Overview

The Saki plugin configuration system uses a **simplified expression-based syntax** for dynamic visibility:

- `visible`: Expression strings for dynamic field/option visibility
- `ctx.*`: Project-level context (e.g., annotation types)
- `form.*`: Form field values (user input)
- `props`: UI component constraints (min, max, step, etc.)

---

## Expression Syntax

### Supported Operators

- Comparison: `===`, `!==`, `==`, `!=`, `<`, `>`, `<=`, `>=`
- Logical: `&&`, `||`, `!`
- Method calls: `ctx.annotation_types.includes('value')`

### Context Namespaces

| Namespace | Description | Example |
|-----------|-------------|---------|
| `ctx.*` | Project-level context (immutable) | `ctx.annotation_types.includes('rect')` |
| `form.*` | Form field values (user input) | `form.yolo_task === 'detect'` |

---

## Configuration Examples

### Context-level Visibility

```yaml
fields:
  - key: yolo_task
    label: YOLO Task Mode
    type: select
    options:
      - label: "Standard Detection"
        value: "detect"
        visible: "ctx.annotation_types.includes('rect')"
      - label: "OBB Detection"
        value: "obb"
        visible: "ctx.annotation_types.includes('obb')"
```

### Field-level Visibility

```yaml
fields:
  - key: model_preset
    label: Preset Model
    type: select
    options:
      - label: "YOLOv8n"
        value: "yolov8n.pt"
        visible: "form.yolo_task === 'detect'"
      - label: "YOLOv8n-OBB"
        value: "yolov8n-obb.pt"
        visible: "form.yolo_task === 'obb'"
```

### Props Mapping

```yaml
fields:
  - key: epochs
    label: Training Epochs
    type: integer
    default: 100
    props:
      min: 1
      max: 5000
      step: 1
      placeholder: "Enter number of epochs..."
```

### Complex Expressions

```yaml
fields:
  - key: advanced_option
    label: Advanced Option
    type: string
    visible: "form.mode === 'advanced' && form.debug === true"
```

---

## Type Mapping

| Schema Type | Python Type | React Component |
|------------|-------------|-----------------|
| `string` | `str` | `Input` |
| `integer` | `int` | `InputNumber` (precision: 0) |
| `number` | `float` | `InputNumber` |
| `boolean` | `bool` | `Switch` |
| `select` | `str` | `Select` |
| `textarea` | `str` | `Input.TextArea` |
| `integer_array` | `list[int]` | `Select` (mode: tags) |

---

## Complete Example

```yaml
config_schema:
  title: "YOLO Detection Config"
  description: "Configuration for YOLO detection models"
  fields:
    - key: yolo_task
      label: Task Mode
      type: select
      required: true
      default: "detect"
      options:
        - label: "Detect"
          value: "detect"
          visible: "ctx.annotation_types.includes('rect')"
        - label: "OBB"
          value: "obb"
          visible: "ctx.annotation_types.includes('obb')"

    - key: epochs
      label: Epochs
      type: integer
      default: 100
      props:
        min: 1
        max: 5000

    - key: model_preset
      label: Model Preset
      type: select
      options:
        - label: "YOLOv8n"
          value: "yolov8n.pt"
          visible: "form.yolo_task === 'detect'"
        - label: "YOLOv8n-OBB"
          value: "yolov8n-obb.pt"
          visible: "form.yolo_task === 'obb'"
```

---

## SDK API Reference

### Python (Backend)

```python
from saki_plugin_sdk import PluginConfig, ConfigSchema

# Parse schema from plugin.yml
schema = ConfigSchema.model_validate(manifest.config_schema)

# Resolve configuration
config = PluginConfig.resolve(
    schema=schema,
    raw_config=user_config,
    validate=True,
)

# Access values
epochs = config.epochs  # type: int
model = config.model_preset  # type: str
```

### TypeScript (Frontend)

```tsx
import { DynamicConfigForm } from '@/components/common';

<DynamicConfigForm
  schema={pluginSchema}
  values={configValues}
  onChange={setConfigValues}
  context={{
    annotationTypes: ['rect'],
    fieldValues: configValues,
  }}
/>
```
