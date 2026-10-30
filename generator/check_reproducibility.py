import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EXPORT_DIR = Path("data/full_scale/submission_exports_v4")
SEED = 20261022
MASTER_FILES = (
    "address_zone.csv",
    "address.csv",
    "student.csv",
    "guardian_contact.csv",
    "stop.csv",
    "bus.csv",
    "driver.csv",
    "bus_capacity_history.csv",
)
OPERATION_FILES = (
    "route.csv",
    "route_stop.csv",
    "assignment.csv",
    "attendance_event.csv",
    "notification.csv",
    "bus_capacity_history.csv",
    "route_disruption.csv",
)
SOURCE_FILES = (
    "generator/generate_data.py",
    "generator/generate_full_scale_operations.py",
    "generator/generate_ground_truth.py",
    "generator/inject_full_scale_anomalies.py",
    "generator/validate_data.py",
    "generator/validate_full_scale_operations.py",
    "generator/validate_ground_truth.py",
    "generator/validate_full_scale_anomalies_output.py",
    "generator/check_reproducibility.py",
    "sql/schema.sql",
    "README.md",
    "docs/data_dictionary.md",
)
SEED_TABLES = (
    ("address_zone", "csv/master/address_zone.csv", None),
    ("address", "csv/master/address.csv", None),
    ("bus", "csv/master/bus.csv", None),
    ("driver", "csv/master/driver.csv", None),
    ("student", "csv/master/student.csv", None),
    ("guardian_contact", "csv/master/guardian_contact.csv", None),
    ("stop", "csv/master/stop.csv", None),
    (
        "bus_capacity_history",
        "csv/operations/bus_capacity_history.csv",
        "effective_to",
    ),
    ("route", "csv/operations/route.csv", None),
    ("route_disruption", "csv/operations/route_disruption.csv", None),
    ("route_stop", "csv/operations/route_stop.csv", None),
    (
        "assignment",
        "csv/operations/assignment.csv",
        "effective_to",
    ),
    (
        "attendance_event",
        "csv/operations/attendance_event.csv",
        None,
    ),
    ("notification", "csv/operations/notification.csv", None),
)
JSON_TABLES = (
    ("master", MASTER_FILES),
    ("operations", OPERATION_FILES),
)
BOOLEAN_COLUMNS = {
    "disclosure_authorized",
    "accessibility_required",
    "is_valid",
    "active_status",
    "is_accessible",
}
INTEGER_COLUMNS = {"capacity", "sequence_no", "travel_minutes"}
FLOAT_COLUMNS = {"x", "y"}


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_rows(path):
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return sum(1 for _ in csv.reader(file)) - 1
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict) and isinstance(data.get("cases"), list):
            return len(data["cases"])
        return None
    return None


def load_field_clause(columns, nullable_column):
    if nullable_column is None:
        return f"({', '.join(f'`{column}`' for column in columns)})"

    fields = ", ".join(
        f"@{column}" if column == nullable_column else f"`{column}`"
        for column in columns
    )
    nullable_assignment = (
        f"`{nullable_column}` = NULLIF(@{nullable_column}, '')"
    )
    return f"({fields})\nSET {nullable_assignment}"


def json_value(column, value):
    if value == "":
        return None
    if column in BOOLEAN_COLUMNS:
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
        raise ValueError(f"Invalid boolean value for {column}: {value!r}")
    if column in INTEGER_COLUMNS:
        return int(value)
    if column in FLOAT_COLUMNS:
        return float(value)
    return value


