"""metrics.py: qbt-rules' metrics on interpose's Registry.

/metrics through the app (auth, content type, the route's 404 when off) is tests/unit/test_web.py's;
the exact exposition is pinned by tests/golden (metrics_200, metrics_200_events).
"""

import threading

import pytest
from interpose.metrics import Registry

from qbt_rules import metrics
from qbt_rules.schema import ACTION_TYPES

STATE = {
    "queue_backend": "SQLiteQueue",
    "queue_depth": 3,
    "job_counts": {"pending": 3, "completed": 7, "failed": 1},
    "worker_running": True,
    "worker_last_job_completed": "2026-11-03T12:00:00+00:00",
    "schedule_entry_count": 2,
}


@pytest.fixture
def recorder() -> metrics.Metrics:
    found = metrics.Metrics(metrics.build_registry("1.2.3"))
    found.declare_backend("SQLiteQueue")
    found.declare_endpoints(["list_jobs"])
    return found


def scrape(recorder: metrics.Metrics, **changes: object) -> str:
    return recorder.scrape(**{**STATE, **changes})  # type: ignore[arg-type]


def lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith("#")]


def test_build_info() -> None:
    assert metrics.build_registry("1.2.3").render() == (
        "# HELP qbt_rules_build_info The running version: always 1\n"
        "# TYPE qbt_rules_build_info gauge\n"
        'qbt_rules_build_info{version="1.2.3"} 1\n'
    )


def test_the_metric_names_and_types_of_0_10(recorder: metrics.Metrics) -> None:
    """The names and label sets prometheus_client exported in 0.10.x, kept for dashboards."""
    found = {m.name: (m.kind, m.label_names) for m in recorder.registry}
    assert found == {
        "qbt_rules_build_info": ("gauge", ("version",)),
        "qbt_rules_queue_depth": ("gauge", ("backend",)),
        "qbt_rules_jobs_total": ("gauge", ("status",)),
        "qbt_rules_worker_running": ("gauge", ()),
        "qbt_rules_worker_last_job_completed_timestamp_seconds": ("gauge", ()),
        "qbt_rules_scheduler_entries": ("gauge", ()),
        "qbt_rules_actions_executed_total": ("counter", ("action_type", "result")),
        "qbt_rules_job_duration_seconds": ("histogram", ()),
        "qbt_rules_scheduler_fires_total": ("counter", ("result",)),
        "qbt_rules_http_requests_total": ("counter", ("endpoint", "method", "status")),
        "qbt_rules_http_request_duration_seconds": ("histogram", ("endpoint", "method")),
    }


class TestStateGauges:
    def test_values(self, recorder: metrics.Metrics) -> None:
        samples = lines(scrape(recorder))
        assert 'qbt_rules_queue_depth{backend="SQLiteQueue"} 3' in samples
        assert 'qbt_rules_jobs_total{status="completed"} 7' in samples
        assert 'qbt_rules_jobs_total{status="processing"} 0' in samples  # missing: 0
        assert "qbt_rules_worker_running 1" in samples
        assert "qbt_rules_worker_last_job_completed_timestamp_seconds 1793707200" in samples
        assert "qbt_rules_scheduler_entries 2" in samples

    def test_every_job_status(self, recorder: metrics.Metrics) -> None:
        statuses = [s for s in lines(scrape(recorder)) if s.startswith("qbt_rules_jobs_total")]
        assert len(statuses) == len(metrics.JOB_STATUSES)

    def test_worker_stopped(self, recorder: metrics.Metrics) -> None:
        assert "qbt_rules_worker_running 0" in lines(scrape(recorder, worker_running=False))

    @pytest.mark.parametrize("last", [None, "", "not a timestamp"])
    def test_no_last_job_no_sample(self, recorder: metrics.Metrics, last: str | None) -> None:
        scrape(recorder)  # a value from an earlier scrape doesn't linger
        text = scrape(recorder, worker_last_job_completed=last)
        # interpose writes a metric's HELP and TYPE even with no sample
        assert not any(s.startswith("qbt_rules_worker_last_job") for s in lines(text))

    def test_an_undeclared_backend_is_left_out(self, recorder: metrics.Metrics) -> None:
        assert "qbt_rules_queue_depth{" not in scrape(recorder, queue_backend="Other")


