import logging

from string import ascii_lowercase
import time
import requests
from celery.result import AsyncResult
from celery import current_app as current_celery_app
from fastapi import FastAPI, Request, Body, Depends, status, Form
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import json

from . import fp_router
from .schemas import FolderRequestsBody
from .tasks import find_new_music_folder_task, callback_acoustID_request, callback_MB_get_releases_by_discid_request, callback_FP_gen, task_test_logger
from .models import Fp
#from fpgenerator.database import get_db_session


logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="fpgenerator/celerytools/templates")

@fp_router.get("/form/get_current_root_task/")
def get_current_live_root_task():
    root_task = []
    response = find_live_jobs()
    resp_body = json.loads(response.body.decode(encoding=response.charset))
    print('resp_body:',resp_body)
    response_item = []
    if resp_body:
        tasks = resp_body['tasks']

        if tasks:
            for task in resp_body['tasks']:
                response = get_task_meta_data(task)
                resp_meta_body = json.loads(response.body.decode(encoding=response.charset))   
                if resp_meta_body['state'] != 'PENDING':     
                    print(resp_meta_body['name'],resp_meta_body['parent_id'])
                    parent_name_response = get_task_meta_data(resp_meta_body['parent_id'])
                    parent = json.loads(parent_name_response.body.decode(encoding=parent_name_response.charset))
                    response = {
                        'state': resp_meta_body['state'],
                        'name': task.name
                        
                    }
                else:
                    response = {
                        'state': resp_meta_body['state'],
                        
                    }
                    
                response_item.append(response)    
            
            return JSONResponse(response_item)
        else:
            return JSONResponse({'error':'no active tasks'})

@fp_router.get("/form/task_meta_data/")
def get_task_meta_data(task_id: str):
    if '\"' in task_id[0] and '\"' in task_id[-1]:
        task_id = task_id[1:-1]
        
    task = AsyncResult(task_id, app=current_celery_app)
    state = task.state
    meta_data = task._get_task_meta()

    if state == 'FAILURE':
        error = str(task.result)
        response = {
            'state': state,
            'error': error,
        }
    else:
        if state == "PENDING":
            response = {
                'state': state,
                'name': task.name
               
            }
        else:    

            response = {
                'state': state,
                'name': task.name,
                'parent_id': meta_data['parent_id']
                
            }
    return JSONResponse(response)

@fp_router.get("/form/tasks_live/")
def find_live_jobs():
    i = current_celery_app.control.inspect()
    # scheduled(): tasks with an ETA or countdown
    # active():    tasks currently running - probably not revokable without terminate=True
    # reserved():  enqueued tasks - usually revoked by purge() above
    tasks = []
    for queues in (i.active(), i.reserved(), i.scheduled()):
        for task_list in queues.values():
            for task in task_list:
                task_id = task.get("request", {}).get("id", None) or task.get("id", None)
                tasks.append(task_id)
          
    return JSONResponse({"tasks": tasks})            

@fp_router.get("/form/")
def form_fp_process_get(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})
   
@fp_router.post("/form/stop")
def stop_fp_process():
    return JSONResponse({"stopped": current_celery_app.control.purge()})
    
@fp_router.post("/form/")
def form_fp_process_start(folder_req_body: FolderRequestsBody):
    arg = ''
    current_celery_app.control.purge()
    if folder_req_body.post_proc_flag:
        print("in view:", folder_req_body.post_proc_flag)
        arg = 'ACOUSTID_MB_REQ'
    if folder_req_body.fp_flag:
        task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',([folder_req_body.path],[],[],'initial'),link=callback_FP_gen.s(arg))
    else:
        task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',([folder_req_body.path],[],[],'initial'))
    print('res:',task)

    return JSONResponse({"task_id": task.task_id})    

@fp_router.get("/fp_test/test_logger")
def fp_test():
    task = task_test_logger.delay()
    return JSONResponse({"message": "send logger message task to Celery successfully","task_id": task.task_id})
    
@fp_router.get("/form/task_status/")
def task_status(task_id: str):

    if '\"' in task_id[0] and '\"' in task_id[-1]:
        task_id = task_id[1:-1]
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
    
@fp_router.get("/form/task_sucessor/")        
def get_sucessor(task_id: str):    
    """ Lookup for a cucessor which is a callback by itself and has childs """
    
    task_items = []
    if '\"' in task_id[0] and '\"' in task_id[-1]:
        task_id = task_id[1:-1]
        
    task = AsyncResult(task_id, app=current_celery_app)
    state = task.state
    if state == 'FAILURE':
        error = str(task.result)
        response = {
            'state': state,
            'error': error,
        }
        return JSONResponse(response)
        
    if task.children:
        total_task_num = len(task.children)
    else:    
        response = {
            'state': state,
            'error': 'None object',
            }
        return JSONResponse(response)    
        
    if total_task_num == 0:
        response = {
            'state': state,
            'error': 'total_task_num = 0',
        }
        return JSONResponse(response) 

    i = 0
    for task_item in task.children:
        if task_item.state == 'SUCCESS':
            i+=1
        print(task_item.task_id, task_item.state)    
        task_items.append(task_item.task_id)
        
        if state == 'SUCCESS' and len(task_items) == 1:
            response = {
                'state': state,
                'task_id': task_items[0]
            }        
    return JSONResponse(response)        
    
@fp_router.get("/form/task_progress/")    
def get_fp_overall_progress(task_id: str):
    progress = 0
    task_items = []
    if '\"' in task_id[0] and '\"' in task_id[-1]:
        task_id = task_id[1:-1]
    task = AsyncResult(task_id, app=current_celery_app)
    state = task.state
    
    if state == 'FAILURE':
        error = str(task.result)
        response = {
            'state': state,
            'error': error,
        }
        return JSONResponse(response)
        
    else:    
        if task.children:
            total_task_num = len(task.children)
        else:    
            response = {
            'state': state,
            'error': 'None object',
            }
            return JSONResponse(response)

        if total_task_num == 0:
            response = {
            'state': state,
            'error': 'total_task_num = 0',
            }
            return JSONResponse(response)
        
        i = 0
        for task_item in task.children:
            if task_item.state == 'SUCCESS':
                i+=1
            task_items.append(task_item.task_id)

        progress = int((i/total_task_num)*100)    
        if state == 'SUCCESS' and len(task_items) >= 1:
            response = {
                'state': state,
                'progress': progress, 
                'total': total_task_num,
                'succeed':i
           }

        
    return JSONResponse(response)