def export_csv_as_json(source_path, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as source, output_path.open("w", encoding="utf-8", newline="\n") as output:
        reader = csv.DictReader(source)
        output.write("[\n")
        for index, row in enumerate(reader):
            if index:
                output.write(",\n")
            converted = {
                column: json_value(column, value)
                for column, value in row.items()
            }
            output.write(
                json.dumps(
                    converted,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
            )
        output.write("\n]\n")
    return count_rows(output_path)


def digest_csv_as_json(source_path):
    digest = hashlib.sha256()
    digest.update(b"[\n")
    row_count = 0
    size_bytes = 2
    with source_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as source:
        for row_count, row in enumerate(csv.DictReader(source), start=1):
            if row_count > 1:
                digest.update(b",\n")
                size_bytes += 2
            converted = {
                column: json_value(column, value)
                for column, value in row.items()
            }
            encoded = json.dumps(
                converted,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            digest.update(encoded)
            size_bytes += len(encoded)
    digest.update(b"\n]\n")
    size_bytes += 3
    return {
        "row_count": row_count,
        "size_bytes": size_bytes,
        "sha256": digest.hexdigest(),
    }


def describe_artifact(path):
    return {
        "row_count": count_rows(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def run_command(command, label):
    result = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"{label} failed with exit code {result.returncode}.\n"
            f"Command: {' '.join(map(str, command))}\n"
            f"STDOUT:\n{result.stdout[-12000:]}\n"
            f"STDERR:\n{result.stderr[-12000:]}"
        )
    pass_lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("PASS:")
    ]
    return {
        "label": label,
        "command": sanitize_command(command),
        "exit_code": result.returncode,
        "pass_count": len(pass_lines),
        "result": "PASS",
    }


def run_module(module, *arguments):
    return [sys.executable, "-m", module, *map(str, arguments)]


def sanitize_command(command):
    sanitized_command = []
    for part in command:
        text = str(part)
        if Path(text) == Path(sys.executable):
            sanitized_command.append("<python>")
            continue
        path_parts = Path(text).parts
        temporary_index = next(
            (
                index
                for index, component in enumerate(path_parts)
                if component.startswith("yottaflex-repro-")
            ),
            None,
        )
        if temporary_index is not None:
            suffix = Path(*path_parts[temporary_index + 1 :]).as_posix()
            sanitized_command.append(f"<TEMP>/{suffix}")
        else:
            sanitized_command.append(text)
    return sanitized_command


def generate_and_validate_run(root, run_name, args):
    run_root = root / run_name
    master_dir = run_root / "master"
    operations_dir = run_root / "operations"
    definitions_dir = run_root / "ground_truth_definitions"
    proposals_dir = run_root / "ground_truth_proposals"
    run_root.mkdir(parents=True)

    validations = []
    validations.append(
        run_command(
            run_module(
                "generator.generate_data",
                "--students",
                args.students,
                "--buses",
                args.buses,
                "--stops",
                args.stops,
                "--seed",
                args.seed,
                "--output",
                master_dir,
            ),
            f"{run_name}: generating master data",
        )
    )
    validations.append(
        run_command(
            run_module("generator.validate_data", "--input", master_dir),
            f"{run_name}: validating master data",
        )
    )
    validations.append(
        run_command(
            run_module(
                "generator.generate_full_scale_operations",
                "--students",
                args.students,
                "--days",
                args.days,
                "--seed",
                args.seed,
                "--input",
                master_dir,
                "--output",
                operations_dir,
            ),
            f"{run_name}: generating operations",
        )
    )
    validations.append(
        run_command(
            run_module(
                "generator.validate_full_scale_operations",
                "--operations",
                operations_dir,
                "--master",
                master_dir,
                "--days",
                args.days,
                "--students",
                args.students,
            ),
            f"{run_name}: validating operations",
        )
    )
    validations.append(
        run_command(
            run_module(
                "generator.generate_ground_truth",
                "--output",
                definitions_dir,
            ),
            f"{run_name}: generating ground-truth definitions",
        )
    )
    validations.append(
        run_command(
            run_module(
                "generator.inject_full_scale_anomalies",
                "--master",
                master_dir,
                "--operations",
                operations_dir,
                "--output",
                proposals_dir,
            ),
            f"{run_name}: deriving ground-truth proposals",
        )
    )
    validations.append(
        run_command(
            run_module(
                "generator.validate_ground_truth",
                "--definitions",
                definitions_dir,
                "--proposals",
                proposals_dir,
                "--master",
                master_dir,
                "--operations",
                operations_dir,
            ),
            f"{run_name}: validating ground-truth cases and label isolation",
        )
    )

    artifacts = {}
    for filename in MASTER_FILES:
        path = master_dir / filename
        artifacts[f"master/{filename}"] = describe_artifact(path)
        json_path = f"json/master/{filename.replace('.csv', '.json')}"
        artifacts[json_path] = digest_csv_as_json(path)
    for filename in OPERATION_FILES:
        path = operations_dir / filename
        artifacts[f"operations/{filename}"] = describe_artifact(path)
        json_path = f"json/operations/{filename.replace('.csv', '.json')}"
        artifacts[json_path] = digest_csv_as_json(path)
    for folder, prefix in (
        (definitions_dir, "ground_truth_definitions"),
        (proposals_dir, "ground_truth_proposals"),
    ):
        for filename in ("ground_truth.csv", "ground_truth.json"):
            path = folder / filename
            artifacts[f"{prefix}/{filename}"] = describe_artifact(path)

    return {
        "artifacts": artifacts,
        "validations": validations,
        "directories": {
            "master": master_dir,
            "operations": operations_dir,
            "ground_truth_definitions": definitions_dir,
            "ground_truth_proposals": proposals_dir,
        },
        "counts": {
            "students": args.students,
            "buses": args.buses,
            "stops": args.stops,
            "school_days": args.days,
            "seed": args.seed,
        },
    }


def compare_runs(first, second):
    comparisons = {}
    if set(first["artifacts"]) != set(second["artifacts"]):
        raise RuntimeError("The two regeneration runs produced different file sets.")
    for artifact in sorted(first["artifacts"]):
        first_record = first["artifacts"][artifact]
        second_record = second["artifacts"][artifact]
        comparisons[artifact] = {
            "row_count_run_1": first_record["row_count"],
            "row_count_run_2": second_record["row_count"],
            "row_counts_match": (
                first_record["row_count"] == second_record["row_count"]
            ),
            "sha256_run_1": first_record["sha256"],
            "sha256_run_2": second_record["sha256"],
            "checksums_match": first_record["sha256"] == second_record["sha256"],
        }
    return comparisons


def export_sql_seed(output_path, output_dir):
    seed_relative_path = output_path.resolve().relative_to(PROJECT_DIR).as_posix()
    lines = [
        "-- Yottaflex synthetic full-scale seed loader.",
        "-- Run from the repository root with LOCAL INFILE enabled:",
        f"-- mysql --local-infile=1 -u USER -p DATABASE < {seed_relative_path}",
        "-- Apply sql/schema.sql first. This loader does not delete or replace rows.",
        "-- Ground-truth labels are evaluation artifacts and are intentionally excluded.",
        "SET NAMES utf8mb4;",
        "START TRANSACTION;",
        "",
    ]
    for table, csv_path, nullable_column in SEED_TABLES:
        packaged_csv = output_dir / csv_path
        load_path = (
            output_dir.resolve().relative_to(PROJECT_DIR) / Path(csv_path)
        ).as_posix()
        with packaged_csv.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            columns = next(csv.reader(file))
        load_columns = load_field_clause(columns, nullable_column)
        lines.extend(
            [
                f"-- {table}: {load_path}",
                f"LOAD DATA LOCAL INFILE '{load_path}'",
                f"INTO TABLE `{table}`",
                "CHARACTER SET utf8mb4",
                "FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"'",
                "LINES TERMINATED BY '\\r\\n'",
                f"IGNORE 1 LINES {load_columns};",
                "",
            ]
        )
    lines.extend(["COMMIT;", ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "path": output_path.resolve().relative_to(PROJECT_DIR).as_posix(),
        "tables": [table for table, _, _ in SEED_TABLES],
        "input_csvs": [
            (
                output_dir.resolve().relative_to(PROJECT_DIR) / Path(csv_path)
            ).as_posix()
            for _, csv_path, _ in SEED_TABLES
        ],
        "schema": "sql/schema.sql",
        "omissions": [
            "ground-truth artifacts are not database input",
            "master bus_capacity_history.csv is superseded by the effective-dated operational history",
            "runtime-only assignment_decision and audit_event tables have no generated CSV seed",
        ],
    }


def validate_seed_sql(seed_metadata, output_dir):
    schema = (PROJECT_DIR / "sql/schema.sql").read_text(
        encoding="utf-8"
    )
    for (table, csv_path, _), reported_table in zip(
        SEED_TABLES, seed_metadata["tables"]
    ):
        if table != reported_table:
            raise ValueError(f"Unexpected seed table order for {table!r}.")
        match = re.search(
            rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?{re.escape(table)}`?"
            rf"\s*\((.*?)\n\);",
            schema,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match is None:
            raise ValueError(f"SQL schema has no table for seed target {table!r}.")
        table_definition = match.group(1)
        schema_columns = {}
        for line in table_definition.splitlines():
            column_match = re.match(
                r"\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\s+"
                r".*?(?:,)?\s*$",
                line,
            )
            if (
                column_match
                and column_match.group(1).upper()
                not in {
                    "PRIMARY",
                    "FOREIGN",
                    "UNIQUE",
                    "INDEX",
                    "KEY",
                    "CHECK",
                    "CONSTRAINT",
                }
            ):
                schema_columns[column_match.group(1)] = line.upper()
        source = output_dir / csv_path
        if not source.exists():
            raise FileNotFoundError(f"SQL seed source missing: {source}")
        with source.open("r", encoding="utf-8-sig", newline="") as file:
            columns = next(csv.reader(file))
        if len(columns) != len(set(columns)):
            raise ValueError(f"{csv_path} has duplicate column names.")
        unknown_columns = set(columns) - set(schema_columns)
        if unknown_columns:
            raise ValueError(
                f"{csv_path} has columns absent from {table}: "
                f"{sorted(unknown_columns)}"
            )
        required_without_default = {
            column
            for column, definition in schema_columns.items()
            if "NOT NULL" in definition and "DEFAULT" not in definition
        }
        missing_required = required_without_default - set(columns)
        if missing_required:
            raise ValueError(
                f"{csv_path} omits required {table} columns: "
                f"{sorted(missing_required)}"
            )


def write_exports(output_dir, args, runs, comparisons, validation_records):
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_directories = runs[0]["directories"]
    package_sources = (
        ("csv/master", MASTER_FILES, "master"),
        ("csv/operations", OPERATION_FILES, "operations"),
        (
            "ground_truth/definitions",
            ("ground_truth.csv", "ground_truth.json"),
            "ground_truth_definitions",
        ),
        (
            "ground_truth/proposals",
            ("ground_truth.csv", "ground_truth.json"),
            "ground_truth_proposals",
        ),
    )
    for package_folder, filenames, source_key in package_sources:
        destination = output_dir / package_folder
        destination.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            shutil.copyfile(
                generated_directories[source_key] / filename,
                destination / filename,
            )

    seed_metadata = {
        "tables": [table for table, _, _ in SEED_TABLES],
    }
    validate_seed_sql(seed_metadata, output_dir)
    seed_metadata = export_sql_seed(
        output_dir / "full_scale_seed.sql", output_dir
    )

    json_exports = {}
    for folder, filenames in JSON_TABLES:
        for filename in filenames:
            source_path = output_dir / "csv" / folder / filename
            relative_json = Path("json") / folder / filename.replace(
                ".csv", ".json"
            )
            output_path = output_dir / relative_json
            json_rows = export_csv_as_json(source_path, output_path)
            csv_rows = count_rows(source_path)
            if json_rows != csv_rows:
                raise ValueError(
                    f"JSON row count mismatch for {source_path}: "
                    f"CSV={csv_rows}, JSON={json_rows}"
                )
            json_exports[str(relative_json).replace("\\", "/")] = {
                **describe_artifact(output_path),
                "source_csv": str(
                    source_path.resolve().relative_to(PROJECT_DIR)
                ).replace("\\", "/"),
                "source_row_count": csv_rows,
            }

    package_files = [
        output_dir / "csv/master" / filename
        for filename in MASTER_FILES
    ]
    package_files.extend(
        output_dir / "csv/operations" / filename
        for filename in OPERATION_FILES
    )
    package_files.extend(
        [
            output_dir / "ground_truth/definitions/ground_truth.csv",
            output_dir / "ground_truth/definitions/ground_truth.json",
            output_dir / "ground_truth/proposals/ground_truth.csv",
            output_dir / "ground_truth/proposals/ground_truth.json",
        ]
    )
    package_files.extend(
        output_dir / Path(path)
        for path in json_exports
    )
    source_manifest = {
        "manifest_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_provenance": {
            "kind": "fully synthetic",
            "external_sources": [],
            "personal_data_used": False,
            "notes": (
                "No external or personal data is used. Values are generated "
                "by the documented project generators."
            ),
        },
        "generation": {
            "seed": args.seed,
            "students": args.students,
            "buses": args.buses,
            "stops": args.stops,
            "school_days": args.days,
            "master_generator": "generator/generate_data.py",
            "operations_generator": (
                "generator/generate_full_scale_operations.py"
            ),
            "ground_truth_generator": "generator/generate_ground_truth.py",
            "proposal_generator": (
                "generator/inject_full_scale_anomalies.py"
            ),
        },
        "source_code": {
            relative: {
                "sha256": sha256_file(PROJECT_DIR / relative),
                "size_bytes": (PROJECT_DIR / relative).stat().st_size,
            }
            for relative in SOURCE_FILES
        },
        "packaged_data": {
            path.resolve().relative_to(PROJECT_DIR).as_posix(): describe_artifact(path)
            for path in package_files
        },
        "json_exports": json_exports,
        "sql_seed": seed_metadata,
    }
    (output_dir / "source_manifest.json").write_text(
        json.dumps(source_manifest, indent=2),
        encoding="utf-8",
    )

    reproducibility = {
        "seed": args.seed,
        "parameters": {
            "students": args.students,
            "buses": args.buses,
            "stops": args.stops,
            "school_days": args.days,
        },
        "method": (
            "Regenerate master, operations, ground-truth definitions, and "
            "source-bound proposals twice in isolated temporary directories; "
            "compare every artifact's row count and SHA-256."
        ),
        "runs": {
            "run_1": runs[0]["artifacts"],
            "run_2": runs[1]["artifacts"],
        },
        "comparisons": comparisons,
        "all_row_counts_match": all(
            result["row_counts_match"] for result in comparisons.values()
        ),
        "all_checksums_match": all(
            result["checksums_match"] for result in comparisons.values()
        ),
    }
    (output_dir / "reproducibility_report.json").write_text(
        json.dumps(reproducibility, indent=2),
        encoding="utf-8",
    )

    validation_summary = {
        "seed": args.seed,
        "parameters": reproducibility["parameters"],
        "result": "PASS",
        "validation_runs": validation_records,
        "sql_seed_validation": {
            "result": "PASS",
            "tables_in_schema": seed_metadata["tables"],
            "csv_headers_checked": len(seed_metadata["input_csvs"]),
            "database_execution": (
                "Not run; no live MySQL execution was requested or required "
                "for local artifact validation."
            ),
        },
        "reproducibility": {
            "row_counts_match": reproducibility["all_row_counts_match"],
            "sha256_checksums_match": reproducibility["all_checksums_match"],
            "artifact_count": len(comparisons),
        },
    }
    (output_dir / "validation_summary.json").write_text(
        json.dumps(validation_summary, indent=2),
        encoding="utf-8",
    )
    summary_lines = [
        "# Validation Summary",
        "",
        f"- Result: **{validation_summary['result']}**",
        f"- Seed: `{args.seed}`",
        (
            f"- Scale: {args.students} students, {args.buses} buses, "
            f"{args.stops} stops, {args.days} school days"
        ),
        f"- Reproducibility: {len(comparisons)}/{len(comparisons)} artifacts "
        "matched row counts and SHA-256 checksums across two runs.",
        "- Ground-truth proposals: five labeled cases independently validated in each regenerated run.",
        f"- SQL seed: `{seed_metadata['path']}`; schema/header order validated.",
        "- SQL seed imports CSV records in foreign-key order and does not include ground truth.",
        "- CSV files and ground-truth artifacts are packaged from regenerated run 1; input datasets outside this package are not modified.",
        f"- JSON exports: {len(json_exports)} table files; each row count matches its source CSV.",
        "- Live MySQL execution was not performed.",
        "",
        "## Validation commands run",
        "",
    ]
    for record in validation_records:
        summary_lines.append(
            f"- PASS — `{record['label']}` "
            f"({record['pass_count']} explicit PASS checks)"
        )
    summary_lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `source_manifest.json`: provenance, generator/schema checksums, and packaged input checksums.",
            "- `reproducibility_report.json`: per-file row counts and checksums from both regenerated runs.",
            "- `validation_summary.json`: machine-readable validation result.",
            "- `full_scale_seed.sql`: MySQL `LOAD DATA LOCAL INFILE` seed loader.",
            "- `json/master/` and `json/operations/`: typed JSON array exports of all 15 CSV tables.",
            "- `csv/master/`, `csv/operations/`, and `ground_truth/`: generated CSV inputs and separate ground-truth definitions/proposals.",
        ]
    )
    (output_dir / "validation_summary.md").write_text(
        "\n".join(summary_lines) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the synthetic dataset twice, compare checksums and "
            "row counts, and create submission export artifacts."
        )
    )
    parser.add_argument("--students", type=int, default=5000)
    parser.add_argument("--buses", type=int, default=100)
    parser.add_argument("--stops", type=int, default=300)
    parser.add_argument("--days", type=int, default=200)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path, default=DEFAULT_EXPORT_DIR)
    args = parser.parse_args()

    if min(args.students, args.buses, args.stops, args.days) < 1:
        raise ValueError("Students, buses, stops, and days must be positive.")
    output_dir = args.output
    if output_dir.exists():
        if any(output_dir.iterdir()):
            raise FileExistsError(
                f"Refusing to overwrite existing export artifacts in {output_dir}."
            )
    else:
        output_dir.parent.mkdir(parents=True, exist_ok=True)

    validation_records = []
    with tempfile.TemporaryDirectory(prefix="yottaflex-repro-") as temporary:
        temporary_root = Path(temporary)
        first = generate_and_validate_run(temporary_root, "run_1", args)
        second = generate_and_validate_run(temporary_root, "run_2", args)
        comparisons = compare_runs(first, second)
        failed = [
            artifact
            for artifact, result in comparisons.items()
            if not result["row_counts_match"] or not result["checksums_match"]
        ]
        if failed:
            raise RuntimeError(
                "Regeneration was not reproducible for: "
                + ", ".join(failed)
            )
        validation_records.extend(first["validations"])
        validation_records.extend(second["validations"])
        write_exports(
            output_dir,
            args,
            [first, second],
            comparisons,
            validation_records,
        )
    print(f"PASS: {len(comparisons)} regenerated artifacts matched exactly.")
    print(f"Seed: {args.seed}; scale: {args.students} students, {args.buses} buses, "
          f"{args.stops} stops, {args.days} school days.")
    for name in (
        "full_scale_seed.sql",
        "source_manifest.json",
        "reproducibility_report.json",
        "validation_summary.json",
        "validation_summary.md",
    ):
        print(f"Exported: {output_dir / name}")


if __name__ == "__main__":
    main()
