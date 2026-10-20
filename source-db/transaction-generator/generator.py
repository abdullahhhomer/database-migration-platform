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


def run_transaction():
    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
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

    finally:
        connection.close()


def main():
    print("Starting PostgreSQL transaction generator...")
    print("Press Ctrl+C to stop.")

    while True:
        try:
            run_transaction()

            # Keep the workload realistic rather than hammering PostgreSQL.
            time.sleep(random.uniform(1.0, 3.0))

        except psycopg2.Error as error:
            print(f"[DATABASE ERROR] {error}")
            time.sleep(5)

        except KeyboardInterrupt:
            print("\nTransaction generator stopped.")
            break


if __name__ == "__main__":
    main()