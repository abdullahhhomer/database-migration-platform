{{ config(materialized='table') }}

SELECT
    id,
    order_id,
    CAST(amount AS DECIMAL(18, 2)) AS amount,
    TRIM(status) AS status,
    TRIM(payment_method) AS payment_method,
    TRIM(transaction_ref) AS transaction_ref,
    paid_at,
    updated_at
FROM {{ source('bronze', 'payments') }}