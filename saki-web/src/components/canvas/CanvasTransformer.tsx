import { forwardRef } from 'react';
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
  // 判断是否为生成的标注（auto-generated）
  const isGenerated = selectedAnnotation?.source === 'auto' || !!selectedAnnotation?.extra?.parent_id;
  
  // 只有主标注（非生成的）可以调整大小
  const canResize = !isGenerated && currentTool === 'select';
  
  return (
    <Transformer
      ref={ref}
      rotateEnabled={canResize && selectedAnnotation?.type === 'obb'}
      enabledAnchors={canResize ? undefined : []} // 如果是生成的标注，禁用所有锚点（无法调整大小）
      resizeEnabled={canResize}
      keepRatio={false}
      ignoreStroke={true}
      boundBoxFunc={(_oldBox, newBox) => {
        // 只对矩形类型应用边界约束，OBB 不限制
        if (!image || selectedAnnotation?.type !== 'rect') return newBox;
        
        let { x, y, width, height, rotation } = newBox;

        // 只限制起始位置不能超出图像边界，不限制大小
        // 如果左上角超出图像，调整位置和大小
        if (x < 0) {
          width += x;
          x = 0;
        }
        if (y < 0) {
          height += y;
          y = 0;
        }

        // 确保最小尺寸
        width = Math.max(5, width);
        height = Math.max(5, height);

        return { x, y, width, height, rotation };
      }}
    />
  );
});

export default CanvasTransformer;
