import { useState, useRef, useEffect, useCallback } from 'react';
import Konva from 'konva';
import { calculateFitScale, calculateZoom } from '../../../utils/canvasUtils';

interface Size {
  width: number;
  height: number;
}

interface UseCanvasViewOptions {
  /** 图像对象 */
  image: HTMLImageElement | undefined;
  /** 容器 ref */
  containerRef: React.RefObject<HTMLDivElement>;
}

interface UseCanvasViewReturn {
  /** Stage 尺寸 */
  stageSize: Size;
  /** 缩放比例 */
  scale: number;
  /** 平移位置 */
  position: { x: number; y: number };
  /** Stage ref */
  stageRef: React.RefObject<Konva.Stage>;
  /** 放大 */
  zoomIn: () => void;
  /** 缩小 */
  zoomOut: () => void;
  /** 重置视图 */
  resetView: () => void;
  /** 滚轮事件处理 */
  handleWheel: (e: Konva.KonvaEventObject<WheelEvent>) => void;
}

/**
 * 画布视图控制 Hook
 * 管理缩放、平移和自适应
 */
export function useCanvasView(options: UseCanvasViewOptions): UseCanvasViewReturn {
  const { image, containerRef } = options;
  
  const [stageSize, setStageSize] = useState<Size>({ width: 0, height: 0 });
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const stageRef = useRef<Konva.Stage>(null);

  // 自适应图像到容器
  const fitToContainer = useCallback(() => {
    if (!containerRef.current || !image) return;
    
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
  }, [containerRef, image]);

  // 响应式尺寸和初始适配
  useEffect(() => {
    if (image) {
      // 延迟执行以确保容器已渲染
      setTimeout(fitToContainer, 10);
    }
    
    window.addEventListener('resize', fitToContainer);
    return () => window.removeEventListener('resize', fitToContainer);
  }, [image, fitToContainer]);

  // 放大
  const zoomIn = useCallback(() => {
    setScale(s => s * 1.2);
  }, []);

  // 缩小
  const zoomOut = useCallback(() => {
    setScale(s => s / 1.2);
  }, []);

  // 重置视图
  const resetView = useCallback(() => {
    fitToContainer();
  }, [fitToContainer]);

  // 滚轮缩放
  const handleWheel = useCallback((e: Konva.KonvaEventObject<WheelEvent>) => {
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
  }, []);

  return {
    stageSize,
    scale,
    position,
    stageRef,
    zoomIn,
    zoomOut,
    resetView,
    handleWheel,
  };
}
