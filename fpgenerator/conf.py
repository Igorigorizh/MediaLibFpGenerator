import os
import pathlib
from functools import lru_cache

from kombu import Queue


def route_task(name, args, kwargs, options, task=None, **kw):
    if ":" in name:
        queue, _ = name.split(":")
        return {"queue": queue}
    return {"queue": "default"}


class BaseConfig:
    FLOWER_API_URL: str = os.environ.get("FLOWER_API_URL", "http://dashboard:5555/api")
    BASE_DIR: pathlib.Path = pathlib.Path(__file__).parent.parent
    #UPLOADS_DEFAULT_DEST: str = str(BASE_DIR / "upload")

    DATABASE_URL: str = os.environ.get("DATABASE_URL", f"sqlite:///./{BASE_DIR}/data.sqlite3")
    DATABASE_CONNECT_DICT: dict = {}

    CELERY_BROKER_URL: str = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND: str = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0")

    WS_MESSAGE_QUEUE: str = os.environ.get("WS_MESSAGE_QUEUE", "redis://redis:6379/0")

    CELERY_BEAT_SCHEDULE: dict = {
        # "task-schedule-work": {
        #     "task": "task_schedule_work",
        #     "schedule": 5.0,  # five seconds
        # },
    }
    # There is an issue with Queue settings below. Celery ignores/missing tasks when uncommented
    
    #CELERY_TASK_DEFAULT_QUEUE: str = "default"

    # Force all queues to be explicitly listed in `CELERY_TASK_QUEUES` to help prevent typos
    #CELERY_TASK_CREATE_MISSING_QUEUES: bool = False

    #CELERY_TASK_QUEUES: list = (
        # need to define default queue here or exception would be raised
    #    Queue("default"),

    #    Queue("high_priority"),
    #    Queue("low_priority"),
    #)

    #CELERY_TASK_ROUTES = (route_task,)


class DevelopmentConfig(BaseConfig):
    pass


class ProductionConfig(BaseConfig):
    pass


class TestingConfig(BaseConfig):
    # https://fastapi.tiangolo.com/advanced/testing-database/
    FLOWER_API_URL: str = os.environ.get("FLOWER_API_URL", "http://192.168.1.63:5556/api")
    DATABASE_URL: str = "sqlite:///./test.db"
    DATABASE_CONNECT_DICT: dict = {"check_same_thread": False}

    CELERY_BROKER_URL: str = os.environ.get("CELERY_BROKER_URL", "redis://192.168.1.63:6379")
    CELERY_RESULT_BACKEND: str = os.environ.get("CELERY_RESULT_BACKEND", "redis://192.168.1.63:6379")

    WS_MESSAGE_QUEUE: str = os.environ.get("WS_MESSAGE_QUEUE", "redis://192.168.1.63:6379")
	

@lru_cache()
def get_settings():
    config_cls_dict = {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
        "testing": TestingConfig
    }

    config_name = os.environ.get("FASTAPI_CONFIG", "testing")
    config_cls = config_cls_dict[config_name]
    return config_cls()


settings = get_settings()
