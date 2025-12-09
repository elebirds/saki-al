import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { Layout, Button, Card, Space, Typography, List, Radio, Tooltip, Select, Tag } from 'antd';
import { useTranslation } from 'react-i18next';
import { LeftOutlined, RightOutlined, CheckOutlined, DragOutlined, BorderOutlined, RotateRightOutlined, DeleteOutlined, UndoOutlined, RedoOutlined, ZoomInOutlined, ZoomOutOutlined, ExpandOutlined } from '@ant-design/icons';
import AnnotationCanvas, { AnnotationCanvasRef } from '../components/AnnotationCanvas';
import { api } from '../services/api';
import { Sample, Annotation, Project, LabelConfig } from '../types';

const { Sider, Content } = Layout;
const { Title } = Typography;

const AnnotationWorkspace: React.FC = () => {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [history, setHistory] = useState<Annotation[][]>([[]]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currentTool, setCurrentTool] = useState<'select' | 'rect' | 'obb'>('select');
  const [selectedLabel, setSelectedLabel] = useState<LabelConfig | null>(null);
  const canvasRef = useRef<AnnotationCanvasRef>(null);

  useEffect(() => {
    if (projectId) {
      api.getProject(projectId).then((p) => {
        if (p) setProject(p);
      });
      api.getSamples(projectId).then(setSamples);
    }
  }, [projectId]);

  useEffect(() => {
    if (project && project.labels.length > 0 && !selectedLabel) {
      setSelectedLabel(project.labels[0]);
    }
  }, [project]);

  const currentSample = samples[currentIndex];

  const addToHistory = (newAnnotations: Annotation[]) => {
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push(newAnnotations);
    setHistory(newHistory);
    setHistoryIndex(newHistory.length - 1);
    setAnnotations(newAnnotations);
  };

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

  const handleAddAnnotation = (ann: Annotation) => {
    // Ensure the new annotation has the selected label and color
    const newAnn = {
      ...ann,
      label: selectedLabel?.name || 'unknown',
      color: selectedLabel?.color || '#ff0000'
    };
    addToHistory([...annotations, newAnn]);
  };

  const handleUpdateAnnotation = (updatedAnn: Annotation) => {
    addToHistory(annotations.map(a => a.id === updatedAnn.id ? updatedAnn : a));
  };

  const handleDeleteAnnotation = (id: string) => {
    addToHistory(annotations.filter(a => a.id !== id));
  };

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

  const handleSubmit = useCallback(() => {
    if (!currentSample) return;
    console.log('Submitting annotations for', currentSample.id, annotations);
    handleNext();
  }, [currentSample, annotations, handleNext]);

  // Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if typing in an input
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

  if (!currentSample || !project) return <div>{t('workspace.loading')}</div>;

  return (
    <Layout style={{ height: '100%' }}>
      <Content style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Toolbar */}
        <div style={{ padding: '10px', background: '#fff', borderBottom: '1px solid #f0f0f0', display: 'flex', gap: '10px', alignItems: 'center' }}>
          <Space>
            <span style={{ fontWeight: 'bold' }}>{t('workspace.label')}</span>
            <Select
              value={selectedLabel?.name}
              onChange={(value) => {
                const label = project.labels.find(l => l.name === value);
                if (label) setSelectedLabel(label);
              }}
              style={{ width: 150 }}
            >
              {project.labels.map(label => (
                <Select.Option key={label.name} value={label.name}>
                  <Tag color={label.color}>{label.name}</Tag>
                </Select.Option>
              ))}
            </Select>
          </Space>
          <div style={{ width: 1, height: 24, background: '#f0f0f0', margin: '0 10px' }} />
          <Space>
            <Tooltip title="Undo (Ctrl+Z)">
              <Button icon={<UndoOutlined />} onClick={undo} disabled={historyIndex === 0} />
            </Tooltip>
            <Tooltip title="Redo (Ctrl+Shift+Z)">
              <Button icon={<RedoOutlined />} onClick={redo} disabled={historyIndex === history.length - 1} />
            </Tooltip>
          </Space>
          <div style={{ width: 1, height: 24, background: '#f0f0f0', margin: '0 10px' }} />
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
          <div style={{ width: 1, height: 24, background: '#f0f0f0', margin: '0 10px' }} />
          <Space>
            <Tooltip title={t('workspace.tools.zoomIn')}>
              <Button icon={<ZoomInOutlined />} onClick={() => canvasRef.current?.zoomIn()} />
            </Tooltip>
            <Tooltip title={t('workspace.tools.zoomOut')}>
              <Button icon={<ZoomOutOutlined />} onClick={() => canvasRef.current?.zoomOut()} />
            </Tooltip>
            <Tooltip title={t('workspace.tools.resetView')}>
              <Button icon={<ExpandOutlined />} onClick={() => canvasRef.current?.resetView()} />
            </Tooltip>
          </Space>
          <div style={{ flex: 1 }} />
          <span style={{ lineHeight: '32px', color: '#888' }}>
            {t('workspace.help')}
          </span>
        </div>

        {/* Canvas Area */}
        <div style={{ flex: 1, position: 'relative', overflow: 'hidden', background: '#333' }}>
          <AnnotationCanvas
            ref={canvasRef}
            imageUrl={currentSample.url}
            annotations={annotations}
            onAddAnnotation={handleAddAnnotation}
            onUpdateAnnotation={handleUpdateAnnotation}
            onDeleteAnnotation={handleDeleteAnnotation}
            currentTool={currentTool}
            labelColor={selectedLabel?.color || '#ff0000'}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
      </Content>

      <Sider width={300} theme="light" style={{ padding: '20px', borderLeft: '1px solid #f0f0f0', overflowY: 'auto' }}>
        <Title level={4}>{t('workspace.annotations')}</Title>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Card size="small" bodyStyle={{ padding: 0 }}>
            <List
              size="small"
              dataSource={annotations}
              renderItem={(item, index) => (
                <List.Item 
                  actions={[<Button type="text" danger icon={<DeleteOutlined />} onClick={(e: React.MouseEvent) => { e.stopPropagation(); handleDeleteAnnotation(item.id); }} />]}
                  style={{ 
                    padding: '8px 16px',
                    background: selectedId === item.id ? '#e6f7ff' : 'transparent',
                    cursor: 'pointer',
                    borderLeft: selectedId === item.id ? `4px solid ${item.color || '#1890ff'}` : '4px solid transparent'
                  }}
                  onClick={() => {
                    setSelectedId(item.id);
                    setCurrentTool('select');
                  }}
                >
                  <Space>
                    {item.type === 'obb' ? <RotateRightOutlined /> : <BorderOutlined />}
                    <span>{item.label} {index + 1}</span>
                  </Space>
                </List.Item>
              )}
            />
            {annotations.length === 0 && <div style={{ padding: 16, textAlign: 'center', color: '#999' }}>{t('workspace.noAnnotations')}</div>}
          </Card>
          
          <div style={{ marginTop: 20 }}>
            <Space>
              <Button icon={<LeftOutlined />} onClick={handlePrev} disabled={currentIndex === 0} />
              <span>{currentIndex + 1} / {samples.length}</span>
              <Button icon={<RightOutlined />} onClick={handleNext} disabled={currentIndex === samples.length - 1} />
            </Space>
          </div>

          <Button type="primary" block icon={<CheckOutlined />} onClick={handleSubmit} style={{ marginTop: 20 }}>
            {t('workspace.submitNext')}
          </Button>
        </Space>
      </Sider>
    </Layout>
  );
};

export default AnnotationWorkspace;
