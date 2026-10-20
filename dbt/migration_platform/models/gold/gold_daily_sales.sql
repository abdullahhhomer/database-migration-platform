{{ config(
    materialized='table',
    schema='gold'
) }}

SELECT
    CAST(order_date AS DATE) AS order_date,
    COUNT(*) AS total_orders,
    COUNT(DISTINCT customer_id) AS unique_customers,
    SUM(total_amount) AS total_sales,
    AVG(total_amount) AS average_order_value
FROM `migration_platform`.`silver`.`silver_orders`
GROUP BY
    CAST(order_date AS DATE)
ORDER BY
    order_date