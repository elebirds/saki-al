import type {
    ImportFormat,
    ProjectAnnotationImportDryRunRequest,
    ProjectAssociatedImportDryRunRequest,
} from '../../../types';

export type Assert<T extends true> = T;

export type HasFormatProfileInAnnotation = 'formatProfile' extends keyof ProjectAnnotationImportDryRunRequest ? true : false;
export type HasFormatInAnnotation = 'format' extends keyof ProjectAnnotationImportDryRunRequest ? true : false;
export type AssertFormatProfileInAnnotation = Assert<HasFormatProfileInAnnotation>;
export type AssertNoLegacyFormatInAnnotation = Assert<HasFormatInAnnotation extends false ? true : false>;

export type HasFormatProfileInAssociated = 'formatProfile' extends keyof ProjectAssociatedImportDryRunRequest ? true : false;
export type HasFormatInAssociated = 'format' extends keyof ProjectAssociatedImportDryRunRequest ? true : false;
export type AssertFormatProfileInAssociated = Assert<HasFormatProfileInAssociated>;
export type AssertNoLegacyFormatInAssociated = Assert<HasFormatInAssociated extends false ? true : false>;

const importFormats: ImportFormat[] = ['coco', 'voc', 'yolo', 'yolo_obb'];
void importFormats;

export const projectImportWorkspaceManualChecklist = [
    '导入页格式选项来自 io-capabilities.import_profiles。',
    '不可用 profile（available=false）不会出现在可选列表中。',
    '请求参数统一使用 format_profile（前端字段 formatProfile）。',
    '选择 yolo_obb 时展示 YOLO 子格式选项（obb_rbox / obb_poly8）。',
] as const;
