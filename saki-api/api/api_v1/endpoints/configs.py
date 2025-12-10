from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from api import deps
from db.session import get_session
from models import (
    User,
    QueryStrategy, QueryStrategyCreate, QueryStrategyRead, QueryStrategyUpdate,
    BaseModel, BaseModelCreate, BaseModelRead, BaseModelUpdate,
)

router = APIRouter()


# --- Query Strategies ---
@router.get("/strategies", response_model=List[QueryStrategyRead])
def get_strategies(
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user),
):
    """
    List available Active Learning query strategies.
    """
    return session.exec(select(QueryStrategy)).all()


@router.post("/strategies", response_model=QueryStrategyRead)
def create_strategy(
    strategy_in: QueryStrategyCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_superuser),
):
    if session.get(QueryStrategy, strategy_in.id):
        raise HTTPException(status_code=400, detail="Strategy ID already exists")
    strategy = QueryStrategy(**strategy_in.model_dump())
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@router.put("/strategies/{strategy_id}", response_model=QueryStrategyRead)
def update_strategy(
    strategy_id: str,
    strategy_in: QueryStrategyUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_superuser),
):
    strategy = session.get(QueryStrategy, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    update_data = strategy_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(strategy, key, value)
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@router.delete("/strategies/{strategy_id}")
def delete_strategy(
    strategy_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_superuser),
):
    strategy = session.get(QueryStrategy, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    session.delete(strategy)
    session.commit()
    return {"ok": True}


# --- Base Models ---
@router.get("/base-models", response_model=List[BaseModelRead])
def list_base_models(
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_user),
):
    """
    List system-level base/foundation models.
    """
    return session.exec(select(BaseModel)).all()


@router.post("/base-models", response_model=BaseModelRead)
def create_base_model(
    base_model_in: BaseModelCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_superuser),
):
    if session.get(BaseModel, base_model_in.id):
        raise HTTPException(status_code=400, detail="Base model ID already exists")
    base_model = BaseModel(**base_model_in.model_dump())
    session.add(base_model)
    session.commit()
    session.refresh(base_model)
    return base_model


@router.put("/base-models/{base_model_id}", response_model=BaseModelRead)
def update_base_model(
    base_model_id: str,
    base_model_in: BaseModelUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_superuser),
):
    base_model = session.get(BaseModel, base_model_id)
    if not base_model:
        raise HTTPException(status_code=404, detail="Base model not found")
    update_data = base_model_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(base_model, key, value)
    session.add(base_model)
    session.commit()
    session.refresh(base_model)
    return base_model


@router.delete("/base-models/{base_model_id}")
def delete_base_model(
    base_model_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_superuser),
):
    base_model = session.get(BaseModel, base_model_id)
    if not base_model:
        raise HTTPException(status_code=404, detail="Base model not found")
    session.delete(base_model)
    session.commit()
    return {"ok": True}
