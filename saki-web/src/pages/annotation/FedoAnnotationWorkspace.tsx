/**
 * FEDO Dual-View Annotation Workspace
 * 
 * Specialized annotation workspace for satellite FEDO data with:
 * - Left panel: Time-Energy view (ax1) for primary annotation
 * - Right panel: L-ωd view (ax3) showing mapped regions
 * - Real-time bidirectional synchronization
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { 
  Layout, 
  Button, 
  Card, 
  Space, 
  Typography, 
  List, 
  Radio, 
  Tooltip, 
  Select, 
  Tag, 
  message, 
  Spin,
  Empty,
  Divider 
} from 'antd';
import { useTranslation } from 'react-i18next';
import { 
  LeftOutlined, 
  RightOutlined, 
  CheckOutlined, 
  DragOutlined, 
  BorderOutlined, 
  RotateRightOutlined, 
  DeleteOutlined, 
  UndoOutlined, 
  RedoOutlined, 
  ZoomInOutlined, 
  ZoomOutOutlined, 
  ExpandOutlined,
  SyncOutlined 
} from '@ant-design/icons';
import { AnnotationCanvas, AnnotationCanvasRef } from '../../components/canvas';
import { api } from '../../services/api';
import { 
  Sample, 
  Annotation, 
  Dataset, 
  Label, 
  DualViewAnnotation, 
  MappedRegion,
  BoundingBox
} from '../../types';
import { useDualViewSync } from '../../hooks/useDualViewSync';

const { Sider, Content } = Layout;
const { Title, Text } = Typography;

// ============================================================================
// Types - Use Sample from types/index.ts which is already converted to camelCase
// ============================================================================

// ============================================================================
// Helper Functions
// ============================================================================

/** Convert DualViewAnnotation to Annotation for AnnotationCanvas */
function dualToAnnotation(dual: DualViewAnnotation): Annotation {
  return {
    id: dual.id,
    sampleId: dual.sampleId,
    labelId: dual.labelId,
    labelName: dual.labelName,
    labelColor: dual.labelColor,
    type: dual.primary.type,
    bbox: dual.primary.bbox,
  };
}

/** Convert Annotation to DualViewAnnotation */
function annotationToDual(ann: Annotation, regions: MappedRegion[] = []): DualViewAnnotation {
  return {
    id: ann.id,
    sampleId: ann.sampleId,
    labelId: ann.labelId,
    labelName: ann.labelName,
    labelColor: ann.labelColor,
    primary: {
      type: ann.type,
      bbox: ann.bbox,
    },
    secondary: {
      regions,
    },
  };
}

// ============================================================================
// Component
// ============================================================================

const FedoAnnotationWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const { datasetId } = useParams<{ datasetId: string }>();
  
  // Dataset & Samples State
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  
  // Annotation State
  const [annotations, setAnnotations] = useState<DualViewAnnotation[]>([]);
  const [history, setHistory] = useState<DualViewAnnotation[][]>([[]]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  
  // Tool State
  const [currentTool, setCurrentTool] = useState<'select' | 'rect' | 'obb'>('select');
  const [labels, setLabels] = useState<Label[]>([]);
  const [selectedLabel, setSelectedLabel] = useState<Label | null>(null);
  
  // Canvas Refs
  const timeEnergyCanvasRef = useRef<AnnotationCanvasRef>(null);
  const lWdCanvasRef = useRef<AnnotationCanvasRef>(null);
  
  // Current sample
  const currentSample = samples[currentIndex];

  // ========================================================================
  // Dual View Sync Hook
  // ========================================================================
  
  const {
    isReady: isSyncReady,
    isMapping,
    initializeWithSample,
    mapBboxToLWd,
    dispose: disposeSyncWorker
  } = useDualViewSync();

  // ========================================================================
  // Memoized Conversions
  // ========================================================================

  // Convert DualViewAnnotation[] to Annotation[] for AnnotationCanvas
  const canvasAnnotations = useMemo(() => {
    return annotations.map(dualToAnnotation);
  }, [annotations]);

  // ========================================================================
  // Data Loading
  // ========================================================================
  
  useEffect(() => {
    if (datasetId) {
      setLoading(true);
      Promise.all([
        api.getDataset(datasetId),
        api.getLabels(datasetId),
        api.getSamples(datasetId)
      ]).then(([ds, loadedLabels, samps]) => {
        if (ds) setDataset(ds);
        setLabels(loadedLabels);
        // Set default selected label
        if (loadedLabels.length > 0 && !selectedLabel) {
          setSelectedLabel(loadedLabels[0]);
        }
        setSamples(samps);
        setLoading(false);
      }).catch(err => {
        console.error('Failed to load dataset:', err);
        message.error('Failed to load dataset');
        setLoading(false);
      });
    }
  }, [datasetId]);

  // Load sample data and initialize worker
  useEffect(() => {
    if (currentSample?.id) {
      // Load annotations for this sample
      api.getSampleAnnotations(currentSample.id).then((anns) => {
        // Convert to DualViewAnnotation format
        const dualAnns: DualViewAnnotation[] = anns.map(ann => annotationToDual(ann, []));
        setAnnotations(dualAnns);
        setHistory([dualAnns]);
        setHistoryIndex(0);
      });

      // Always try to initialize worker for FEDO samples
      // The lookup table should exist for all processed FEDO samples
      initializeWithSample(currentSample.id);
    }
  }, [currentSample?.id, initializeWithSample]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disposeSyncWorker();
    };
  }, [disposeSyncWorker]);

  // ========================================================================
  // History Management
  // ========================================================================

  const addToHistory = useCallback((newAnnotations: DualViewAnnotation[]) => {
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push(newAnnotations);
    setHistory(newHistory);
    setHistoryIndex(newHistory.length - 1);
    setAnnotations(newAnnotations);
  }, [history, historyIndex]);

  const undo = useCallback(() => {
    if (historyIndex > 0) {
      const newIndex = historyIndex - 1;
      setHistoryIndex(newIndex);
      setAnnotations(history[newIndex]);
    }
  }, [history, historyIndex]);

  const redo = useCallback(() => {
    if (historyIndex < history.length - 1) {
      const newIndex = historyIndex + 1;
      setHistoryIndex(newIndex);
      setAnnotations(history[newIndex]);
    }
  }, [history, historyIndex]);

  // ========================================================================
  // Annotation Handlers
  // ========================================================================

  const handleAnnotationCreate = useCallback(async (event: { 
    type: 'rect' | 'obb'; 
    bbox: { x: number; y: number; width: number; height: number; rotation?: number } 
  }) => {
    const newId = Date.now().toString();
    
    // Map bbox to L-ωd space
    let regions: MappedRegion[] = [];
    if (isSyncReady) {
      try {
        const result = await mapBboxToLWd(event.bbox as BoundingBox);
        regions = result.regions;
      } catch (err) {
        console.warn('Failed to map bbox:', err);
      }
    }
    
    const newAnn: DualViewAnnotation = {
      id: newId,
      sampleId: currentSample?.id || 'current',
      labelId: selectedLabel?.id || '',
      labelName: selectedLabel?.name || 'unknown',
      labelColor: selectedLabel?.color || '#ff0000',
      primary: {
        type: event.type,
        bbox: event.bbox,
      },
      secondary: {
        regions,
      },
    };
    
    addToHistory([...annotations, newAnn]);
  }, [currentSample?.id, selectedLabel, isSyncReady, mapBboxToLWd, addToHistory, annotations]);

  const handleUpdateAnnotation = useCallback(async (updatedAnn: Annotation) => {
    // Re-map bbox when annotation is updated
    let regions: MappedRegion[] = [];
    if (isSyncReady && updatedAnn.bbox) {
      try {
        const result = await mapBboxToLWd(updatedAnn.bbox as BoundingBox);
        regions = result.regions;
      } catch (err) {
        console.warn('Failed to map bbox:', err);
      }
    }
    
    const dualAnn: DualViewAnnotation = annotationToDual(updatedAnn, regions);
    
    addToHistory(annotations.map(a => a.id === updatedAnn.id ? dualAnn : a));
  }, [isSyncReady, mapBboxToLWd, addToHistory, annotations]);

  const handleDeleteAnnotation = useCallback((id: string) => {
    addToHistory(annotations.filter(a => a.id !== id));
    if (selectedId === id) {
      setSelectedId(null);
    }
  }, [addToHistory, annotations, selectedId]);

  // ========================================================================
  // Navigation
  // ========================================================================

  const handleNext = useCallback(() => {
    if (currentIndex < samples.length - 1) {
      setCurrentIndex(c => c + 1);
      setAnnotations([]);
      setHistory([[]]);
      setHistoryIndex(0);
      setSelectedId(null);
    }
  }, [currentIndex, samples.length]);

  const handlePrev = useCallback(() => {
    if (currentIndex > 0) {
      setCurrentIndex(c => c - 1);
      setAnnotations([]);
      setHistory([[]]);
      setHistoryIndex(0);
      setSelectedId(null);
    }
  }, [currentIndex]);

  const handleSubmit = useCallback(async () => {
    if (!currentSample) return;
    try {
      // Convert DualViewAnnotation back to Annotation for saving
      const annsToSave: Annotation[] = annotations.map(dualToAnnotation);
      await api.saveSampleAnnotations(currentSample.id, annsToSave);
      message.success(t('annotation.saved') || 'Saved');
      handleNext();
    } catch (error) {
      message.error('Failed to save annotations');
    }
  }, [currentSample, annotations, handleNext, t]);

  // ========================================================================
  // Keyboard Shortcuts
  // ========================================================================

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      switch (e.key.toLowerCase()) {
        case 'v':
          setCurrentTool('select');
          break;
        case 'r':
          setCurrentTool('rect');
          break;
        case 'o':
          setCurrentTool('obb');
          break;
        case 'arrowright':
          handleNext();
          break;
        case 'arrowleft':
          handlePrev();
          break;
        case 's':
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            handleSubmit();
          }
          break;
        case 'z':
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            if (e.shiftKey) {
              redo();
            } else {
              undo();
            }
          }
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleNext, handlePrev, handleSubmit, undo, redo]);

  // ========================================================================
  // Get Image URLs
  // ========================================================================

  const timeEnergyImageUrl = currentSample?.id 
    ? `/api/v1/specialized/samples/${currentSample.id}/image/time_energy`
    : '';
  
  const lWdImageUrl = currentSample?.id 
    ? `/api/v1/specialized/samples/${currentSample.id}/image/l_wd`
    : '';

  // ========================================================================
  // Selected Annotation Info
  // ========================================================================

  const selectedAnnotation = annotations.find(a => a.id === selectedId);
  const currentMappedRegions = selectedAnnotation?.secondary?.regions || [];

  // ========================================================================
  // Render
  // ========================================================================

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Spin size="large" tip="Loading..." />
      </div>
    );
  }

  if (!dataset || samples.length === 0) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Empty description="No samples found for this dataset" />
      </div>
    );
  }

  if (!currentSample) {
    return <div>{t('workspace.loading')}</div>;
  }

  return (
    <Layout style={{ height: '100%' }}>
      <Content style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Toolbar */}
        <div style={{ 
          padding: '10px', 
          background: '#fff', 
          borderBottom: '1px solid #f0f0f0', 
          display: 'flex', 
          gap: '10px', 
          alignItems: 'center' 
        }}>
          <Space>
            <span style={{ fontWeight: 'bold' }}>{t('workspace.label')}</span>
            <Select
              value={selectedLabel?.id}
              onChange={(value) => {
                const label = labels.find(l => l.id === value);
                if (label) setSelectedLabel(label);
              }}
              style={{ width: 150 }}
            >
              {labels.map(label => (
                <Select.Option key={label.id} value={label.id}>
                  <Tag color={label.color}>{label.name}</Tag>
                </Select.Option>
              ))}
            </Select>
          </Space>
          
          <Divider type="vertical" />
          
          <Space>
            <Tooltip title="Undo (Ctrl+Z)">
              <Button icon={<UndoOutlined />} onClick={undo} disabled={historyIndex === 0} />
            </Tooltip>
            <Tooltip title="Redo (Ctrl+Shift+Z)">
              <Button icon={<RedoOutlined />} onClick={redo} disabled={historyIndex === history.length - 1} />
            </Tooltip>
          </Space>
          
          <Divider type="vertical" />
          
          <Radio.Group value={currentTool} onChange={e => setCurrentTool(e.target.value)} buttonStyle="solid">
            <Radio.Button value="select">
              <Tooltip title={t('workspace.tools.select')}>
                <DragOutlined /> Select
              </Tooltip>
            </Radio.Button>
            <Radio.Button value="rect">
              <Tooltip title={t('workspace.tools.rect')}>
                <BorderOutlined /> Rect
              </Tooltip>
            </Radio.Button>
            <Radio.Button value="obb">
              <Tooltip title={t('workspace.tools.obb')}>
                <RotateRightOutlined /> OBB
              </Tooltip>
            </Radio.Button>
          </Radio.Group>
          
          <Divider type="vertical" />
          
          <Space>
            <Tooltip title={t('workspace.tools.zoomIn')}>
              <Button icon={<ZoomInOutlined />} onClick={() => {
                timeEnergyCanvasRef.current?.zoomIn();
                lWdCanvasRef.current?.zoomIn();
              }} />
            </Tooltip>
            <Tooltip title={t('workspace.tools.zoomOut')}>
              <Button icon={<ZoomOutOutlined />} onClick={() => {
                timeEnergyCanvasRef.current?.zoomOut();
                lWdCanvasRef.current?.zoomOut();
              }} />
            </Tooltip>
            <Tooltip title={t('workspace.tools.resetView')}>
              <Button icon={<ExpandOutlined />} onClick={() => {
                timeEnergyCanvasRef.current?.resetView();
                lWdCanvasRef.current?.resetView();
              }} />
            </Tooltip>
          </Space>
          
          <Divider type="vertical" />
          
          <Space>
            {isMapping && <Spin size="small" />}
            <Tag color={isSyncReady ? 'green' : 'orange'} icon={<SyncOutlined spin={isMapping} />}>
              {isSyncReady ? 'Sync Ready' : 'Initializing...'}
            </Tag>
          </Space>
          
          <div style={{ flex: 1 }} />
          
          <span style={{ lineHeight: '32px', color: '#888' }}>
            {t('workspace.help')}
          </span>
        </div>

        {/* Dual Canvas Area */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* Left: Time-Energy View */}
          <div style={{ 
            flex: 1, 
            position: 'relative', 
            overflow: 'hidden', 
            background: '#333',
            borderRight: '2px solid #666'
          }}>
            <div style={{ 
              position: 'absolute', 
              top: 8, 
              left: 8, 
              zIndex: 10,
              background: 'rgba(0,0,0,0.6)',
              color: '#fff',
              padding: '4px 8px',
              borderRadius: 4,
              fontSize: 12
            }}>
              Time-Energy (Primary)
            </div>
            <AnnotationCanvas
              ref={timeEnergyCanvasRef}
              imageUrl={timeEnergyImageUrl}
              annotations={canvasAnnotations}
              onAnnotationCreate={handleAnnotationCreate}
              onAnnotationUpdate={handleUpdateAnnotation}
              onAnnotationDelete={handleDeleteAnnotation}
              currentTool={currentTool}
              labelColor={selectedLabel?.color || '#ff0000'}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>

          {/* Right: L-ωd View (Read-only mapped regions) */}
          <div style={{ 
            flex: 1, 
            position: 'relative', 
            overflow: 'hidden', 
            background: '#333'
          }}>
            <div style={{ 
              position: 'absolute', 
              top: 8, 
              left: 8, 
              zIndex: 10,
              background: 'rgba(0,0,0,0.6)',
              color: '#fff',
              padding: '4px 8px',
              borderRadius: 4,
              fontSize: 12
            }}>
              L-ωd (Mapped Regions)
            </div>
            {/* For now, just show the image. Mapped regions overlay will be added later */}
            <AnnotationCanvas
              ref={lWdCanvasRef}
              imageUrl={lWdImageUrl}
              annotations={[]}  // TODO: Convert mappedRegions to polygon Annotation format
              currentTool="select"  // Force select mode - L-ωd view is read-only
              selectedId={null}
              onSelect={() => {}}
            />
            {/* Mapped regions count indicator */}
            {currentMappedRegions.length > 0 && (
              <div style={{ 
                position: 'absolute', 
                bottom: 8, 
                left: 8, 
                zIndex: 10,
                background: 'rgba(0,0,0,0.6)',
                color: '#fff',
                padding: '4px 8px',
                borderRadius: 4,
                fontSize: 12
              }}>
                {currentMappedRegions.length} mapped region{currentMappedRegions.length > 1 ? 's' : ''}
              </div>
            )}
          </div>
        </div>
      </Content>

      {/* Right Sidebar */}
      <Sider width={300} theme="light" style={{ padding: '20px', borderLeft: '1px solid #f0f0f0', overflowY: 'auto' }}>
        <Title level={4}>{t('workspace.annotations')}</Title>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Card size="small" bodyStyle={{ padding: 0 }}>
            <List
              size="small"
              dataSource={annotations}
              renderItem={(item, index) => (
                <List.Item 
                  actions={[
                    <Button 
                      type="text" 
                      danger 
                      icon={<DeleteOutlined />} 
                      onClick={(e: React.MouseEvent) => { 
                        e.stopPropagation(); 
                        handleDeleteAnnotation(item.id); 
                      }} 
                    />
                  ]}
                  style={{ 
                    padding: '8px 16px',
                    background: selectedId === item.id ? '#e6f7ff' : 'transparent',
                    cursor: 'pointer',
                    borderLeft: selectedId === item.id ? `4px solid ${item.labelColor || '#1890ff'}` : '4px solid transparent'
                  }}
                  onClick={() => {
                    setSelectedId(item.id);
                    setCurrentTool('select');
                  }}
                >
                  <Space direction="vertical" size={2} style={{ width: '100%' }}>
                    <Space>
                      {item.primary.type === 'obb' ? <RotateRightOutlined /> : <BorderOutlined />}
                      <span>{item.labelName} {index + 1}</span>
                    </Space>
                    {item.secondary.regions.length > 0 && (
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        → {item.secondary.regions.length} L-ωd region{item.secondary.regions.length > 1 ? 's' : ''}
                      </Text>
                    )}
                  </Space>
                </List.Item>
              )}
            />
            {annotations.length === 0 && (
              <div style={{ padding: 16, textAlign: 'center', color: '#999' }}>
                {t('workspace.noAnnotations')}
              </div>
            )}
          </Card>
          
          <div style={{ marginTop: 20 }}>
            <Space>
              <Button icon={<LeftOutlined />} onClick={handlePrev} disabled={currentIndex === 0} />
              <span>{currentIndex + 1} / {samples.length}</span>
              <Button icon={<RightOutlined />} onClick={handleNext} disabled={currentIndex === samples.length - 1} />
            </Space>
          </div>

          <Button 
            type="primary" 
            block 
            icon={<CheckOutlined />} 
            onClick={handleSubmit} 
            style={{ marginTop: 20 }}
          >
            {t('workspace.submitNext')}
          </Button>
        </Space>
      </Sider>
    </Layout>
  );
};

export default FedoAnnotationWorkspace;
