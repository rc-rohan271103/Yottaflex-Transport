
from app.db import get_connection

connection = get_connection()
cursor = connection.cursor()

try:
    cursor.execute("""
        SELECT
            r.route_id,
            r.bus_id,
            b.capacity,
            COUNT(a.assignment_id) AS assigned_passengers,
            MIN(rs.arrival_time) AS first_pickup,
            MAX(rs.arrival_time) AS last_pickup
        FROM route AS r
        JOIN bus AS b ON b.bus_id = r.bus_id
        JOIN route_stop AS rs ON rs.route_id = r.route_id
        LEFT JOIN assignment AS a
          ON a.route_id = r.route_id
         AND a.status = 'ASSIGNED'
         AND a.effective_from <= r.service_date
         AND (a.effective_to IS NULL OR a.effective_to >= r.service_date)
        WHERE r.service_date = '2026-10-29'
          AND r.status IN ('PLANNED', 'ACTIVE')
        GROUP BY r.route_id, r.bus_id, b.capacity
        ORDER BY assigned_passengers ASC
    """)

    print("Routes and their capacity:")
    for row in cursor.fetchall():
        route_id, bus_id, capacity, passengers, first, last = row
        print(
            f"Route {route_id} | Bus {bus_id} | "
            f"Capacity {capacity} | Assigned {passengers} | "
            f"Pickup times {first}–{last}"
        )

finally:
    cursor.close()
    connection.close()
