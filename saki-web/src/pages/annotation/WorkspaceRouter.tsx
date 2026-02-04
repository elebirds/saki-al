/**
 * WorkspaceRouter
 * 
 * Routes to the appropriate annotation workspace based on dataset's annotation system type.
 * This allows the same URL pattern (/workspace/:datasetId) to work for all annotation systems.
 */

import React, { useState, useEffect } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import { api } from '../../services/api';
import { Dataset, DatasetType } from '../../types';
import ClassicAnnotationWorkspace from './ClassicAnnotationWorkspace.tsx';
import FedoAnnotationWorkspace from './FedoAnnotationWorkspace';

const WorkspaceRouter: React.FC = () => {
  const { datasetId } = useParams<{ datasetId: string }>();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (datasetId) {
      setLoading(true);
      api.getDataset(datasetId)
        .then((ds) => {
          if (ds) {
            setDataset(ds);
          } else {
            setError('Dataset not found');
          }
        })
        .catch((err) => {
          setError(err.message || 'Failed to load dataset');
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [datasetId]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spin size="large">
          <div className="min-h-[200px]" />
        </Spin>
      </div>
    );
  }

  if (error || !dataset) {
    return <Navigate to="/" replace />;
  }

  // Route to appropriate workspace based on annotation system
  return getWorkspaceComponent(dataset.annotationSystem);
};

/**
 * Get the appropriate workspace component for an annotation system type
 */
function getWorkspaceComponent(annotationSystem: DatasetType): React.ReactElement {
  switch (annotationSystem) {
    case 'fedo':
      return <FedoAnnotationWorkspace />;
    case 'classic':
    default:
      return <ClassicAnnotationWorkspace />;
  }
}

export default WorkspaceRouter;
