import type {
    ExportBundleLayout,
    FormatProfileId,
    ProjectExportChunkFile,
    ProjectExportChunkRequest,
    ProjectExportChunkResponse,
    ProjectExportResolveRequest,
    SampleScope,
    YoloLabelFormat,
} from '../../../types';
import type {ApiService} from '../../../services/api/interface';

export type Assert<T extends true> = T;

export type HasResolveApi = 'resolveProjectExport' extends keyof ApiService ? true : false;
export type HasChunkApi = 'getProjectExportChunk' extends keyof ApiService ? true : false;
export type AssertResolveApi = Assert<HasResolveApi>;
export type AssertChunkApi = Assert<HasChunkApi>;

export type HasFormatProfile = 'formatProfile' extends keyof ProjectExportResolveRequest ? true : false;
export type AssertFormatProfile = Assert<HasFormatProfile>;
export type HasYoloLabelFormat = 'yoloLabelFormat' extends keyof ProjectExportResolveRequest ? true : false;
export type AssertYoloLabelFormat = Assert<HasYoloLabelFormat>;

export type HasResolvedCommitId = 'resolvedCommitId' extends keyof ProjectExportChunkRequest ? true : false;
export type AssertResolvedCommitId = Assert<HasResolvedCommitId>;
export type HasChunkFormatProfile = 'formatProfile' extends keyof ProjectExportChunkRequest ? true : false;
export type AssertChunkFormatProfile = Assert<HasChunkFormatProfile>;
export type HasChunkYoloLabelFormat = 'yoloLabelFormat' extends keyof ProjectExportChunkRequest ? true : false;
export type AssertChunkYoloLabelFormat = Assert<HasChunkYoloLabelFormat>;
export type HasChunkBundleLayout = 'bundleLayout' extends keyof ProjectExportChunkRequest ? true : false;
export type AssertChunkBundleLayout = Assert<HasChunkBundleLayout>;

export type HasChunkFiles = 'files' extends keyof ProjectExportChunkResponse ? true : false;
export type AssertChunkFiles = Assert<HasChunkFiles>;
export type HasSampleCount = 'sampleCount' extends keyof ProjectExportChunkResponse ? true : false;
export type AssertSampleCount = Assert<HasSampleCount>;
export type HasChunkItems = 'items' extends keyof ProjectExportChunkResponse ? true : false;
export type AssertNoChunkItems = Assert<HasChunkItems extends false ? true : false>;
export type HasChunkLabels = 'labels' extends keyof ProjectExportChunkResponse ? true : false;
export type AssertNoChunkLabels = Assert<HasChunkLabels extends false ? true : false>;
export type HasFilePath = 'path' extends keyof ProjectExportChunkFile ? true : false;
export type AssertFilePath = Assert<HasFilePath>;

const formatProfiles: FormatProfileId[] = ['coco', 'voc', 'yolo', 'yolo_obb', 'dota'];
const yoloLabelFormats: YoloLabelFormat[] = ['det', 'obb_rbox', 'obb_poly8'];
const sampleScopes: SampleScope[] = ['all', 'labeled', 'unlabeled'];
const layouts: ExportBundleLayout[] = ['merged_zip', 'per_dataset_zip'];

void formatProfiles;
void yoloLabelFormats;
void sampleScopes;
void layouts;

export const projectExportWorkspaceManualChecklist = [
    'HTTPS + 支持 File System Access API 的浏览器：使用本地文件流式写入导出。',
    '不支持 File System Access API 或非安全上下文：自动回退为内存打包下载，按钮仍可用。',
    '选择 merged_zip：导出单个 ZIP，目录中包含 datasets/<dataset>/...。',
    '选择 per_dataset_zip：选择目录后，为每个数据集生成一个 ZIP 文件。',
    '选择 yolo_obb：可切换 OBB RBox / OBB Poly8，导出请求需携带 yoloLabelFormat。',
    '导出中点击取消：请求中断，文件流关闭，状态显示已取消。',
] as const;
