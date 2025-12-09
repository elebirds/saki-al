import { ApiService } from './interface';
import { MockApiService } from './mock';
import { RealApiService } from './real';

// Default to mock if not specified or set to 'true'
const useMock = (import.meta as any).env.VITE_USE_MOCK_API !== 'false';

export const api: ApiService = useMock ? new MockApiService() : new RealApiService();
export * from './interface';
