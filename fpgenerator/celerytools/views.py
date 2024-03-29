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
import urllib.parse
import celery_progress.backend

from medialib.myMediaLib_cue import sec2hour

from . import fp_router, cdtoc_router
from .schemas import FolderRequestsBody
from .tasks import find_new_music_folder_task, callback_acoustID_request, callback_MB_get_releases_by_discid_request
from .tasks import callback_FP_gen, callback_FP_gen_2, task_test_logger
from .tasks import callback_CDTOC_gen
from .models import Fp

#from fpgenerator.database import get_db_session

from fpgenerator.conf import settings
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="fpgenerator/celerytools/templates")

flower_host_api = settings.FLOWER_API_URL
flower_task_api = '{}/task'.format(flower_host_api)

@fp_router.get("/get_current_root_task/")
def get_current_live_root_task_fp():
    root_task = []
    response = find_live_jobs()
    resp_body = json.loads(response.body.decode(encoding=response.charset))
    #print('resp_body:',resp_body)
    response_item = []
    parent_tasks = []
    parent_name = ''
    if resp_body:
        tasks = resp_body['tasks']

        if tasks:
            for task in resp_body['tasks']:
                name = 'no-name-in-failure'
                response = get_task_meta_data(task)
                response_flower = flower_task_info(task)
                resp_meta_body = json.loads(response.body.decode(encoding=response.charset))   
                response_flower_body = json.loads(response_flower.body.decode(encoding=response_flower.charset)) 
                
                if resp_meta_body['state'] == 'FAILURE': 
                    parent_id = resp_meta_body['parent_id']
                    parent_tasks.append(parent_id)
                    response = {
                        'task_id': task,
                        'state': resp_meta_body['state'],
                        'parent_id': parent_id,
                        'name': name,
                        'parent_name': None
                    }
                    response_item.append(response)
                    continue
                    
                    
                if resp_meta_body['state'] != 'PENDING':
                    name = resp_meta_body['name']
                    print(resp_meta_body['name'],resp_meta_body['parent_id'])
                    if resp_meta_body['parent_id']:
                        parent_name_response = get_task_meta_data(resp_meta_body['parent_id'])
                        parent = json.loads(parent_name_response.body.decode(encoding=parent_name_response.charset))
                    
                        parent_id = resp_meta_body['parent_id']
                        parent_tasks.append(parent_id)

                        if 'name' in parent:
                            parent_name = parent['name']
                    else:
                        parent_id = None
                        parent_name = None
                        
                    response = {
                        'task_id': task,
                        'state': resp_meta_body['state'],
                        'parent_id': parent_id,
                        'name': name,
                        'parent_name': parent_name
                        
                    }
                elif resp_meta_body['state'] == 'PENDING':
                    print('----------Pending:', resp_meta_body['name'])
                    
                    if 'parent_id' in response_flower_body:
                        parent_name_response = get_task_meta_data(response_flower_body['parent_id'])
                        parent = json.loads(parent_name_response.body.decode(encoding=parent_name_response.charset))
                        parent_id = response_flower_body['parent_id']
                        parent_tasks.append(parent_id)
                        
                        if 'name' in parent:
                            parent_name = parent['name']
                        response = {
                            'task_id': task,
                            'state': response_flower_body['state'],
                            'parent_id': response_flower_body['parent_id'],
                            'name': name,
                            'parent_name': parent_name
                        }
                    else:
                        #print("------------********---------->",resp_meta_body)
                        
                        response = {
                            'task_id': task,
                            'state': resp_meta_body['state'],
                            'message': "No parents found"
                        }
                
                response_item.append(response) 
            if parent_tasks:    
                if len(set(parent_tasks)) == 1:
                    return JSONResponse({'root_id': parent_tasks[0], 'root_name': parent_name})
                else:
                    return JSONResponse({'root_id': parent_tasks[0][0], 'root_name': parent_name})
            else:
                return JSONResponse(response_item)
        else:
            return JSONResponse({'message':'no active FP tasks'})



