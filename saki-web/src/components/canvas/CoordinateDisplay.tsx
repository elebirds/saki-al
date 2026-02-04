import { FC } from 'react';

interface CoordinateDisplayProps {
  /** 当前鼠标位置（图像坐标） */
  cursorPos: { x: number; y: number } | null;
  /** 是否可见 */
  visible: boolean;
}

/**
 * 坐标显示组件
 * 在画布上显示当前鼠标位置对应的图像坐标
 */
const CoordinateDisplay: FC<CoordinateDisplayProps> = ({ cursorPos, visible }) => {
  if (!visible || !cursorPos) return null;

  // 格式化坐标，保留2位小数
  const formatCoordinate = (value: number): string => {
    return value.toFixed(2);
  };

  return (
    <div
      className="absolute bottom-2 right-2 z-10 select-none rounded bg-black/70 px-3 py-1.5 text-xs font-mono text-white shadow-[0_2px_4px_rgba(0,0,0,0.3)] pointer-events-none"
    >
      X: {formatCoordinate(cursorPos.x)}, Y: {formatCoordinate(cursorPos.y)}
    </div>
  );
};

export default CoordinateDisplay;
