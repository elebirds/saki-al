/**
 * DynamicConfigForm - 通用动态配置表单组件
 *
 * 根据 PluginConfigSchema 自动生成 Ant Design 表单
 * 支持 visible 表达式和 props 映射
 *
 * 可以独立使用（自带 Form）或嵌套在现有 Form 中使用
 */

import React, { useEffect, useMemo, useCallback } from 'react';
import {
  Alert,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Typography,
} from 'antd';
import { PluginConfigFormProps, PluginConfigField } from '../../types/plugin';

const { Text } = Typography;

/**
 * 安全评估 visible 表达式
 *
 * 支持 JS 风格的表达式语法：
 * - ctx.annotation_types.includes('rect')
 * - form.yolo_task === 'detect'
 * - form.field1 && form.field2 !== 'value'
 *
 * @param expr - 表达式字符串
 * @param context - 包含 annotationTypes 和 fieldValues 的上下文
 * @returns 表达式评估结果（失败返回 false）
 */
function evaluateVisible(
  expr: string | undefined | null,
  context: {
    annotationTypes?: string[];
    fieldValues?: Record<string, any>;
  },
): boolean {
  if (!expr || typeof expr !== 'string') {
    return true;
  }

  const trimmed = expr.trim();
  if (!trimmed) {
    return true;
  }

  try {
    // 构建安全的评估上下文
    const ctx = {
      annotation_types: [...context.annotationTypes ?? []] as any,
    };

    // 添加 includes 辅助方法
    ctx.annotation_types.includes = (value: string) =>
      (context.annotationTypes ?? []).some(
        (t) => String(t).toLowerCase() === String(value).toLowerCase()
      );

    const form = { ...context.fieldValues };

    // 创建安全的评估函数
    const safeEval = new Function('ctx', 'form', `
      "use strict";
      try {
        return ${trimmed};
      } catch (e) {
        return false;
      }
    `);

    const result = safeEval(ctx, form);
    return Boolean(result);
  } catch (error) {
    // 表达式评估失败，默认不可见（安全原则）
    console.warn(`Failed to evaluate visible expression: "${expr}"`, error);
    return false;
  }
}

/**
 * 过滤选项列表（支持 visible 表达式）
 */
function filterOptions(
  options: any[] | undefined,
  context: {
    annotationTypes?: string[];
    fieldValues?: Record<string, any>;
  },
): any[] {
  if (!options) return [];
  return options.filter((opt) => evaluateVisible(opt.visible, context));
}

/**
 * 表单值转换：后端 -> 表单
 */
function toFormValue(field: PluginConfigField, value: unknown): unknown {
  if (field.type === 'integer_array') {
    if (Array.isArray(value)) {
      return value.map((item) => String(item));
    }
    if (value == null) {
      return [];
    }
    return [String(value)];
  }
  if (field.type === 'boolean') {
    return Boolean(value);
  }
  if (field.type === 'integer' || field.type === 'number') {
    if (typeof value === 'number') {
      return value;
    }
    if (value === undefined || value === null || value === '') {
      return undefined;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  if (value === undefined || value === null) {
    return '';
  }
  return String(value);
}

/**
 * 表单值转换：表单 -> 后端
 */
export function normalizeSubmitValue(field: PluginConfigField, value: unknown): unknown {
  if (field.type === 'integer_array') {
    const source = Array.isArray(value) ? value : [];
    const result: number[] = [];
    const seen = new Set<number>();
    for (const item of source) {
      const parsed = Number(String(item).trim());
      if (!Number.isInteger(parsed)) {
        continue;
      }
      if (seen.has(parsed)) {
        continue;
      }
      seen.add(parsed);
      result.push(parsed);
    }
    return result;
  }

  if (field.type === 'boolean') {
    return Boolean(value);
  }

  if (field.type === 'integer') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return Math.trunc(parsed);
    }
    return field.default ?? 0;
  }

  if (field.type === 'number') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
    return field.default ?? 0;
  }

  if (value === undefined || value === null) {
    return '';
  }

  return String(value).trim();
}

