import {
    AnnotationDraftCommitRequest,
    AnnotationDraftPayload,
    AnnotationDraftRead,
    AnnotationRead,
    AnnotationSyncRequest,
    AnnotationSyncResponse,
    Loop,
    AvailableTypesResponse,
    CommitDiff,
    CommitHistoryItem,
    CommitRead,
    CommitResult,
    Dataset,
    DatasetCreate,
    DatasetUpdate,
    LoginResponse,
    PaginationResponse,
    Project,
    ProjectBranch,
    ProjectCreate,
    ProjectForkCreate,
    ProjectLabel,
    ProjectLabelCreate,
    ProjectLabelUpdate,
    ProjectSample,
    RuntimeRound,
    RoundSelectionApplyRequest,
    RoundSelectionApplyResponse,
    RoundSelectionRead,
    RuntimeRoundCommandResponse,
    RuntimeStep,
    RuntimeRoundArtifactsResponse,
    RuntimeStepArtifactsResponse,
    RuntimeStepCandidate,
    RuntimeStepCommandResponse,
    StepEventQuery,
    StepEventQueryResponse,
    RuntimeStepMetricPoint,
    StepArtifactDownload,
    RoundPredictionCleanupResponse,
    LoopCreateRequest,
    LoopActionRequest,
    LoopActionResponse,
    LoopUpdateRequest,
    LoopSummary,
    LoopSnapshotRead,
    LoopGateResponse,
    LoopLabelReadinessResponse,
    SimulationComparison,
    SimulationExperimentCreateRequest,
    SimulationExperimentCreateResponse,
    RuntimePluginCatalogResponse,
    RuntimeExecutorListResponse,
    RuntimeExecutorRead,
    RuntimeExecutorStatsRange,
    RuntimeExecutorStatsResponse,
    ProjectModel,
    ModelArtifactDownload,
    ResourceMember,
    ResourceMemberCreate,
    ResourceMemberUpdate,
    ResourcePermissions,
    Role,
    RoleCreate,
    RolePermissionCatalog,
    RoleInfo,
    RoleType,
    RoleUpdate,
    Sample,
    SystemSettingsBundle,
    SystemStatus,
    SystemPermissions,
    User,
    UserSystemRole,
    UserSystemRoleAssign,
    ImportDryRunResponse,
    ImportExecuteRequest,
    ImportProgressEvent,
    ImportTaskCreateResponse,
    ImportTaskStatusResponse,
    SampleBulkImportRequest,
    UploadProgressEvent,
    AnnotationBulkRequest,
    ProjectAnnotationImportDryRunRequest,
    ProjectAssociatedImportDryRunRequest,
    ProjectExportChunkRequest,
    ProjectExportChunkResponse,
    ProjectExportResolveRequest,
    ProjectExportResolveResponse,
    ProjectIOCapabilities,
} from '../../types';


export interface ApiService {
    // ============================================================================
    // Auth
    // ============================================================================
    login(username: string, password: string): Promise<LoginResponse>;

    register(email: string, password: string, fullName?: string): Promise<User>;

    getCurrentUser(): Promise<User>;

    changePassword(oldPassword: string, newPassword: string): Promise<{ message: string }>;

    refreshToken(): Promise<LoginResponse>;

    // ============================================================================
    // System
    // ============================================================================
    getSystemStatus(): Promise<SystemStatus>;

    setupSystem(email: string, password: string, fullName?: string): Promise<User>;

    getAvailableTypes(): Promise<AvailableTypesResponse>;

    getSystemSettingsBundle(): Promise<SystemSettingsBundle>;

    updateSystemSettings(values: Record<string, unknown>): Promise<SystemSettingsBundle>;

    // ============================================================================
    // User Management
    // ============================================================================
    getUsers(page?: number, limit?: number): Promise<PaginationResponse<User>>;

    getUserList(
        page?: number,
        limit?: number,
        q?: string,
        resourceType?: 'dataset' | 'project',
        resourceId?: string,
    ): Promise<PaginationResponse<{
        id: string;
        email: string;
        fullName?: string
    }>>;

    createUser(user: Partial<User> & { password: string }): Promise<User>;

    updateUser(id: string, user: Partial<User> & { password?: string }): Promise<User>;

    deleteUser(id: string): Promise<void>;

