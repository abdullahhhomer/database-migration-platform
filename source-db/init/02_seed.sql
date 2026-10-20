-- Customers
INSERT INTO customers (first_name, last_name, email, phone)
SELECT
    'Customer' || g,
    'User' || g,
    'customer' || g || '@example.com',
    '+92' || LPAD((3000000000 + g)::TEXT, 10, '0')
FROM generate_series(1, 10000) AS g;


-- Products
INSERT INTO products (sku, name, category, price, stock_quantity)
SELECT
    'SKU-' || LPAD(g::TEXT, 6, '0'),
    'Product ' || g,
    CASE (g % 5)
        WHEN 0 THEN 'Electronics'
        WHEN 1 THEN 'Clothing'
        WHEN 2 THEN 'Home'
        WHEN 3 THEN 'Sports'
        ELSE 'Books'
    END,
    ROUND((10 + random() * 990)::NUMERIC, 2),
    (random() * 500)::INTEGER
FROM generate_series(1, 2000) AS g;


-- Orders
INSERT INTO orders (customer_id, status, total_amount, order_date)
SELECT
    (1 + floor(random() * 10000))::BIGINT,
    CASE (g % 5)
        WHEN 0 THEN 'pending'
        WHEN 1 THEN 'confirmed'
        WHEN 2 THEN 'shipped'
        WHEN 3 THEN 'delivered'
        ELSE 'cancelled'
    END,
    ROUND((20 + random() * 1980)::NUMERIC, 2),
    CURRENT_TIMESTAMP - (random() * INTERVAL '365 days')
FROM generate_series(1, 50000) AS g;


-- Order Items
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT
    (1 + floor(random() * 50000))::BIGINT,
    (1 + floor(random() * 2000))::BIGINT,
    (1 + floor(random() * 5))::INTEGER,
    ROUND((10 + random() * 990)::NUMERIC, 2)
FROM generate_series(1, 150000) AS g;


-- Payments
INSERT INTO payments (
    order_id,
    amount,
    status,
    payment_method,
    transaction_ref,
    paid_at
)
SELECT
    o.id,
    o.total_amount,
    CASE
        WHEN o.status = 'cancelled' THEN 'refunded'
        WHEN o.status = 'pending' THEN 'pending'
        ELSE 'completed'
    END,
    CASE (o.id % 4)
        WHEN 0 THEN 'card'
        WHEN 1 THEN 'bank_transfer'
        WHEN 2 THEN 'wallet'
        ELSE 'cash'
    END,
    'TXN-' || LPAD(o.id::TEXT, 10, '0'),
    CASE
        WHEN o.status IN ('confirmed', 'shipped', 'delivered')
        THEN o.order_date + INTERVAL '1 hour'
        ELSE NULL
    END
FROM orders o;


-- Shipments
INSERT INTO shipments (
    order_id,
    status,
    carrier,
    tracking_number,
    shipped_at,
    delivered_at
)
SELECT
    o.id,
    CASE o.status
        WHEN 'shipped' THEN 'in_transit'
        WHEN 'delivered' THEN 'delivered'
        ELSE 'pending'
    END,
    CASE (o.id % 3)
        WHEN 0 THEN 'TCS'
        WHEN 1 THEN 'Leopards'
        ELSE 'M&P'
    END,
    'TRK-' || LPAD(o.id::TEXT, 10, '0'),
    CASE
        WHEN o.status IN ('shipped', 'delivered')
        THEN o.order_date + INTERVAL '2 days'
        ELSE NULL
    END,
    CASE
        WHEN o.status = 'delivered'
        THEN o.order_date + INTERVAL '5 days'
        ELSE NULL
    END
FROM orders o;


-- Returns
INSERT INTO returns (
    order_item_id,
    reason,
    quantity,
    status
)
SELECT
    oi.id,
    CASE (oi.id % 4)
        WHEN 0 THEN 'Damaged item'
        WHEN 1 THEN 'Wrong item'
        WHEN 2 THEN 'Customer changed mind'
        ELSE 'Quality issue'
    END,
    1,
    CASE (oi.id % 3)
        WHEN 0 THEN 'requested'
        WHEN 1 THEN 'approved'
        ELSE 'completed'
    END
FROM order_items oi
WHERE oi.id % 20 = 0;