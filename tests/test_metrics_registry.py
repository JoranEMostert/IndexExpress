from telemetry import MetricsRegistry


def test_metrics_registry_tracks_requests_and_tools():
    metrics = MetricsRegistry()
    metrics.record_request("tools/call", "ok", 0.2)
    metrics.record_request("tools/call", "error", 0.1)
    metrics.record_tool("skim", "ok", 1.2)

    snapshot = metrics.snapshot()
    requests = snapshot["requests"]["tools/call"]
    tools = snapshot["tools"]["skim"]

    assert requests["count"] == 2
    assert requests["errors"] == 1
    assert requests["avg_s"] > 0
    assert tools["count"] == 1
    assert tools["errors"] == 0
