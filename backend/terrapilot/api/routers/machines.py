"""Machines and manifests (§9.2 Machines & live)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import select

from terrapilot.api.deps import ConfigDep, CurrentUser, DbDep, api_error
from terrapilot.api.schemas import MachineOut
from terrapilot.core.config import ConfigBundle
from terrapilot.db.schema import machines

router = APIRouter(prefix="/api/machines", tags=["machines"])


def machine_out(cfg: ConfigBundle, row: dict[str, Any]) -> MachineOut:
    manifest = cfg.manifests.get(row["manifest_id"])
    return MachineOut(
        id=row["id"],
        site_id=row["site_id"],
        manifest_id=row["manifest_id"],
        machine_class=row["machine_class"],
        model_key=manifest.name_key if manifest else row["manifest_id"],
        powertrain=row["powertrain"],
        status=row["status"],
        hour_meter=float(row["hour_meter"]),
    )


@router.get("", response_model=list[MachineOut])
def list_machines(principal: CurrentUser, cfg: ConfigDep, conn: DbDep, site_id: str | None = None) -> list[MachineOut]:
    """Operators see machines on their own site; other roles may filter by site."""
    query = select(machines).order_by(machines.c.id)
    scope = site_id or (principal.site_id if principal.role == "operator" else None)
    if scope:
        query = query.where(machines.c.site_id == scope)
    return [machine_out(cfg, dict(r)) for r in conn.execute(query).mappings()]


@router.get("/{machine_id}", response_model=MachineOut)
def get_machine(machine_id: str, principal: CurrentUser, cfg: ConfigDep, conn: DbDep) -> MachineOut:
    row = conn.execute(select(machines).where(machines.c.id == machine_id)).mappings().first()
    if row is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return machine_out(cfg, dict(row))


@router.get("/{machine_id}/manifest")
def get_manifest(machine_id: str, principal: CurrentUser, cfg: ConfigDep, conn: DbDep) -> dict[str, Any]:
    row = conn.execute(select(machines.c.manifest_id).where(machines.c.id == machine_id)).first()
    if row is None or row[0] not in cfg.manifests_raw:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return cfg.manifests_raw[row[0]]
