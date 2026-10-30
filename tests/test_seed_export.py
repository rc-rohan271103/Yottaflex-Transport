from generator.check_reproducibility import load_field_clause


def test_nullable_load_column_does_not_route_enum_columns_through_user_variables():
    clause = load_field_clause(
        [
            "assignment_id",
            "student_id",
            "effective_to",
            "status",
        ],
        "effective_to",
    )

    assert clause == (
        "(`assignment_id`, `student_id`, @effective_to, `status`)\n"
        "SET `effective_to` = NULLIF(@effective_to, '')"
    )


def test_non_nullable_load_columns_are_loaded_directly():
    assert load_field_clause(["route_id", "status"], None) == (
        "(`route_id`, `status`)"
    )
