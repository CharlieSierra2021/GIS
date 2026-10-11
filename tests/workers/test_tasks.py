import pytest

from connectors.registry import TASK_TYPES
from resolution.intake import IntakeKind, IntakeRequest
from tests.workers.test_pipeline import _runner
from workers import runtime, tasks
from workers.jobs import JobState

REGISTERED = {
    "resolve_parcel",
    "route_jurisdiction",
    "screen_profile",
    "quality_gates",
    "publish_report",
}


def test_task_names_are_normative() -> None:
    assert REGISTERED <= TASK_TYPES
    for name in REGISTERED:
        assert name in celery_task_names()


def celery_task_names() -> set[str]:
    return set(tasks.celery_app.tasks)


def test_resolve_parcel_task_runs_eager() -> None:
    runner = _runner_publishable()
    runtime.set_runner(runner)
    try:
        job = runner.submit(
            "acct-1", IntakeRequest(kind=IntakeKind.ADDRESS, address="500 Ocean Blvd")
        )
        assert job.state == JobState.AWAITING_CUSTOMER_INPUT
        result = tasks.resolve_parcel.apply(args=[job.id, "acct-1"]).get()
        assert result["id"] == job.id
        assert result["state"] == JobState.AWAITING_CUSTOMER_INPUT
    finally:
        runtime.set_runner(None)


def _runner_publishable():
    from tests.support.stubs import publishable_registry

    return _runner(publishable_registry())


def test_publish_report_stub() -> None:
    runtime.set_runner(_runner_publishable())
    try:
        with pytest.raises(NotImplementedError):
            tasks.publish_report.apply(args=["x", "y"]).get()
    finally:
        runtime.set_runner(None)
