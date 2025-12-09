import { Project, Sample, Annotation, ALStrategy, ModelArchitecture } from '../types';

// Mock Data
const mockStrategies: ALStrategy[] = [
  { id: 'least_confidence', name: 'Least Confidence', description: 'Selects samples where the model is least confident.' },
  { id: 'margin_sampling', name: 'Margin Sampling', description: 'Selects samples with the smallest margin between top two predictions.' },
  { id: 'entropy_sampling', name: 'Entropy Sampling', description: 'Selects samples with the highest entropy.' },
  { id: 'random', name: 'Random Sampling', description: 'Selects samples randomly.' },
];

const mockArchitectures: ModelArchitecture[] = [
  { id: 'resnet18', name: 'ResNet-18', taskType: 'classification' },
  { id: 'resnet50', name: 'ResNet-50', taskType: 'classification' },
  { id: 'efficientnet_b0', name: 'EfficientNet-B0', taskType: 'classification' },
  { id: 'yolov5', name: 'YOLOv5', taskType: 'detection' },
  { id: 'faster_rcnn', name: 'Faster R-CNN', taskType: 'detection' },
];

const mockProjects: Project[] = [
  {
    id: '1',
    name: 'Traffic Sign Detection',
    description: 'Detect traffic signs in street view images.',
    taskType: 'detection',
    createdAt: '2023-10-01T10:00:00Z',
    stats: {
      totalSamples: 1200,
      labeledSamples: 150,
      accuracy: 0.85,
    },
    labels: [
      { name: 'stop sign', color: '#ff0000' },
      { name: 'traffic light', color: '#00ff00' },
      { name: 'pedestrian', color: '#0000ff' }
    ],
    alConfig: {
      strategy: 'least_confidence',
      batchSize: 20,
    },
    modelConfig: {
      architecture: 'yolov5',
    },
  },
  {
    id: '2',
    name: 'Cat vs Dog Classification',
    description: 'Classify images as cat or dog.',
    taskType: 'classification',
    createdAt: '2023-10-05T14:30:00Z',
    stats: {
      totalSamples: 5000,
      labeledSamples: 20,
      accuracy: 0.60,
    },
    labels: [
      { name: 'cat', color: '#ffa500' },
      { name: 'dog', color: '#800080' }
    ],
    alConfig: {
      strategy: 'entropy_sampling',
      batchSize: 10,
    },
    modelConfig: {
      architecture: 'resnet50',
    },
  },
];

const mockSamples: Sample[] = Array.from({ length: 20 }).map((_, i) => ({
  id: `sample-${i}`,
  projectId: '1',
  url: `https://picsum.photos/seed/${i}/800/600`, // Random image
  status: i < 5 ? 'labeled' : 'unlabeled',
  score: Math.random(),
}));

export const api = {
  getProjects: async (): Promise<Project[]> => {
    return new Promise((resolve) => setTimeout(() => resolve(mockProjects), 500));
  },

  getProject: async (id: string): Promise<Project | undefined> => {
    return new Promise((resolve) =>
      setTimeout(() => resolve(mockProjects.find((p) => p.id === id)), 300)
    );
  },

  getSamples: async (projectId: string): Promise<Sample[]> => {
    // In a real app, we would filter by projectId
    console.log(`Fetching samples for project ${projectId}`);
    return new Promise((resolve) => setTimeout(() => resolve(mockSamples), 400));
  },

  getSample: async (sampleId: string): Promise<Sample | undefined> => {
    return new Promise((resolve) =>
      setTimeout(() => resolve(mockSamples.find((s) => s.id === sampleId)), 300)
    );
  },
  
  saveAnnotation: async (annotation: Annotation): Promise<void> => {
      console.log('Saved annotation:', annotation);
      return new Promise((resolve) => setTimeout(resolve, 300));
  },

  getALStrategies: async (): Promise<ALStrategy[]> => {
    return new Promise((resolve) => setTimeout(() => resolve(mockStrategies), 300));
  },

  getModelArchitectures: async (): Promise<ModelArchitecture[]> => {
    return new Promise((resolve) => setTimeout(() => resolve(mockArchitectures), 300));
  }
};
