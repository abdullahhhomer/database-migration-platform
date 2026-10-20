# Database Migration & Validation Platform

A production-style data engineering platform for migrating a live PostgreSQL
workload into Databricks while maintaining synchronization through CDC,
transforming data through a Bronze/Silver/Gold lakehouse architecture,
validating source-to-target consistency, and determining migration readiness
for cutover.

## Architecture

```text
PostgreSQL
    |
    +-- Initial Snapshot
    |
    +-- CDC
    |
    v
Databricks Bronze
    |
    v
dbt Silver
    |
    v
dbt Gold
    |
    v
Validation Engine
    |
    v
Migration Readiness