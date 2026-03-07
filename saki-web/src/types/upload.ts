export type UploadStatus = 'idle' | 'uploading' | 'complete' | 'error';

export type UploadFileStatus = 'success' | 'error';

export interface UploadFileResult {
    id?: string;
    filename: string;
    status: UploadFileStatus;
    error?: string;
}

export interface UploadResult {
    uploaded: number;
    errors: number;
    results: UploadFileResult[];
}

export interface UploadProgress {
    status: UploadStatus;
    currentFile: number;
    totalFiles: number;
    percentage: number;
    currentFilename: string;
    results: UploadFileResult[];
    error?: string;
}

export interface UploadProgressEvent {
    event: 'start' | 'file_start' | 'progress' | 'file_complete' | 'file_error' | 'complete';
    total?: number;
    index?: number;
    filename?: string;
    success?: boolean;
    sampleId?: string;
    error?: string;
    uploaded?: number;
    errors?: number;
    results?: UploadFileResult[];
}