@cdtoc_router.get("/get_current_live_task/")
def get_current_live_root_task_cdtoc():
    root_task = []
    response = find_live_jobs()
    resp_body = json.loads(response.body.decode(encoding=response.charset))
    #print('resp_body:',resp_body)
    response_item = []
    parent_tasks = []
    parent_name = ''
    if resp_body:
        tasks = resp_body['tasks']

        if tasks:
            # cdtoc can have only one child
            name = 'no-name-in-failure'
            if len(resp_body['tasks']) == 1:
                response = get_task_meta_data(tasks[0])
                response_flower = flower_task_info(tasks[0])
                resp_meta_body = json.loads(response.body.decode(encoding=response.charset))   
                response_flower_body = json.loads(response_flower.body.decode(encoding=response_flower.charset)) 
                
                if resp_meta_body['state'] == 'FAILURE': 
                    parent_id = resp_meta_body['parent_id']
                    response = {
                        'task_id': tasks[0],
                        'state': resp_meta_body['state'],
                        'parent_id': parent_id,
                        'name': name 
                    }
                elif resp_meta_body['state'] != 'PENDING':     
                    #print(resp_meta_body['name'],resp_meta_body['parent_id'])
                    print('in ! PENDING+++++++++++++++++++++')
                    name_response = get_task_meta_data(tasks[0])
                    task = json.loads(name_response.body.decode(encoding=name_response.charset))
                    parent_id = resp_meta_body['parent_id']

                    if 'name' in task:
                        name = task['name']

       
                    response = {
                            'task_id': tasks[0],
                            'state': resp_meta_body['state'],
                            'parent_id': parent_id,
                            'name': name
                        }
                elif resp_meta_body['state'] == 'PENDING':
                    name_response = get_task_meta_data(response_flower_body['parent_id'])
                    task = json.loads(name_response.body.decode(encoding=name_response.charset))
                    parent_id = response_flower_body['parent_id']
                            
                    if 'name' in task:
                        name = task['name']
                        
                    response = {
                                'task_id': tasks[0],
                                'state': response_flower_body['state'],
                                'parent_id': response_flower_body['parent_id'],
                                'name': name
                    }
                    
                return JSONResponse(response)    
            
            else:
                return JSONResponse({'message':'no active CDTOC tasks'})
        else:
            return JSONResponse({'message':'no active CDTOC tasks'})



@fp_router.get("/flower/task_info/")
def flower_task_info_fp(task_id: str):
    return flower_task_info(task_id)
 
@cdtoc_router.get("/flower/task_info/")
def flower_task_info_cdtoc(task_id: str):
    return flower_task_info(task_id)


def flower_task_info(task_id: str):
    url = '{}/info/{}'.format(flower_task_api,task_id)
    response_text=requests.get(url).text

    if response_text:
        response = json.loads(response_text)
    else:
        response = {
            'error': 'No data in response',
        }
    
    return JSONResponse(response) 

@fp_router.get("/task_meta_data/")
def get_task_meta_data_fp(task_id: str):
    return get_task_meta_data(task_id)


@cdtoc_router.get("/task_meta_data/")
def get_task_meta_data_cdtoc(task_id: str):
    return get_task_meta_data(task_id)
    
    
def get_task_meta_data(task_id: str):
    if '\"' in task_id[0] and '\"' in task_id[-1]:
        task_id = task_id[1:-1]
        
    task = AsyncResult(task_id, app=current_celery_app)
    state = task.state
    children = []
    meta_data = task._get_task_meta()
    
    parent_id = None
    worker = ""
    if 'parent_id' in meta_data:
        parent_id = meta_data['parent_id']
    if 'children' in meta_data:
        children = [a.task_id for a in meta_data['children']]
    if 'worker'  in meta_data:  
        worker = meta_data['worker']
    if state == 'FAILURE':
        error = str(task.result)
        response = {
            'state': state,
            'error': error,
            'name': task.name,
            'parent_id': parent_id,
            'children': children,
            'total_children': len(children),
            'worker': worker
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
                'parent_id': parent_id,
                'children': children,
                'total_children': len(children),
                'worker': worker
                
            }
    return JSONResponse(response)
    
    

@fp_router.get("/tasks_live/")
def find_live_jobs_fp():
    return find_live_jobs()

@cdtoc_router.get("/tasks_live/")
def find_live_jobs_cdtoc():
    return find_live_jobs()


def find_live_jobs():
    i = current_celery_app.control.inspect()
    # scheduled(): tasks with an ETA or countdown
    # active():    tasks currently running - probably not revokable without terminate=True
    # reserved():  enqueued tasks - usually revoked by purge() above
    tasks = []
    for queues in (i.active(), i.reserved(), i.scheduled()):
        if queues:
            for task_list in queues.values():
                for task in task_list:
                    task_id = task.get("request", {}).get("id", None) or task.get("id", None)
                    tasks.append(task_id)

    return JSONResponse({"tasks": tasks})


@fp_router.get("/form/")
def fp_form_process_get(request: Request):
    return templates.TemplateResponse("fp_form.html", {"request": request})

@cdtoc_router.get("/form/")
def cdtoc_form_process_get(request: Request):
    return templates.TemplateResponse("cdtoc_form.html", {"request": request})    
   
