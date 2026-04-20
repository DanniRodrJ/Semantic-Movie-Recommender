import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'streaming_service.settings')

app = Celery('streaming_service')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

sync_hour = os.getenv('CELERY_SYNC_HOUR', '0')
sync_minute = os.getenv('CELERY_SYNC_MINUTE', '0')
sync_week = os.getenv('CELERY_SYNC_WEEK', '0')

app.conf.beat_schedule = {
    'fetch-new-movies-every-night': {
        'task': 'core.tasks.fetch_and_vectorize_movies',
        'schedule': crontab(day_of_week=sync_week, hour=sync_hour, minute=sync_minute),
    },
}