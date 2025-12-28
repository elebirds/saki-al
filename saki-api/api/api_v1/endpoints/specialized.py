"""
API endpoints for specialized annotation tasks (e.g., Satellite FEDO).
"""

import os
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query, Response
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from pydantic import BaseModel

from db.session import get_session
from models.project import Project
from models.sample import Sample
from models.enums import AnnotationSystemType, SampleStatus
from core.config import settings
from annotation_systems.satellite_fedo.processor import FedoProcessor
from annotation_systems.satellite_fedo.lookup import load_lookup_table, indices_to_physical

import numpy as np

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class FedoSampleMetadata(BaseModel):
    """Metadata for a processed FEDO sample."""
    n_time: int
    n_energy: int
    L_range: List[float]
    Wd_range: List[float]
    visualization_config: dict


class FedoSampleResponse(BaseModel):
    """Response after uploading/processing a FEDO file."""
    id: str
    project_id: str
    time_energy_image_url: str
    l_wd_image_url: str
    metadata: FedoSampleMetadata


class CoordinateMappingRequest(BaseModel):
    """Request for coordinate mapping."""
    indices: List[List[int]]  # List of [time_idx, energy_idx] pairs


class CoordinateMappingResponse(BaseModel):
    """Response with mapped physical coordinates."""
    L_values: List[float]
    Wd_values: List[float]


class BboxToIndicesRequest(BaseModel):
    """Request to get indices within a bounding box."""
    # Normalized coordinates (0-1) in Time-Energy view
    x: float       # Normalized X (time axis)
    y: float       # Normalized Y (energy axis)
    width: float   # Normalized width
    height: float  # Normalized height
    rotation: float = 0.0  # Rotation in degrees (for OBB)


