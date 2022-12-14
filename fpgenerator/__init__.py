# -*- coding: utf-8 -*-
#from broadcaster import Broadcast
BASE_ENCODING = 'UTF-8'

from fastapi import FastAPI

from fpgenerator.conf import settings

#broadcast = Broadcast(settings.WS_MESSAGE_QUEUE)


def create_app() -> FastAPI:
    app = FastAPI()
    from fpgenerator.logging import configure_logging
    configure_logging()

    # do this before loading routes
    from fpgenerator.celery_utils import create_celery
    app.celery_app = create_celery()

    from fpgenerator.celerytools import fp_router
    app.include_router(fp_router)

    """
    from project.tdd import tdd_router
    app.include_router(tdd_router)

    from project.ws import ws_router
    app.include_router(ws_router)

    from project.ws.views import register_socketio_app
    register_socketio_app(app)

    @app.on_event("startup")
    async def startup_event():
        await broadcast.connect()

    @app.on_event("shutdown")
    async def shutdown_event():
        await broadcast.disconnect()
    """
    @app.get("/")
    async def root():
        return {"message": "FpGenerator service is live"}

    return app
