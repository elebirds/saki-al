
export interface Sample {
  id: string;
  datasetId: string;
  name: string;
  remark?: string;
  metaInfo?: Record<string, any>;
  assetGroup: Record<string, string>;
  primaryAssetId?: string;
  primaryAssetUrl?: string; // Presigned URL for the primary asset (for direct display)
  createdAt: string;
  updatedAt: string;
}

// Optional: specific types for different asset groups
export interface ClassicSample extends Sample {
  assetGroup: {
    imageMain: string;
  };
}

export interface FedoSample extends Sample {
  assetGroup: {
    rawText: string;
    timeEnergyImage: string;
    lOmegadImage: string;
    lookupTable?: string;
    dataNpz?: string;
  };
}

