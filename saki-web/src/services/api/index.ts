import { ApiService } from './interface';
import { RealApiService } from './real';

export const api: ApiService = new RealApiService();
export * from './interface';
