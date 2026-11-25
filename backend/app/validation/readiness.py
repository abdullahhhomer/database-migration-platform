"""
Cutover readiness: every condition must hold before the application can be
pointed at the new systems.
"""

from app.control import fetch_all_dicts, get_control, latest_run, run_targets
from app.migration.reader import get_db_connection
from app.validation.validator import latest_validation


def _cdc_status() -> dict[str, dict]:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM cdc_status")
            return {r["target"]: r for r in fetch_all_dicts(cursor)}
    finally:
        connection.close()


def get_migration_readiness() -> dict:
    control = get_control()
    run = latest_run()
    targets = run_targets(run)
    cdc = _cdc_status()
    validation = latest_validation()
    token = control.get("heartbeat_token")

    conditions = []

    conditions.append({
        "name": "Full load completed",
        "ok": bool(run) and run["status"] == "full_load_completed",
        "detail": f"run {run['id']}: {run['status']}" if run else "no migration run yet",
    })

    conditions.append({
        "name": "Application writes frozen",
        "ok": bool(control.get("writes_frozen")),
        "detail": "frozen" if control.get("writes_frozen") else "source is still taking writes",
    })

    for target in targets:
        status = cdc.get(target, {})
        drained = bool(token) and status.get("last_heartbeat") == token
        conditions.append({
            "name": f"CDC drained: {target}",
            "ok": drained,
            "detail": status.get("state") or "no applier status",
        })

    if validation:
        covered = set((validation.get("targets") or "").split(","))
        valid = (
            validation["status"] == "passed"
            and bool(validation.get("writes_frozen"))
            and run is not None
            and validation.get("migration_run_id") == run["id"]
            and set(targets) <= covered
        )
        detail = (
            f"validation #{validation['run_id']}: {validation['passed_checks']}/"
            f"{validation['total_checks']} checks passed"
            + ("" if validation.get("writes_frozen") else " (taken while source was live)")
        )
    else:
        valid, detail = False, "no validation run yet"

    conditions.append({"name": "Validation passed on a frozen source", "ok": valid, "detail": detail})

    ready = bool(conditions) and all(c["ok"] for c in conditions)

    failed_checks = []
    if validation:
        failed_checks = [r for r in validation["results"] if r["status"] != "passed"][:50]

    return {
        "status": "ready" if ready else "not_ready",
        "cutover_status": control.get("cutover_status"),
        "migration_run_id": run["id"] if run else None,
        "validation_run_id": validation["run_id"] if validation else None,
        "conditions": conditions,
        "failed_checks": failed_checks,
    }
