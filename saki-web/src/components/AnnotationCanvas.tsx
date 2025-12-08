import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react';
import { Stage, Layer, Image as KonvaImage, Rect, Transformer } from 'react-konva';
import useImage from 'use-image';
import Konva from 'konva';
import { Annotation } from '../types';
import AnnotationItem from './canvas/AnnotationItem';
import Crosshair from './canvas/Crosshair';

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
  // const [selectedId, setSelectedId] = useState<string | null>(null); // Lifted up
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
        const containerW = containerRef.current.offsetWidth;
        const containerH = containerRef.current.offsetHeight;
        const scaleW = containerW / image.width;
        const scaleH = containerH / image.height;
        const newScale = Math.min(scaleW, scaleH);
        setScale(newScale);
        setPosition({
          x: (containerW - image.width * newScale) / 2,
          y: (containerH - image.height * newScale) / 2
        });
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

  // Helper to clamp point to image bounds
  const clampPoint = (p: { x: number; y: number }) => {
    if (!image) return p;
    return {
      x: Math.max(0, Math.min(image.width, p.x)),
      y: Math.max(0, Math.min(image.height, p.y))
    };
  };

  // Responsive Stage & Initial Fit
  useEffect(() => {
    const checkSize = () => {
      if (containerRef.current && image) {
        const containerW = containerRef.current.offsetWidth;
        const containerH = containerRef.current.offsetHeight;
        
        setStageSize({
          width: containerW,
          height: containerH
        });

        // Calculate scale to fit image
        const scaleW = containerW / image.width;
        const scaleH = containerH / image.height;
        // Use 0.95 to leave a small margin, or 1.0 for full fit. User asked to "fill".
        // Let's use 0.98 for a tiny margin so it doesn't touch edges exactly, or 1.0.
        // "Image should fill annotation area" -> 1.0 is probably what they mean by "fill".
        const newScale = Math.min(scaleW, scaleH); 
        
        setScale(newScale);
        
        // Center image
        setPosition({
          x: (containerW - image.width * newScale) / 2,
          y: (containerH - image.height * newScale) / 2
        });
      }
    };
    
    if (image) {
      // Small timeout to ensure container has size
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

    const oldScale = stage.scaleX();
    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    const scaleBy = 1.1;
    const newScale = e.evt.deltaY < 0 ? oldScale * scaleBy : oldScale / scaleBy;

    const mousePointTo = {
      x: (pointer.x - stage.x()) / oldScale,
      y: (pointer.y - stage.y()) / oldScale,
    };

    const newPos = {
      x: pointer.x - mousePointTo.x * newScale,
      y: pointer.y - mousePointTo.y * newScale,
    };

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
    if (!pos) return;

    const clampedPos = clampPoint(pos);

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
        // Start Step 1: Click to define first point
        setObbStep('width');
        startPos.current = clampedPos;
        // Initialize with 0 size
        setNewRect({ x: clampedPos.x, y: clampedPos.y, w: 0, h: 0, rotation: 0 });
        onSelect(null);
      } else if (obbStep === 'width') {
        // Finish Step 1: Click to define second point (width & rotation)
        setObbStep('height');
      } else if (obbStep === 'height') {
        // Finish Step 2: Click to define height and finalize
        if (newRect) {
          // Normalize negative height/width if needed
          let finalRect = { ...newRect };
          
          if (finalRect.h < 0) {
             const rad = (finalRect.rotation || 0) * Math.PI / 180;
             const shiftX = -Math.sin(rad) * finalRect.h;
             const shiftY = Math.cos(rad) * finalRect.h;
             
             finalRect.x += shiftX;
             finalRect.y += shiftY;
             finalRect.h = Math.abs(finalRect.h);
          }

          onAddAnnotation({
            id: Date.now().toString(),
            sampleId: 'current',
            label: 'Object',
            type: 'obb',
            bbox: {
              x: finalRect.x,
              y: finalRect.y,
              width: finalRect.w,
              height: finalRect.h,
              rotation: finalRect.rotation
            },
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
    
    if (pos) {
      const clamped = clampPoint(pos);
      if (currentTool !== 'select') {
        setCursorPos(clamped);
      } else {
        setCursorPos(null);
      }
    }

    if (!pos || !startPos.current) return;

    const clampedPos = clampPoint(pos);

    if (currentTool === 'rect' && isDrawing.current) {
      setNewRect({
        x: startPos.current.x,
        y: startPos.current.y,
        w: clampedPos.x - startPos.current.x,
        h: clampedPos.y - startPos.current.y,
      });
    } else if (currentTool === 'obb') {
      if (obbStep === 'width') {
        // Moving to define width and rotation (after first click)
        const dx = clampedPos.x - startPos.current.x;
        const dy = clampedPos.y - startPos.current.y;
        const width = Math.sqrt(dx * dx + dy * dy);
        const rotation = Math.atan2(dy, dx) * 180 / Math.PI;
        
        setNewRect({
          x: startPos.current.x,
          y: startPos.current.y,
          w: width,
          h: 0, 
          rotation: rotation
        });
      } else if (obbStep === 'height' && newRect) {
        // Moving to define height (after second click)
        const dx = clampedPos.x - startPos.current.x;
        const dy = clampedPos.y - startPos.current.y;
        
        const rad = (newRect.rotation || 0) * Math.PI / 180;
        const perpX = -Math.sin(rad);
        const perpY = Math.cos(rad);
        
        const height = dx * perpX + dy * perpY;
        
        setNewRect({
          ...newRect,
          h: height
        });
      }
    }
  };

  const handleMouseUp = () => {
    if (currentTool === 'rect' && isDrawing.current && newRect) {
      if (Math.abs(newRect.w) > 5 && Math.abs(newRect.h) > 5) {
        const normalizedRect = {
          x: newRect.w < 0 ? newRect.x + newRect.w : newRect.x,
          y: newRect.h < 0 ? newRect.y + newRect.h : newRect.y,
          width: Math.abs(newRect.w),
          height: Math.abs(newRect.h),
          rotation: 0
        };

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
    // OBB logic is now handled in handleMouseDown (clicks)
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
        draggable={currentTool === 'select' && !selectedId} // Pan when nothing selected in select mode
        ref={stageRef}
      >
        <Layer>
          {image && (
            <KonvaImage 
              image={image} 
              // Fit image to stage initially if needed, or just display at 0,0
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

          {newRect && (
            <Rect
              x={newRect.x}
              y={newRect.y}
              width={newRect.w}
              height={newRect.h}
              rotation={newRect.rotation || 0}
              stroke={labelColor}
              strokeWidth={2 / scale}
            />
          )}

          <Crosshair
            cursorPos={cursorPos}
            imageWidth={image ? image.width : 0}
            imageHeight={image ? image.height : 0}
            scale={scale}
            visible={(currentTool === 'rect' || currentTool === 'obb') && !!image}
          />

          <Transformer
            ref={transformerRef}
            rotateEnabled={currentTool === 'select' && selectedAnnotation?.type === 'obb'}
            keepRatio={false}
            ignoreStroke={true}
            boundBoxFunc={(_oldBox, newBox) => {
              if (!image || selectedAnnotation?.type !== 'rect') return newBox;
              
              let { x, y, width, height, rotation } = newBox;

              // Clamp to image bounds instead of rejecting
              if (x < 0) {
                width += x;
                x = 0;
              }
              if (y < 0) {
                height += y;
                y = 0;
              }
              
              if (x + width > image.width) {
                width = image.width - x;
              }
              if (y + height > image.height) {
                height = image.height - y;
              }

              return { x, y, width, height, rotation };
            }}
          />
        </Layer>
      </Stage>
    </div>
  );
});

export default AnnotationCanvas;
