/**
 * WorkspaceRouter
 * 
 * Routes to the appropriate annotation workspace based on project's annotation system type.
 * This allows the same URL pattern (/workspace/:projectId) to work for all annotation systems.
 */

import React, { useState, useEffect } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { Spin } from 'antd';
import { api } from '../services/api';
import { Project, AnnotationSystemType } from '../types';
import AnnotationWorkspace from './AnnotationWorkspace';
import FedoAnnotationWorkspace from './FedoAnnotationWorkspace';

const WorkspaceRouter: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (projectId) {
      setLoading(true);
      api.getProject(projectId)
        .then((proj) => {
          if (proj) {
            setProject(proj);
          } else {
            setError('Project not found');
          }
        })
        .catch((err) => {
          setError(err.message || 'Failed to load project');
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [projectId]);

  if (loading) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '100%' 
      }}>
        <Spin size="large" tip="Loading workspace..." />
      </div>
    );
  }

  if (error || !project) {
    return <Navigate to="/" replace />;
  }

  // Route to appropriate workspace based on annotation system
  return getWorkspaceComponent(project.annotationSystem);
};

/**
 * Get the appropriate workspace component for an annotation system type
 */
function getWorkspaceComponent(annotationSystem: AnnotationSystemType): React.ReactElement {
  switch (annotationSystem) {
    case 'fedo':
      return <FedoAnnotationWorkspace />;
    case 'classic':
    default:
      return <AnnotationWorkspace />;
  }
}

export default WorkspaceRouter;
