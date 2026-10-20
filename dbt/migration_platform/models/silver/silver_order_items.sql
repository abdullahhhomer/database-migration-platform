{{ config(materialized='table') }}

SELECT
    id,
    order_id,
    product_id,
    quantity,
    CAST(unit_price AS DECIMAL(18, 2)) AS unit_price,
    CAST(quantity * unit_price AS DECIMAL(18, 2)) AS line_total,
    created_at
FROM {{ source('bronze', 'order_items') }}