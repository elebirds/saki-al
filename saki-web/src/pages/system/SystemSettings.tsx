import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
    Alert,
    Button,
    Card,
    Form,
    Input,
    InputNumber,
    message,
    Result,
    Select,
    Spin,
    Switch,
    Tabs,
    Typography,
} from 'antd';
import {ReloadOutlined, SaveOutlined} from '@ant-design/icons';
import {useTranslation} from 'react-i18next';
import {api} from '../../services/api';
import {SystemSettingField, SystemSettingsBundle} from '../../types';
import {usePermission} from '../../hooks';

const {Title, Text} = Typography;

const getUiComponent = (field: SystemSettingField): string => {
    const component = field.ui?.component;
    return typeof component === 'string' ? component : '';
};

const isIntegerArrayType = (field: SystemSettingField): boolean =>
    field.type === 'integer_array' || field.type === 'integerArray';

const toFormValue = (field: SystemSettingField, value: unknown): unknown => {
    if (isIntegerArrayType(field)) {
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
};

const normalizeSubmitValue = (field: SystemSettingField, value: unknown): unknown => {
    if (isIntegerArrayType(field)) {
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
        return Number(field.default ?? 0);
    }

    if (field.type === 'number') {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) {
            return parsed;
        }
        return Number(field.default ?? 0);
    }

    if (value === undefined || value === null) {
        return '';
    }

    return String(value).trim();
};

const getGroupTitle = (group: string, t: (key: string) => string): string => {
    const key = `systemSettings.groups.${group}`;
    const translated = t(key);
    return translated === key ? group : translated;
};

const isSameValue = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

