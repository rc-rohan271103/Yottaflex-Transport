
import pandas as pd
from pathlib import Path

data_dir = Path("data/generated")
csv_path = data_dir / "stop.csv"
sql_path = data_dir / "sync_stop_zones.sql"

df = pd.read_csv(csv_path, dtype=str)

required_columns = {"stop_id", "zone_id"}
if not required_columns.issubset(df.columns):
    raise ValueError(f"stop.csv must contain columns: {required_columns}")

if df["stop_id"].isna().any() or df["zone_id"].isna().any():
    raise ValueError("Found an empty stop_id or zone_id.")

if df["stop_id"].duplicated().any():
    raise ValueError("Duplicate stop IDs found in stop.csv.")

lines = [
    "USE yottaflex_transport;",
    "START TRANSACTION;",
    "SET @audit_correlation_id = UUID();",
]

for row in df.itertuples(index=False):
    stop_id = row.stop_id.replace("'", "''")
    zone_id = row.zone_id.replace("'", "''")

    lines.extend(
        [
            "INSERT INTO audit_event (audit_id, entity_type, entity_id, "
            "action, before_json, after_json, created_at, correlation_id) "
            "SELECT CONCAT('AUD-', SUBSTRING(REPLACE(UUID(), '-', ''), 1, 24)), "
            f"'stop', stop_id, 'UPDATED', "
            "JSON_OBJECT('zone_id', zone_id), "
            f"JSON_OBJECT('zone_id', '{zone_id}'), NOW(), "
            f"@audit_correlation_id FROM stop WHERE stop_id = '{stop_id}' "
            f"AND NOT (zone_id <=> '{zone_id}');",
            f"UPDATE stop SET zone_id = '{zone_id}' "
            f"WHERE stop_id = '{stop_id}';",
        ]
    )

lines.append("COMMIT;")

sql_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

print(f"Created: {sql_path}")
print(f"Stop updates: {len(df)}")
print("\nFirst 3 statements:")
print("\n".join(lines[:5]))
