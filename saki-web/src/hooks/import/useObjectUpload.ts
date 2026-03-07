import {useCallback, useState} from 'react';
import {api} from '../../services/api';
import {
    ImportUploadCompletedPart,
    ImportUploadInitRequest,
    ImportUploadSessionResponse,
    ImportUploadStrategy,
} from '../../types';

export interface UseObjectUploadProgress {
    phase: 'idle' | 'uploading' | 'completed' | 'error';
    uploadedBytes: number;
    totalBytes: number;
    percent: number;
    strategy?: ImportUploadStrategy;
    sessionId?: string;
    error?: string;
}

interface UploadZipParams {
    mode: ImportUploadInitRequest['mode'];
    resourceType: ImportUploadInitRequest['resourceType'];
    resourceId: string;
    file: File;
    signal?: AbortSignal;
}

interface UploadZipResult {
    sessionId: string;
    session: ImportUploadSessionResponse;
}

const MAX_PART_RETRIES = 3;
const MAX_PART_CONCURRENCY = 3;

function computePercent(uploaded: number, total: number): number {
    if (!total) return 0;
    return Math.min(100, Math.round((uploaded / total) * 100));
}

function uploadBlobByXhr(
    url: string,
    blob: Blob,
    headers: Record<string, string>,
    signal: AbortSignal | undefined,
    onProgress: (loaded: number) => void,
): Promise<string> {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();

        const abortHandler = () => {
            xhr.abort();
            reject(new DOMException('The operation was aborted.', 'AbortError'));
        };

        xhr.open('PUT', url, true);
        Object.entries(headers || {}).forEach(([key, value]) => {
            if (value != null) xhr.setRequestHeader(key, value);
        });

        xhr.upload.onprogress = (event) => {
            if (!event.lengthComputable) return;
            onProgress(event.loaded);
        };

        xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                const etag = xhr.getResponseHeader('ETag') || xhr.getResponseHeader('etag') || '';
                resolve(etag.replace(/^"|"$/g, ''));
                return;
            }
            reject(new Error(`Upload failed (${xhr.status})`));
        };

        xhr.onerror = () => reject(new Error('Network error while uploading'));
        xhr.onabort = () => reject(new DOMException('The operation was aborted.', 'AbortError'));

        if (signal) {
            if (signal.aborted) {
                abortHandler();
                return;
            }
            signal.addEventListener('abort', abortHandler, {once: true});
        }

        xhr.send(blob);
    });
}

