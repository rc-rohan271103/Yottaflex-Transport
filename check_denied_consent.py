
from app.db import get_connection

connection = get_connection()
cursor = connection.cursor()

cursor.execute(
    """
    SELECT guardian_id, student_id
    FROM guardian_contact
    WHERE consent_status = %s
      AND is_valid = TRUE
    LIMIT 5
    """,
    ("DENIED",),
)

print(cursor.fetchall())

cursor.close()
connection.close()
