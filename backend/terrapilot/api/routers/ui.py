"""Server-driven UI: bootstrap, layouts, forms (§2.1, §14).

The frontend is a generic renderer: everything it shows — strings, colours, navigation, widget
placement, thresholds — comes from these endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status

from terrapilot.api.deps import ConfigDep, OptionalUser, api_error
from terrapilot.api.schemas import (
    Bootstrap,
    FormOut,
    LayoutOut,
    NavItem,
    ResolvedWidget,
    UiBootstrap,
    UserOut,
    WsConfig,
)
from terrapilot.core.config import ConfigBundle, resolve_ref_value
from terrapilot.core.refs import RefError

router = APIRouter(tags=["ui"])


def _units_for(cfg: ConfigBundle, locale: str) -> dict[str, Any]:
    system = cfg.units.system_by_locale.get(locale, cfg.units.default_system)
    return {"system": system, "quantities": cfg.units.systems[system].model_dump()["quantities"]}


def _nav_for(cfg: ConfigBundle, role: str) -> list[NavItem]:
    items = []
    for sid in cfg.nav.roles.get(role, []):
        screen = cfg.nav.screens[sid]
        items.append(
            NavItem(
                id=sid,
                path=screen.path,
                label_key=screen.label_key,
                public=screen.public,
                chrome=screen.chrome,
                requires=screen.requires,
                in_menu=sid not in cfg.nav.menu_hidden,
            )
        )
    return items


@router.get("/api/bootstrap", response_model=Bootstrap)
def bootstrap(cfg: ConfigDep, principal: OptionalUser, locale: str | None = None) -> Bootstrap:
    app = cfg.app
    loc = locale or principal.locale or app.locales.default
    if loc not in cfg.i18n:
        loc = app.locales.default
    role = principal.role
    user = None
    if role != "anonymous":
        user = UserOut(id=principal.user_id, name=principal.name, role=role, locale=loc, site_id=principal.site_id)
    return Bootstrap(
        product=app.product.model_dump(),
        locale=loc,
        locales=app.locales.available,
        features=app.features,
        theme=cfg.theme.model_dump(),
        i18n=cfg.i18n[loc],
        units=_units_for(cfg, loc),
        nav=_nav_for(cfg, role),
        ws=WsConfig(**app.api.ws.model_dump()),
        refresh=app.refresh,
        ui=UiBootstrap(
            default_device=app.ui.default_device,
            devices=list(app.ui.devices),
            default_screen=app.ui.default_screen_by_role.get(role, app.ui.default_screen_by_role["anonymous"]),
            alert_stack_max=app.ui.alert_stack_max,
            state_diff_throttle_ms=app.ui.state_diff_throttle_ms,
        ),
        timezone=str(app.site_calendar.get("timezone", "UTC")),
        user=user,
    )


@router.get("/api/ui/layout", response_model=LayoutOut)
def layout(
    cfg: ConfigDep,
    principal: OptionalUser,
    screen: str = Query(...),
    device: str = Query(...),
    machine_class: str | None = Query(default=None),
    manifest_id: str | None = Query(default=None),
) -> LayoutOut:
    screen_cfg = cfg.nav.screens.get(screen)
    if screen_cfg is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    if not screen_cfg.public and screen not in cfg.nav.roles.get(principal.role, []):
        raise api_error(
            status.HTTP_403_FORBIDDEN if principal.role != "anonymous" else status.HTTP_401_UNAUTHORIZED,
            "forbidden" if principal.role != "anonymous" else "unauthorized",
        )
    if manifest_id and manifest_id not in cfg.manifests:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    if manifest_id and not machine_class:
        machine_class = cfg.manifests[manifest_id].class_
    found = cfg.layout_for(screen, device, machine_class)
    if found is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    widgets = [
        ResolvedWidget(
            id=w.id,
            type=w.type,
            area=w.area,
            bind=w.bind,
            props=w.props,
            resolved=_resolve_widget(cfg, w.refs(), w.sensor_ref, manifest_id),
        )
        for w in found.widgets
    ]
    return LayoutOut(
        screen=found.screen,
        device=found.device,
        machine_class=found.machine_class,
        grid=found.grid.model_dump(),
        modes={k: v.model_dump() for k, v in found.modes.items()},
        widgets=widgets,
    )


def _resolve_widget(
    cfg: ConfigBundle, refs: dict[str, str], sensor_ref: str | None, manifest_id: str | None
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, ref in refs.items():
        name = key.removesuffix("_ref")
        try:
            out[name] = resolve_ref_value(cfg, ref, manifest_id)
        except (RefError, KeyError):
            out[name] = None  # manifest-scoped refs resolve once a machine is selected
    if sensor_ref and manifest_id:
        sensor = cfg.manifests[manifest_id].sensor(sensor_ref)
        out["sensor"] = sensor.model_dump() if sensor else None
    return out


@router.get("/api/ui/forms/{form_id}", response_model=FormOut, response_model_by_alias=True)
def form(form_id: str, cfg: ConfigDep) -> FormOut:
    f = cfg.forms.get(form_id)
    if f is None:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found")
    return FormOut.model_validate(
        dict(
            id=f.id,
            title_key=f.title_key,
            submit_key=f.submit_key,
            action=f.action,
            errors=f.errors,
            schema=f.schema_,
            ui_schema=f.ui_schema,
        )
    )
