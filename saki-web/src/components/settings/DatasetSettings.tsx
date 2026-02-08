import React, {useState} from 'react';
import {Button, Card, Divider, Form, Input, message, Popconfirm, Tabs} from 'antd';
import {useTranslation} from 'react-i18next';
import {useNavigate} from 'react-router-dom';
import {Dataset} from '../../types';
import {api} from '../../services/api';
import {DeleteOutlined, SaveOutlined} from '@ant-design/icons';
import DatasetMembers from './DatasetMembers';
import {useResourcePermission} from '../../hooks';

interface DatasetSettingsProps {
    dataset: Dataset;
    onUpdate: (dataset: Dataset) => void;
}

const DatasetSettings: React.FC<DatasetSettingsProps> = ({dataset, onUpdate}) => {
    const {t} = useTranslation();
    const navigate = useNavigate();
    const [form] = Form.useForm();
    const [loading, setLoading] = useState(false);
    const [activeTab, setActiveTab] = useState('basic');

    // Permission check
    const {can} = useResourcePermission('dataset', dataset.id);
    const canManageMembers = can('dataset:assign');

    React.useEffect(() => {
        form.setFieldsValue({
            name: dataset.name,
            description: dataset.description,
        });
    }, [dataset, form]);

    const handleSave = async (values: any) => {
        setLoading(true);
        try {
            const updated = await api.updateDataset(dataset.id, {
                name: values.name,
                description: values.description,
            });
            onUpdate(updated);
            message.success(t('dataset.settings.successMessage'));
        } catch (error) {
            message.error(t('dataset.settings.errorMessage'));
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async () => {
        try {
            await api.deleteDataset(dataset.id);
            message.success(t('dataset.settings.deleteSuccess'));
            navigate('/');
        } catch (error) {
            message.error(t('dataset.settings.deleteError'));
        }
    };

    const tabItems = [
        {
            key: 'basic',
            label: t('dataset.settings.basicInfo'),
            children: (
                <Card title={t('dataset.settings.basicInfo')}>
                    <Form
                        form={form}
                        layout="vertical"
                        onFinish={handleSave}
                    >
                        <Form.Item
                            label={t('dataset.settings.datasetName')}
                            name="name"
                            rules={[
                                {required: true, message: t('dataset.settings.nameRequired')},
                                {min: 1, max: 100},
                            ]}
                        >
                            <Input placeholder={t('dataset.settings.namePlaceholder')}/>
                        </Form.Item>

                        <Form.Item
                            label={t('dataset.settings.description')}
                            name="description"
                        >
                            <Input.TextArea
                                placeholder={t('dataset.settings.descriptionPlaceholder')}
                                rows={4}
                            />
                        </Form.Item>

                        <Form.Item>
                            <div className="flex items-center gap-2">
                                <Button type="primary" icon={<SaveOutlined/>} htmlType="submit" loading={loading}>
                                    {t('dataset.settings.saveBasicInfo')}
                                </Button>
                            </div>
                        </Form.Item>
                    </Form>

                    <Divider/>

                    <Card title={t('dataset.settings.dangerZone')} className="!border !border-red-500">
                        <p>{t('dataset.settings.deleteConfirmDesc')}</p>
                        <Popconfirm
                            title={t('dataset.settings.deleteConfirm')}
                            description={t('dataset.settings.deleteConfirmDesc')}
                            onConfirm={handleDelete}
                            okText={t('common.yes')}
                            cancelText={t('common.no')}
                            okButtonProps={{danger: true}}
                        >
                            <Button danger icon={<DeleteOutlined/>}>
                                {t('dataset.settings.deleteDataset')}
                            </Button>
                        </Popconfirm>
                    </Card>
                </Card>
            ),
        },
        ...(canManageMembers ? [{
            key: 'members',
            label: t('dataset.members.title'),
            children: (
                <DatasetMembers datasetId={dataset.id} ownerId={dataset.ownerId}/>
            ),
        }] : []),
    ];

    return (
        <div>
            <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems}/>
        </div>
    );
};

export default DatasetSettings;
