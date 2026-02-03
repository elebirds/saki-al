export interface TypeInfo {
    value: string;
    label: string;
    description: string;
    color: string;
}

export interface AvailableTypes {
    taskTypes: TypeInfo[];
    datasetTypes: TypeInfo[];
}

export interface AvailableTypesResponse {
    taskTypes: TypeInfo[];
    datasetTypes: TypeInfo[];
}