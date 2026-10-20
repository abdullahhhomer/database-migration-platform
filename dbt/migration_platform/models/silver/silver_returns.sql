{{ config(materialized='table') }}

SELECT
    id,
    order_item_id,
    TRIM(reason) AS reason,
    quantity,
    TRIM(status) AS status,
    created_at
FROM {{ source('bronze', 'returns') }}