"""Health, config validation and LLM status (§9.2 Admin)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from terrapilot.api.deps import Principal, require_roles
from terrapilot.core.config import load_config
from terrapilot.db.engine import get_engine
from terrapilot.llm.gateway import get_gateway

router = APIRouter(tags=["admin"])


@router.get("/api/health")
def health() -> dict[str, Any]:
    db_ok = True
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


@router.get("/api/admin/config/validate")
def config_validate(_: Principal = Depends(require_roles("admin", "supervisor"))) -> dict[str, Any]:
    bundle = load_config(strict=False)
    return {
        "valid": not any(i.level == "error" for i in bundle.issues),
        "issues": [{"file": i.file, "key": i.key, "message": i.message, "level": i.level} for i in bundle.issues],
    }


@router.get("/api/admin/llm/status")
def llm_status(_: Principal = Depends(require_roles("admin", "supervisor"))) -> dict[str, Any]:
    return get_gateway().status()


@router.get("/api/evals/latest")
def evals_latest(_: Principal = Depends(require_roles("admin", "supervisor"))) -> dict[str, Any]:
    import json
    import sys
    from pathlib import Path
    from terrapilot.core.settings import REPO_ROOT

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    report_file = REPO_ROOT / "evals" / "reports" / "latest.json"
    if not report_file.is_file():
        from evals.runner import run_all_evals, save_reports
        reports = run_all_evals()
        report_file = save_reports(reports)
    return json.loads(report_file.read_text(encoding="utf-8"))

