import React, { forwardRef } from 'react';
import { Transformer } from 'react-konva';
import Konva from 'konva';
import { Annotation } from '../../types';

interface CanvasTransformerProps {
  selectedAnnotation?: Annotation;
  currentTool: string;
  image?: HTMLImageElement;
}

const CanvasTransformer = forwardRef<Konva.Transformer, CanvasTransformerProps>(({
  selectedAnnotation,
  currentTool,
  image
}, ref) => {
  return (
    <Transformer
      ref={ref}
      rotateEnabled={currentTool === 'select' && selectedAnnotation?.type === 'obb'}
      keepRatio={false}
      ignoreStroke={true}
      boundBoxFunc={(_oldBox, newBox) => {
        if (!image || selectedAnnotation?.type !== 'rect') return newBox;
        
        let { x, y, width, height, rotation } = newBox;

        // Clamp the transformer box to the image boundaries
        // This prevents resizing the annotation outside the image area
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
  );
});

export default CanvasTransformer;
