{{ config(
    materialized='table'
) }}

SELECT
    id,
    TRIM(first_name) AS first_name,
    TRIM(last_name) AS last_name,
    LOWER(TRIM(email)) AS email,
    NULLIF(TRIM(phone), '') AS phone,
    created_at,
    updated_at
FROM {{ source('bronze', 'customers') }}