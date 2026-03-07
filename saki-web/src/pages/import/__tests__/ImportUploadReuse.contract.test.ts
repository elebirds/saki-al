import type {
    ImportUploadInitRequest,
    ImportUploadInitResponse,
} from '../../../types';

export type Assert<T extends true> = T;

export type HasFileSha256Field = 'fileSha256' extends keyof ImportUploadInitRequest ? true : false;
export type AssertHasFileSha256Field = Assert<HasFileSha256Field>;

export type HasInitStatusField = 'status' extends keyof ImportUploadInitResponse ? true : false;
export type AssertHasInitStatusField = Assert<HasInitStatusField>;

export type HasReuseHitField = 'reuseHit' extends keyof ImportUploadInitResponse ? true : false;
export type AssertHasReuseHitField = Assert<HasReuseHitField>;

const initStatuses: ImportUploadInitResponse['status'][] = ['initiated', 'uploaded'];
void initStatuses;