const SystemSettings: React.FC = () => {
    const {t} = useTranslation();
    const [form] = Form.useForm();
    const [bundle, setBundle] = useState<SystemSettingsBundle | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [activeGroup, setActiveGroup] = useState<string>('');

    const {can, isSuperAdmin, isLoading: permissionLoading} = usePermission();
    const canRead = can('system_setting:read') || isSuperAdmin;
    const canUpdate = can('system_setting:update') || isSuperAdmin;

    const applyBundleToForm = useCallback(
        (nextBundle: SystemSettingsBundle) => {
            const values: Record<string, unknown> = {};
            for (const field of nextBundle.fields) {
                const rawValue = nextBundle.values[field.key] ?? field.default;
                values[field.key] = toFormValue(field, rawValue);
            }
            form.setFieldsValue(values);
        },
        [form],
    );

    const loadBundle = useCallback(async () => {
        setLoading(true);
        try {
            const nextBundle = await api.getSystemSettingsBundle();
            setBundle(nextBundle);
            applyBundleToForm(nextBundle);
        } catch (error: any) {
            message.error(error.message || t('systemSettings.loadFailed'));
        } finally {
            setLoading(false);
        }
    }, [applyBundleToForm, t]);

    useEffect(() => {
        if (permissionLoading) {
            return;
        }
        if (!canRead) {
            setLoading(false);
            return;
        }
        loadBundle();
    }, [permissionLoading, canRead, loadBundle]);

    const groupedFields = useMemo(() => {
        const groups = new Map<string, SystemSettingField[]>();
        for (const field of bundle?.fields ?? []) {
            const group = field.group || 'other';
            if (!groups.has(group)) {
                groups.set(group, []);
            }
            groups.get(group)!.push(field);
        }

        return Array.from(groups.entries())
            .map(([group, fields]) => ({
                group,
                fields: [...fields].sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.key.localeCompare(b.key)),
                groupOrder: fields[0]?.groupOrder ?? 999,
            }))
            .sort((a, b) => a.groupOrder - b.groupOrder || a.group.localeCompare(b.group));
    }, [bundle]);

    useEffect(() => {
        if (groupedFields.length === 0) {
            if (activeGroup) {
                setActiveGroup('');
            }
            return;
        }
        const exists = groupedFields.some((item) => item.group === activeGroup);
        if (!exists) {
            setActiveGroup(groupedFields[0].group);
        }
    }, [groupedFields, activeGroup]);

    const handleSave = async () => {
        if (!bundle || !canUpdate) {
            return;
        }

        setSaving(true);
        try {
            await form.validateFields();
            const payload: Record<string, unknown> = {};
            for (const field of bundle.fields) {
                if (!field.editable) {
                    continue;
                }
                if (!form.isFieldTouched(field.key)) {
                    continue;
                }

                const nextValue = normalizeSubmitValue(field, form.getFieldValue(field.key));
                const prevValue = normalizeSubmitValue(
                    field,
                    bundle.values[field.key] ?? field.default,
                );
                if (isSameValue(nextValue, prevValue)) {
                    continue;
                }
                payload[field.key] = nextValue;
            }

            if (Object.keys(payload).length === 0) {
                message.info(t('systemSettings.noChanges'));
                return;
            }

            const nextBundle = await api.updateSystemSettings(payload);
            setBundle(nextBundle);
            applyBundleToForm(nextBundle);
            message.success(t('systemSettings.saveSuccess'));
        } catch (error: any) {
            message.error(error.message || t('systemSettings.saveFailed'));
        } finally {
            setSaving(false);
        }
    };

    const renderFieldControl = (field: SystemSettingField) => {
        const uiComponent = getUiComponent(field);
        const disabled = !field.editable || !canUpdate;

        if (field.type === 'boolean' || uiComponent === 'switch') {
            return <Switch disabled={disabled}/>;
        }

        if (field.type === 'enum' || uiComponent === 'select') {
            const options = (field.options || []).map((item) => ({
                value: item.value,
                label: item.label,
            }));
            return <Select options={options} disabled={disabled}/>;
        }

        if (isIntegerArrayType(field) || uiComponent === 'tags') {
            return (
                <Select
                    mode="tags"
                    tokenSeparators={[',']}
                    open={false}
                    disabled={disabled}
                    placeholder={t('systemSettings.integerArrayPlaceholder')}
                />
            );
        }

        if (field.type === 'integer' || field.type === 'number' || uiComponent === 'number') {
            const min = typeof field.constraints?.min === 'number' ? field.constraints.min : undefined;
            const max = typeof field.constraints?.max === 'number' ? field.constraints.max : undefined;
            const stepFromUi = field.ui?.step;
            const step = typeof stepFromUi === 'number'
                ? stepFromUi
                : (field.type === 'integer' ? 1 : 0.01);
            return (
                <InputNumber
                    className="w-full"
                    min={min}
                    max={max}
                    step={step}
                    precision={field.type === 'integer' ? 0 : undefined}
                    disabled={disabled}
                />
            );
        }

        if (uiComponent === 'textarea') {
            const rows = typeof field.ui?.rows === 'number' ? field.ui.rows : 3;
            const placeholder = typeof field.ui?.placeholder === 'string' ? field.ui.placeholder : undefined;
            return <Input.TextArea rows={rows} placeholder={placeholder} disabled={disabled}/>;
        }

        const placeholder = typeof field.ui?.placeholder === 'string' ? field.ui.placeholder : undefined;
        return <Input placeholder={placeholder} disabled={disabled}/>;
    };

    if (permissionLoading || loading) {
        return (
            <div className="flex min-h-full items-center justify-center p-6">
                <Spin size="large" tip={t('common.loading')}/>
            </div>
        );
    }

    if (!canRead) {
        return (
            <div className="p-6">
                <Result
                    status="403"
                    title="403"
                    subTitle={t('common.noPermission')}
                />
            </div>
        );
    }

    return (
        <div className="flex min-h-full flex-col p-6">
            <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                    <Title level={4} className="!mb-1">{t('systemSettings.title')}</Title>
                    <Text type="secondary">{t('systemSettings.subtitle')}</Text>
                </div>
                <div className="flex items-center gap-2">
                    <Button icon={<ReloadOutlined/>} onClick={loadBundle} disabled={saving}>
                        {t('common.retry')}
                    </Button>
                    <Button
                        type="primary"
                        icon={<SaveOutlined/>}
                        onClick={handleSave}
                        loading={saving}
                        disabled={!canUpdate}
                    >
                        {t('common.save')}
                    </Button>
                </div>
            </div>

            {!canUpdate ? (
                <Alert className="mb-4" type="info" showIcon message={t('systemSettings.readOnlyHint')}/>
            ) : null}

            <Form form={form} layout="vertical">
                <Tabs
                    activeKey={activeGroup || undefined}
                    onChange={setActiveGroup}
                    items={groupedFields.map((groupItem) => ({
                        key: groupItem.group,
                        label: getGroupTitle(groupItem.group, t),
                        children: (
                            <Card className="!border-0 !shadow-none" bodyStyle={{padding: 0}}>
                                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                                    {groupItem.fields.map((field) => {
                                        const isSwitch = field.type === 'boolean' || getUiComponent(field) === 'switch';
                                        const minLength = typeof field.constraints?.minLength === 'number'
                                            ? field.constraints.minLength
                                            : undefined;
                                        const maxLength = typeof field.constraints?.maxLength === 'number'
                                            ? field.constraints.maxLength
                                            : undefined;
                                        const rules = field.type === 'string'
                                            ? [
                                                ...(typeof minLength === 'number' ? [{min: minLength}] : []),
                                                ...(typeof maxLength === 'number' ? [{max: maxLength}] : []),
                                            ]
                                            : [];

                                        return (
                                            <Form.Item
                                                key={field.key}
                                                name={field.key}
                                                label={field.title}
                                                tooltip={field.key}
                                                valuePropName={isSwitch ? 'checked' : 'value'}
                                                rules={rules}
                                                extra={field.description}
                                            >
                                                {renderFieldControl(field)}
                                            </Form.Item>
                                        );
                                    })}
                                </div>
                            </Card>
                        ),
                    }))}
                />
            </Form>
        </div>
    );
};

export default SystemSettings;
