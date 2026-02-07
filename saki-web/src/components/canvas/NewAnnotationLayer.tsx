import React from 'react';
import {Rect} from 'react-konva';

interface NewAnnotationLayerProps {
    newRect: { x: number; y: number; w: number; h: number; rotation?: number } | null;
    labelColor: string;
    scale: number;
}

const NewAnnotationLayer: React.FC<NewAnnotationLayerProps> = ({newRect, labelColor, scale}) => {
    if (!newRect) return null;

    return (
        <Rect
            x={newRect.x}
            y={newRect.y}
            width={newRect.w}
            height={newRect.h}
            rotation={newRect.rotation || 0}
            stroke={labelColor}
            strokeWidth={2 / scale}
        />
    );
};

export default NewAnnotationLayer;
