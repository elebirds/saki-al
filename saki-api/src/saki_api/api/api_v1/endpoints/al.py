from typing import List

from fastapi import APIRouter, Depends
from saki_api.api import deps
from saki_api.db.session import get_session
from saki_api.models import (
    Sample, SampleRead, SampleStatus
)
from saki_api.models.user import User
from sqlmodel import Session, select

router = APIRouter()


@router.post("/{project_id}/query", response_model=List[SampleRead])
def query_samples(
        project_id: str,
        n: int = 10,
        session: Session = Depends(get_session),
        current_user: User = Depends(deps.get_current_user)
):
    """
    Query next batch of samples to label.
    """
    # Mock implementation: return random unlabeled samples
    # In real implementation, this would call the AL strategy
    statement = select(Sample).where(
        Sample.project_id == project_id,
        Sample.status == SampleStatus.UNLABELED
    ).limit(n)
    samples = session.exec(statement).all()
    return samples
