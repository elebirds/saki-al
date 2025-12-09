import { FC, Fragment } from 'react';
import { Rect, Text as KonvaText } from 'react-konva';
import Konva from 'konva';
import { Annotation } from '../../types';

interface AnnotationItemProps {
  annotation: Annotation;
  isSelected: boolean;
  scale: number;
  image: HTMLImageElement | undefined;
  stageX: number;
  stageY: number;
  currentTool: string;
  onSelect: (id: string) => void;
  onUpdate: (annotation: Annotation) => void;
}

const AnnotationItem: FC<AnnotationItemProps> = ({
  annotation: ann,
  isSelected,
  scale,
  image,
  stageX,
  stageY,
  currentTool,
  onSelect,
  onUpdate,
}) => {
  const handleTransformEnd = (e: Konva.KonvaEventObject<Event>) => {
    const node = e.target;
    const scaleX = node.scaleX();
    const scaleY = node.scaleY();

    // Reset scale and update width/height
    node.scaleX(1);
    node.scaleY(1);

    let x = node.x();
    let y = node.y();
    // Handle negative scale (flipping)
    let width = node.width() * scaleX;
    let height = node.height() * scaleY;
    const rotation = node.rotation();

    if (width < 0) {
      x += width;
      width = Math.abs(width);
    }
    if (height < 0) {
      y += height;
      height = Math.abs(height);
    }

    onUpdate({
      ...ann,
      bbox: {
        x,
        y,
        width: Math.max(5, width),
        height: Math.max(5, height),
        rotation,
      }
    });
  };

  const handleDragEnd = (e: Konva.KonvaEventObject<DragEvent>) => {
    const node = e.target;
    onUpdate({
      ...ann,
      bbox: {
        ...ann.bbox,
        x: node.x(),
        y: node.y(),
      }
    });
  };

  // Manually update text position during drag/transform to keep it synced
  // before the React state update occurs on dragEnd/transformEnd.
  const updateTextPosition = (e: Konva.KonvaEventObject<Event>) => {
    const stage = e.target.getStage();
    const textNode = stage?.findOne(`#text-${ann.id}`);
    if (textNode) {
      textNode.position({
        x: e.target.x(),
        y: e.target.y() - (20 / scale)
      });
      textNode.rotation(e.target.rotation());
    }
  };

  return (
    <Fragment>
      <Rect
        id={ann.id}
        x={ann.bbox.x}
        y={ann.bbox.y}
        width={ann.bbox.width}
        height={ann.bbox.height}
        rotation={ann.bbox.rotation || 0}
        stroke={ann.color || '#ff0000'}
        strokeWidth={isSelected ? 4 / scale : 2 / scale}
        shadowColor={ann.color || '#ff0000'}
        shadowBlur={isSelected ? 10 : 0}
        shadowOpacity={0.6}
        draggable={currentTool === 'select'}
        onClick={() => currentTool === 'select' && onSelect(ann.id)}
        onTap={() => currentTool === 'select' && onSelect(ann.id)}
        onDragMove={updateTextPosition}
        onTransform={updateTextPosition}
        onTransformEnd={handleTransformEnd}
        onDragEnd={handleDragEnd}
        dragBoundFunc={(pos) => {
          if (!image) return pos;
          
          // Convert absolute pos to local pos using passed stage props
          // pos is absolute. stageX/Y are absolute position of stage. scale is stage scale.
          // local = (absolute - stagePos) / scale
          
          let x = (pos.x - stageX) / scale;
          let y = (pos.y - stageY) / scale;
          
          if (ann.type === 'rect') {
            const w = ann.bbox.width;
            const h = ann.bbox.height;
            if (x < 0) x = 0;
            if (y < 0) y = 0;
            if (x + w > image.width) x = image.width - w;
            if (y + h > image.height) y = image.height - h;
          } else {
            // For OBB, loose constraint
            if (x < -image.width) x = -image.width;
            if (y < -image.height) y = -image.height;
            if (x > image.width * 2) x = image.width * 2;
            if (y > image.height * 2) y = image.height * 2;
          }
          
          return {
            x: x * scale + stageX,
            y: y * scale + stageY
          };
        }}
      />
      {/* Label Text */}
      <KonvaText
        id={`text-${ann.id}`}
        x={ann.bbox.x}
        y={ann.bbox.y - (20 / scale)}
        text={ann.label}
        fontSize={16 / scale}
        fill={ann.color || '#ff0000'}
        rotation={ann.bbox.rotation || 0}
        shadowColor="black"
        shadowBlur={2}
        shadowOpacity={1}
        shadowOffsetX={1}
        shadowOffsetY={1}
        listening={false} // Text shouldn't capture events usually
      />
    </Fragment>
  );
};

export default AnnotationItem;
