"""
Celeryアプリケーションの初期化
"""
from celery import Celery
from app.config import settings

# Celeryアプリケーションの作成
celery_app = Celery(
    "prompt_provision_tool",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.execution_tasks"]
)

# Celery設定
celery_app.conf.update(
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    accept_content=settings.CELERY_ACCEPT_CONTENT,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=True,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    worker_max_memory_per_child=settings.CELERY_WORKER_MAX_MEMORY_PER_CHILD,
    worker_max_tasks_per_child=settings.CELERY_WORKER_MAX_TASKS_PER_CHILD,
    task_max_retries=settings.CELERY_TASK_MAX_RETRIES,
    task_default_retry_delay=settings.CELERY_TASK_DEFAULT_RETRY_DELAY,
)

