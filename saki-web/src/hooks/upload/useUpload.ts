import { useState, useCallback, useRef } from 'react';
import { UploadProgress, UploadProgressEvent, UploadFileResult, UploadResult } from '../../types';
import { api } from '../../services/api';

interface UseUploadOptions {
  /** Callback for each file completion */
  onFileComplete?: (result: UploadFileResult) => void;
  /** Callback when upload starts */
  onStart?: (totalFiles: number) => void;
  /** Callback when upload completes */
  onComplete?: (result: UploadResult) => void;
  /** Callback for errors */
  onError?: (error: string) => void;
}

export function useUpload(datasetId: string, options: UseUploadOptions = {}) {
  const { onFileComplete, onStart, onComplete, onError } = options;
  const abortControllerRef = useRef<AbortController | null>(null);

  const [progress, setProgress] = useState<UploadProgress>({
    status: 'idle',
    currentFile: 0,
    totalFiles: 0,
    percentage: 0,
    currentFilename: '',
    results: [],
  });

  const reset = useCallback(() => {
    setProgress({
      status: 'idle',
      currentFile: 0,
      totalFiles: 0,
      percentage: 0,
      currentFilename: '',
      results: [],
    });
  }, []);

  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setProgress((prev) => ({
      ...prev,
      status: 'error',
      error: 'Upload cancelled',
    }));
  }, []);

  const handleProgressEvent = useCallback(
    (event: UploadProgressEvent) => {
      switch (event.event) {
        case 'start':
          setProgress((prev) => ({
            ...prev,
            status: 'uploading',
            totalFiles: event.total || prev.totalFiles,
          }));
          break;

        case 'file_start':
          setProgress((prev) => ({
            ...prev,
            currentFile: (event.index || 0) + 1,
            currentFilename: event.filename || '',
            percentage: ((event.index || 0) / prev.totalFiles) * 100,
          }));
          break;

        case 'file_complete':
          const fileResult: UploadFileResult = {
            id: event.sampleId,
            filename: event.filename || '',
            status: event.success ? 'success' : 'error',
            error: event.error,
          };
          setProgress((prev) => ({
            ...prev,
            results: [...prev.results, fileResult],
            percentage: (((event.index || 0) + 1) / prev.totalFiles) * 100,
          }));
          onFileComplete?.(fileResult);
          break;

        case 'file_error':
          const errorResult: UploadFileResult = {
            filename: event.filename || '',
            status: 'error',
            error: event.error,
          };
          setProgress((prev) => ({
            ...prev,
            results: [...prev.results, errorResult],
          }));
          onFileComplete?.(errorResult);
          break;

        case 'complete':
          const uploadResult: UploadResult = {
            uploaded: event.uploaded || 0,
            errors: event.errors || 0,
            results: event.results || [],
          };
          setProgress((prev) => ({
            ...prev,
            status: 'complete',
            percentage: 100,
          }));
          onComplete?.(uploadResult);
          break;
      }
    },
    [onFileComplete, onComplete]
  );

  const upload = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;

      abortControllerRef.current = new AbortController();

      setProgress({
        status: 'uploading',
        currentFile: 0,
        totalFiles: files.length,
        percentage: 0,
        currentFilename: '',
        results: [],
      });

      onStart?.(files.length);

      try {
        await api.uploadSamplesWithProgress(
          datasetId,
          files,
          handleProgressEvent,
          abortControllerRef.current.signal
        );
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
          return;
        }
        const errorMsg = error instanceof Error ? error.message : 'Upload failed';
        setProgress((prev) => ({
          ...prev,
          status: 'error',
          error: errorMsg,
        }));
        onError?.(errorMsg);
      }
    },
    [datasetId, handleProgressEvent, onStart, onError]
  );

  return {
    progress,
    upload,
    cancel,
    reset,
    isUploading: progress.status === 'uploading',
    isComplete: progress.status === 'complete',
    hasError: progress.status === 'error',
  };
}

export default useUpload;