export function useObjectUpload() {
    const [progress, setProgress] = useState<UseObjectUploadProgress>({
        phase: 'idle',
        uploadedBytes: 0,
        totalBytes: 0,
        percent: 0,
    });

    const reset = useCallback(() => {
        setProgress({
            phase: 'idle',
            uploadedBytes: 0,
            totalBytes: 0,
            percent: 0,
        });
    }, []);

    const uploadZip = useCallback(async (params: UploadZipParams): Promise<UploadZipResult> => {
        const {mode, resourceType, resourceId, file, signal} = params;

        setProgress({
            phase: 'uploading',
            uploadedBytes: 0,
            totalBytes: file.size,
            percent: 0,
        });

        let sessionId: string | null = null;
        try {
            const init = await api.initImportUploadSession({
                mode,
                resourceType,
                resourceId,
                filename: file.name,
                size: file.size,
                contentType: file.type || 'application/zip',
            });

            sessionId = init.sessionId;
            const strategy = init.strategy;

            setProgress((prev) => ({
                ...prev,
                strategy,
                sessionId: sessionId || undefined,
            }));

            if (strategy === 'single_put') {
                if (!init.url) {
                    throw new Error('Upload URL is missing for single PUT strategy.');
                }

                await uploadBlobByXhr(
                    init.url,
                    file,
                    init.headers || {},
                    signal,
                    (loaded) => {
                        setProgress((prev) => ({
                            ...prev,
                            uploadedBytes: loaded,
                            totalBytes: file.size,
                            percent: computePercent(loaded, file.size),
                        }));
                    },
                );

                const session = await api.completeImportUploadSession(sessionId, {
                    size: file.size,
                    parts: [],
                });

                setProgress((prev) => ({
                    ...prev,
                    phase: 'completed',
                    uploadedBytes: file.size,
                    totalBytes: file.size,
                    percent: 100,
                }));

                return {sessionId, session};
            }

            const partSize = Math.max(1, Number(init.partSize || 16 * 1024 * 1024));
            const totalParts = Math.max(1, Math.ceil(file.size / partSize));
            const partNumbers = Array.from({length: totalParts}, (_, idx) => idx + 1);

            const signedMap = new Map<number, {url: string; headers: Record<string, string>}>();
            const chunkSize = 100;
            for (let start = 0; start < partNumbers.length; start += chunkSize) {
                const slice = partNumbers.slice(start, start + chunkSize);
                const signed = await api.signImportUploadParts(sessionId, {partNumbers: slice});
                signed.parts.forEach((item) => {
                    signedMap.set(item.partNumber, {
                        url: item.url,
                        headers: item.headers || {},
                    });
                });
            }

            const uploadedByPart = new Map<number, number>();
            const completedParts: ImportUploadCompletedPart[] = [];
            let cursor = 0;

            const runWorker = async () => {
                while (true) {
                    const index = cursor;
                    cursor += 1;
                    if (index >= partNumbers.length) return;

                    const partNumber = partNumbers[index];
                    const signed = signedMap.get(partNumber);
                    if (!signed) {
                        throw new Error(`Missing signed URL for part ${partNumber}`);
                    }

                    const startOffset = (partNumber - 1) * partSize;
                    const endOffset = Math.min(file.size, startOffset + partSize);
                    const blob = file.slice(startOffset, endOffset);

                    let attempt = 0;
                    let lastError: unknown = null;
                    while (attempt < MAX_PART_RETRIES) {
                        attempt += 1;
                        uploadedByPart.set(partNumber, 0);
                        try {
                            const etag = await uploadBlobByXhr(
                                signed.url,
                                blob,
                                signed.headers,
                                signal,
                                (loaded) => {
                                    uploadedByPart.set(partNumber, loaded);
                                    const uploaded = Array.from(uploadedByPart.values()).reduce((acc, val) => acc + val, 0);
                                    setProgress((prev) => ({
                                        ...prev,
                                        uploadedBytes: uploaded,
                                        totalBytes: file.size,
                                        percent: computePercent(uploaded, file.size),
                                    }));
                                },
                            );
                            completedParts.push({partNumber, etag});
                            break;
                        } catch (error) {
                            lastError = error;
                            if (error instanceof DOMException && error.name === 'AbortError') {
                                throw error;
                            }
                            if (attempt >= MAX_PART_RETRIES) {
                                throw lastError instanceof Error ? lastError : new Error(String(lastError || 'part upload failed'));
                            }
                        }
                    }
                }
            };

            const workers = Array.from({length: Math.min(MAX_PART_CONCURRENCY, totalParts)}, () => runWorker());
            await Promise.all(workers);

            const session = await api.completeImportUploadSession(sessionId, {
                size: file.size,
                parts: completedParts.sort((a, b) => a.partNumber - b.partNumber),
            });

            setProgress((prev) => ({
                ...prev,
                phase: 'completed',
                uploadedBytes: file.size,
                totalBytes: file.size,
                percent: 100,
            }));

            return {sessionId, session};
        } catch (error) {
            try {
                if (sessionId) {
                    await api.abortImportUploadSession(sessionId);
                }
            } catch {
                // best effort
            }
            const message = error instanceof Error ? error.message : 'Object upload failed';
            setProgress((prev) => ({
                ...prev,
                phase: 'error',
                error: message,
            }));
            throw error;
        }
    }, []);

    return {
        progress,
        reset,
        uploadZip,
    };
}

export default useObjectUpload;
