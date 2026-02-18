import {FC, Fragment, useMemo} from 'react';
import {Rect, Text as KonvaText} from 'react-konva';
import Konva from 'konva';
import {Annotation} from '../../types';
import {canvasDataToGeometry, geometryToCanvasData} from '../../utils/annotationGeometry';

// Helper to extract bbox from Annotation.geometry
interface BBox {
    x: number;
    y: number;
    width: number;
    height: number;
    rotation?: number;
}

function getBBox(ann: Annotation): BBox {
    const data = geometryToCanvasData(ann.type, ann.geometry);
    return {
        x: data.x || 0,
        y: data.y || 0,
        width: data.width || 0,
        height: data.height || 0,
        rotation: data.rotation,
    };
}

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
    /** 是否可以编辑此标注（基于用户权限） */
    canEdit?: boolean;
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
                                                     canEdit = true,
                                                 }) => {
    // Extract bbox from geometry field
    const bbox = useMemo(() => getBBox(ann), [ann]);
    const color = ann.labelColor || '#ff0000';
    const label = ann.labelName || '';

    // 判断是否为生成的标注（auto-generated）
    const isGenerated = ann.source === 'auto' || ann.source === 'system' || ann.source === 'model' || ann.source === 'fedo_mapping';

    // 生成的标注不能拖拽和变换，没有编辑权限的标注也不能
    const canDrag = currentTool === 'select' && !isGenerated && canEdit;
    const canTransform = !isGenerated && canEdit;

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

        const nextData = {
            x,
            y,
            width: Math.max(5, width),
            height: Math.max(5, height),
            rotation,
        };
        onUpdate({
            ...ann,
            geometry: canvasDataToGeometry(ann.type, nextData),
        });
    };

    const handleDragEnd = (e: Konva.KonvaEventObject<DragEvent>) => {
        const node = e.target;
        const nextData = {
            ...bbox,
            x: node.x(),
            y: node.y(),
        };
        onUpdate({
            ...ann,
            geometry: canvasDataToGeometry(ann.type, nextData),
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
                x={bbox.x}
                y={bbox.y}
                width={bbox.width}
                height={bbox.height}
                rotation={bbox.rotation || 0}
                stroke={color}
                strokeWidth={isSelected ? 4 / scale : 2 / scale}
                shadowColor={color}
                shadowBlur={isSelected ? 10 : 0}
                shadowOpacity={0.6}
                draggable={canDrag}
                onClick={() => currentTool === 'select' && onSelect(ann.id)}
                onTap={() => currentTool === 'select' && onSelect(ann.id)}
                onDragMove={canDrag ? updateTextPosition : undefined}
                onTransform={canTransform ? updateTextPosition : undefined}
                onTransformEnd={canTransform ? handleTransformEnd : undefined}
                onDragEnd={canDrag ? handleDragEnd : undefined}
                dragBoundFunc={(pos) => {
                    if (!image) return pos;

                    // Convert absolute pos to local pos using passed stage props
                    // pos is absolute. stageX/Y are absolute position of stage. scale is stage scale.
                    // local = (absolute - stagePos) / scale

                    let x = (pos.x - stageX) / scale;
                    let y = (pos.y - stageY) / scale;

                    if (ann.type === 'rect') {
                        const w = bbox.width;
                        const h = bbox.height;
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
                x={bbox.x}
                y={bbox.y - (20 / scale)}
                text={label}
                fontSize={16 / scale}
                fill={color}
                rotation={bbox.rotation || 0}
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
