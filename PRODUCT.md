# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Dashboard: React + TypeScript + Vite with a small motion library for state transitions, built in a multi-stage Docker image and served by nginx (chosen by the author over plain HTML/JS and Streamlit). Backend stays FastAPI.

## Users

Engineers and data teams at a company the author is demoing to (e.g. a hiring panel or data engineering team). They judge whether the author understands live database migration: change data capture, consistency between source and targets, validation and a safe cutover. They see the product through a screen recording or screenshots, not by operating it themselves, so every state must read on its own as a still image.

## Product Purpose

A demo platform that migrates a live PostgreSQL database (~1.2M rows, continuous writes) into three systems and formats at once (Databricks lakehouse, SQL Server, MongoDB documents), keeps them in sync with CDC, proves correctness, and runs a controlled cutover. The dashboard is the control room that makes this visible: progress, sync state, proof of correctness, and cutover readiness. Success: a viewer can follow the migration story and trust the result from a recording.

## Positioning

Shows the hard parts that toy migrations skip, with real evidence on screen:
- migration while the source keeps taking writes (full load and CDC run together, replay is idempotent);
- per-target proof (counts, foreign keys, money checksums, duplicate keys, sampled row compares);
- a watermark-based drain before cutover (heartbeat through every Kinesis shard);
- AWS-shaped infrastructure (S3, Kinesis, DynamoDB, Secrets Manager) mocked locally with moto, so the same code points at real AWS.

## Operating Context

The author runs `docker compose up`, then clicks through the dashboard at http://localhost:3000 while recording: Start migration -> watch full load and CDC backlog -> Validate -> Start cutover -> Rollback to repeat. Sequential (1 worker) vs parallel (4 workers) runs are compared in the run history. Recordings are typically 1080p.

## Capabilities and Constraints

- Static HTML/CSS/JS served by nginx; no build step. Polls `GET /api/dashboard` every 2 s; actions are POSTs to `/api/migration/*`, `/api/validation/run`, `/api/cutover/*`.
- Targets: `databricks` (real Free Edition workspace), `sqlserver` (stands in for Amazon RDS for SQL Server), `mongodb` (stands in for Amazon DocumentDB).
- AWS services are mocked by moto; the UI must say "mocked" / "stands in for" honestly, never imply real AWS.
- Terminology: run, job (table x target), full load, CDC, producer, applier, backlog, in sync, watermark/heartbeat, validation check, readiness condition, cutover, rollback, writes frozen.

## Brand Commitments

- Product name: "Migration Control Room" (neutral product name).
- Author credit: "built by Abdullah Omer" (author's name from the repository history; confirm spelling with the author).
- No company logos or company names.

## Evidence on Hand

Real measured results from the author's run #1: ~2.76M rows loaded into 3 targets in 1 min 45 s with 4 workers (~26k rows/s), 31 Parquet files (33 MB) in the S3 landing zone, validation 79/79 checks passed on a frozen source, cutover completed. Everything on screen comes from the live API; never fabricate numbers, customers or benchmarks.

## Product Principles

1. Truth on screen: every number comes from the running system; mocked infrastructure is labeled as mocked.
2. Tell the story in order: source -> stream -> targets -> proof -> cutover, readable without narration.
3. Correctness is the hero: proof of matching data outranks throughput.
4. Every state reads as a still image: empty, running, catching up, failed and ready states each explain themselves.

## Accessibility & Inclusion

Status must never rely on color alone (recordings get compressed and viewers may be color-blind): pair color with text or icons. Text must stay legible in a 1080p recording.