@fp_router.post("/form/stop")
def fp_form_process_stop(task_id: str):
    if '\"' in task_id[0] and '\"' in task_id[-1]:
        task_id = task_id[1:-1]
        
    task = AsyncResult(task_id, app=current_celery_app)
    
    return JSONResponse({"stopped": current_celery_app.control.purge()})
    
@cdtoc_router.post("/form/stop")
def cdtoc_form_process_stop(task_id: str):
    if '\"' in task_id[0] and '\"' in task_id[-1]:
        task_id = task_id[1:-1]
        
    task = AsyncResult(task_id, app=current_celery_app)
    return JSONResponse({"stopped": current_celery_app.control.purge()})




@fp_router.post("/form/start")
def fp_form_process_start(folder_req_body: FolderRequestsBody):
    arg = ''
    current_celery_app.control.purge()
    if folder_req_body.post_proc_flag:
        print("in view:", folder_req_body.post_proc_flag)
        arg = 'ACOUSTID_MB_REQ'
    if folder_req_body.fp_flag:
        #task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',([folder_req_body.path],[],[],'initial'),link=callback_FP_gen.s(arg))
        task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',\
            ([folder_req_body.path],[],[],'initial'),link=callback_FP_gen_2.s(arg))
    else:
        task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',([folder_req_body.path],[],[],'initial'))
    print('res:',task)

    return JSONResponse({"task_id": task.task_id})    

@cdtoc_router.post("/form/start")
def form_cdtoc_process_start(folder_req_body: FolderRequestsBody):
    arg = ''
    current_celery_app.control.purge()
    if folder_req_body.post_proc_flag:
        print("in view:", folder_req_body.post_proc_flag)
        arg = 'ACOUSTID_MB_REQ'
    if folder_req_body.cdtoc_flag:
        #task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',([folder_req_body.path],[],[],'initial'),link=callback_FP_gen.s(arg))
        task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',\
            ([folder_req_body.path],[],[],'initial'),link=callback_CDTOC_gen.s(arg))
    else:
        task = current_celery_app.send_task('find_new_music_folder-new_recogn_name',\
            ([folder_req_body.path],[],[],'initial'))
    print('res:',task)
        

    return JSONResponse({"task_id": task.task_id})    



@fp_router.get("/fp_test/test_logger")
def fp_test():
    task = task_test_logger.delay()
    return JSONResponse({"message": "send logger message task to Celery successfully","task_id": task.task_id})
 
@fp_router.get("/task_status/")
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
            'state': state
        }
    return JSONResponse(response)

@cdtoc_router.get("/current_task_progress/")
def get_current_task_progress_cdtoc(task_id: str):
    return get_current_task_progress(task_id)
 
@fp_router.get("/folder_task_progress/")
def get_current_task_progress_fp(task_id: str):
    return get_current_task_progress(task_id)
    
def get_current_task_progress(task_id: str):

    if '\"' in task_id[0] and '\"' in task_id[-1]:
        task_id = task_id[1:-1]
    task = AsyncResult(task_id, app=current_celery_app)
    state = task.state
    res = celery_progress.backend.Progress(task).get_info()
    progress = res
    failed = 0
    runtime = 0
    
    if state == 'FAILURE':
        error = str(task.result)
        response = {
            'state': state,
            'error': error
        }
    elif state == 'SUCCESS':
        if res['result']:
            if 'error' in res['result']:
                error = res['result']['error']

                response = {
                    'state': state,
                    'error': error,
                    'progress': res['progress']['percent'],
                    'total': res['result']['total_proceed'],
                    'succeed': res['result']['total_proceed']
                }    
                return JSONResponse(response)
        
            if 'result' in res['result']:
                if 'failed' in res['result']:
                    failed = res['result']['failed']
                    
                try:
                    if 'started_at' in task.result:
                        runtime = sec2hour(time.time() - task.result['started_at'] )[:-3]
                except Exception as e:
                    print(f'Exception at time estimation: {e}')
                    
                if 'error' in res['result']['result']:
                    error = str(res['result']['result']['error'])
                    response = {
                        'state': state,
                        'error': error,
                        'progress': res['progress']['percent'],
                        'total': res['result']['total_proceed'],
                        'succeed': res['result']['total_proceed']
                    }    
                    return JSONResponse(response)    
        
       
            response = {
                    'state': state,
                    'progress': res['progress']['percent'],
                    'total': res['result']['total_proceed'],
                    'succeed': res['result']['total_proceed'],
                    'succeed_final':res['result']['total_proceed'],
                    'runtime': runtime,
                    'failed': failed
                }
        else:
            response = {
                    'state': state,
                    'progress': res['progress']['percent']
                }
            
    else:   
    # PENDING
        response = {
            'state': state,
            'progress': res['progress']['percent'],
            'total': res['progress']['total'],
            'succeed': res['progress']['current'],
        }
    return JSONResponse(response)
    
