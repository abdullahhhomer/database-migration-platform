# Source database: PostgreSQL 17 with the wal2json logical decoding plugin.
# wal2json turns WAL changes into JSON so the CDC worker can stream
# row-level inserts/updates/deletes without parsing a binary protocol.
FROM postgres:17

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-wal2json \
    && rm -rf /var/lib/apt/lists/*
