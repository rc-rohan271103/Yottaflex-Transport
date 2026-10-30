
import pandas as pd
from pathlib import Path
from uuid import uuid4

from app.db import get_connection, record_import_audit_events

DATA_DIR = Path("data/generated")

TABLES = [
    ("route", "route.csv"),
    ("route_stop", "route_stop.csv"),
    ("assignment", "assignment.csv"),
]


def main():
    connection = get_connection()
    correlation_id = str(uuid4())

    try:
        cursor = connection.cursor()

        cursor.execute("SELECT DATABASE()")
        database_name = cursor.fetchone()[0]

        if database_name != "yottaflex_transport":
            raise RuntimeError(
                f"Wrong database: {database_name}. "
                "Expected yottaflex_transport."
            )

        # Refuse to duplicate existing operational records.
        for table_name, _ in TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
            count = cursor.fetchone()[0]

            if count:
                raise RuntimeError(
                    f"Table {table_name} already has {count} rows. "
                    "Nothing was imported."
                )

        # Read all files and check they are not empty.
        dataframes = {}

        for table_name, filename in TABLES:
            path = DATA_DIR / filename

            if not path.exists():
                raise FileNotFoundError(f"Missing file: {path}")

            df = pd.read_csv(path, dtype=str)

            if df.empty:
                raise ValueError(f"No records found in {path}")

            if df.columns.duplicated().any():
                raise ValueError(f"Duplicate columns in {path}")

            dataframes[table_name] = df

        # Insert in foreign-key order, within one transaction.
       
        for table_name, filename in TABLES:
            df = dataframes[table_name]
            columns = list(df.columns)

            column_sql = ", ".join(f"`{c}`" for c in columns)
            placeholders = ", ".join(["%s"] * len(columns))

            sql = (
                f"INSERT INTO `{table_name}` ({column_sql}) "
                f"VALUES ({placeholders})"
            )

            records = [
                tuple(None if pd.isna(value) else value for value in row)
                for row in df.itertuples(index=False, name=None)
            ]

            cursor.executemany(sql, records)
            record_import_audit_events(
                cursor,
                table_name,
                df.to_dict(orient="records"),
                correlation_id,
            )
            print(f"Prepared {len(records)} rows for {table_name}")

        connection.commit()
        print("Operational data imported successfully.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