@fp_router.get("/task_sucessor/")
def get_sucessor_fp(task_id: str):
    return get_sucessor(task_id)
    
@cdtoc_router.get("/task_sucessor/")
def get_sucessor_cdtoc(task_id: str):
    return get_sucessor(task_id)


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
        #print(task_item.task_id, task_item.state)    
        task_items.append(task_item.task_id)
        
        if state == 'SUCCESS' and len(task_items) == 1:
            response = {
                'state': state,
                'task_id': task_items[0]
            }        
    return JSONResponse(response)        
    
@fp_router.get("/task_subt_progress/")    
def get_fp_overall_progress(task_id: str):
    progress = 0
    task_items = []
    albums = 0
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
        #return JSONResponse(response)
        
    if True:    
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
        total_runtime = 0
        failed_num = 0
        folders = []
        
        for task_item in task.children:
            
            if task_item.state == 'SUCCESS':
                i+=1
                total_runtime+=task_item.result['result']['runtime']
                
                if 'RC' in task_item.result['result']:
                    if task_item.result['result']['RC'] < 1:
                        failed_num +=1
                        print('------------res_failed:',task_item.result['result'])
                    else:
                         if task_item.result['result']['folder_name'] not in folders:
                            folders.append(task_item.result['result']['folder_name'])
                else:
                    failed_num +=1
                    print('------------res_failed2:',task_item.result)
                
            task_items.append(task_item.task_id)
            
        progress = int((i/total_task_num)*100)    
        if state != 'PENDING' and len(task_items) >= 1:
            runtime = 0
            try:
                if 'started_at' in task.result:
                    runtime = sec2hour(time.time() - task.result['started_at'] )[:-3]
            except Exception as e:
                print(f'Exception at time estimation: {e}')
                
            try:
                if 'albums' in task.result:
                    albums = task.result['albums']
            except Exception as e:
                print(f'Exception at albums: {e}')                

            
                
            response = {
                'state': state,
                'progress': progress, 
                'total': total_task_num,
                'succeed': i,
                'runtime': runtime,
                'failed': failed_num,
                'albums_succeeded': len(folders),
                'albums_total': albums
           }

        
    return JSONResponse(response)
    
    
    
@fp_router.get("/get_subt_log/")    
def get_fp_subtask_log(task_id: str):
    progress = 0
    total_task_num = 0
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
        #return JSONResponse(response)
        
    
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
    total_runtime = 0
    failed_num = 0
    
    log_data = []
    log_folder_data = []
    for task_item in task.children:
            
        if task_item.state == 'SUCCESS':
            i+=1
            total_runtime+=task_item.result['result']['runtime']
            
            if 'RC' in task_item.result['result']:
                if task_item.result['result']['RC'] < 1:
                    failed_num +=1
                    if type(task_item.result['result']['folder_name']) == str:
                        data = task_item.result['result']['folder_name']
                    else:
                        data = task_item.result['result']['folder_name'].decode('utf-8')
                        
                    #log_data += f'{failed_num}. {data} \n'    
                    if data not in log_data:
                        log_data.append(data)
                        
                else:
                    if type(task_item.result['result']['folder_name']) == str:
                        data = task_item.result['result']['folder_name']
                    else:
                        data = task_item.result['result']['folder_name'].decode('utf-8')
                    
                    if data not in log_folder_data:
                        log_folder_data.append(data)
                    #log_data += f'{i}. {data} \n'

            else:
                failed_num +=1
                print('------------res_failed2:',task_item.result)
                
        task_items.append(task_item.task_id)
            
    if state != 'PENDING' and len(task_items) >= 1:
        runtime = 0
        try:
            if 'started_at' in task.result:
                runtime = sec2hour(time.time() - task.result['started_at'] )[:-3]
        except Exception as e:
            print(f'Exception at time estimation: {e}')

            
                
        response = {
                'state': state,
                'total': total_task_num,
                'succeed': i,
                'log': log_data,
                'succeed_folders_log': log_folder_data,
                'succeed_folders': len(log_folder_data),
                'failed': len(log_data)
        }

        
    return JSONResponse(response)    

@fp_router.get("/task_subt_stop/")    
def stop_active_tasks_of_root(task_id: str):
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
            if task_item.state == 'PENDING':
                i+=1
            task_items.append(task_item.task_id)
            current_celery_app.control.revoke(task_item.task_id, terminate=True, signal='SIGKILL')
            
        progress = int((i/total_task_num)*100)
        if state == 'SUCCESS' and len(task_items) >= 1:
            response = {
                'state': state,
                'progress': progress, 
                'total': total_task_num,
                'succeed':i
           }

        
    return JSONResponse(response)

