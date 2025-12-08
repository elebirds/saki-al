import { FC } from 'react';
import { Line } from 'react-konva';

interface CrosshairProps {
  cursorPos: { x: number; y: number } | null;
  imageWidth: number;
  imageHeight: number;
  scale: number;
  visible: boolean;
}

const Crosshair: FC<CrosshairProps> = ({ cursorPos, imageWidth, imageHeight, scale, visible }) => {
  if (!visible || !cursorPos) return null;

  return (
    <>
      <Line
        points={[0, cursorPos.y, imageWidth, cursorPos.y]}
        stroke="white"
        strokeWidth={1 / scale}
        dash={[4 / scale, 4 / scale]}
        listening={false}
        opacity={0.8}
      />
      <Line
        points={[cursorPos.x, 0, cursorPos.x, imageHeight]}
        stroke="white"
        strokeWidth={1 / scale}
        dash={[4 / scale, 4 / scale]}
        listening={false}
        opacity={0.8}
      />
    </>
  );
};

export default Crosshair;
