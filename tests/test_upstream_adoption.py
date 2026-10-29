from freecad_addon.AICADCopilot.bridge.dispatch_health import DispatchHealth


class Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


def test_dispatch_health_reports_busy_and_recovers():
    clock = Clock()
    health = DispatchHealth(clock)
    health.start("request-1", "get_view")
    clock.value += 2.5

    busy = health.snapshot(queued=3)
    assert busy["state"] == "busy"
    assert busy["operation"] == "get_view"
    assert busy["running_for_seconds"] == 2.5
    assert busy["queued"] == 3

    health.finish("request-1")
    recovered = health.snapshot()
    assert recovered["state"] == "healthy"
    assert recovered["completed"] == 1

