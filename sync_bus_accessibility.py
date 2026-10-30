
import pandas as pd
from pathlib import Path

data_dir = Path("data/generated")
df = pd.read_csv(data_dir / "bus.csv", dtype=str)

required = {"bus_id", "is_accessible"}
if not required.issubset(df.columns):
    raise ValueError(f"bus.csv must contain {required}")

if df["bus_id"].isna().any() or df["bus_id"].duplicated().any():
    raise ValueError("Bus IDs are missing or duplicated.")

lines = [
    "USE yottaflex_transport;",
    "START TRANSACTION;",
    "SET @audit_correlation_id = UUID();",
]

for row in df.itertuples(index=False):
    bus_id = row.bus_id.replace("'", "''")
    value = row.is_accessible.strip()

    if value not in {"0", "1"}:
        raise ValueError(f"Unexpected accessibility value: {value}")

    lines.extend(
        [
            "INSERT INTO audit_event (audit_id, entity_type, entity_id, "
            "action, before_json, after_json, created_at, correlation_id) "
            "SELECT CONCAT('AUD-', SUBSTRING(REPLACE(UUID(), '-', ''), 1, 24)), "
            f"'bus', bus_id, 'UPDATED', "
            "JSON_OBJECT('is_accessible', is_accessible), "
            f"JSON_OBJECT('is_accessible', {value}), NOW(), "
            f"@audit_correlation_id FROM bus WHERE bus_id = '{bus_id}' "
            f"AND NOT (is_accessible <=> {value});",
            f"UPDATE bus SET is_accessible = {value} "
            f"WHERE bus_id = '{bus_id}';",
        ]
    )

lines.append("COMMIT;")

output = data_dir / "sync_bus_accessibility.sql"
output.write_text("\n".join(lines) + "\n", encoding="utf-8")

print(f"Created {output} with {len(df)} updates.")
