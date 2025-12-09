from typing import List, Dict, Any
from fastapi import APIRouter, Depends
from app.models.user import User
from app.api import deps

router = APIRouter()

@router.get("/strategies", response_model=List[Dict[str, str]])
def get_strategies(
    current_user: User = Depends(deps.get_current_user)
):
    """
    Get available Active Learning strategies.
    """
    return [
        {"id": "least_confidence", "name": "Least Confidence", "description": "Selects samples where the model is least confident."},
        {"id": "margin_sampling", "name": "Margin Sampling", "description": "Selects samples with the smallest margin between top two predictions."},
        {"id": "entropy_sampling", "name": "Entropy Sampling", "description": "Selects samples with the highest entropy."},
        {"id": "random", "name": "Random Sampling", "description": "Selects samples randomly."},
    ]

@router.get("/architectures", response_model=List[Dict[str, str]])
def get_architectures(
    current_user: User = Depends(deps.get_current_user)
):
    """
    Get available Model Architectures.
    """
    return [
        {"id": "resnet18", "name": "ResNet-18", "taskType": "classification"},
        {"id": "resnet50", "name": "ResNet-50", "taskType": "classification"},
        {"id": "efficientnet_b0", "name": "EfficientNet-B0", "taskType": "classification"},
        {"id": "yolov5", "name": "YOLOv5", "taskType": "detection"},
        {"id": "faster_rcnn", "name": "Faster R-CNN", "taskType": "detection"},
    ]