    updateCurrentUser(user: Partial<User>): Promise<User>;

    uploadUserAvatar(file: File): Promise<User>;

    // ============================================================================
    // Permission APIs
    // ============================================================================

    // Get system-level permissions
    getSystemPermissions(): Promise<SystemPermissions>;

    // Get resource-specific permissions
    getResourcePermissions(resourceType: string, resourceId: string): Promise<ResourcePermissions>;

    // Role management
    getPermissionCatalog(): Promise<RolePermissionCatalog>;

    getRoles(type?: RoleType, page?: number, limit?: number): Promise<PaginationResponse<Role>>;

    getRole(roleId: string): Promise<Role>;

    createRole(role: RoleCreate): Promise<Role>;

    updateRole(roleId: string, role: RoleUpdate): Promise<Role>;

    deleteRole(roleId: string): Promise<{ ok: boolean; message: string }>;

    // User role management
    getUserRoles(userId: string): Promise<UserSystemRole[]>;

    assignUserRole(userId: string, role: UserSystemRoleAssign): Promise<UserSystemRole>;

    revokeUserRole(userId: string, roleId: string): Promise<{ ok: boolean; message: string }>;

    // ============================================================================
    // Dataset APIs
    // ============================================================================
    getDatasets(page?: number, limit?: number, q?: string): Promise<PaginationResponse<Dataset>>;

    getDataset(id: string): Promise<Dataset | undefined>;

    createDataset(dataset: DatasetCreate): Promise<void>;

    updateDataset(id: string, dataset: Partial<DatasetUpdate>): Promise<Dataset>;

    deleteDataset(id: string): Promise<void>;

    // ============================================================================
    // Dataset Members APIs
    // ============================================================================
    getDatasetMembers(datasetId: string): Promise<ResourceMember[]>;

    addDatasetMember(datasetId: string, member: ResourceMemberCreate): Promise<ResourceMember>;

    updateDatasetMemberRole(datasetId: string, userId: string, member: ResourceMemberUpdate): Promise<ResourceMember>;

    removeDatasetMember(datasetId: string, userId: string): Promise<{ ok: boolean; message: string }>;

    getAvailableDatasetRoles(datasetId: string): Promise<RoleInfo[]>;

    // ============================================================================
    // Project APIs
    // ============================================================================
    getProjects(page?: number, limit?: number): Promise<PaginationResponse<Project>>;

    createProject(payload: ProjectCreate): Promise<Project>;
    forkProject(projectId: string, payload: ProjectForkCreate): Promise<Project>;

    getProject(id: string): Promise<Project>;

    updateProject(projectId: string, payload: Partial<Project>): Promise<Project>;
    archiveProject(projectId: string): Promise<Project>;
    unarchiveProject(projectId: string): Promise<Project>;

    getProjectDatasets(projectId: string): Promise<string[]>;
    getProjectDatasetDetails(projectId: string): Promise<Dataset[]>;
    linkProjectDatasets(projectId: string, datasetIds: string[]): Promise<string[]>;
    unlinkProjectDatasets(projectId: string, datasetIds: string[]): Promise<number>;

    getProjectBranches(projectId: string): Promise<ProjectBranch[]>;

    getProjectIOCapabilities(projectId: string): Promise<ProjectIOCapabilities>;

    resolveProjectExport(
        projectId: string,
        payload: ProjectExportResolveRequest,
        signal?: AbortSignal,
    ): Promise<ProjectExportResolveResponse>;

    getProjectExportChunk(
        projectId: string,
        payload: ProjectExportChunkRequest,
        signal?: AbortSignal,
    ): Promise<ProjectExportChunkResponse>;

    getProjectLoops(projectId: string): Promise<Loop[]>;

    createProjectLoop(projectId: string, payload: LoopCreateRequest): Promise<Loop>;

    getLoopById(loopId: string): Promise<Loop>;

    updateLoop(loopId: string, payload: LoopUpdateRequest): Promise<Loop>;

    actLoop(loopId: string, payload: LoopActionRequest): Promise<LoopActionResponse>;
    getLoopSnapshot(loopId: string): Promise<LoopSnapshotRead>;
    getLoopGate(loopId: string): Promise<LoopGateResponse>;
    getLoopLabelReadiness(loopId: string): Promise<LoopLabelReadinessResponse>;
    cleanupRoundPredictions(loopId: string, roundIndex: number): Promise<RoundPredictionCleanupResponse>;

