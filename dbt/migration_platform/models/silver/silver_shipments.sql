{{ config(materialized='table') }}

SELECT
    id,
    order_id,
    TRIM(status) AS status,
    NULLIF(TRIM(carrier), '') AS carrier,
    NULLIF(TRIM(tracking_number), '') AS tracking_number,
    shipped_at,
    delivered_at,
    updated_at
FROM {{ source('bronze', 'shipments') }}