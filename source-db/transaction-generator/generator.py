import os
import random
import time
from decimal import Decimal

import psycopg2


DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "database": os.getenv("POSTGRES_DB", "migration_source"),
    "user": os.getenv("POSTGRES_USER", "migration_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "migration_password"),
}

# Average transactions per second. Each wait is randomised around 1 / TPS
# so the traffic looks organic rather than metronomic.
TPS = max(float(os.getenv("GENERATOR_TPS", "1")), 0.01)


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def update_customer(cursor):
    cursor.execute(
        """
        UPDATE customers
        SET phone = '+92' || LPAD((3000000000 + floor(random() * 999999999))::BIGINT::TEXT, 10, '0'),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = (
            SELECT id FROM customers
            ORDER BY random()
            LIMIT 1
        )
        """
    )


def update_product(cursor):
    cursor.execute(
        """
        UPDATE products
        SET price = ROUND((10 + random() * 990)::NUMERIC, 2),
            stock_quantity = GREATEST(0, stock_quantity + (floor(random() * 41) - 20)::INTEGER),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = (
            SELECT id FROM products
            ORDER BY random()
            LIMIT 1
        )
        """
    )


def update_order(cursor):
    cursor.execute(
        """
        UPDATE orders
        SET status = (
            ARRAY['pending', 'confirmed', 'shipped', 'delivered', 'cancelled']
        )[floor(random() * 5 + 1)::INTEGER],
            updated_at = CURRENT_TIMESTAMP
        WHERE id = (
            SELECT id FROM orders
            ORDER BY random()
            LIMIT 1
        )
        """
    )


def update_payment(cursor):
    cursor.execute(
        """
        UPDATE payments
        SET status = (
            ARRAY['pending', 'completed', 'failed', 'refunded']
        )[floor(random() * 4 + 1)::INTEGER],
            updated_at = CURRENT_TIMESTAMP
        WHERE id = (
            SELECT id FROM payments
            ORDER BY random()
            LIMIT 1
        )
        """
    )


def insert_order(cursor):
    cursor.execute(
        """
        INSERT INTO orders (
            customer_id,
            status,
            total_amount,
            order_date,
            updated_at
        )
        SELECT
            id,
            'pending',
            ROUND((20 + random() * 1980)::NUMERIC, 2),
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM customers
        ORDER BY random()
        LIMIT 1
        RETURNING id
        """
    )

    return cursor.fetchone()[0]


def insert_order_item(cursor, order_id):
    cursor.execute(
        """
        INSERT INTO order_items (
            order_id,
            product_id,
            quantity,
            unit_price
        )
        SELECT
            %s,
            id,
            (1 + floor(random() * 5))::INTEGER,
            price
        FROM products
        ORDER BY random()
        LIMIT 1
        """,
        (order_id,),
    )


def delete_return(cursor):
    cursor.execute(
        """
        DELETE FROM returns
        WHERE id = (
            SELECT id
            FROM returns
            ORDER BY random()
            LIMIT 1
        )
        """
    )


def is_frozen(cursor) -> bool:
    """
    The cutover runbook sets migration_control.writes_frozen to stop the
    "application" from writing, so CDC can drain and validation can run
    against a quiet source.
    """
    cursor.execute(
        "SELECT to_regclass('public.migration_control') IS NOT NULL"
    )

    if not cursor.fetchone()[0]:
        return False

    cursor.execute(
        "SELECT writes_frozen FROM migration_control WHERE id = 1"
    )
    row = cursor.fetchone()

    return bool(row and row[0])


def run_transaction() -> bool:
    """Runs one random transaction. Returns False if writes are frozen."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                if is_frozen(cursor):
                    return False

                operations = [
                    update_customer,
                    update_product,
                    update_order,
                    update_payment,
                    insert_order,
                    delete_return,
                ]

                operation = random.choice(operations)

                if operation == insert_order:
                    order_id = operation(cursor)
                    insert_order_item(cursor, order_id)
                    print(
                        f"[INSERT] Created order {order_id} "
                        f"and an order item"
                    )
                else:
                    operation(cursor)
                    print(f"[{operation.__name__.replace('_', ' ').upper()}]")

        return True

    finally:
        connection.close()


def main():
    print(f"Starting PostgreSQL transaction generator (~{TPS:g} tx/s)...")
    print("Press Ctrl+C to stop.")

    frozen = False

    while True:
        try:
            ran = run_transaction()

            if not ran:
                if not frozen:
                    print("[FROZEN] Writes are frozen for cutover; pausing.", flush=True)
                    frozen = True
                time.sleep(1)
                continue

            if frozen:
                print("[RESUMED] Writes unfrozen; generating traffic again.", flush=True)
                frozen = False

            time.sleep(random.uniform(0.5, 1.5) / TPS)

        except psycopg2.Error as error:
            print(f"[DATABASE ERROR] {error}")
            time.sleep(5)

        except KeyboardInterrupt:
            print("\nTransaction generator stopped.")
            break


if __name__ == "__main__":
    main()