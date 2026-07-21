from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import Folder, Tag, WorkflowStatus


CatalogModel = TypeVar("CatalogModel", Folder, Tag, WorkflowStatus)


def _kind(model: type[Any]) -> str:
    if model is WorkflowStatus:
        return "workflow_status"
    return model.__name__.lower()


def list_catalog(session: Session, model: type[CatalogModel]) -> list[CatalogModel]:
    order = [model.name]
    if hasattr(model, "position"):
        order = [model.position, model.name]
    return list(session.scalars(select(model).order_by(*order)))


def create_catalog(
    session: Session, model: type[CatalogModel], values: dict[str, Any]
) -> CatalogModel:
    if hasattr(model, "position"):
        maximum = session.scalar(select(func.max(model.position)))
        values["position"] = 0 if maximum is None else maximum + 1
    item = model(**values)
    session.add(item)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        kind = _kind(model)
        raise ManagerError(
            f"{kind}_name_conflict",
            f"A {kind.replace('_', ' ')} with this name already exists.",
            409,
            {"name": "already_exists"},
        ) from error
    session.refresh(item)
    return item


def get_catalog(
    session: Session, model: type[CatalogModel], item_id: str
) -> CatalogModel:
    item = session.get(model, item_id)
    if item is None:
        kind = _kind(model)
        raise ManagerError(
            f"{kind}_not_found",
            f"The requested {kind.replace('_', ' ')} was not found.",
            404,
        )
    return item


def update_catalog(
    session: Session,
    model: type[CatalogModel],
    item_id: str,
    values: dict[str, Any],
) -> CatalogModel:
    item = get_catalog(session, model, item_id)
    for field, value in values.items():
        setattr(item, field, value)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        kind = _kind(model)
        raise ManagerError(
            f"{kind}_name_conflict",
            f"A {kind.replace('_', ' ')} with this name already exists.",
            409,
            {"name": "already_exists"},
        ) from error
    session.refresh(item)
    return item


def delete_catalog(session: Session, model: type[CatalogModel], item_id: str) -> None:
    item = get_catalog(session, model, item_id)
    session.delete(item)
    session.commit()


def reorder_catalog(
    session: Session,
    model: type[CatalogModel],
    ids: Sequence[str],
) -> list[CatalogModel]:
    kind = _kind(model)
    if not hasattr(model, "position"):
        raise ManagerError(
            f"invalid_{kind}_order",
            f"{kind.replace('_', ' ').title()} ordering is not supported.",
            422,
        )
    existing = list(session.scalars(select(model)))
    existing_ids = {item.id for item in existing}
    if len(ids) != len(set(ids)) or set(ids) != existing_ids:
        raise ManagerError(
            f"invalid_{kind}_order",
            "The order must contain every existing ID exactly once.",
            422,
            {"ids": "must_match_existing_ids"},
        )
    by_id = {item.id: item for item in existing}
    for position, item_id in enumerate(ids):
        by_id[item_id].position = position
    session.commit()
    return list_catalog(session, model)
