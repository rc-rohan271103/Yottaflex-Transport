from app.auth import Principal
from app import main


class SummaryCursor:
    def __init__(self):
        self.queries = []

    def execute(self, query):
        self.queries.append(query)

    def fetchone(self):
        return {"total": 0}

    def close(self):
        pass


class SummaryConnection:
    def __init__(self):
        self.cursor_instance = SummaryCursor()
        self.closed = False

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_anomaly_summary_uses_effective_bus_capacity_history(monkeypatch):
    connection = SummaryConnection()
    monkeypatch.setattr(main, "get_connection", lambda: connection)

    result = main.anomaly_summary(
        Principal("admin", "platform_administrator")
    )

    capacity_query = connection.cursor_instance.queries[0]
    assert "bus_capacity_history" in capacity_query
    assert "h.effective_from <= r.service_date" in capacity_query
    assert "h.effective_to >= r.service_date" in capacity_query
    assert "HAVING COUNT(a.assignment_id) > h.capacity" in capacity_query
    assert "travel_minutes < 10" in connection.cursor_instance.queries[2]
    assert "illustrative 10-minute threshold" in result["threshold_note"]
    assert result["findings"]["GT-001"] == 0
    assert connection.closed
