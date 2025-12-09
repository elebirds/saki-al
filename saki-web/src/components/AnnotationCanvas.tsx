import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react';
import { Stage, Layer, Image as KonvaImage } from 'react-konva';
import useImage from 'use-image';
import Konva from 'konva';
import { Annotation } from '../types';
import AnnotationItem from './canvas/AnnotationItem';
import Crosshair from './canvas/Crosshair';
import CanvasTransformer from './canvas/CanvasTransformer';
import NewAnnotationLayer from './canvas/NewAnnotationLayer';
import { 
  clampPoint, 
  calculateFitScale, 
  calculateZoom, 
  normalizeRect, 
  calculateObbRect, 
  finalizeObbRect 
} from '../utils/canvasUtils';

export interface AnnotationCanvasRef {
  zoomIn: () => void;
  zoomOut: () => void;
  resetView: () => void;
}

interface AnnotationCanvasProps {
  imageUrl: string;
  annotations: Annotation[];
  onAddAnnotation: (annotation: Annotation) => void;
  onUpdateAnnotation: (annotation: Annotation) => void;
  onDeleteAnnotation: (id: string) => void;
  currentTool: 'select' | 'rect' | 'obb';
  labelColor?: string;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

const AnnotationCanvas = forwardRef<AnnotationCanvasRef, AnnotationCanvasProps>(({ 
  imageUrl, 
  annotations, 
  onAddAnnotation,
  onUpdateAnnotation,
  onDeleteAnnotation,
  currentTool,
  labelColor = '#ff0000',
  selectedId,
  onSelect
}, ref) => {
  const [image] = useImage(imageUrl);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [newRect, setNewRect] = useState<{ x: number; y: number; w: number; h: number; rotation?: number } | null>(null);
  const [obbStep, setObbStep] = useState<'none' | 'width' | 'height'>('none');
  const [cursorPos, setCursorPos] = useState<{ x: number; y: number } | null>(null);
  
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage>(null);
  const transformerRef = useRef<Konva.Transformer>(null);
  const isDrawing = useRef(false);
  const startPos = useRef<{ x: number; y: number } | null>(null);

  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      setScale(s => s * 1.2);
    },
    zoomOut: () => {
      setScale(s => s / 1.2);
    },
    resetView: () => {
      if (containerRef.current && image) {
        const { scale: newScale, position: newPos } = calculateFitScale(
          { width: containerRef.current.offsetWidth, height: containerRef.current.offsetHeight },
          { width: image.width, height: image.height }
        );
        setScale(newScale);
        setPosition(newPos);
      }
    }
  }));

  // Reset OBB step when tool changes
  useEffect(() => {
    setObbStep('none');
    setNewRect(null);
    isDrawing.current = false;
  }, [currentTool]);

  const selectedAnnotation = annotations.find(a => a.id === selectedId);

  // Responsive Stage & Initial Fit
  useEffect(() => {
    const checkSize = () => {
      if (containerRef.current && image) {
        const containerSize = {
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight
        };
        
        setStageSize(containerSize);

        const { scale: newScale, position: newPos } = calculateFitScale(
          containerSize,
          { width: image.width, height: image.height }
        );
        
        setScale(newScale);
        setPosition(newPos);
      }
    };
    
    if (image) {
      setTimeout(checkSize, 10);
    }
    
    window.addEventListener('resize', checkSize);
    return () => window.removeEventListener('resize', checkSize);
  }, [image]);

  // Handle Selection & Transformer
  useEffect(() => {
    if (selectedId && transformerRef.current && stageRef.current) {
      const node = stageRef.current.findOne('#' + selectedId);
      if (node) {
        transformerRef.current.nodes([node]);
        transformerRef.current.getLayer()?.batchDraw();
      }
    } else {
      transformerRef.current?.nodes([]);
      transformerRef.current?.getLayer()?.batchDraw();
    }
  }, [selectedId, annotations]);

  // Keyboard Delete
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedId) {
        onDeleteAnnotation(selectedId);
        onSelect(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedId, onDeleteAnnotation, onSelect]);

  const handleWheel = (e: Konva.KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault();
    const stage = stageRef.current;
    if (!stage) return;

    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    const { scale: newScale, position: newPos } = calculateZoom(
      stage.scaleX(),
      { x: stage.x(), y: stage.y() },
      pointer,
      e.evt.deltaY
    );

    setScale(newScale);
    setPosition(newPos);
  };

  const handleMouseDown = (e: Konva.KonvaEventObject<MouseEvent>) => {
    if (currentTool === 'select') {
      const clickedOnEmpty = e.target === e.target.getStage() || e.target.className === 'Image';
      if (clickedOnEmpty) {
        onSelect(null);
      }
      return;
    }

    const stage = e.target.getStage();
    const pos = stage?.getRelativePointerPosition();
    if (!pos || !image) return;

    const clampedPos = clampPoint(pos, { width: image.width, height: image.height });

    // Rect Tool Logic
    if (currentTool === 'rect') {
      isDrawing.current = true;
      startPos.current = clampedPos;
      setNewRect({ x: clampedPos.x, y: clampedPos.y, w: 0, h: 0 });
      onSelect(null);
      return;
    }

    // OBB Tool Logic
    if (currentTool === 'obb') {
      if (obbStep === 'none') {
        // Step 1: Start drawing the baseline (width)
        setObbStep('width');
        startPos.current = clampedPos;
        setNewRect({ x: clampedPos.x, y: clampedPos.y, w: 0, h: 0, rotation: 0 });
        onSelect(null);
      } else if (obbStep === 'width') {
        // Step 2: Finish baseline, start drawing height
        setObbStep('height');
      } else if (obbStep === 'height') {
        // Step 3: Finish height, finalize OBB
        if (newRect) {
          const finalRect = finalizeObbRect(newRect);

          onAddAnnotation({
            id: Date.now().toString(),
            sampleId: 'current',
            label: 'Object', // Label will be overwritten by parent
            type: 'obb',
            bbox: finalRect,
          });
        }
        setObbStep('none');
        setNewRect(null);
      }
    }
  };

  const handleMouseMove = (e: Konva.KonvaEventObject<MouseEvent>) => {
    const stage = e.target.getStage();
    const pos = stage?.getRelativePointerPosition();
    
    if (pos && image) {
      const clamped = clampPoint(pos, { width: image.width, height: image.height });
      if (currentTool !== 'select') {
        setCursorPos(clamped);
      } else {
        setCursorPos(null);
      }

      if (!startPos.current) return;

      if (currentTool === 'rect' && isDrawing.current) {
        setNewRect({
          x: startPos.current.x,
          y: startPos.current.y,
          w: clamped.x - startPos.current.x,
          h: clamped.y - startPos.current.y,
        });
      } else if (currentTool === 'obb') {
        if (obbStep !== 'none') {
          const obbRect = calculateObbRect(startPos.current, clamped, obbStep as 'width' | 'height', newRect);
          if (obbRect) {
            setNewRect(obbRect);
          }
        }
      }
    }
  };

  const handleMouseUp = () => {
    if (currentTool === 'rect' && isDrawing.current && newRect) {
      if (Math.abs(newRect.w) > 5 && Math.abs(newRect.h) > 5) {
        const normalizedRect = normalizeRect(newRect);

        onAddAnnotation({
          id: Date.now().toString(),
          sampleId: 'current',
          label: 'Object',
          type: 'rect',
          bbox: normalizedRect,
        });
      }
      isDrawing.current = false;
      setNewRect(null);
    }
  };

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', overflow: 'hidden', background: '#1e1e1e' }}>
      <Stage
        width={stageSize.width}
        height={stageSize.height}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setCursorPos(null)}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
        scaleX={scale}
        scaleY={scale}
        x={position.x}
        y={position.y}
        draggable={currentTool === 'select' && !selectedId}
        ref={stageRef}
      >
        <Layer>
          {image && (
            <KonvaImage 
              image={image} 
            />
          )}
          
          {annotations.map((ann: Annotation) => (
            <AnnotationItem
              key={ann.id}
              annotation={ann}
              isSelected={selectedId === ann.id}
              scale={scale}
              image={image}
              stageX={position.x}
              stageY={position.y}
              currentTool={currentTool}
              onSelect={onSelect}
              onUpdate={onUpdateAnnotation}
            />
          ))}

          <NewAnnotationLayer 
            newRect={newRect} 
            labelColor={labelColor} 
            scale={scale} 
          />

          <Crosshair
            cursorPos={cursorPos}
            imageWidth={image ? image.width : 0}
            imageHeight={image ? image.height : 0}
            scale={scale}
            visible={(currentTool === 'rect' || currentTool === 'obb') && !!image}
          />

          <CanvasTransformer
            ref={transformerRef}
            selectedAnnotation={selectedAnnotation}
            currentTool={currentTool}
            image={image}
          />
        </Layer>
      </Stage>
    </div>
  );
});

export default AnnotationCanvas;
