# -*- coding: utf-8 -*-
import os
from posixpath import join, dirname
from os import scandir
import pickle
import zlib
import sqlite3
import chardet
import codecs
import re
import subprocess
import asyncio
import functools
from functools import wraps
import configparser
from pathlib import Path

from redis import Redis
from celery import Celery
from celery_progress.backend import ProgressRecorder
from celery.result import AsyncResult
import celery_progress
import time
import logging


logger = logging.getLogger('controller_logger.scheduler')

	

def get_fp_overall_progress(root_task):
	
	total_task_num = len(root_task.children)
	print('Sub tasks for progress:',total_task_num)
	i = 0
	for task_item in root_task.children:
		if task_item.state == 'SUCCESS':
			i+=1
		time.sleep(.1)	
	return int((i/total_task_num)*100)

def check_job_status_via_result(result):
	#1. task_first_res = c_a.send_task('music_folders_generation_scheduler-new_recogn_name',(p3,[],[]),link=callback_FP_gen.s())
	#2. check_job_status_via_result(task_first_res)
	res = {'state':'INIT'}
	for a in range(100):
        
		res = celery_progress.backend.Progress(result).get_info()
		if res['state'] == 'SUCCESS':
			break
		if res['state'] == 'PROGRESS':
			print(res['progress']['percent'],res['progress']['description'],res['progress']['current'])
		else:
			print(res['state'],end=' ')
		time.sleep(3)
	print()	
	print('Sub tasks level 2:',len(result.children))
	res = {'state':'INIT'}
	if len(result.children) == 1:
		i = 0
		while res['state'] != 'SUCCESS':
			try:
				res = celery_progress.backend.Progress(result.children[0]).get_info()
			except Exception as e:
				print('Error',e,i)
				time.sleep(3)
				continue
				
			if res['state'] == 'SUCCESS':
				print(res['state'], 'First Found')
				break
			if res['state'] == 'PROGRESS':
				print()
				print(res['state'],end=' ')
				print(res['progress']['percent'],res['progress']['description'],res['progress']['current'])
			else:
				print(res['state'],end=' ')
			time.sleep(3)
			i+=1
			
		if len(result.children[0].children) >=1:
			total_task_num = len(result.children[0].children)
			print('Sub tasks level 3:',total_task_num)
			i = 0
			for task_item in result.children[0].children:
				try:
					#print()
					print(task_item.state,task_item.task_id,end=' ')
				except:
					print('Celery connection error')
                
				if task_item.state == 'PROGRESS':
					res_item = celery_progress.backend.Progress(task_item).get_info()
					print(res_item)
				elif task_item.state == 'SUCCESS':
					res_item = celery_progress.backend.Progress(task_item).get_info()
					print(res_item['result']['RC'])	
					i+=1
				else:
					print()
				#time.sleep(.1)	
			print()	
			print('Progress:', get_fp_overall_progress(result.children[0]))

def get_async_res_via_id(res_id_str):
	app = Celery(__name__)
	app.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://192.168.1.65:6379")
	app.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://192.168.1.65:6379")
	app.conf.imports = 'fpgenerator'
	app.conf.task_serializer = 'pickle'
	app.conf.result_serializer = 'pickle'
	app.conf.accept_content = ['application/json', 'application/x-python-serialize']
	return AsyncResult(res_id_str,app=app)
	