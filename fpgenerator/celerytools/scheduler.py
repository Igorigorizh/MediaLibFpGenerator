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
from multiprocessing import Pool, cpu_count
from itertools import tee
import configparser

from redis import Redis

import musicbrainzngs
import time
import logging
from pathlib import Path

from medialib.myMediaLib_init import readConfigData

from medialib import BASE_ENCODING
from medialib import mymedialib_cfg
from medialib import medialib_fp_cfg

from configparser import ConfigParser

import warnings
from medialib.myMediaLib_tools import get_FP_and_discID_for_album
from medialib.myMediaLib_tools import find_new_music_folder
from medialib.myMediaLib_tools import redis_state_notifier

#from worker import app

from functools import wraps

cfgD = readConfigData(mymedialib_cfg)
cfg_fp = ConfigParser()
cfg_fp.read(medialib_fp_cfg)

logger = logging.getLogger('controller_logger.scheduler')

musicbrainzngs.set_useragent("python-discid-example", "0.1", "your@mail")

redis_connection = Redis(host=cfg_fp['REDIS']['host'], port=cfg_fp['REDIS']['port'], db=0)

import celery_progress

def music_folders_generation_scheduler(self, folder_node_path, prev_fpDL, prev_music_folderL,*args):	
	# Генерация линейного списка папок с аудио данным с учетом вложенных папок
	# Промежуточные статусы писать в Redis!!!!
	
	
	if not os.path.exists(folder_node_path):
		print('---!Album path Error:%s - not exists'%folder_node_path)
		return 
	cnt=1	
	fpDL = []
	music_folderL = []
	use_prev_res = False
	prev_fpDL_used = False
	dump_path = ''

	if prev_music_folderL:
		if len(prev_music_folderL)>0:
			music_folderL = prev_music_folderL
			print("Media Folders structure is taken from prev music_folderL with len:",len(music_folderL))
	else:	
		dirL = find_new_music_folder(self,[folder_node_path],[],[],'initial')
		music_folderL = list(map(lambda x: bytes(x+'/',BASE_ENCODING),dirL['music_folderL']))
		print("Media folders structure build with initial folders:",len(music_folderL))
	
	tmp_music_folderL = music_folderL
	
	if prev_fpDL:
		if len(prev_fpDL) > 0:
			
			fpDL = prev_fpDL
			cnt = len(music_folderL) - len(tmp_music_folderL) + 1
			prev_fpDL_used = True
			print("Media Folders structure is recalculated from prev music_folderL with len:",len(tmp_music_folderL))

		if fpDL == []:		
			print('Error with last result folder. Not found in current folders structures')
			return{'music_folderL':music_folderL,'last_folder':last_folder}
			
	print(tmp_music_folderL,len(tmp_music_folderL))
	return tmp_music_folderL
	#job_folders_collect = q.enqueue('myMediaLib_tools.find_new_music_folder', [folder_node_path],[],[],'initial')

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

	