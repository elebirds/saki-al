/**
 * 插件配置相关类型定义
 *
 * 与后端 Pydantic 模型保持类型同步
 * 支持 visible 表达式和 props 映射
 */

/** UI 组件属性映射 (v-bind 风格) */
export interface PluginConfigFieldProps {
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  rows?: number;
  [key: string]: any; // 允许额外的任意属性
}

/** 选项定义 */
export interface PluginConfigFieldOption {
  label: string;
  value: string | number | boolean;
  visible?: string; // 可见性表达式
}

/** 配置字段定义 */
export interface PluginConfigField {
  key: string;
  label: string;
  type: 'string' | 'integer' | 'number' | 'boolean' | 'select' | 'multi_select' | 'textarea' | 'integer_array';
  required?: boolean;
  min?: number;
  max?: number;
  default?: any;
  description?: string;
  group?: string;
  depends_on?: string[];
  ui?: {
    placeholder?: string;
    step?: number;
    rows?: number;
    min?: number;
    max?: number;
  };
  props?: PluginConfigFieldProps;
  visible?: string;
  options?: PluginConfigFieldOption[];
}

/** 配置 Schema */
export interface PluginConfigSchema {
  title?: string;
  description?: string;
  fields: PluginConfigField[];
}

import type { FormInstance } from 'antd';

/** 配置表单组件属性 */
export interface PluginConfigFormProps {
  schema: PluginConfigSchema;
  values: Record<string, any>;
  onChange: (values: Record<string, any>) => void;
  context?: {
    annotationTypes?: string[]; // ctx.annotation_types
    fieldValues?: Record<string, any>; // form.*
    samplingStrategy?: string; // ctx.sampling_strategy
  };
  disabled?: boolean;
  /** 外部 Form 实例（可选，用于嵌套表单场景） */
  form?: FormInstance;
  /** 字段名称前缀（用于嵌套表单） */
  namePrefix?: string | number[];
}
