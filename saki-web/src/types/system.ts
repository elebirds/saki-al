export interface TypeInfo {
    value: string;
    label: string;
    description: string;
    color: string;
    enabled?: boolean;
    allowedAnnotationTypes?: string[];
    mustAnnotationTypes?: string[];
    bannedAnnotationTypes?: string[];
    // Backward compatible fields (deprecated)
    annotationTypes?: string[];
    defaultAnnotationTypes?: string[];
}

export interface AvailableTypes {
    taskTypes: TypeInfo[];
    datasetTypes: TypeInfo[];
}

export interface AvailableTypesResponse {
    taskTypes: TypeInfo[];
    datasetTypes: TypeInfo[];
}

export interface SystemStatus {
    initialized: boolean;
    allowSelfRegister: boolean;
}

export interface SystemSettingOption {
    value: string;
    label: string;
}

export type SystemSettingValue = boolean | string | number | number[];

export interface SystemSettingField {
    key: string;
    group: string;
    title: string;
    description: string;
    type: 'boolean' | 'string' | 'integer' | 'number' | 'enum' | 'integer_array' | 'integerArray';
    default: SystemSettingValue;
    editable: boolean;
    order: number;
    groupOrder: number;
    options: SystemSettingOption[];
    constraints: Record<string, unknown>;
    ui: Record<string, unknown>;
}

export interface SystemSettingsBundle {
    fields: SystemSettingField[];
    values: Record<string, SystemSettingValue>;
}