/**
 * 构建表单验证规则
 */
function buildRules(field: PluginConfigField) {
  const rules: any[] = [];

  // 必填验证
  if (field.required) {
    rules.push({ required: true, message: `${field.label} 是必填项` });
  }

  // 数值类型约束 (从 props 或字段级属性获取)
  const props = field.props ?? field.ui ?? {};
  const min = props.min ?? field.min;
  const max = props.max ?? field.max;

  if (field.type === 'integer' || field.type === 'number') {
    if (min !== undefined && min !== null) {
      rules.push({
        type: 'number',
        min,
        message: `${field.label} 不能小于 ${min}`,
      });
    }
    if (max !== undefined && max !== null) {
      rules.push({
        type: 'number',
        max,
        message: `${field.label} 不能大于 ${max}`,
      });
    }
  }

  return rules.length > 0 ? rules : undefined;
}

/**
 * DynamicConfigForm 组件
 */
export const DynamicConfigForm: React.FC<PluginConfigFormProps> = ({
  schema,
  values,
  onChange,
  context = {},
  disabled = false,
  form: externalForm,
  namePrefix,
}) => {
  // 如果没有外部 form，创建内部 form
  const [internalForm] = Form.useForm();
  const form = externalForm ?? internalForm;
  const isEmbedded = !!externalForm;

  // 构建 name 路径
  const getNamePath = useCallback((fieldKey: string): (string | number)[] => {
    if (namePrefix) {
      const prefix = Array.isArray(namePrefix) ? namePrefix : [namePrefix];
      return [...prefix, fieldKey];
    }
    return [fieldKey];
  }, [namePrefix]);

  // 构建评估上下文
  const evalContext = useMemo(
    () => ({
      annotationTypes: context.annotationTypes ?? [],
      fieldValues: values ?? {},
    }),
    [context.annotationTypes, values],
  );

  // 评估字段可见性
  const isFieldVisible = useCallback(
    (field: PluginConfigField): boolean => {
      if (field.visible) {
        return evaluateVisible(field.visible, evalContext);
      }
      return true;
    },
    [evalContext],
  );

  // 处理字段依赖 - 当父字段变化时重置子字段
  useEffect(() => {
    const currentValues = isEmbedded ? values : form.getFieldsValue();
    let needsUpdate = false;
    const newValues = { ...currentValues };

    for (const field of schema.fields) {
      if (field.depends_on && field.depends_on.length > 0) {
        const shouldReset = field.depends_on.some((depKey) => {
          const depValue = currentValues[depKey];
          return depValue === undefined || depValue === null || depValue === '';
        });

        if (shouldReset && currentValues[field.key] !== undefined) {
          newValues[field.key] = undefined;
          needsUpdate = true;
        }
      }
    }

    if (needsUpdate) {
      if (isEmbedded) {
        onChange(newValues);
      } else {
        form.setFieldsValue(newValues);
        onChange(newValues);
      }
    }
  }, [form, schema.fields, onChange, isEmbedded, values]);

  // 分组字段
  const groupedFields = useMemo(() => {
    const groups = new Map<string, PluginConfigField[]>();
    for (const field of schema.fields) {
      if (!isFieldVisible(field)) continue;
      const group = field.group || 'default';
      if (!groups.has(group)) {
        groups.set(group, []);
      }
      groups.get(group)!.push(field);
    }
    return Array.from(groups.entries());
  }, [schema.fields, isFieldVisible]);

  // 渲染单个字段
  const renderField = useCallback(
    (field: PluginConfigField) => {
      if (!isFieldVisible(field)) return null;

      const keyPath = getNamePath(field.key);
      const rules = buildRules(field);

      // 获取 props（新风格）或 ui（旧风格）
      const props = field.props ?? field.ui ?? {};

      switch (field.type) {
        case 'boolean': {
          return (
            <Form.Item
              key={field.key}
              name={keyPath}
              label={field.label}
              valuePropName="checked"
              rules={rules}
              extra={field.description}
            >
              <Switch disabled={disabled} />
            </Form.Item>
          );
        }

        case 'integer':
        case 'number': {
          const min = props.min ?? field.min;
          const max = props.max ?? field.max;
          const step = props.step ?? (field.type === 'integer' ? 1 : 0.01);

          return (
            <Form.Item
              key={field.key}
              name={keyPath}
              label={field.label}
              rules={rules}
              extra={field.description}
            >
              <InputNumber
                className="w-full"
                min={min}
                max={max}
                step={step}
                precision={field.type === 'integer' ? 0 : undefined}
                placeholder={props.placeholder}
                disabled={disabled}
              />
            </Form.Item>
          );
        }

        case 'select': {
          const filteredOptions = filterOptions(field.options, evalContext);

          return (
            <Form.Item
              key={field.key}
              name={keyPath}
              label={field.label}
              rules={rules}
              extra={field.description}
            >
              <Select
                options={filteredOptions.map((opt) => ({
                  label: opt.label,
                  value: opt.value,
                }))}
                disabled={disabled}
                placeholder={props.placeholder}
              />
            </Form.Item>
          );
        }

        case 'textarea': {
          const rows = props.rows ?? 3;

          return (
            <Form.Item
              key={field.key}
              name={keyPath}
              label={field.label}
              rules={rules}
              extra={field.description}
            >
              <Input.TextArea
                rows={rows}
                placeholder={props.placeholder}
                disabled={disabled}
              />
            </Form.Item>
          );
        }

        case 'integer_array': {
          return (
            <Form.Item
              key={field.key}
              name={keyPath}
              label={field.label}
              rules={rules}
              extra={field.description}
            >
              <Select
                mode="tags"
                tokenSeparators={[',']}
                open={false}
                placeholder={props.placeholder ?? '请输入值，用逗号分隔'}
                disabled={disabled}
              />
            </Form.Item>
          );
        }

        default: {
          // string
          return (
            <Form.Item
              key={field.key}
              name={keyPath}
              label={field.label}
              rules={rules}
              extra={field.description}
            >
              <Input
                placeholder={props.placeholder}
                disabled={disabled}
              />
            </Form.Item>
          );
        }
      }
    },
    [disabled, evalContext, isFieldVisible, values],
  );

  // 处理表单值变化
  const handleValuesChange = (
    _changedValues: Record<string, any>,
    allValues: Record<string, any>,
  ) => {
    // 如果是嵌套模式，只提取 namePrefix 下的值
    if (isEmbedded && namePrefix) {
      const prefix = Array.isArray(namePrefix) ? namePrefix : [namePrefix];
      const prefixedValues = prefix.reduce((acc: any, key: string | number) => acc?.[key], allValues);
      onChange(prefixedValues || {});
    } else {
      onChange(allValues);
    }
  };

  // 初始化表单值（仅在独立模式下使用）
  const initialValues = useMemo(() => {
    if (isEmbedded) return undefined; // 嵌入模式由父 Form 管理

    const init: Record<string, any> = {};
    for (const field of schema.fields) {
      init[field.key] = toFormValue(field, values[field.key]);
    }
    return init;
  }, [isEmbedded, schema.fields, values]);

  // 表单内容（可独立渲染或嵌套在 Form 中）
  const formContent = (
    <>
      {(schema.title || schema.description) && (
        <Alert
          message={schema.title}
          description={schema.description}
          type="info"
          showIcon
          className="mb-4"
        />
      )}

      {groupedFields.map(([groupName, fields]) => (
        <div key={groupName} className="mb-6">
          {groupName !== 'default' && (
            <Text strong className="block mb-3">
              {groupName}
            </Text>
          )}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {fields.map((field) => renderField(field))}
          </div>
        </div>
      ))}
    </>
  );

  // 如果是嵌套模式，只渲染内容
  if (isEmbedded) {
    return <>{formContent}</>;
  }

  // 独立模式，渲染 Form 包装器
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={initialValues}
      onValuesChange={handleValuesChange}
    >
      {formContent}
    </Form>
  );
};

export default DynamicConfigForm;
