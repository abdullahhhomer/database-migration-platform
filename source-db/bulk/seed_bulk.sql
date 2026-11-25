-- ============================================================
-- Bulk seed: adds ~700k rows on top of the base seed (02_seed.sql)
-- so the source holds ~1M rows in total.
--
-- Run it BEFORE starting a migration, otherwise every seeded row
-- also flows through CDC:
--   docker compose --profile seed run --rm seeder
--
-- Scale it with -v scale=N (default 1, i.e. ~700k extra rows).
-- Safe to run more than once: new rows always get new ids,
-- emails, SKUs and references.
-- ============================================================

\if :{?scale}
\else
    \set scale 1
\endif

\timing on
\echo 'Bulk seeding with scale =' :scale

-- Wall-clock start, for the total elapsed time printed at the end.
SELECT clock_timestamp() AS seed_started \gset

BEGIN;

-- Remember where existing data ends, so new child rows only
-- reference the new parents.
CREATE TEMP TABLE seed_base ON COMMIT DROP AS
SELECT
    (SELECT COALESCE(MAX(id), 0) FROM customers)   AS customer_base,
    (SELECT COALESCE(MAX(id), 0) FROM products)    AS product_base,
    (SELECT COALESCE(MAX(id), 0) FROM orders)      AS order_base,
    (SELECT COALESCE(MAX(id), 0) FROM order_items) AS order_item_base,
    40000  * :scale AS new_customers,
    3000   * :scale AS new_products,
    200000 * :scale AS new_orders,
    250000 * :scale AS new_order_items;


-- Customers (~40k)
INSERT INTO customers (first_name, last_name, email, phone, created_at, updated_at)
SELECT
    'Customer' || n,
    'User' || n,
    'customer.b' || n || '@example.com',
    '+92' || LPAD((3100000000 + n)::TEXT, 10, '0'),
    ts,
    ts
FROM (
    -- random() in a derived table is evaluated once per row
    SELECT
        b.customer_base + g AS n,
        CURRENT_TIMESTAMP - (random() * INTERVAL '730 days') AS ts
    FROM seed_base b
    CROSS JOIN generate_series(1, b.new_customers) AS g
) s;


-- Products (~3k)
INSERT INTO products (sku, name, category, price, stock_quantity)
SELECT
    'SKU-B' || LPAD((b.product_base + g)::TEXT, 7, '0'),
    'Product ' || (b.product_base + g),
    (ARRAY['Electronics', 'Clothing', 'Home', 'Sports', 'Books'])[1 + (g % 5)],
    ROUND((10 + random() * 990)::NUMERIC, 2),
    (random() * 500)::INTEGER
FROM seed_base b
CROSS JOIN generate_series(1, b.new_products) AS g;


-- Orders (~200k), spread over all customers
INSERT INTO orders (customer_id, status, total_amount, order_date, updated_at)
SELECT customer_id, status, total_amount, od, od
FROM (
    SELECT
        1 + floor(random() * (b.customer_base + b.new_customers))::BIGINT AS customer_id,
        (ARRAY['pending', 'confirmed', 'shipped', 'delivered', 'cancelled'])[1 + (g % 5)] AS status,
        ROUND((20 + random() * 1980)::NUMERIC, 2) AS total_amount,
        CURRENT_TIMESTAMP - (random() * INTERVAL '365 days') AS od
    FROM seed_base b
    CROSS JOIN generate_series(1, b.new_orders) AS g
) s;


-- Order items (~250k), attached to the new orders
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT
    b.order_base + 1 + floor(random() * b.new_orders)::BIGINT,
    1 + floor(random() * (b.product_base + b.new_products))::BIGINT,
    (1 + floor(random() * 5))::INTEGER,
    ROUND((10 + random() * 990)::NUMERIC, 2)
FROM seed_base b
CROSS JOIN generate_series(1, b.new_order_items) AS g;


-- Payments (one per new order, ~200k)
INSERT INTO payments (order_id, amount, status, payment_method, transaction_ref, paid_at)
SELECT
    o.id,
    o.total_amount,
    CASE
        WHEN o.status = 'cancelled' THEN 'refunded'
        WHEN o.status = 'pending' THEN 'pending'
        ELSE 'completed'
    END,
    (ARRAY['card', 'bank_transfer', 'wallet', 'cash'])[1 + (o.id % 4)::INTEGER],
    'TXN-' || LPAD(o.id::TEXT, 10, '0'),
    CASE
        WHEN o.status IN ('confirmed', 'shipped', 'delivered')
        THEN o.order_date + INTERVAL '1 hour'
    END
FROM orders o, seed_base b
WHERE o.id > b.order_base;


-- Shipments (one per new order, ~200k)
INSERT INTO shipments (order_id, status, carrier, tracking_number, shipped_at, delivered_at)
SELECT
    o.id,
    CASE o.status
        WHEN 'shipped' THEN 'in_transit'
        WHEN 'delivered' THEN 'delivered'
        ELSE 'pending'
    END,
    (ARRAY['TCS', 'Leopards', 'M&P'])[1 + (o.id % 3)::INTEGER],
    'TRK-' || LPAD(o.id::TEXT, 10, '0'),
    CASE WHEN o.status IN ('shipped', 'delivered') THEN o.order_date + INTERVAL '2 days' END,
    CASE WHEN o.status = 'delivered' THEN o.order_date + INTERVAL '5 days' END
FROM orders o, seed_base b
WHERE o.id > b.order_base;


-- Returns (every 20th new order item, ~12.5k)
INSERT INTO returns (order_item_id, reason, quantity, status)
SELECT
    oi.id,
    (ARRAY['Damaged item', 'Wrong item', 'Customer changed mind', 'Quality issue'])[1 + (oi.id % 4)::INTEGER],
    1,
    (ARRAY['requested', 'approved', 'completed'])[1 + (oi.id % 3)::INTEGER]
FROM order_items oi, seed_base b
WHERE oi.id > b.order_item_base
  AND oi.id % 20 = 0;

COMMIT;

ANALYZE;

-- Summary
SELECT 'customers'   AS table_name, COUNT(*) AS row_count FROM customers
UNION ALL SELECT 'products',    COUNT(*) FROM products
UNION ALL SELECT 'orders',      COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL SELECT 'payments',    COUNT(*) FROM payments
UNION ALL SELECT 'shipments',   COUNT(*) FROM shipments
UNION ALL SELECT 'returns',     COUNT(*) FROM returns
UNION ALL SELECT 'TOTAL', (
    (SELECT COUNT(*) FROM customers) + (SELECT COUNT(*) FROM products)
  + (SELECT COUNT(*) FROM orders) + (SELECT COUNT(*) FROM order_items)
  + (SELECT COUNT(*) FROM payments) + (SELECT COUNT(*) FROM shipments)
  + (SELECT COUNT(*) FROM returns)
);

-- Total wall-clock time for the whole seed (inserts + ANALYZE).
SELECT date_trunc(
    'millisecond',
    clock_timestamp() - :'seed_started'::timestamptz
) AS total_elapsed;
