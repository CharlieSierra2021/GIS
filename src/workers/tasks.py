"""Celery task shells — task names are normative (ICD §8).

Each task is a thin shell over the JobRunner obtained from
``workers.runtime.get_runner()``; payload schemas live with the pipeline.
"""

import os

from celery import Celery

from workers.runtime import get_runner

celery_app = Celery(
    "property_intel",
    broker=os.environ.get("CELERY_BROKER_URL", "memory://"),
)
celery_app.conf.task_always_eager = (
    os.environ.get("CELERY_TASK_ALWAYS_EAGER", "0") == "1"
)


def _runner():
    runner = get_runner()
    if runner is None:
        raise RuntimeError("no JobRunner configured; call workers.runtime.set_runner")
    return runner


@celery_app.task(name="resolve_parcel")
def resolve_parcel(job_id: str, account_id: str):
    job = _runner().run(job_id, account_id)
    return job.model_dump(mode="json")


@celery_app.task(name="route_jurisdiction")
def route_jurisdiction(job_id: str, account_id: str):
    job = _runner().run(job_id, account_id)
    return job.model_dump(mode="json")


@celery_app.task(name="screen_profile")
def screen_profile(job_id: str, account_id: str):
    job = _runner().run(job_id, account_id)
    return job.model_dump(mode="json")


@celery_app.task(name="quality_gates")
def quality_gates(job_id: str, account_id: str):
    job = _runner().run(job_id, account_id)
    return job.model_dump(mode="json")


@celery_app.task(name="publish_report")
def publish_report(job_id: str, account_id: str):
    raise NotImplementedError("M9")
