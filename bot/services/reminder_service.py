"""Тонкая обертка: при завершении опроса отменяем висящий reminder job."""

from telegram.ext import Application

from bot.services.scheduler_service import REMINDER_JOB_PREFIX


def cancel_reminder_for_pending(application: Application, pending_id: int) -> None:
    job_queue = application.job_queue
    if job_queue is None:
        return
    for job in job_queue.get_jobs_by_name(f"{REMINDER_JOB_PREFIX}{pending_id}"):
        job.schedule_removal()