    getLoopSummary(loopId: string): Promise<LoopSummary>;

    createSimulationExperiment(
        projectId: string,
        payload: SimulationExperimentCreateRequest
    ): Promise<SimulationExperimentCreateResponse>;

    getSimulationExperimentComparison(groupId: string, metricName?: string): Promise<SimulationComparison>;

    getRuntimePlugins(): Promise<RuntimePluginCatalogResponse>;

    getLoopRounds(loopId: string, limit?: number): Promise<RuntimeRound[]>;

    stopRound(roundId: string, reason?: string): Promise<RuntimeRoundCommandResponse>;

    getRound(roundId: string): Promise<RuntimeRound>;
    getRoundSelection(roundId: string): Promise<RoundSelectionRead>;
    applyRoundSelection(roundId: string, payload: RoundSelectionApplyRequest): Promise<RoundSelectionApplyResponse>;
    resetRoundSelection(roundId: string): Promise<RoundSelectionApplyResponse>;

    getRoundSteps(roundId: string, limit?: number): Promise<RuntimeStep[]>;
    getRoundArtifacts(roundId: string, limit?: number): Promise<RuntimeRoundArtifactsResponse>;

    getStep(stepId: string): Promise<RuntimeStep>;

    stopStep(stepId: string, reason?: string): Promise<RuntimeStepCommandResponse>;

    getStepEvents(stepId: string, query?: StepEventQuery): Promise<StepEventQueryResponse>;

    getStepMetricSeries(stepId: string, limit?: number): Promise<RuntimeStepMetricPoint[]>;

    getStepCandidates(stepId: string, limit?: number): Promise<RuntimeStepCandidate[]>;

    getStepArtifacts(stepId: string): Promise<RuntimeStepArtifactsResponse>;

    getStepArtifactDownloadUrl(stepId: string, artifactName: string, expiresInHours?: number): Promise<StepArtifactDownload>;

    getRuntimeExecutors(): Promise<RuntimeExecutorListResponse>;

    getRuntimeExecutorStats(range: RuntimeExecutorStatsRange): Promise<RuntimeExecutorStatsResponse>;

    getRuntimeExecutor(executorId: string): Promise<RuntimeExecutorRead>;

    registerModelFromRound(projectId: string, payload: {
        roundId: string;
        name?: string;
        versionTag?: string;
        status?: string;
    }): Promise<ProjectModel>;

    getProjectModels(projectId: string, limit?: number): Promise<ProjectModel[]>;

    promoteModel(modelId: string, status?: string): Promise<ProjectModel>;

    getModelArtifactDownloadUrl(modelId: string, artifactName: string, expiresInHours?: number): Promise<ModelArtifactDownload>;

    getAssetDownloadUrl(
        assetId: string,
        expiresInHours?: number,
        datasetId?: string,
    ): Promise<{
        assetId: string;
        downloadUrl: string;
        expiresIn: number;
        filename?: string;
    }>;

    createProjectBranch(
        projectId: string,
        payload: {
            name: string;
            fromCommitId: string;
            description?: string;
        }
    ): Promise<ProjectBranch>;

    updateBranch(
        projectId: string,
        branchId: string,
        payload: {
            name?: string;
            description?: string;
            isProtected?: boolean;
        }
    ): Promise<ProjectBranch>;

    deleteBranch(projectId: string, branchId: string): Promise<void>;

    getProjectCommits(projectId: string): Promise<CommitHistoryItem[]>;

    getCommitHistory(commitId: string, depth?: number): Promise<CommitHistoryItem[]>;

    getCommit(commitId: string): Promise<CommitRead>;

    getCommitDiff(commitId: string, compareWithId?: string): Promise<CommitDiff>;

    getProjectMembers(projectId: string): Promise<ResourceMember[]>;
    getAvailableProjectRoles(projectId: string): Promise<RoleInfo[]>;

    addProjectMember(projectId: string, member: ResourceMemberCreate): Promise<void>;

    updateProjectMemberRole(projectId: string, userId: string, member: ResourceMemberUpdate): Promise<void>;

    removeProjectMember(projectId: string, userId: string): Promise<void>;

