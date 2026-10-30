
"""Check address disclosure permissions without returning address data."""

from app.db import get_connection
from app.anomaly_detector import check_address_disclosure
from app.auth import requester_is_authorized


def check_address_access(address_id, requester_role):
    """Return an access decision without exposing address details."""

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT approval_status, disclosure_authorized
            FROM address
            WHERE address_id = %s
            """,
            (address_id,),
        )
        address = cursor.fetchone()

        if address is None:
            return {
                "decision": "BLOCK",
                "reason": "Address not found",
            }

        address_is_eligible = (
            address["approval_status"] == "APPROVED"
            and bool(address["disclosure_authorized"])
        )

        decision = check_address_disclosure(
            address_is_eligible,
            requester_is_authorized(requester_role),
        )

        if decision == "BLOCK":
            reason = "Address or requester is not authorized"
        else:
            reason = "Authorization checks passed"

        return {"decision": decision, "reason": reason}

    finally:
        cursor.close()
        connection.close()
