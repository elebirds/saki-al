import { useState, useCallback, useRef } from 'react';
import { UploadProgress, UploadProgressEvent, UploadFileResult, UploadResult } from '../types';
import { useAuthStore } from '../store/authStore';

// Use same base URL as the API service
const API_BASE_URL = 'http://localhost:8000/api/v1';

interface UseUploadOptions {
  /** Use SSE streaming for progress updates */
  useStreaming?: boolean;
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
  const { useStreaming = true, onFileComplete, onStart, onComplete, onError } = options;
  const token = useAuthStore((state) => state.token);
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

  const uploadWithStreaming = useCallback(
    async (files: File[]) => {
      const formData = new FormData();
      files.forEach((file) => formData.append('files', file));

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
        const response = await fetch(`${API_BASE_URL}/samples/${datasetId}/samples/stream`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${token}`,
          },
          body: formData,
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          throw new Error(`Upload failed: ${response.statusText}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error('No response body');
        }

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const event: UploadProgressEvent = JSON.parse(line.slice(6));
                handleProgressEvent(event);
              } catch (e) {
                console.error('Failed to parse SSE event:', e);
              }
            }
          }
        }
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
    [datasetId, token, onStart, onError]
  );

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
            percentage: ((event.index || 0) + 1) / prev.totalFiles * 100,
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

  const uploadWithPolling = useCallback(
    async (files: File[]) => {
      const formData = new FormData();
      files.forEach((file) => formData.append('files', file));

      abortControllerRef.current = new AbortController();

      setProgress({
        status: 'uploading',
        currentFile: 0,
        totalFiles: files.length,
        percentage: 0,
        currentFilename: files[0]?.name || '',
        results: [],
      });

      onStart?.(files.length);

      try {
        const response = await fetch(`${API_BASE_URL}/samples/${datasetId}/samples`, {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${token}`,
          },
          body: formData,
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          throw new Error(`Upload failed: ${response.statusText}`);
        }

        const result: UploadResult = await response.json();
        
        setProgress({
          status: 'complete',
          currentFile: files.length,
          totalFiles: files.length,
          percentage: 100,
          currentFilename: '',
          results: result.results,
        });

        onComplete?.(result);
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
    [datasetId, token, onStart, onComplete, onError]
  );

  const upload = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;

      if (useStreaming) {
        await uploadWithStreaming(files);
      } else {
        await uploadWithPolling(files);
      }
    },
    [useStreaming, uploadWithStreaming, uploadWithPolling]
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