    getProjectLabels(projectId: string): Promise<ProjectLabel[]>;

    createProjectLabel(projectId: string, payload: ProjectLabelCreate): Promise<ProjectLabel>;

    updateProjectLabel(projectId: string, labelId: string, payload: ProjectLabelUpdate): Promise<ProjectLabel>;

    deleteProjectLabel(projectId: string, labelId: string): Promise<void>;

    getProjectSamples(
        projectId: string,
        datasetId: string,
        params: {
            q?: string;
            status?: 'all' | 'labeled' | 'unlabeled' | 'draft';
            branchName?: string;
            sortBy?: string;
            sortOrder?: 'asc' | 'desc';
            page?: number;
            limit?: number;
        }
    ): Promise<PaginationResponse<ProjectSample>>;

    getAnnotationsAtCommit(projectId: string, commitId: string, sampleId?: string): Promise<AnnotationRead[]>;

    getWorkingAnnotations(projectId: string, sampleId: string, branchName?: string): Promise<AnnotationDraftPayload | null>;

    upsertWorkingAnnotations(
        projectId: string,
        sampleId: string,
        payload: AnnotationDraftPayload & { branchName?: string }
    ): Promise<void>;

    syncWorkingToDraft(
        projectId: string,
        sampleId: string,
        branchName?: string,
        reviewEmpty?: boolean
    ): Promise<AnnotationDraftRead | null>;

    listAnnotationDrafts(
        projectId: string,
        branchName?: string,
        sampleId?: string
    ): Promise<AnnotationDraftRead[]>;

    commitAnnotationDrafts(projectId: string, payload: AnnotationDraftCommitRequest): Promise<CommitResult>;

    syncAnnotation(projectId: string, sampleId: string, payload: AnnotationSyncRequest): Promise<AnnotationSyncResponse>;

    // ============================================================================
    // Import APIs
    // ============================================================================
    dryRunDatasetImageImport(
        datasetId: string,
        file: File,
        options?: {
            pathFlattenMode?: 'basename' | 'preserve_path';
            nameCollisionPolicy?: 'abort' | 'auto_rename' | 'overwrite';
        },
    ): Promise<ImportDryRunResponse>;

    executeDatasetImageImport(
        datasetId: string,
        payload: ImportExecuteRequest,
    ): Promise<ImportTaskCreateResponse>;

    dryRunProjectAnnotationImport(
        projectId: string,
        payload: ProjectAnnotationImportDryRunRequest,
    ): Promise<ImportDryRunResponse>;

    executeProjectAnnotationImport(
        projectId: string,
        payload: ImportExecuteRequest,
    ): Promise<ImportTaskCreateResponse>;

    dryRunProjectAssociatedImport(
        projectId: string,
        payload: ProjectAssociatedImportDryRunRequest,
    ): Promise<ImportDryRunResponse>;

    executeProjectAssociatedImport(
        projectId: string,
        payload: ImportExecuteRequest,
    ): Promise<ImportTaskCreateResponse>;

    getImportTaskStatus(taskId: string): Promise<ImportTaskStatusResponse>;

    streamImportTaskEvents(
        taskId: string,
        afterSeq: number,
        onProgress: (event: ImportProgressEvent) => void,
        signal?: AbortSignal,
    ): Promise<void>;

    bulkUploadSamples(
        datasetId: string,
        files: File[],
    ): Promise<ImportTaskCreateResponse>;

    bulkImportSamples(
        datasetId: string,
        payload: SampleBulkImportRequest,
    ): Promise<ImportTaskCreateResponse>;

    bulkSaveAnnotations(
        projectId: string,
        payload: AnnotationBulkRequest,
    ): Promise<ImportTaskCreateResponse>;

    // ============================================================================
    // Sample APIs
    // ============================================================================
    getSamples(datasetId: string,
               page?: number,
               limit?: number,
               sortBy?: string,
               sortOrder?: 'asc' | 'desc',
               q?: string
    ): Promise<PaginationResponse<Sample>>;

    deleteSample(datasetId: string, sampleId: string, force?: boolean): Promise<void>;

    uploadSamplesWithProgress(
        datasetId: string,
        files: File[],
        onProgress: (event: UploadProgressEvent) => void,
        signal?: AbortSignal
    ): Promise<void>;
}
