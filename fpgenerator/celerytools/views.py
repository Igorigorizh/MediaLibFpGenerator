import logging
import random
from string import ascii_lowercase

import requests
from celery.result import AsyncResult
from celery import current_app as current_celery_app
from fastapi import FastAPI, Request, Body, Depends, status, Form
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import fp_router
from .schemas import FolderRequestsBody
from .tasks import find_new_music_folder_task, callback_acoustID_request, callback_MB_get_releases_by_discid_request, callback_FP_gen, task_test_logger
from .models import Fp
#from fpgenerator.database import get_db_session


logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="fpgenerator/celerytools/templates")


@fp_router.get("/form/")
def form_example_get(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})

@fp_router.post("/form/")
def form_fp_process_start(folder_req_body: FolderRequestsBody):
    arg = ''
    if folder_req_body.post_proc_flag:
        arg = 'ACOUSTID_MB_REQ'
    if folder_req_body.fp_flag:
        task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',([folder_req_body.path],[],[],'initial'),link=callback_FP_gen.s(arg))
    else:
        task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',([folder_req_body.path],[],[],'initial'))
    print('res:',task)

    return JSONResponse({"task_id": task.task_id})    

@fp_router.get("/fp_test/")
def fp_test():
    task_test_logger.delay()
    return {"message": "send task to Celery successfully"}
    
@fp_router.get("/form/task_status/")
def task_status(task_id: str):
    task = AsyncResult(task_id, app=current_celery_app)
    state = task.state

    if state == 'FAILURE':
        error = str(task.result)
        response = {
            'state': state,
            'error': error,
        }
    else:
        response = {
            'state': state,
        }
    return JSONResponse(response)

