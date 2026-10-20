{{ config(materialized='table') }}

SELECT
    id,
    TRIM(sku) AS sku,
    TRIM(name) AS name,
    TRIM(category) AS category,
    CAST(price AS DECIMAL(18, 2)) AS price,
    stock_quantity,
    created_at,
    updated_at
FROM {{ source('bronze', 'products') }}