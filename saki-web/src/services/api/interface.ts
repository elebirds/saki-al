import { Project, Sample, Annotation, QueryStrategy, BaseModel, ModelVersion, User, LoginResponse, AvailableTypes, Dataset, Label, LabelCreate, LabelUpdate, UploadProgressEvent, UploadResult, SyncAction, SyncResponse, BatchSaveResult, SampleAnnotationsResponse, DatasetMember, DatasetMemberCreate, DatasetMemberUpdate, GlobalRole } from '../../types';

/**
 * Callback type for upload progress events
 */
export type UploadProgressCallback = (event: UploadProgressEvent) => void;

export interface ApiService {
  // Auth
  login(username: string, password: string): Promise<LoginResponse>;
  register(email: string, password: string, fullName?: string): Promise<User>;
  getCurrentUser(): Promise<User>;

  // System
  getSystemStatus(): Promise<{ initialized: boolean }>;
  setupSystem(email: string, password: string, fullName?: string): Promise<User>;
  refreshToken(): Promise<LoginResponse>;
  
  // Types & Capabilities
  getAvailableTypes(): Promise<AvailableTypes>;

  // Dataset APIs (for data annotation)
  getDatasets(): Promise<Dataset[]>;
  getDataset(id: string): Promise<Dataset | undefined>;
  createDataset(dataset: Omit<Dataset, 'id' | 'createdAt' | 'updatedAt' | 'sampleCount' | 'labeledCount'>): Promise<Dataset>;
  updateDataset(id: string, dataset: Partial<Dataset>): Promise<Dataset>;
  deleteDataset(id: string): Promise<void>;
  getDatasetStats(id: string): Promise<{
    datasetId: string;
    totalSamples: number;
    labeledSamples: number;
    unlabeledSamples: number;
    skippedSamples: number;
    completionRate: number;
    linkedProjects: number;
  }>;
  exportDataset(id: string, format?: string, includeUnlabeled?: boolean): Promise<any>;

  // Label APIs (belong to Dataset)
  getLabels(datasetId: string): Promise<Label[]>;
  createLabel(datasetId: string, label: LabelCreate): Promise<Label>;
  createLabelsBatch(datasetId: string, labels: LabelCreate[]): Promise<Label[]>;
  updateLabel(labelId: string, label: LabelUpdate): Promise<Label>;
  deleteLabel(labelId: string, force?: boolean): Promise<{ ok: boolean; deletedLabel: string; deletedAnnotations: number }>;

  // Sample APIs (belong to Dataset)
  getSamples(datasetId: string): Promise<Sample[]>;
  getSample(sampleId: string): Promise<Sample | undefined>;
  uploadSamplesWithProgress(
    datasetId: string,
    files: File[],
    onProgress?: UploadProgressCallback,
    signal?: AbortSignal
  ): Promise<UploadResult>;
  
  // Annotation APIs
  getSampleAnnotations(sampleId: string): Promise<SampleAnnotationsResponse>;
  syncAnnotations(sampleId: string, actions: SyncAction[]): Promise<SyncResponse>;
  saveAnnotations(sampleId: string, annotations: Annotation[], updateStatus?: 'labeled' | 'skipped'): Promise<BatchSaveResult>;
  
  // Dataset Member APIs (for permission management)
  getDatasetMembers(datasetId: string): Promise<DatasetMember[]>;
  addDatasetMember(datasetId: string, member: DatasetMemberCreate): Promise<DatasetMember>;
  updateDatasetMemberRole(datasetId: string, userId: string, memberUpdate: DatasetMemberUpdate): Promise<DatasetMember>;
  removeDatasetMember(datasetId: string, userId: string): Promise<{ ok: boolean; message: string }>;
  
  // Config APIs
  getStrategies(): Promise<QueryStrategy[]>;
  getBaseModels(): Promise<BaseModel[]>;

  // Project APIs (for active learning - optional, can be added later)
  getProjects(): Promise<Project[]>;
  getProject(id: string): Promise<Project | undefined>;
  createProject(project: Omit<Project, 'id' | 'createdAt' | 'stats'>): Promise<Project>;
  updateProject(id: string, project: Partial<Project>): Promise<Project>;
  deleteProject(id: string): Promise<void>;
  trainProject(projectId: string): Promise<void>;
  querySamples(projectId: string, n: number): Promise<Sample[]>;
  getModelVersions(projectId: string): Promise<ModelVersion[]>;

  // User Management
  getUsers(skip?: number, limit?: number): Promise<User[]>;
  createUser(user: Partial<User> & { password: string; globalRole?: GlobalRole }): Promise<User>;
  updateUser(id: string, user: Partial<User> & { password?: string; globalRole?: GlobalRole }): Promise<User>;
  deleteUser(id: string): Promise<void>;
}
