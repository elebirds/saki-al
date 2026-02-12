import {
    AnnotationDraftCommitRequest,
    AnnotationDraftPayload,
    AnnotationDraftRead,
    AnnotationRead,
    AnnotationSyncRequest,
    AnnotationSyncResponse,
    ALLoop,
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
    RuntimeJob,
    RuntimeJobCommandResponse,
    RuntimeJobCreateRequest,
    RuntimeJobTask,
    RuntimeTaskArtifactsResponse,
    RuntimeTaskCandidate,
    RuntimeTaskCommandResponse,
    RuntimeTaskEvent,
    RuntimeTaskMetricPoint,
    TaskArtifactDownload,
    LoopCreateRequest,
    LoopConfirmResponse,
    LoopUpdateRequest,
    LoopSummary,
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
    UploadProgressEvent,
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

    getUserList(page?: number, limit?: number, q?: string): Promise<PaginationResponse<{
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

    getProjectLoops(projectId: string): Promise<ALLoop[]>;

    createProjectLoop(projectId: string, payload: LoopCreateRequest): Promise<ALLoop>;

    getLoopById(loopId: string): Promise<ALLoop>;

    updateLoop(loopId: string, payload: LoopUpdateRequest): Promise<ALLoop>;

    startLoop(loopId: string): Promise<ALLoop>;

    confirmLoop(loopId: string): Promise<LoopConfirmResponse>;

    pauseLoop(loopId: string): Promise<ALLoop>;

    resumeLoop(loopId: string): Promise<ALLoop>;

    stopLoop(loopId: string): Promise<ALLoop>;

    getLoopSummary(loopId: string): Promise<LoopSummary>;

    createSimulationExperiment(
        projectId: string,
        payload: SimulationExperimentCreateRequest
    ): Promise<SimulationExperimentCreateResponse>;

    getSimulationExperimentComparison(groupId: string, metricName?: string): Promise<SimulationComparison>;

    getRuntimePlugins(): Promise<RuntimePluginCatalogResponse>;

    getLoopJobs(loopId: string, limit?: number): Promise<RuntimeJob[]>;

    createLoopJob(loopId: string, payload: RuntimeJobCreateRequest): Promise<RuntimeJob>;

    stopJob(jobId: string, reason?: string): Promise<RuntimeJobCommandResponse>;

    getJob(jobId: string): Promise<RuntimeJob>;

    getJobTasks(jobId: string, limit?: number): Promise<RuntimeJobTask[]>;

    getTask(taskId: string): Promise<RuntimeJobTask>;

    stopTask(taskId: string, reason?: string): Promise<RuntimeTaskCommandResponse>;

    getTaskEvents(taskId: string, afterSeq?: number, limit?: number): Promise<RuntimeTaskEvent[]>;

    getTaskMetricSeries(taskId: string, limit?: number): Promise<RuntimeTaskMetricPoint[]>;

    getTaskCandidates(taskId: string, limit?: number): Promise<RuntimeTaskCandidate[]>;

    getTaskArtifacts(taskId: string): Promise<RuntimeTaskArtifactsResponse>;

    getTaskArtifactDownloadUrl(taskId: string, artifactName: string, expiresInHours?: number): Promise<TaskArtifactDownload>;

    getRuntimeExecutors(): Promise<RuntimeExecutorListResponse>;

    getRuntimeExecutorStats(range: RuntimeExecutorStatsRange): Promise<RuntimeExecutorStatsResponse>;

    getRuntimeExecutor(executorId: string): Promise<RuntimeExecutorRead>;

    registerModelFromJob(projectId: string, payload: {
        jobId: string;
        name?: string;
        versionTag?: string;
        status?: string;
    }): Promise<ProjectModel>;

    getProjectModels(projectId: string, limit?: number): Promise<ProjectModel[]>;

    promoteModel(modelId: string, status?: string): Promise<ProjectModel>;

    getModelArtifactDownloadUrl(modelId: string, artifactName: string, expiresInHours?: number): Promise<ModelArtifactDownload>;

    getAssetDownloadUrl(
        assetId: string,
        expiresInHours?: number
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
        branchId: string,
        payload: {
            name?: string;
            description?: string;
            isProtected?: boolean;
        }
    ): Promise<ProjectBranch>;

    deleteBranch(branchId: string): Promise<void>;

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

    updateProjectLabel(labelId: string, payload: ProjectLabelUpdate): Promise<ProjectLabel>;

    deleteProjectLabel(labelId: string): Promise<void>;

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

    getAnnotationsAtCommit(commitId: string, sampleId?: string): Promise<AnnotationRead[]>;

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
    // Sample APIs
    // ============================================================================
    getSamples(datasetId: string,
               page?: number,
               limit?: number,
               sortBy?: string,
               sortOrder?: 'asc' | 'desc',
               q?: string
    ): Promise<PaginationResponse<Sample>>;

    deleteSample(datasetId: string, sampleId: string): Promise<void>;

    uploadSamplesWithProgress(
        datasetId: string,
        files: File[],
        onProgress: (event: UploadProgressEvent) => void,
        signal?: AbortSignal
    ): Promise<void>;
}
