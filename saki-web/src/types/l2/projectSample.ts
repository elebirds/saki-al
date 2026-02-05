import { Sample } from '../l1/sample';

export interface ProjectSample extends Sample {
  annotationCount: number;
  isLabeled: boolean;
  hasDraft: boolean;
}
