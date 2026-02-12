"""
坐标转换工具模块

统一管理 OBB（Oriented Bounding Box）坐标转换逻辑

坐标系说明：
- 前端 Canvas：使用左上角坐标 (x, y) 作为起点
- 后端存储：使用中心点坐标 (x, y) 作为定位点

所有与前端的数据交互都需要进行坐标转换：
- 从前端接收：左上角坐标 → 中心点坐标
- 返回前端：中心点坐标 → 左上角坐标
"""

import math
from typing import Dict, Any, List, Optional


def origin_to_center(bbox: Dict[str, Any]) -> Dict[str, Any]:
    """
    将左上角坐标转换为中心点坐标
    
    Args:
        bbox: 包含 x, y, width, height, rotation 的字典（左上角坐标）
    
    Returns:
        包含 x, y, width, height, rotation 的字典（中心点坐标）
    """
    x = bbox.get('x', 0)
    y = bbox.get('y', 0)
    width = bbox.get('width', 0)
    height = bbox.get('height', 0)
    rotation = bbox.get('rotation', 0)

    # 将角度转换为弧度
    rad = math.radians(rotation)

    # 计算从左上角到中心的偏移向量（在局部未旋转坐标系中）
    # 左上角是原点，所以偏移是 (width/2, height/2)
    local_offset_x = width / 2
    local_offset_y = height / 2

    # 将偏移向量旋转到世界坐标系
    cos_rad = math.cos(rad)
    sin_rad = math.sin(rad)
    world_offset_x = local_offset_x * cos_rad - local_offset_y * sin_rad
    world_offset_y = local_offset_x * sin_rad + local_offset_y * cos_rad

    # 中心点 = 左上角点 + 旋转后的偏移量
    return {
        'x': x + world_offset_x,
        'y': y + world_offset_y,
        'width': width,
        'height': height,
        'rotation': rotation,
    }


def center_to_origin(bbox: Dict[str, Any]) -> Dict[str, Any]:
    """
    将中心点坐标转换为左上角坐标
    
    Args:
        bbox: 包含 x, y, width, height, rotation 的字典（中心点坐标）
    
    Returns:
        包含 x, y, width, height, rotation 的字典（左上角坐标）
    """
    x = bbox.get('x', 0)
    y = bbox.get('y', 0)
    width = bbox.get('width', 0)
    height = bbox.get('height', 0)
    rotation = bbox.get('rotation', 0)

    # 将角度转换为弧度
    rad = math.radians(rotation)

    # 计算从中心到左上角的偏移向量（在局部未旋转坐标系中）
    # 偏移是 -(width/2, height/2)
    local_offset_x = -width / 2
    local_offset_y = -height / 2

    # 将偏移向量旋转到世界坐标系
    cos_rad = math.cos(rad)
    sin_rad = math.sin(rad)
    world_offset_x = local_offset_x * cos_rad - local_offset_y * sin_rad
    world_offset_y = local_offset_x * sin_rad + local_offset_y * cos_rad

    # 左上角点 = 中心点 + 旋转后的偏移量
    return {
        'x': x + world_offset_x,
        'y': y + world_offset_y,
        'width': width,
        'height': height,
        'rotation': rotation,
    }


def convert_annotation_data_to_backend(annotation_type: str, data: Optional[Dict[str, Any]]) -> Optional[
    Dict[str, Any]]:
    """
    将前端标注数据转换为后端存储格式（左上角坐标 → 中心点坐标）
    
    Args:
        annotation_type: 标注类型 ('rect' 或 'obb')
        data: 标注数据字典
    
    Returns:
        转换后的标注数据字典，如果不需要转换则返回原数据
    """
    if not data:
        return data

    # 对于 rect 和 obb 类型，都需要转换（因为后端统一使用中心点坐标存储）
    if annotation_type in ('rect', 'obb'):
        # 检查是否包含必要的字段
        if 'x' in data and 'y' in data and 'width' in data and 'height' in data:
            return origin_to_center(data)

    # 其他类型（polygon 等）不需要转换
    return data


def convert_annotation_data_to_frontend(annotation_type: str, data: Optional[Dict[str, Any]]) -> Optional[
    Dict[str, Any]]:
    """
    将后端存储格式转换为前端显示格式（中心点坐标 → 左上角坐标）
    
    Args:
        annotation_type: 标注类型 ('rect' 或 'obb')
        data: 标注数据字典
    
    Returns:
        转换后的标注数据字典，如果不需要转换则返回原数据
    """
    if not data:
        return data

    # 对于 rect 和 obb 类型，都需要转换（因为后端存储使用中心点坐标）
    if annotation_type in ('rect', 'obb'):
        # 检查是否包含必要的字段
        if 'x' in data and 'y' in data and 'width' in data and 'height' in data:
            return center_to_origin(data)

    # 其他类型（polygon 等）不需要转换
    return data


def convert_annotation_item_to_backend(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    将前端 AnnotationItem 转换为后端存储格式
    
    Args:
        item: 前端标注项字典
    
    Returns:
        转换后的标注项字典
    """
    item_copy = item.copy()
    annotation_type = item_copy.get('type', 'rect')

    if 'data' in item_copy:
        item_copy['data'] = convert_annotation_data_to_backend(annotation_type, item_copy['data'])

    return item_copy


def convert_annotation_item_to_frontend(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    将后端存储格式转换为前端 AnnotationItem 格式
    
    Args:
        item: 后端标注项字典
    
    Returns:
        转换后的标注项字典
    """
    item_copy = item.copy()
    annotation_type = item_copy.get('type', 'rect')

    if 'data' in item_copy:
        item_copy['data'] = convert_annotation_data_to_frontend(annotation_type, item_copy['data'])

    return item_copy


def convert_annotations_to_backend(annotations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    批量转换前端标注列表为后端存储格式
    
    Args:
        annotations: 前端标注项列表
    
    Returns:
        转换后的标注项列表
    """
    return [convert_annotation_item_to_backend(ann) for ann in annotations]


def convert_annotations_to_frontend(annotations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    批量转换后端存储格式为前端标注列表
    
    Args:
        annotations: 后端标注项列表
    
    Returns:
        转换后的标注项列表
    """
    return [convert_annotation_item_to_frontend(ann) for ann in annotations]
