{{ config(materialized='table') }}

SELECT
    o.id,
    o.customer_id,
    TRIM(o.status) AS status,
    CAST(o.total_amount AS DECIMAL(18, 2)) AS total_amount,
    o.order_date,
    o.updated_at
FROM {{ source('bronze', 'orders') }} AS o