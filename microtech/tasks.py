from __future__ import annotations

from celery import shared_task


@shared_task(name="microtech.process_graphql_job_result")
def process_graphql_job_result(job_id: int) -> None:
    from microtech.services import MicrotechJobSentinelService
    import products.tasks  # noqa: F401 - registers product sync continuations

    MicrotechJobSentinelService().process_continuation(job_id=job_id)


@shared_task(name="microtech.poll_graphql_jobs")
def poll_graphql_jobs(limit: int = 50) -> int:
    from microtech.services import MicrotechJobSentinelService

    return MicrotechJobSentinelService().poll_due_jobs(limit=limit)


@shared_task(name="microtech.poll_graphql_job")
def poll_graphql_job(job_id: int) -> bool:
    from microtech.services import MicrotechJobSentinelService

    return MicrotechJobSentinelService().poll_job_once(job_id=job_id)
