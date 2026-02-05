export interface ProjectLabel {
  id: string;
  projectId: string;
  name: string;
  color: string;
  description?: string;
  shortcut?: string;
  sortOrder: number;
  createdAt: string;
  updatedAt?: string;
}

export interface ProjectLabelCreate {
  name: string;
  color?: string;
  description?: string;
  shortcut?: string;
  sortOrder?: number;
}

export interface ProjectLabelUpdate {
  name?: string;
  color?: string;
  description?: string;
  shortcut?: string;
  sortOrder?: number;
}
