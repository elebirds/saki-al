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
      style={{
        position: 'absolute',
        bottom: 8,
        right: 8,
        zIndex: 10,
        background: 'rgba(0, 0, 0, 0.7)',
        color: '#fff',
        padding: '6px 12px',
        borderRadius: 4,
        fontSize: 12,
        fontFamily: 'monospace',
        pointerEvents: 'none',
        userSelect: 'none',
        boxShadow: '0 2px 4px rgba(0, 0, 0, 0.3)',
      }}
    >
      X: {formatCoordinate(cursorPos.x)}, Y: {formatCoordinate(cursorPos.y)}
    </div>
  );
};

export default CoordinateDisplay;

