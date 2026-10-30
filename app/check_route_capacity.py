
from app.db import get_connection


def main():
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        query = """
            SELECT
                r.route_id,
                b.capacity,
                COUNT(a.assignment_id) AS passengers
            FROM route AS r
            JOIN bus AS b
                ON b.bus_id = r.bus_id
            LEFT JOIN assignment AS a
                ON a.route_id = r.route_id
                AND a.status = 'ASSIGNED'
            GROUP BY r.route_id, b.capacity
            ORDER BY r.route_id
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        print("Route capacity report")
        print("-" * 40)

        for row in rows:
            status = (
                "OVER CAPACITY"
                if row["passengers"] > row["capacity"]
                else "OK"
            )
            print(
                f'{row["route_id"]}: '
                f'{row["passengers"]}/{row["capacity"]} passengers '
                f'[{status}]'
            )

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
