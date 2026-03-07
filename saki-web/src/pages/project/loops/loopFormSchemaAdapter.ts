import {
    PluginConfigField,
    PluginConfigSchema,
    RuntimeRequestConfigField,
    RuntimeRequestConfigSchema,
} from '../../../types';

export function toPluginConfigField(field: RuntimeRequestConfigField): PluginConfigField {
    const options = field.options?.map((opt) => ({
        label: opt.label,
        value: opt.value,
        visible: (opt as any).visible,
    }));

    return {
        key: field.key,
        label: field.label,
        type: field.type as any,
        required: field.required,
        min: field.min,
        max: field.max,
        default: field.default,
        description: field.description,
        group: field.group,
        depends_on: field.depends_on,
        visible: (field as any).visible,
        props: (field as any).props ?? (field.ui ? {
            placeholder: field.ui.placeholder,
            step: field.ui.step,
            rows: field.ui.rows,
            min: field.ui.min ?? field.min,
            max: field.ui.max ?? field.max,
        } : undefined),
        options: options && options.length > 0 ? options : undefined,
    };
}

export function toPluginConfigSchema(schema: RuntimeRequestConfigSchema | undefined): PluginConfigSchema {
    return {
        title: schema?.title,
        fields: (schema?.fields || []).map(toPluginConfigField),
    };
}