class BboxToIndicesResponse(BaseModel):
    """Response with indices and their physical mappings."""
    indices: List[List[int]]  # List of [time_idx, energy_idx] pairs
    L_values: List[float]
    Wd_values: List[float]
    # For non-monotonic mapping: may return multiple regions
    regions: List[dict]  # Each region has {indices, polygon_points}


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/projects/{project_id}/fedo/upload", response_model=FedoSampleResponse)
async def upload_fedo_file(
    project_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """
    Upload and process a FEDO data file.
    
    This endpoint:
    1. Validates the project uses FEDO annotation system
    2. Saves and parses the uploaded file
    3. Generates Time-Energy and L-ωd view images
    4. Creates coordinate lookup table
    5. Creates a Sample record
    """
    # Validate project
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.annotation_system != AnnotationSystemType.FEDO:
        raise HTTPException(status_code=400, detail="Project does not use FEDO annotation system")
    
    # Save uploaded file temporarily
    upload_dir = os.path.join(settings.UPLOAD_DIR, project_id, "raw")
    os.makedirs(upload_dir, exist_ok=True)
    
    temp_path = os.path.join(upload_dir, file.filename)
    with open(temp_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    try:
        # Process the file
        storage_path = os.path.join(settings.UPLOAD_DIR, project_id, "processed")
        processor = FedoProcessor(storage_path)
        
        # Get visualization config from project settings
        viz_config = project.annotation_config.get('visualization', {})
        dpi = viz_config.get('dpi', 200)
        l_xlim = tuple(viz_config.get('l_xlim', [1.2, 1.9]))
        wd_ylim = tuple(viz_config.get('wd_ylim', [0.0, 4.0]))
        
        result = processor.process_file(
            temp_path,
            dpi=dpi,
            l_xlim=l_xlim,
            wd_ylim=wd_ylim,
        )
        
        # Create Sample record
        sample = Sample(
            project_id=project_id,
            file_path=temp_path,
            parquet_path=result['parquet_path'],
            time_energy_image_path=result['time_energy_image_path'],
            l_wd_image_path=result['l_wd_image_path'],
            lookup_table_path=result['lookup_table_path'],
            status=SampleStatus.UNLABELED,
            meta_data=result['metadata'],
        )
        sample.id = result['sample_id']
        
        session.add(sample)
        session.commit()
        session.refresh(sample)
        
        # Build response
        base_url = f"/api/v1/specialized/samples/{sample.id}"
        return FedoSampleResponse(
            id=sample.id,
            project_id=project_id,
            time_energy_image_url=f"{base_url}/image/time_energy",
            l_wd_image_url=f"{base_url}/image/l_wd",
            metadata=FedoSampleMetadata(
                n_time=result['metadata']['n_time'],
                n_energy=result['metadata']['n_energy'],
                L_range=result['metadata']['L_range'],
                Wd_range=result['metadata']['Wd_range'],
                visualization_config=result['metadata']['visualization_config'],
            ),
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")


@router.get("/samples/{sample_id}/image/{view}")
async def get_sample_image(
    sample_id: str,
    view: str,  # 'time_energy' or 'l_wd'
    session: Session = Depends(get_session),
):
    """Get the visualization image for a FEDO sample."""
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    
    if view == 'time_energy':
        image_path = sample.time_energy_image_path
    elif view == 'l_wd':
        image_path = sample.l_wd_image_path
    else:
        raise HTTPException(status_code=400, detail="Invalid view type")
    
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(image_path, media_type="image/png")


@router.get("/samples/{sample_id}/lookup")
async def get_lookup_table(
    sample_id: str,
    format: str = Query("binary", description="Response format: 'binary' or 'json'"),
    session: Session = Depends(get_session),
):
    """
    Get the coordinate lookup table for a FEDO sample.
    
    The lookup table contains pre-computed (L, ωd) values for each data index (i, j).
    Binary format is recommended for frontend performance.
    """
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    
    if not sample.lookup_table_path or not os.path.exists(sample.lookup_table_path):
        raise HTTPException(status_code=404, detail="Lookup table not found")
    
    lookup = load_lookup_table(sample.lookup_table_path)
    
    if format == "binary":
        binary_data = lookup.to_binary()
        return Response(
            content=binary_data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename=lookup_{sample_id}.bin"}
        )
    else:
        return lookup.to_dict()


@router.post("/samples/{sample_id}/map-indices", response_model=CoordinateMappingResponse)
async def map_indices_to_physical(
    sample_id: str,
    request: CoordinateMappingRequest,
    session: Session = Depends(get_session),
):
    """
    Map data indices to physical coordinates (L, ωd).
    
    Args:
        sample_id: Sample identifier
        request: List of [time_idx, energy_idx] pairs
        
    Returns:
        Corresponding L and ωd values
    """
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    
    if not sample.lookup_table_path or not os.path.exists(sample.lookup_table_path):
        raise HTTPException(status_code=404, detail="Lookup table not found")
    
    lookup = load_lookup_table(sample.lookup_table_path)
    indices = np.array(request.indices)
    
    L_values, Wd_values = indices_to_physical(lookup, indices)
    
    return CoordinateMappingResponse(
        L_values=L_values.tolist(),
        Wd_values=Wd_values.tolist(),
    )


@router.post("/samples/{sample_id}/bbox-to-indices", response_model=BboxToIndicesResponse)
async def bbox_to_indices(
    sample_id: str,
    request: BboxToIndicesRequest,
    session: Session = Depends(get_session),
):
    """
    Convert a bounding box in normalized Time-Energy coordinates to data indices
    and their corresponding physical (L, ωd) coordinates.
    
    This handles the non-monotonic mapping where one region in L-ωd space
    may correspond to two separate time regions.
    
    Args:
        sample_id: Sample identifier
        request: Bounding box in normalized coordinates
        
    Returns:
        Indices within the bbox and their physical mappings,
        plus separated regions for L-ωd view
    """
    sample = session.get(Sample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    
    if not sample.lookup_table_path or not os.path.exists(sample.lookup_table_path):
        raise HTTPException(status_code=404, detail="Lookup table not found")
    
    lookup = load_lookup_table(sample.lookup_table_path)
    
    # Convert normalized coordinates to index ranges
    n_time = lookup.n_time
    n_energy = lookup.n_energy
    
    # Handle rotation for OBB (Oriented Bounding Box)
    # For simplicity, we first handle axis-aligned case
    # TODO: Implement rotated bbox detection
    
    x_min = request.x
    x_max = request.x + request.width
    y_min = request.y
    y_max = request.y + request.height
    
    # Clamp to [0, 1]
    x_min = max(0, min(1, x_min))
    x_max = max(0, min(1, x_max))
    y_min = max(0, min(1, y_min))
    y_max = max(0, min(1, y_max))
    
    # Convert to indices
    i_min = int(x_min * n_time)
    i_max = int(x_max * n_time)
    j_min = int(y_min * n_energy)
    j_max = int(y_max * n_energy)
    
    # Clamp to valid range
    i_min = max(0, min(n_time - 1, i_min))
    i_max = max(0, min(n_time - 1, i_max))
    j_min = max(0, min(n_energy - 1, j_min))
    j_max = max(0, min(n_energy - 1, j_max))
    
    # Generate all indices in the bbox
    indices = []
    for i in range(i_min, i_max + 1):
        for j in range(j_min, j_max + 1):
            indices.append([i, j])
    
    if not indices:
        return BboxToIndicesResponse(
            indices=[],
            L_values=[],
            Wd_values=[],
            regions=[],
        )
    
    indices_np = np.array(indices)
    L_values, Wd_values = indices_to_physical(lookup, indices_np)
    
    # Detect regions for non-monotonic mapping
    # The L values typically form a parabola shape over time
    # We need to identify if the selection spans the inflection point
    regions = _split_into_regions(
        indices_np, L_values, Wd_values,
        lookup.L, lookup.Wd, n_time, n_energy
    )
    
    return BboxToIndicesResponse(
        indices=indices,
        L_values=L_values.tolist(),
        Wd_values=Wd_values.tolist(),
        regions=regions,
    )


def _split_into_regions(
    indices: np.ndarray,
    L_values: np.ndarray,
    Wd_values: np.ndarray,
    L_full: np.ndarray,
    Wd_full: np.ndarray,
    n_time: int,
    n_energy: int,
) -> List[dict]:
    """
    Split indices into separate regions based on L-ωd mapping.
    
    For satellite data, L typically has a parabolic shape over time
    (goes down then up, or up then down). This means one L range
    can correspond to two different time ranges.
    """
    if len(indices) == 0:
        return []
    
    # Find the time range of selected indices
    time_indices = np.unique(indices[:, 0])
    
    # Check if L values are monotonic within selection
    L_in_selection = L_full[time_indices]
    
    # Find inflection point (if any) - where derivative changes sign
    L_diff = np.diff(L_in_selection)
    sign_changes = np.where(np.diff(np.sign(L_diff)))[0]
    
    if len(sign_changes) == 0:
        # Monotonic - single region
        # Compute convex hull in L-ωd space for polygon
        polygon = _compute_boundary_polygon(indices, L_values, Wd_values)
        return [{
            'time_range': [int(time_indices[0]), int(time_indices[-1])],
            'polygon_points': polygon,
            'is_primary': True,
        }]
    
    # Non-monotonic - split at inflection point
    inflection_idx = sign_changes[0] + 1
    split_time = time_indices[inflection_idx]
    
    regions = []
    
    # Region 1: before inflection
    mask1 = indices[:, 0] < split_time
    if np.any(mask1):
        polygon1 = _compute_boundary_polygon(
            indices[mask1], L_values[mask1], Wd_values[mask1]
        )
        regions.append({
            'time_range': [int(time_indices[0]), int(split_time - 1)],
            'polygon_points': polygon1,
            'is_primary': True,
        })
    
    # Region 2: after inflection
    mask2 = indices[:, 0] >= split_time
    if np.any(mask2):
        polygon2 = _compute_boundary_polygon(
            indices[mask2], L_values[mask2], Wd_values[mask2]
        )
        regions.append({
            'time_range': [int(split_time), int(time_indices[-1])],
            'polygon_points': polygon2,
            'is_primary': False,
        })
    
    return regions


def _compute_boundary_polygon(
    indices: np.ndarray,
    L_values: np.ndarray,
    Wd_values: np.ndarray,
) -> List[List[float]]:
    """
    Compute boundary polygon in L-ωd space.
    Returns list of [L, Wd] points forming the polygon boundary.
    """
    if len(indices) < 3:
        # Not enough points for a polygon
        return [[float(L_values[i]), float(Wd_values[i])] for i in range(len(L_values))]
    
    try:
        from scipy.spatial import ConvexHull
        points = np.column_stack([L_values, Wd_values])
        hull = ConvexHull(points)
        polygon = points[hull.vertices].tolist()
        # Close the polygon
        polygon.append(polygon[0])
        return polygon
    except Exception:
        # Fallback: return bounding box
        L_min, L_max = float(np.min(L_values)), float(np.max(L_values))
        Wd_min, Wd_max = float(np.min(Wd_values)), float(np.max(Wd_values))
        return [
            [L_min, Wd_min],
            [L_max, Wd_min],
            [L_max, Wd_max],
            [L_min, Wd_max],
            [L_min, Wd_min],
        ]
