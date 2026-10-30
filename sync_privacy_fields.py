
import pandas as pd
from pathlib import Path

data_dir = Path("data/generated")

addresses = pd.read_csv(data_dir / "address.csv", dtype=str)
guardians = pd.read_csv(data_dir / "guardian_contact.csv", dtype=str)

# Validate the expected columns and values before generating SQL.
if not {"address_id", "disclosure_authorized"}.issubset(addresses.columns):
    raise ValueError("address.csv is missing required columns.")

if not {"guardian_id", "is_valid"}.issubset(guardians.columns):
    raise ValueError("guardian_contact.csv is missing required columns.")

if addresses["address_id"].isna().any() or addresses["address_id"].duplicated().any():
    raise ValueError("Address IDs are missing or duplicated.")

if guardians["guardian_id"].isna().any() or guardians["guardian_id"].duplicated().any():
    raise ValueError("Guardian IDs are missing or duplicated.")

lines = [
    "USE yottaflex_transport;",
    "START TRANSACTION;",
    "SET @audit_correlation_id = UUID();",
]

for row in addresses.itertuples(index=False):
    address_id = row.address_id.replace("'", "''")
    value = str(row.disclosure_authorized).strip()

    if value not in {"0", "1"}:
        raise ValueError(f"Invalid disclosure value: {value}")

    lines.extend(
        [
            "INSERT INTO audit_event (audit_id, entity_type, entity_id, "
            "action, before_json, after_json, created_at, correlation_id) "
            "SELECT CONCAT('AUD-', SUBSTRING(REPLACE(UUID(), '-', ''), 1, 24)), "
            f"'address', address_id, 'UPDATED', "
            "JSON_OBJECT('disclosure_authorized', disclosure_authorized), "
            f"JSON_OBJECT('disclosure_authorized', {value}), NOW(), "
            f"@audit_correlation_id FROM address "
            f"WHERE address_id = '{address_id}' "
            f"AND NOT (disclosure_authorized <=> {value});",
            f"UPDATE address SET disclosure_authorized = {value} "
            f"WHERE address_id = '{address_id}';",
        ]
    )

for row in guardians.itertuples(index=False):
    guardian_id = row.guardian_id.replace("'", "''")
    value = str(row.is_valid).strip()

    if value not in {"0", "1"}:
        raise ValueError(f"Invalid guardian validity value: {value}")

    lines.extend(
        [
            "INSERT INTO audit_event (audit_id, entity_type, entity_id, "
            "action, before_json, after_json, created_at, correlation_id) "
            "SELECT CONCAT('AUD-', SUBSTRING(REPLACE(UUID(), '-', ''), 1, 24)), "
            f"'guardian_contact', guardian_id, 'UPDATED', "
            "JSON_OBJECT('is_valid', is_valid), "
            f"JSON_OBJECT('is_valid', {value}), NOW(), "
            f"@audit_correlation_id FROM guardian_contact "
            f"WHERE guardian_id = '{guardian_id}' "
            f"AND NOT (is_valid <=> {value});",
            f"UPDATE guardian_contact SET is_valid = {value} "
            f"WHERE guardian_id = '{guardian_id}';",
        ]
    )

lines.append("COMMIT;")

output = data_dir / "sync_privacy_fields.sql"
output.write_text("\n".join(lines) + "\n", encoding="utf-8")

print(f"Created: {output}")
print(f"Address updates: {len(addresses)}")
print(f"Guardian updates: {len(guardians)}")
