from app.targets.base import Change, Target


def get_target(name: str) -> Target:
    """Creates a new target instance (each thread/process uses its own)."""
    if name == "databricks":
        from app.targets.databricks import DatabricksTarget
        return DatabricksTarget()
    if name == "sqlserver":
        from app.targets.sqlserver import SqlServerTarget
        return SqlServerTarget()
    if name == "mongodb":
        from app.targets.mongodb import MongoTarget
        return MongoTarget()
    raise ValueError(f"Unknown target '{name}'")


__all__ = ["Change", "Target", "get_target"]
