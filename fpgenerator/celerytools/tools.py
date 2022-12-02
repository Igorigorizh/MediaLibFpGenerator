# -*- coding: utf-8 -*-
import os
from posixpath import join, dirname
from os import scandir
import pickle
import acoustid
import zlib
import sqlite3
import chardet
import codecs
import re
import subprocess
import asyncio
from multiprocessing import Pool, cpu_count
from itertools import tee
import json

import discid

import musicbrainzngs
import time
import logging
import ast
from pathlib import Path


from medialib.myMediaLib_cue import simple_parseCue
from medialib.myMediaLib_cue import parseCue
from medialib.myMediaLib_cue import GetTrackInfoVia_ext

from celerytools import BASE_ENCODING
from celerytools import mymedialib_cfg
from celerytools import medialib_fp_cfg


from functools import wraps


import warnings
from redis import Redis
from celery_progress.backend import ProgressRecorder
from configparser import ConfigParser


cfg_fp = ConfigParser()
cfg_fp.read(medialib_fp_cfg)

logger = logging.getLogger('controller_logger.tools')

musicbrainzngs.set_useragent("python-discid-example", "0.1", "your@mail")


posix_nice_value = int(cfg_fp['FP_PROCESS']['posix_nice_value'])
	
		
def acoustID_lookup_celery_wrapper(self,*fp_args):
	scoreL = fp_item = []
	err_cnt = 0
	
	print('fp:',fp_args)
	API_KEY = 'cSpUJKpD'
	meta = ["recordings","recordingids","releases","releaseids","releasegroups","releasegroupids", "tracks", "compress", "usermeta", "sources"]
	response=acoustid.lookup(API_KEY, fp_args[1], fp_args[0],meta)
	print(response)
	
	return {'response':response,'fname':fp_args[2]}

def MB_get_releases_by_discid_celery_wrapper(self,*discID_arg):	
	discID = discID_arg[0]
	MB_discID_result = ''
	try:
		MB_discID_result = musicbrainzngs.get_releases_by_discid(discID,includes=["artists","recordings","release-groups"])
	except Exception as e:
		print(e)
		return {'RC':-6,'error':str(e)}
		
	if 'disc' not in MB_discID_result:	
		return {'RC':-7,'error':'DiskID MB - NOT detected','MB_discID_result':MB_discID_result}
	
		
	return {'RC':1,'MB_discID_result':MB_discID_result}
	
async def acoustID_lookup_wrapper(fp):
    API_KEY = 'cSpUJKpD'
    meta = ["recordings","recordingids","releases","releaseids","releasegroups","releasegroupids", "tracks", "compress", "usermeta", "sources"]
    return acoustid.lookup(API_KEY, fp[1], fp[0],meta)	
	
	
	
async def acoustID_lookup_wrapper_parent(fp):
    return await acoustID_lookup_wrapper(fp)	

			
	
	