class TestEvents:
    def test_off_until_activated(self, recorder: metrics.Metrics) -> None:
        metrics.record_action_executed("stop", True)
        metrics.record_job_duration(1.0)
        metrics.record_scheduler_fire(True)
        assert "qbt_rules_actions_executed_total{" not in recorder.registry.render()

    def test_recorded_once_active(self, recorder: metrics.Metrics) -> None:
        metrics.activate(recorder)
        metrics.record_action_executed("stop", True)
        metrics.record_action_executed("stop", False)
        metrics.record_action_executed("stop", False)
        metrics.record_job_duration(0.3)
        metrics.record_scheduler_fire(True)
        metrics.record_scheduler_fire(False)
        samples = lines(recorder.registry.render())
        assert 'qbt_rules_actions_executed_total{action_type="stop",result="success"} 1' in samples
        assert 'qbt_rules_actions_executed_total{action_type="stop",result="failure"} 2' in samples
        assert 'qbt_rules_job_duration_seconds_bucket{le="0.25"} 0' in samples
        assert 'qbt_rules_job_duration_seconds_bucket{le="0.5"} 1' in samples
        assert 'qbt_rules_job_duration_seconds_bucket{le="+Inf"} 1' in samples
        assert "qbt_rules_job_duration_seconds_count 1" in samples
        assert 'qbt_rules_scheduler_fires_total{result="success"} 1' in samples
        assert 'qbt_rules_scheduler_fires_total{result="failure"} 1' in samples

    def test_an_unknown_action_type_is_not_counted(self, recorder: metrics.Metrics) -> None:
        recorder.action_executed("no_such_action", True)  # never raises into the engine
        assert "qbt_rules_actions_executed_total{" not in recorder.registry.render()

    def test_http_request(self, recorder: metrics.Metrics) -> None:
        recorder.http_request("GET", "list_jobs", 200, 0.02)
        recorder.http_request("GET", "not_a_route", 404, 0.01)  # counted as unknown
        recorder.http_request("BREW", "list_jobs", 418, 0.01)  # an unusual method: not counted
        samples = lines(recorder.registry.render())
        assert (
            'qbt_rules_http_requests_total{endpoint="list_jobs",method="GET",status="200"} 1'
            in samples
        )
        assert (
            'qbt_rules_http_requests_total{endpoint="unknown",method="GET",status="404"} 1'
            in samples
        )
        assert not any('method="BREW"' in s for s in samples)
        assert (
            'qbt_rules_http_request_duration_seconds_count{endpoint="list_jobs",method="GET"} 1'
            in samples
        )


def test_threads_change_metrics_while_scrapes_render(recorder: metrics.Metrics) -> None:
    """The worker, scheduler and event loop record while a scrape renders (metrics.LOCK):
    no 'dictionary changed size during iteration', and nothing lost."""
    metrics.activate(recorder)
    actions = list(ACTION_TYPES)
    statuses = [str(code) for code in range(200, 600)]
    errors: list[BaseException] = []
    rounds = 400

    def worker() -> None:
        for i in range(rounds):
            metrics.record_action_executed(actions[i % len(actions)], i % 2 == 0)
            metrics.record_job_duration(i / 100)

    def loop() -> None:
        for i in range(rounds):
            recorder.http_request("GET", "list_jobs", int(statuses[i % len(statuses)]), 0.001)

    def scraper() -> None:
        try:
            for _ in range(50):
                scrape(recorder)
        except BaseException as e:  # pragma: no cover - the failure being tested for
            errors.append(e)

    threads = [threading.Thread(target=t) for t in (worker, loop, scraper, scraper)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    samples = lines(recorder.registry.render())
    assert f"qbt_rules_job_duration_seconds_count {rounds}" in samples
    total = sum(
        float(s.rsplit(" ", 1)[1])
        for s in samples
        if s.startswith("qbt_rules_http_requests_total{")
    )
    assert total == rounds


def test_registry_is_per_app() -> None:
    """Two apps (two tests) never share counts: no process-global registry."""
    a, b = metrics.Metrics(Registry()), metrics.Metrics(Registry())
    a.scheduler_fired(True)
    assert "qbt_rules_scheduler_fires_total{" not in b.registry.render()
