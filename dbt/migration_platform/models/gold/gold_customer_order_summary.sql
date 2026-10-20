{{ config(
    materialized='table',
    schema='gold'
) }}

SELECT
    c.id AS customer_id,
    c.first_name,
    c.last_name,
    c.email,
    COUNT(o.id) AS total_orders,
    COALESCE(SUM(o.total_amount), 0) AS total_spent,
    COALESCE(AVG(o.total_amount), 0) AS average_order_value,
    MAX(o.order_date) AS last_order_date
FROM `migration_platform`.`silver`.`silver_customers` AS c
LEFT JOIN `migration_platform`.`silver`.`silver_orders` AS o
    ON c.id = o.customer_id
GROUP BY
    c.id,
    c.first_name,
    c.last_name,
    c.email