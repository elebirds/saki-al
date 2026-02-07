// ============================================================================
// Annotation Hooks
// ============================================================================

export {useAnnotationState} from './annotation/useAnnotationState';
export {useAnnotationShortcuts} from './annotation/useAnnotationShortcuts';
export {useFedoAnnotations} from './annotation/useFedoAnnotations';
export {useAnnotationSync} from './annotation/useAnnotationSync';
export {useWorkspaceCommon} from './annotation/useWorkspaceCommon';
export {useWorkingDraftPipeline} from './annotation/useWorkingDraftPipeline';

export type {
    AnnotationLike, UseAnnotationStateReturn, UseAnnotationStateOptions
} from './annotation/useAnnotationState';
export type {UseAnnotationShortcutsOptions} from './annotation/useAnnotationShortcuts';
export type {UseFedoAnnotationsReturn, UseFedoAnnotationsOptions} from './annotation/useFedoAnnotations';
export type {UseAnnotationSyncReturn, UseAnnotationSyncOptions} from './annotation/useAnnotationSync';
export type {UseWorkspaceCommonReturn, UseWorkspaceCommonOptions} from './annotation/useWorkspaceCommon';
export type {UseWorkingDraftPipelineReturn, UseWorkingDraftPipelineOptions} from './annotation/useWorkingDraftPipeline';

// ============================================================================
// Project Hooks
// ============================================================================

export {useProjectSampleList} from './project/useProjectSampleList';
export type {
    UseProjectSampleListOptions, ProjectSampleFilters, ProjectSampleListMeta
} from './project/useProjectSampleList';

// ============================================================================
// Permission Hooks
// ============================================================================

export {
    usePermission,
    useResourcePermission,
    useInitPermissions,
    useAnnotationPermission,
} from './permission';
export type {Scope as AccessScope} from '../types';

// ============================================================================
// System Hooks
// ============================================================================

export {useSystemCapabilities, useInitSystemCapabilities} from './system/useSystemCapabilities';

// ============================================================================
// Upload Hooks
// ============================================================================

export {useUpload} from './upload/useUpload';

// ============================================================================
// Pagination Hooks
// ============================================================================

export {usePagination} from './usePagination';
