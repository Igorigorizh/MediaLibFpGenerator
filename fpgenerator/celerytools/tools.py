# -*- coding: utf-8 -*-
import os

import logging
import ast
from pathlib import Path

from celery import current_app as current_celery_app, shared_task
from celery.result import AsyncResult

from celery.utils.log import get_task_logger
from celerytools import medialib_fp_cfg


from functools import wraps


import warnings
from redis import Redis
from celery_progress.backend import ProgressRecorder
from configparser import ConfigParser


cfg_fp = ConfigParser()
cfg_fp.read(medialib_fp_cfg)

logger = logging.getLogger('celery.tools')

def create_celery():
    celery_app = current_celery_app
    celery_app.config_from_object(settings, namespace="CELERY")

    return celery_app


def get_task_info(task_id):
    """
    return task info according to the task_id
    """
    task = AsyncResult(task_id)
    state = task.state

    if state == "FAILURE":
        error = str(task.result)
        response = {
            "state": task.state,
            "error": error,
        }
    else:
        response = {
            "state": task.state,
        }
    return response
	
		
def acoustID_lookup_celery_wrapper(self,*fp_args):
    scoreL = fp_item = []
    err_cnt = 0
	
    print('fp:',fp_args)
    API_KEY = 'cSpUJKpD'
    meta = ["recordings","recordingids","releases","releaseids","releasegroups","releasegroupids", "tracks", "compress", "usermeta", "sources"]
    response = acoustid.lookup(API_KEY, fp_args[1], fp_args[0],meta)
    print(response)

    return {'response': response,'fname': fp_args[2]}


def MB_get_releases_by_discid_celery_wrapper(self, *discID_arg):
    discID = discID_arg[0]
    MB_discID_result = ''
    try:
        MB_discID_result = musicbrainzngs.get_releases_by_discid(discID,includes=["artists", "recordings", "release-groups"])
    except Exception as e:
        print(e)
        return {'RC': -6, 'error': str(e)}

    if 'disc' not in MB_discID_result:
        return {'RC':-7,'error':'DiskID MB - NOT detected','MB_discID_result':MB_discID_result}


    return {'RC':1,'MB_discID_result':MB_discID_result}

async def acoustID_lookup_wrapper(fp):
    API_KEY = 'cSpUJKpD'
    meta = ["recordings","recordingids","releases","releaseids","releasegroups","releasegroupids", "tracks", "compress", "usermeta", "sources"]
    return acoustid.lookup(API_KEY, fp[1], fp[0], meta)	

async def acoustID_lookup_wrapper_parent(fp):
    return await acoustID_lookup_wrapper(fp)
