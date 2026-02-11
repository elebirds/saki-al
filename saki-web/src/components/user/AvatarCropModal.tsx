import React, {useEffect, useRef, useState} from 'react';
import {Button, Modal, Slider, Typography} from 'antd';
import {ReloadOutlined, ZoomInOutlined, ZoomOutOutlined} from '@ant-design/icons';
import {useTranslation} from 'react-i18next';
import AvatarEditor from 'react-avatar-editor';

const OUTPUT_SIZE = 128;
const EDITOR_SIZE = 320;
const DEFAULT_POSITION = {x: 0.5, y: 0.5};

export interface AvatarCropModalProps {
    open: boolean;
    sourceFile: File | null;
    uploading?: boolean;
    onCancel: () => void;
    onConfirm: (file: File) => Promise<void> | void;
}

export const AvatarCropModal: React.FC<AvatarCropModalProps> = ({
                                                                      open,
                                                                      sourceFile,
                                                                      uploading = false,
                                                                      onCancel,
                                                                      onConfirm,
                                                                  }) => {
    const {t} = useTranslation();
    const editorRef = useRef<AvatarEditor | null>(null);
    const [zoom, setZoom] = useState(1);
    const [position, setPosition] = useState(DEFAULT_POSITION);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (!open || !sourceFile) {
            return;
        }
        setZoom(1);
        setPosition(DEFAULT_POSITION);
    }, [sourceFile, open]);

    const handleReset = () => {
        setZoom(1);
        setPosition(DEFAULT_POSITION);
    };

    const buildCroppedFile = async (): Promise<File> => {
        if (!sourceFile || !editorRef.current) {
            throw new Error('Invalid crop state');
        }
        const croppedCanvas = editorRef.current.getImageScaledToCanvas();
        const outputCanvas = document.createElement('canvas');
        outputCanvas.width = OUTPUT_SIZE;
        outputCanvas.height = OUTPUT_SIZE;
        const context = outputCanvas.getContext('2d');
        if (!context) {
            throw new Error('Canvas context not available.');
        }
        context.drawImage(croppedCanvas, 0, 0, OUTPUT_SIZE, OUTPUT_SIZE);

        const blob = await new Promise<Blob | null>((resolve) => {
            outputCanvas.toBlob(resolve, 'image/png');
        });
        if (!blob) {
            throw new Error('Unable to generate avatar image.');
        }
        const nameWithoutExt = sourceFile.name.replace(/\.[^/.]+$/, '') || 'avatar';
        return new File([blob], `${nameWithoutExt}-avatar.png`, {type: 'image/png'});
    };

    const handleConfirm = async () => {
        try {
            setSaving(true);
            const file = await buildCroppedFile();
            await onConfirm(file);
        } finally {
            setSaving(false);
        }
    };

    const busy = uploading || saving;

    return (
        <Modal
            title={t('user.profile.avatarCropTitle')}
            open={open}
            onCancel={busy ? undefined : onCancel}
            width={760}
            destroyOnClose
            footer={[
                <Button key="cancel" onClick={onCancel} disabled={busy}>
                    {t('common.cancel')}
                </Button>,
                <Button key="save" type="primary" onClick={handleConfirm} loading={busy} disabled={!sourceFile}>
                    {t('user.profile.avatarCropConfirm')}
                </Button>,
            ]}
        >
            <div className="space-y-4">
                <div className="flex justify-center rounded-md border border-github-border bg-github-base p-4">
                    {sourceFile ? (
                        <AvatarEditor
                            ref={editorRef}
                            image={sourceFile}
                            width={EDITOR_SIZE}
                            height={EDITOR_SIZE}
                            border={12}
                            borderRadius={EDITOR_SIZE / 2}
                            color={[0, 0, 0, 0.35]}
                            scale={zoom}
                            position={position}
                            onPositionChange={(nextPosition: { x: number; y: number }) => setPosition(nextPosition)}
                            rotate={0}
                        />
                    ) : null}
                </div>

                <div className="flex items-center gap-3">
                    <ZoomOutOutlined className="text-github-muted"/>
                    <Slider
                        min={1}
                        max={3}
                        step={0.01}
                        value={zoom}
                        onChange={(value) => setZoom(Array.isArray(value) ? value[0] : value)}
                        className="flex-1"
                    />
                    <ZoomInOutlined className="text-github-muted"/>
                    <Button icon={<ReloadOutlined/>} onClick={handleReset} disabled={busy}>
                        {t('user.profile.avatarCropReset')}
                    </Button>
                </div>

                <Typography.Text type="secondary" className="text-xs">
                    {t('user.profile.avatarCropHint')}
                </Typography.Text>
            </div>
        </Modal>
    );
};
