
import pandas as pd
from uuid import uuid4

from app.db import get_connection, record_import_audit_events

DATA_DIR = "data/generated"

# Parent tables must be loaded before their dependent tables.
TABLES = [
    ("address_zone", "address_zone.csv"),
    ("address", "address.csv"),
    ("bus", "bus.csv"),
    ("driver", "driver.csv"),
    ("student", "student.csv"),
    ("guardian_contact", "guardian_contact.csv"),
    ("stop", "stop.csv"),
    ("bus_capacity_history", "bus_capacity_history.csv"),
]


def main():
    connection = get_connection()
    correlation_id = str(uuid4())

    try:
        cursor = connection.cursor()

        # Prevent accidental mixing with an earlier dataset.
        cursor.execute("SELECT DATABASE()")
        database_name = cursor.fetchone()[0]

        if database_name != "yottaflex_transport":
            raise RuntimeError(
                f"Connected to {database_name!r}, not 'yottaflex_transport'."
            )

        for table_name, filename in TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
            existing_count = cursor.fetchone()[0]

            if existing_count:
                raise RuntimeError(
                    f"Table {table_name} already has {existing_count} rows. "
                    "Import stopped to avoid mixing datasets."
                )

        for table_name, filename in TABLES:
            df = pd.read_csv(f"{DATA_DIR}/{filename}", dtype=str)
            df = df.where(pd.notna(df), None)

            columns = list(df.columns)
            column_sql = ", ".join(f"`{column}`" for column in columns)
            placeholders = ", ".join(["%s"] * len(columns))

            sql = (
                f"INSERT INTO `{table_name}` ({column_sql}) "
                f"VALUES ({placeholders})"
            )

            rows = [
                tuple(row)
                for row in df.itertuples(index=False, name=None)
            ]

            if rows:
                cursor.executemany(sql, rows)
                record_import_audit_events(
                    cursor,
                    table_name,
                    df.to_dict(orient="records"),
                    correlation_id,
                )

            print(f"Prepared {len(rows):,} rows for {table_name}")

        connection.commit()
        print("\nMaster-data import completed successfully.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
