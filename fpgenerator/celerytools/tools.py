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

from medialib.myMediaLib_init import readConfigData

from medialib.myMediaLib_cue import simple_parseCue
from medialib.myMediaLib_cue import parseCue
from medialib.myMediaLib_cue import GetTrackInfoVia_ext
from medialib.myMediaLib_adm import getFolderAlbumD_fromDB
from medialib.myMediaLib_adm import db_request_wrapper
from medialib.myMediaLib_adm import collect_albums_folders

from medialib import BASE_ENCODING
from medialib import mymedialib_cfg
from medialib import medialib_fp_cfg


from functools import wraps


import warnings
from redis import Redis
from celery_progress.backend import ProgressRecorder
from configparser import ConfigParser

cfgD = readConfigData(mymedialib_cfg)

cfg_fp = ConfigParser()
cfg_fp.read(medialib_fp_cfg)

logger = logging.getLogger('controller_logger.tools')

musicbrainzngs.set_useragent("python-discid-example", "0.1", "your@mail")

redis_connection = Redis(host=cfg_fp['REDIS']['host'], port=cfg_fp['REDIS']['port'], db=0)

posix_nice_value = int(cfg_fp['FP_PROCESS']['posix_nice_value'])

def redis_state_notifier(state_name='medialib:', action='progress'):
	if action == 'progress':
		try:
			#print('get:',state_name)
			redis_connection.incr(state_name, 1)
			#print('result:',redis_connection.get(state_name))
		except Exception as e:
			logger.warning('Redis is not connected %s'%str(e))
	elif action == 'init':
		try:
			#print('get:',state_name)
			redis_connection.set(state_name,0)
			#print('result:',redis_connection.get(state_name))
		except Exception as e:
			logger.warning('Redis is not connected %s'%str(e))		
	elif action == 'progress-stop':
		try:
			#print('get:',state_name)
			redis_connection.delete(state_name)
		except Exception as e:
			logger.warning('Redis is not connected %s'%str(e))

class JobInternalStateRedisKeeper:
	# запоминаем аргументы декоратора
	def __init__(self, state_name='medialib:', action='init'):
		self._state_name = state_name
		self._action = action
	

	# декоратор общего назначения
	def __call__(self, func):
		@wraps(func)
		def wrapper(*args, **kwargs):
            
			val = func(*args, **kwargs)
			redis_state_notifier(self._state_name, self._action)
			
			return val
		return wrapper



def is_only_one_media_type(filesL):
	fTypeL = []
	media_typeL = ['flac', 'mp3', 'ape', 'wv', 'm4a', 'dsf']
	if type(filesL[0]) == bytes:
		media_typeL = list(map(lambda x: bytes(x,BASE_ENCODING), media_typeL))

	for orig_file in filesL:
		fType = os.path.splitext(orig_file)[1][1:]
		if (fType in media_typeL) and (fType not in fTypeL):
			fTypeL.append(fType)
			if len(fTypeL) > 1:
				return False
		elif (fType in media_typeL) and (fType in fTypeL):
			continue
	if len(fTypeL) == 1:
		return True
	return False



def detect_cue_FP_scenario(album_path,*args):

	image_cue = ''
	
	cueD = {}
	cueD = {}	
	orig_cue_title_cnt = 0
	f_numb = 0
	real_track_numb=0
	error_logL=[]
	cue_state = {'single_image_CUE':False, 'multy_tracs_CUE': False, 'only_tracks_wo_CUE':False,'media_format_mixture':False}
	
	if not os.path.exists(album_path):
		print('---!Album path Error:%s - not exists'%album_path)
		error_logL.append('[CUE check]:---!Album path Error:%s - not exists'%album_path)
		return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':0,cue_state:cue_state,'error_logL':error_logL}
	
	filesL = os.listdir(album_path)
	
	cue_cnt = 0
	#Валидация CUE через соответствие реальным данным для цели дальнейшей разбивки
	# Либо это нормальный CUE (TITLES > 1 и образ физически есть) -> нужна разбивка на трэки - ОК 
	# Либо это любой в тч 'битый' CUE, но есть отдельные трэки -> разбивка не нужна проверить соотв. количества трэков и титлов в #`CUE приоритет tracks и сверка с КУЕ
	
	normal_trackL = []

	for a in filesL:
		#print(a)
		ext = os.path.splitext(a)[1]
		#print(ext,a)
		if ext == b'.cue':
			print('in cue')
			image_cue = a
			
			normal_trackL = []
			try:	
				cueD = simple_parseCue(album_path+image_cue)	
			except Exception as e:
				print(e)
				return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':0,'errorL':['cue_corrupted'],cue_state:cue_state}
				
			cue_cnt+=1
			if cue_cnt>1:
				print('--!-- Error Critical! several CUE Files! Keep only one CUE!')
				error_logL.append('[CUE state check]:--!-- Error Critical! several CUE Files! Keep only one CUE!')
				return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':0,'errorL':['cue','cue_error','several cue'],cue_state:cue_state,'error_logL':error_logL}
				
			if 'orig_file_pathL' in cueD:
				orig_cue_title_cnt = len(cueD['songL'])
				real_track_numb = len(cueD['orig_file_pathL'])
				if real_track_numb == 1:
					if os.path.exists(cueD['orig_file_pathL'][0]['orig_file_path']):
						cue_state['single_image_CUE']=True
						break
				elif real_track_numb > 1:
					cue_state['multy_tracs_CUE']=True
					for orig_file in cueD['orig_file_pathL']:
						if not os.path.exists(orig_file['orig_file_path']):
							print('Failed CUE albumfile not exists:%s'%str(orig_file['orig_file_path'],BASE_ENCODING))
							error_logL.append('[CUE state check]: multy track mode. no real media detected for cue title:%s'%str(orig_file['orig_file_path'],BASE_ENCODING)) 
					break
				else:
					error_logL.append('[CUE state check]:--!-- Error Critical! - no media detected')
					return {'RC':-1,'f_numb':0,'title_numb':0,'errorL':['cue_corrupted','no media detected'],'orig_cue_title_numb':orig_cue_title_cnt,cue_state:cue_state,'cueD':cueD,'f_numb':real_track_numb,'error_logL':error_logL}
		else:

			# если до этого найден CUE, то проверка на only tracs не нужно
			if  cue_state['single_image_CUE'] or  cue_state['multy_tracs_CUE']: continue
			ext = os.path.splitext(a)[1]
			#print('in tracks 1',ext)
			
			if ext in [b'.ape',b'.mp3',b'.flac',b'.wv',b'.m4a',b'.dsf']:
				#print('in tracks 3')
				normal_trackL.append(a)

	RC = real_track_numb
	if (not cue_state['single_image_CUE'] and not cue_state['multy_tracs_CUE']) and normal_trackL and is_only_one_media_type(filesL):
		cue_state['only_tracks_wo_CUE']=True
	elif (not cue_state['single_image_CUE'] and not cue_state['multy_tracs_CUE']) and normal_trackL and not is_only_one_media_type(filesL):
		cue_state['media_format_mixture']=True
			
		
			
	#1. ОК - single CUE, 1 -original image, several tracks frof cue -> split is possible
	#2. ОК - several tracks > 1 ape,mp3,flac - no mix of them -> no split 
	#3. OK 2. tracks > 1 + splited CUE files from CUE tracks = cue title - Good cue can me ignored  -> no needed
	#4.  2. tracks > 1 + cue with no existed 1 image file  - BAD cue can me ignored  -> no needed
	#5.  2. tracks > 1 + cue with no existed several slitted tracks files - BAD cue can me ignored  -> no needed
	
	# В этом месте необходимо иметь образ wav и ссылку на него во временном CUE
	
	return {'RC':RC,'cue_state':cue_state,'orig_cue_title_numb':orig_cue_title_cnt,'title_numb':0,'f_numb':real_track_numb,'cueD':cueD,'normal_trackL':normal_trackL,'error_logL':error_logL}

#@JobInternalStateRedisKeeper(state_name='medialib-job-fp-albums-total-progress',action='progress')		
def get_FP_and_discID_for_album(self, album_path,fp_min_duration,cpu_reduce_num,*args):
	hi_res = False
	scenarioD = detect_cue_FP_scenario(album_path,*args)
	print('Self:',type(self))

	TOC_dataD = get_TOC_from_log(album_path)
	
	guess_TOC_dataD = {}
	if TOC_dataD['TOC_dataL']:
		print("Log TOC is here!:", TOC_dataD['toc_string'])
	else:
		print("No Log TOC detected")
	cueD = {}	
	paramsL = []	
	result = b''
	convDL = []
	prog = b''
	MB_discID_result = ''		
	API_KEY = 'cSpUJKpD'
	meta = ["recordings","recordingids","releases","releaseids","releasegroups","releasegroupids", "tracks", "compress", "usermeta", "sources"]	
	discID = log_discID = ''
	if os.name == 'nt':
		prog = b'ffmpeg.exe'
	elif os.name == 'posix':
		prog = b'ffmpeg'
	t_all_start = time.time()
	failed_fpL=[]
	if 0 <= cpu_reduce_num < cpu_count():
		cpu_num = cpu_count()-cpu_reduce_num
	else:
		cpu_reduce_num = 1
		print("Wrong CPU reduce provided, changed to ",cpu_reduce_num)
		cpu_num = cpu_count()-cpu_reduce_num
	redis_state_notifier('medialib-job-fp-albums-total-progress','progress')
	redis_state_notifier('medialib-job-fp-album-progress','init')
	
	if scenarioD['cue_state']['single_image_CUE']:
		print("\n\n-------FP generation for CUE scenario:  single_image_CUE-----------")
		try:
			print("Full cue parsing")
			cueD = parseCue(scenarioD['cueD']['cue_file_name'],'with_bitrate')
		except Exception as e:
				print(e)
				return {'RC':-1,'cueD':cueD}	
		if 'multy' in args and ('FP' in  args or 'split_only_keep' in args):
			print('--MULTY processing of FP --- on [%i] CPU Threads'%(cpu_num))
			image_name = cueD['orig_file_pathL'][0]['orig_file_path']
			
			command_ffmpeg = b'ffmpeg -y -i "%b" -t %.3f -ss %.3f "%b"'
			
			# Get 4 iterators for image name,  total_sec, start_sec, temp_file_name
			iter_image_name_1 = iter(image_name for i in range(len(cueD['trackD'])))
			iter_params = iter(args for i in range(len(cueD['trackD'])))
			iter_dest_tmp_name_4 = iter(join(album_path,b'temp%i.wav'%(num))  for num in cueD['trackD'])
			#iter_dest_tmp_name_4 = iter(b'temp%i.wav'%(num)  for num in cueD['trackD'])
			iter_dest_tmp_name_4, iter_dest_tmp_name = tee(iter_dest_tmp_name_4)
			iter_start_sec_3 = iter(cueD['trackD'][num]['start_in_sec']  for num in cueD['trackD'])
			if fp_min_duration > 10:
				iter_total_sec_2 = iter(fp_time_cut(cueD['trackD'][num]['total_in_sec'],fp_min_duration)	for num in cueD['trackD'])
				iter_total_sec_orig = iter(float('%.1f'%cueD['trackD'][num]['total_in_sec'])  for num in cueD['trackD'])
				# get iterator for ffmpeg command
				iter_command_ffmpeg = map(lambda x: command_ffmpeg%x,zip(iter_image_name_1,iter_total_sec_2,iter_start_sec_3,iter_dest_tmp_name_4))
			else:
				iter_total_sec_2 = iter(cueD['trackD'][num]['total_in_sec']  for num in cueD['trackD'])
				# get iterator for ffmpeg command
				iter_command_ffmpeg = map(lambda x: command_ffmpeg%x,zip(iter_image_name_1,iter_total_sec_2,iter_start_sec_3,iter_dest_tmp_name_4 ))
			
			
			res = ''
			if self:
				progress_recorder = ProgressRecorder(self)
				progress_recorder_descr = 'medialib-job-folder-FP-album:'+str(album_path)
				progress_recorder.set_progress(0, len(cueD['trackD']), description=progress_recorder_descr)

			start_t = time.time()
			try:
				with Pool(cpu_num) as p:
					res = p.starmap_async(worker_ffmpeg_and_fingerprint, zip(iter_command_ffmpeg,iter_dest_tmp_name,iter_params,)).get()
			except Exception as e:
				print("Caught exception in map_async 1",str(e))
				return {'RC':-1,'cueD':cueD}
				#p.terminate()
			#	p.join()
			p.join()	
			print('\n -----  album splite FP calc processing finished in [%i]sec'%(time.time()-start_t))
			try:
				if fp_min_duration > 10:
					convDL_iter = zip(iter_total_sec_orig, res)
					#a[1]:(fp,f_name,failed_fpL)
					convDL = [{'fname':a[1][1],'fp':(a[0],a[1][0][1])} for a in convDL_iter]
				else:
					convDL = [{'fname':a[1],'fp':a[0]} for a in res]
					
				failed_fpL = [a[2] for a in res if a[2] != []]
			except Exception as e:
				print('Error ar async get:',str(e))
				convDL = []
				failed_fpL = []
				
			
		else:
			cnt=1
			image_name = cueD['orig_file_pathL'][0]['orig_file_path']
			for num in cueD['trackD']:
				new_name = b'temp%i.wav'%(cnt)
				start_sec = int(cueD['trackD'][num]['start_in_sec'])
				total_sec = int(cueD['trackD'][num]['total_in_sec'])
				if 'FP' in  args:
					print("Track extact from from:",image_name,start_sec, total_sec)	
					ffmpeg_command = str(b'ffmpeg -y -i "%b" -aframes %i -ss %i "%b"'% (image_name,total_sec,start_sec,join(album_path,new_name)),BASE_ENCODING)
						
					#b"\""+join(album_path,new_name)+b"\"")
						
					
					print (ffmpeg_command)
					
					if prog != '' and ffmpeg_command != ():	
						try:
							print("Decompressing partly with:",prog)
							res = subprocess.Popen(ffmpeg_command, stderr=subprocess.PIPE ,stdout=subprocess.PIPE,shell=True)
							out, err = res.communicate()
						except OSError as e:
							print('get_FP_and_discID_for_cue 232:', e, "-->",prog,ffmpeg_command)
							return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':num,'errorL':['Error at decocmpression of [%i]'%(int(num))] }
						except Exception as e:
							print('Error in get_FP_and_discID_for_cue 235:', e, "-->", prog,ffmpeg_command)
							return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':num,'errorL':['Error at decocmpression of [%i]'%(int(num))]}	
					else:
						print('Error in get_FP_and_discID_for_cue 243:', e, "-->", prog,cueD['orig_file_pathL'][0]['orig_file_path'])
						return{'RC':-1,'cueD':cueD,'TOC_dataD':TOC_dataD,'scenarioD':scenarioD}		
					fp = []
					try:
						
						fp = acoustid.fingerprint_file(str(join(album_path,new_name),BASE_ENCODING))
					except  Exception as e:
						print("Error in fp gen with:",new_name,e)
						
						os.rename(join(album_path,new_name),join(album_path,bytes(str(time.time())+'_failed_','utf-8')+new_name))
						failed_fpL.append((new_name,e))
						cnt+=1
						continue
						#result = result + str(a,BASE_ENCODING) + str(fp)+"\n"
					#result = result + a + bytes(str(fp),BASE_ENCODING)+b'\n'
					
					convDL.append({"fname":new_name,"fp":fp})
					print("*", end=' ')
				
					os.remove(join(album_path,new_name))
					cnt+=1
					
					
					if self:
						progress_recorder = ProgressRecorder(self)
						progress_recorder_descr = 'medialib-job-folder-FP-album:'+str(album_path)
						progress_recorder.set_progress(0, len(cueD['trackD']), description=progress_recorder_descr)
	elif scenarioD['cue_state']['multy_tracs_CUE']:
		print("\n\n FP generation for CUE scenario:  multy_tracs_CUE")
		try:
			print("Full cue parsing")
			cueD = parseCue(scenarioD['cueD']['cue_file_name'],'with_bitrate')
		except Exception as e:
				print(e)
				return {'RC':-1,'cueD':cueD}	
		cnt=1
		
		if 'multy' in args and 'FP' in  args:
			#print('--MULTY---:',list(map(lambda x: str(join(album_path,x),BASE_ENCODING),scenarioD['normal_trackL'])))
			
			print('--MULTY processing of FP --- on [%i] CPU Threads'%(cpu_num))
			
			
			try:
				with Pool(cpu_num) as p:
					res = p.map_async(worker_fingerprint, [a['orig_file_path'] for a in cueD['orig_file_pathL']]).get()
					
			except Exception as e:
				print("Caught exception in map_async 2",e)
				return {'RC':-1,'cueD':cueD}	
			#	p.join()
			p.join()	
			#print(res)
			#return res
			try:	
				convDL = [{'fname':a[1],'fp':a[0]} for a in res]
			except Exception as e:
				print('Error:',str(e))	
		else:
			for track_item in cueD['orig_file_pathL']:
				track = track_item['orig_file_path']
				if 'FP' in  args:
					fp = []
					try:
						fp = acoustid.fingerprint_file(track)
					except  Exception as e:
						print("Error in fp gen with:",track)
						continue
						#result = result + str(a,BASE_ENCODING) + str(fp)+"\n"
					#result = result + a + bytes(str(fp),BASE_ENCODING)+b'\n'
					
					convDL.append({"fname":os.path.basename(track),"fp":fp})
					print("*", end=' ')
		
		
	elif scenarioD['cue_state']['only_tracks_wo_CUE']:
		print("\n\n FP generation for scenario only_tracks_wo_CUE")	
		scenarioD['normal_trackL'].sort()
		trackL = []
		for a in scenarioD['normal_trackL']:
			trackL.append(str(album_path,BASE_ENCODING)+str(a,BASE_ENCODING))
		
		try:	
			guess_TOC_dataD = guess_TOC_from_tracks_list(trackL)
		except Exception as e:
			print('Error in guess_TOC_from_tracks_list:',e)	
		
		sample_rate = guess_TOC_dataD['trackDL'][0]['sample_rate']
		if sample_rate > 44100:
			print('------------HI-RES check scenario details------------')
			hi_res = True	
		
		if 'multy' in args and 'FP' in  args:
			#print('--MULTY---:',list(map(lambda x: str(join(album_path,x),BASE_ENCODING),scenarioD['normal_trackL'])))
			print('--MULTY processing of FP --- on [%i] CPU Threads'%(cpu_num))
			
			
			try:
				with Pool(cpu_num) as p:
					res = p.map_async(worker_fingerprint, list(map(lambda x: str(join(album_path,x),BASE_ENCODING),scenarioD['normal_trackL']))).get()
					
			except Exception as e:
				print("Caught exception in map_async 3",e)
				return {'RC':-2,'normal_trackL':scenarioD['normal_trackL']}
				#p.terminate()
			#	p.join()
			p.join()	
			try:	
				convDL = [{'fname':a[1],'fp':a[0]} for a in res]
			except Exception as e:
				print('Error:',str(e))	
				
				
			if self:
				progress_recorder = ProgressRecorder(self)
				progress_recorder_descr = 'medialib-job-folder-FP-album:'+str(album_path)
				progress_recorder.set_progress(0, len(trackL), description=progress_recorder_descr)	
		else:
			for track in  scenarioD['normal_trackL']:
				fp = []
				if 'FP' in  args:	
					try:
						fp = acoustid.fingerprint_file(str(join(album_path,track),BASE_ENCODING))
					except  Exception as e:
						print("Error in fp gen with:",track)
						continue
							#result = result + str(a,BASE_ENCODING) + str(fp)+"\n"
						#result = result + a + bytes(str(fp),BASE_ENCODING)+b'\n'
					
					convDL.append({"fname":track,"fp":fp})
					print("*", end=' ')
					
					if self:
						progress_recorder = ProgressRecorder(self)
						progress_recorder_descr = 'medialib-job-folder-FP-album:'+str(album_path)
						progress_recorder.set_progress(0, len(cueD['trackD']), description=progress_recorder_descr)
		
			
	time_stop_diff = time.time()-t_all_start	
	if 'FP' in  args: 
		print("\n********** Album FP takes:%i sec.***********************"%(int(time_stop_diff)))
		
	redis_state_notifier('medialib-job-fp-album-progress','progress-stop')
	
				
	time_ACOUSTID_FP_REQ = time.time()
	if 'ACOUSTID_FP_REQ' in args and 'LOCAL' in args:
		print("\n Getting Album ACOUSTID_FP_REQ from https://acoustid.org/ **********************")
		err_cnt = 0
		scoreL = []
		for fp_item in convDL: 	
			response=asyncio.run(acoustID_lookup_wrapper_parent(fp_item['fp']))
			#response = acoustid.lookup(API_KEY, fp_item['fp'][1], fp_item['fp'][0],meta)
			if 'error' in response:
				err_cnt+=1
			else:
				if 'results' in response:
					l = [item['score'] for item in response['results']  if 'score' in item]
					if l != []:
						scoreL.append(max(l))
			if response == {'results': [], 'status': 'ok'}:
				duration_init = fp_item['fp'][0]
				fp_item['fp'] = list(fp_item['fp'])
				print('\n Empty FP response. duration [%s], trying to guess duration'%str(duration_init))
				for i in range(1,10):
					fp_item['fp'][0] = fp_item['fp'][0] - i
					response=asyncio.run(acoustID_lookup_wrapper_parent(fp_item['fp']))
					if response != {'results': [], 'status': 'ok'}:
						if 'results' in response:
							print('Succeceed with duration:',fp_item['fp'][0])
							l = [item['score'] for item in response['results']  if 'score' in item]
							if l != []:
								scoreL.append(max(l))
						
							break
				if response == {'results': [], 'status': 'ok'}:		
					fp_item['fp'][0] = duration_init
					
			fp_item['response'] = response
			
		if err_cnt > 0 and err_cnt < len(convDL):
			print('Errors %i in responses from %i'%(err_cnt,len(convDL)))
			for fp_item in convDL: 	
				if 'error' in fp_item['response']:
					response=asyncio.run(acoustID_lookup_wrapper_parent(fp_item['fp']))
					if 'error' not in  response:
						fp_item['response'] = response
						print('No more error in response %i'%(convDL.index(fp_item)))
						if 'results' in response:
							l = [item['score'] for item in response['results']  if 'score' in item]
							if l != []:
								scoreL.append(max(l))
					else:
						print('Error 2-nd time in response %i'%(convDL.index(fp_item)))
		if 	convDL:			
			if len(scoreL) == len(convDL):
				print('FP score rate:',sum(scoreL)/len(convDL))
			elif len(scoreL) < len(convDL) and len(scoreL) > 0:
				print('FP score rate with skipped FP:',sum(scoreL)/len(scoreL),'%i of %i'%(len(scoreL),len(convDL)))
			else:	
				print('Wrong FP scoreL:',scoreL)
		else:
			print("Error: convDL is empty")
			
	
		print("********** Album ACOUSTID_FP_REQ request takes:%i sec.***********************"%(int(time.time() - time_ACOUSTID_FP_REQ )))		
	
	# Выделеить в отдельную функцию
	TOC_src = ''
	
	time_discid_MB_REQ = time.time()
	if scenarioD['cue_state']['only_tracks_wo_CUE']:
		print("Try guess TOC from tracks list")	
		try:
			discID = discid.put(guess_TOC_dataD['discidInput']['First_Track'],guess_TOC_dataD['discidInput']['Last_Track'],guess_TOC_dataD['discidInput']['total_lead_off'],guess_TOC_dataD['discidInput']['offsetL'])
			print('Guess Toc:',discID.toc_string)
			TOC_src = 'guess'
			print("discId from guess - is OK")	
		except Exception as e:
			print("Issue with Guess TOC")
			print(e)
	else:
		print("Try TOC from CUE")	
		try:
			discID = discid.put(1,cueD['cue_tracks_number'],cueD['lead_out_track_offset'],cueD['offsetL'])
			print('Cue TOC:',discID.toc_string)
		except Exception as e:
			if 'offsetL' not in cueD: 
				print('offsetL is missing in cueD')
			else:	
				print("Issue with CUE TOC len(offsetL)",len(cueD['offsetL']))
			print(e)
	
	if TOC_dataD['discidInput'] and discID:
		if TOC_dataD['toc_string'] == discID.toc_string:
			TOC_src = 'cue'
			print("TOCs log and cue are identical")
		else:
			print("TOCs log and cue are NOT identical")
			print((TOC_dataD['toc_string']))
			TOC_src = 'log'
			print((discID.toc_string))	
		
	if TOC_dataD['discidInput']:
		print("Try TOC from log")
		try:
			log_discID = discid.put(TOC_dataD['discidInput']['First_Track'],TOC_dataD['discidInput']['Last_Track'],TOC_dataD['discidInput']['total_lead_off'],TOC_dataD['discidInput']['offsetL'])
			print('Log Toc:',log_discID.toc_string)
			print("discId from log is taken for MB request")	
		except Exception as e:
			print("Issue with Log TOC")
			print(e)
			
	if log_discID:
		discID = log_discID

	if 'MB_DISCID_REQ' in args:	
		if discID:
			
			try:
				MB_discID_result = musicbrainzngs.get_releases_by_discid(discID,includes=["artists","recordings","release-groups"])
			except Exception as e:
				print(e)
			if 'disc' in MB_discID_result:	
				print("DiskID MB - OK", MB_discID_result['disc']['id'],TOC_src) 	
				MB_discID_result['TOC_src'] = TOC_src
			else:
				print("DiskID MB - NOT detected") 	
				
			print("********** Album MB_DISCID_REQ MusicBrainz request takes:%i sec.***********************"%(int(time.time() - time_discid_MB_REQ )))		
	
	print("********** Album process in total takes:%i sec.***********************"%(int(time.time() - t_all_start )))
	
	return{'RC':len(convDL),'cueD':cueD,'TOC_dataD':TOC_dataD,'scenarioD':scenarioD,'MB_discID':MB_discID_result,'convDL':convDL,'discID':str(discID),'failed_fpL':failed_fpL,'guess_TOC_dataD':guess_TOC_dataD,'hi_res':hi_res,'album_path':album_path,'TOC_src':TOC_src}
def fp_time_cut(x,cut_sec):
	if x > cut_sec:
		return cut_sec
	else:
		return x

#@JobInternalStateRedisKeeper(state_name='medialib-job-fp-album-progress',action='progress')		
def worker_ffmpeg_and_fingerprint(ffmpeg_command, new_name, *args):
	#command template b'ffmpeg -y -i "%b" -aframes %i -ss %i "%b"'( new_name )
	failed_fpL = []
	#print('in worker')				
	f_name = os.path.basename(new_name)			
	#print (ffmpeg_command)
	prog = 'ffmpeg'				
	
	redis_state_notifier(state_name='medialib-job-fp-album-progress',action='progress')
	#print("Worker before ffmmeg pid:",os.getpid())
	if os.name == 'posix':
		try:
			nice_value = os.nice(posix_nice_value)	
		except Exception as e:
			print('Error in nice:',e)
	
	try:
		#print("Decompressing partly with:",prog)
		res = subprocess.Popen(ffmpeg_command.decode(), stderr=subprocess.PIPE ,stdout=subprocess.PIPE,shell=True)
		out, err = res.communicate()
	except OSError as e:
		print('get_FP_and_discID_for_cue 232:', e, "-->",prog,ffmpeg_command)
		return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':num,'errorL':['Error at decompression of [%i]'%(int(num))] }
	except Exception as e:
		print('Error in get_FP_and_discID_for_cue 235:', e, "-->", prog,ffmpeg_command)
		return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':num,'errorL':['Error at decompression of [%i]'%(int(num))]}
	
	fp = []
	#print("+", end=' ')
	
	if len(args)>0:
		if 'split_only_keep' in args[0]:
			return (fp,f_name,failed_fpL)	
	
	try:
		
		fp = acoustid.fingerprint_file(str(new_name,BASE_ENCODING))
	except  Exception as e:
		print("Error in fp gen with:",new_name,e)
		print('ffmpeg command:',ffmpeg_command)
		f_name = os.path.basename(new_name)
		os.rename(new_name,new_name.replace(f_name,bytes(str(time.time()).replace('.','_'),BASE_ENCODING)+f_name))
		failed_fpL.append((new_name,e))

	#print("*", end=' ')
		
	os.remove(new_name)	
	
	return (fp,f_name,failed_fpL)
	
#@JobInternalStateRedisKeeper(state_name='medialib-job-fp-album-progress',action='progress')	
def worker_fingerprint(file_path):
	print("Worker acoustid.fingerprint pid:",os.getpid())
	redis_state_notifier(state_name='medialib-job-fp-album-progress',action='progress')
	
	if os.name == 'posix':
		try:
			nice_value = os.nice(posix_nice_value)	
		except Exception as e:
			print('Error in nice:',e)
		
	try:
		fp = acoustid.fingerprint_file(file_path)
	except  Exception as e:
		print("Error [%s] in fp gen with:"%(str(e)),file_path)
		return ((),os.path.split(file_path)[-1])
	#print(fp[0],os.path.split(file_path)[-1])	

	return (fp,os.path.split(file_path)[-1])	
	

def do_mass_album_FP_and_AccId(folder_node_path,min_duration,prev_fpDL,prev_music_folderL,*args):	
	# Генерация FP и AccuesticIDs по альбомам из указанной дирректории (folder_node_path), для загрузок двойных альбомов и других массовых загрузок
	
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
		dirL = find_new_music_folder([folder_node_path],[],[],'initial')
		music_folderL = list(map(lambda x: bytes(x+'/',BASE_ENCODING),dirL['music_folderL']))
		print("Media folders structure build with initial folders:",len(music_folderL))
	
	tmp_music_folderL = music_folderL
	
	if prev_fpDL:
		if len(prev_fpDL) > 0:
			print(len(prev_fpDL),prev_fpDL[0:4])
			
			tmp_music_folderL = list(set(music_folderL) - set([a['album_path'] for a in prev_fpDL]))
			
			fpDL = prev_fpDL
			cnt = len(music_folderL) - len(tmp_music_folderL) + 1
			prev_fpDL_used = True
			print("Media Folders structure is recalculated from prev music_folderL with len:",len(tmp_music_folderL))

		if fpDL == []:		
			print('Error with last result folder. Not found in current folders structures')
			return{'music_folderL':music_folderL,'last_folder':last_folder}
	print(tmp_music_folderL)
	

	mode_dif = 30
	t_all_start = time.time()
	process_time = 	0
	redis_state_notifier('medialib-job-fp-albums-total-progress','init')
	for album_path in tmp_music_folderL:
		fpRD = {}
		
		print(cnt, ' of:',len(music_folderL),'--> Album folder:', [album_path])
		t_start = time.time()
		try:
			cnt+=1
			process_time = 0
			fpRD = get_FP_and_discID_for_album(album_path,min_duration,*args)
			process_time = 	int(time.time()-t_start)
			fpRD['album_path']=album_path
			fpRD['process_time'] = process_time
			fpDL.append(fpRD)	
			print('album finished in:',	process_time, "time since starting the job:",int(time.time()-t_all_start))
			print('\n-------------------   Validation ------------------')
			validatedD = album_FP_discid_response_validate([fpRD])
			print()
		except Exception as e:	
			print("Exception with FP generation [%s]: \n in %s"%(str(e),str(album_path)))	
			fpRD = {'RC':-3,'error_logL':["Exception with FP generation [%s]:  [%s]"%(str(e),str(album_path))],'album_path':album_path,'process_time': process_time}
			fpDL.append(fpRD)	

			
		if cnt%mode_dif == 0:
			if dump_path:
				try:
					os.remove(dump_path)
				except Exception as e:
					print('Last dump not deleted:',str(e))
					
			fname=b'fpgen_%i.dump'%int(time.time())
			dump_path = album_path+fname
			d = ''
			try:	
				with open(dump_path, 'wb') as f:
					d = pickle.dump({'fpDL':fpDL,'music_folderL':music_folderL,'dump_path':dump_path},f)
			except Exception as e:
				print('Error in pickle',e)
			print('Saved temp dump in:',fname)	
	
	redis_state_notifier('medialib-job-fp-albums-total-progress','progress-stop')	
	d = ''
	fname=b'fpgen_%i.dump'%int(time.time())
	dump_path = folder_node_path+fname
	try:	
		with open(folder_node_path+fname, 'wb') as f:
			d = pickle.dump( {'fpDL':fpDL,'music_folderL':music_folderL,'dump_path':dump_path},f)
	except Exception as e:
		print('Error in pickle',e)
	
	time_stop_diff = time.time()-t_all_start
	print('\n\n\n')
	print("*********************************************************************")
	print("**********Generation Summary for %i albums. All takes:%i sec.***********************"%(len(fpDL),int(time_stop_diff)))
	print("*********************************************************************\n")
	for a in fpDL:
		if 'RC' not in a: a['RC'] = -3
		if 'error_logL' not in a: a['error_logL'] = []
		
		if a['RC'] < 0:
			print("RC=(",a['RC'],")",a['album_path'],'IN TIME:',a['process_time'])
			print('*****************************')
			for b in a['error_logL']:
				print(b)
			print('*****************************')
			print()

			
	print('Some statistics:')
	if fpDL:
		print("Collected: albums number %i, time pro album %i sec."%(len(fpDL),int(time_stop_diff/len(fpDL))))	
	if prev_fpDL_used:	
		print("Skipped [FP is ready]:",len(prev_fpDL))
	else:
		print("All FP are initialy generagetd")
	print("Error while generation FP:",len([a['RC'] for a in fpDL if a['RC'] < 0]))
	print("Albums with bad FP:",len([a['RC'] for a in fpDL if a['RC'] < 0]))
	print("Albums with OK FP:",len([a['RC'] for a in fpDL if a['RC'] > 0]))
	
	check_MB_discID_in_fpDL(fpDL)
	
	return {'fpDL':fpDL,'music_folderL':music_folderL}
	
def check_MB_discID_in_fpDL(fpDL):
	cnt = 0
	no_discid_cnt = more_release_cnt = 	no_mb_data_for_discid_cnt = no_release_data_cnt = one_release_cnt = 0
	for item in fpDL:
		if 'MB_discID' in item:
			if 'disc' in item['MB_discID']:
				if 'release-list' in item['MB_discID']['disc']: 
					if len(item['MB_discID']['disc']['release-list']) == 1:
						print(cnt,item['MB_discID']['disc']['release-list'][0]['title'],'\n',item['album_path'],'utf-8')
						print(cnt,item['discID'])
						one_release_cnt+=1
					elif len(item['MB_discID']['disc']['release-list']) > 1:
						print(cnt, "! Releases:",len(item['MB_discID']['disc']['release-list']),'\n',item['album_path'],'utf-8')
						more_release_cnt+=1
					else:
						print(cnt,"MB out of data [release-list] is empty for %s: %s "%(str(item['MB_discID']['disc']['id']),str(item['album_path'],'utf-8')))
						no_mb_data_for_discid_cnt+=1
						#return (item['MB_discID']['disc'],item['album_path'])
					cnt+=1
				else:                
					print('-r', end=' ')
					no_release_data_cnt+=1
					cnt+=1		
			else:
				cnt+=1	
				continue
				
		else:
			print(cnt,"No discID in:",item['album_path'])
			no_discid_cnt +=1
			cnt+=1
	print('No discId generated in:',no_discid_cnt)		
	print('No MB release data for existed mb discId:',no_mb_data_for_discid_cnt)
	print('Strange case with no release:',no_release_data_cnt)
	print('OK - One release in MB:',one_release_cnt)
	print('OK - More releases in MB:',more_release_cnt)

def guess_TOC_from_tracks_list(tracksL):
	track_offset_cnt = 0
	total_track_sectors = 0
	first_track_offset = 150
	pregap = 0
	offset_mediaL = []
	discidInputD = {}
	next_frame = 0
	trackDL = []
	print('in guess_TOC_from_tracks_list')
	track_num = 0
	for track in tracksL:
		
		fType = os.path.splitext(track)[1][1:]
		try:
			trackD = GetTrackInfoVia_ext(track,fType)
		except Exception as e:
			print('Error in guess_TOC_from_tracks_list:',e)
			print('No TOC calculation possible')
			return{'TOC_dataL':[],'discidInput':{},'toc_string':''}
		full_length = trackD['full_length']
		
		total_track_sectors = total_track_sectors + int(full_length *75)+1
		if track_num == 0:
			offset_mediaL.append(first_track_offset + pregap)	
			next_frame = total_track_sectors - track_offset_cnt - pregap + first_track_offset - 1	
		else:
			offset_mediaL.append(next_frame)
		#print('Sector:',next_frame)	
		next_frame = total_track_sectors - track_offset_cnt - pregap + first_track_offset - 1		
		track_offset_cnt+=1	
		track_num +=1
		trackDL.append(trackD)
		
		
	lead_out_track_offset=next_frame	
	toc_string = 	''		
	if offset_mediaL:
		discidInputD = {'First_Track':1,'Last_Track':len(tracksL),'offsetL':offset_mediaL,'total_lead_off':lead_out_track_offset}
		toc_string = '%s %s %s %s'	%(discidInputD['First_Track'],discidInputD['Last_Track'],discidInputD['total_lead_off'],str(discidInputD['offsetL'])[1:-1].replace(',',''))
	
	return{'discidInput':discidInputD,'toc_string':toc_string,'trackDL':trackDL}	
	
def get_TOC_from_log(album_folder):
	files = os.listdir(album_folder)
	logs = [f for f in files if os.path.splitext(f)[1] == b'.log']
	logs.sort()
	TOC_dataL = []
	discidInputD = {}
	TOC_lineD= {}
	for f in logs:
		print(f)
		# detect file character encoding
		with open(os.path.join(album_folder,f),'rb') as fh:
			d = chardet.universaldetector.UniversalDetector()
			for line in fh.readlines():
				d.feed(line)
			d.close()
			encoding = d.result['encoding']
			print(encoding)
		with codecs.open( os.path.join(album_folder,f),'rb', encoding=encoding) as fh:
			lines = fh.readlines()
			regex = re.compile(r'^\s+[0-9]+\s+\|.+\|\s+(.+)\s+\|\s+[0-9]+\s+|\s+[0-9]+\s+$')
			
		matches = [tl for tl in map(regex.match,lines) if tl]

		if matches:
			start_offset = 150
			offsetL = []
			for tl in matches:
			     TOC_line = tl.string.split('|')
			     TOC_lineD = {'Track':int(TOC_line[0]),'Start':TOC_line[1],'Length':TOC_line[2],'Start_Sector':int(TOC_line[3]),'End_Sector':int(TOC_line[4])}
			     TOC_dataL.append(TOC_lineD)
			     offsetL.append(start_offset+int(TOC_line[3]))
			break
	toc_string = 	''		
	if TOC_dataL:
		discidInputD = {'First_Track':TOC_dataL[0]['Track'],'Last_Track':TOC_dataL[-1]['Track'],'offsetL':offsetL,'total_lead_off':1+start_offset+int(TOC_lineD['End_Sector'])}
		toc_string = '%s %s %s %s'	%(discidInputD['First_Track'],discidInputD['Last_Track'],discidInputD['total_lead_off'],str(discidInputD['offsetL'])[1:-1].replace(',',''))
	return{'TOC_dataL':TOC_dataL,'discidInput':discidInputD,'toc_string':toc_string}
	
		
def get_acoustID_from_FP_collection(fpDL):
	API_KEY = 'cSpUJKpD'
	resD = {}
	album_OK_cnt = 0
	album_missed_cnt = 0
	album_partly_covered=0
	album_RC_ge_0_cnt = 0
	meta = ["recordings","recordingids","releases","releaseids","releasegroups","releasegroupids", "tracks", "compress", "usermeta", "sources"]
	meta = ["recordings"]

	
	fpDL_len = len([a['RC'] for a in fpDL if a['RC']>0])  
	for a in fpDL:
		if a['RC']>0:
			album_RC_ge_0_cnt +=1
			print(a['album_path'])
			track_OK_cnt = 0
			for trackD in a['FP']:
				duration, fp = trackD['fp']
				time.sleep(.3)
				response = acoustid.lookup(API_KEY, fp, duration,meta)
				res = acoustid.parse_lookup_result(response)
				trackD['recording_idL']=[]
				for score, recording_id, title, artist in res:
					resD = {'score':score,'recording_id': recording_id,'title':title, 'artist':artist}
					trackD['recording_idL'].append(resD)

				if len(trackD['recording_idL'])> 0:
					track_OK_cnt+=1
					print(len(trackD['recording_idL']), end=' ')
			if track_OK_cnt == 0:
				print("[ :-( Album missed")
				album_missed_cnt+=1
			elif	len(a['FP'])	> track_OK_cnt:
				album_partly_covered +=1
				print("[ Partly covered: %i of %i tracks."%(track_OK_cnt,len(a['FP'])))
				
			elif	len(a['FP'])	== track_OK_cnt:
				album_OK_cnt+=1
				print("[ Album - OK: %i tracks.  "%track_OK_cnt)
			print(album_RC_ge_0_cnt,' .Total OK:{0} -> [{3:.0%}] Missed:{1} -> [{4:.0%}] Partly: {2} -> [{5:.0%}] from {6}.'.format(album_OK_cnt,album_missed_cnt,album_partly_covered,
			float(album_OK_cnt)/fpDL_len,float(album_missed_cnt)/fpDL_len,float(album_partly_covered)/fpDL_len,fpDL_len))	
		print()
	return resD		

def identify_music_folder(init_dirL,*args):
	#print args
	logger.debug('in identify_music_folder - start [%s]'%str(init_dirL))
	music_folderL = []
	file_extL = ['.flac','.mp3','.ape','.wv','.m4a','.dsf']

	for init_dir in init_dirL:
		if not isinstance(init_dir, str):
			print(init_dir)
			init_dirL[init_dirL.index(init_dir)] = init_dir.decode('utf8')
		else:
			if not os.path.exists(init_dir):
				print(init_dir, ': does not exists')
				return {'music_folderL':[]}
	i = 0
	t = time.time()
	print("Folders scanning ...")
	for new_folder in init_dirL:
		print("new_folder:",new_folder)
		with os.scandir(new_folder) as it:
			for entry in it:
				print(entry)
				if not entry.name.startswith('.') and entry.is_file():
					if os.path.splitext(entry.name)[-1] in file_extL:

						dir_name = os.path.dirname(''.join((new_folder,entry.name)))
						print(dir_name)
						#print [join(root.decode('utf8'),a.decode('utf8'))]
						if dir_name not in music_folderL:
					
							music_folderL.append(dir_name)
							#print 'dir_name:',type(dir_name),[dir_name]
							break

	print()
	time_stop_diff = time.time()-t
	print('Scanning for music folder: Finished in %i sec'%(int(time_stop_diff)))
	logger.debug('in identify_music_folder found[%s]- finished'%str(len(music_folderL)))
	return {'music_folderL':music_folderL}
	


def bulld_subfolders_list(self, init_dirL, *args):
	#1. job run
	#task_first_res = c_a.send_task('find_new_music_folder-new_recogn_name',([path],[],[],'initial')) 
	#2. get progress results 
	#res = celery_progress.backend.Progress(task_first_res).get_info()
	# if res['state'] == 'PROGRESS': ....
	resL = []
	if self:
		progress_recorder = ProgressRecorder(self)
		progress_recorder_descr = 'medialib-job-folder-scan-progress-first-run'

	for init_dir in init_dirL:
		if 'verbose' in args:
			print()
			if not os.path.exists(init_dir):
				print(init_dir,'  Not exists')
				continue
			else:
				print(init_dir,'  Ok')
		i = 0		
		for root, dirs, files in os.walk(init_dir):
			for a in dirs:
				if 'verbose' in args:
					if i%100 == 0:
						print(i, end=' ',flush=True)
					
					
				i+=1
				if self:
					if i%10 == 0:
						#redis_state_notifier(state_name='medialib-job-folder-progress', action='progress')
						progress_recorder.set_progress(i + 1, i + 100, description=progress_recorder_descr)

				yield(Path(root).as_posix(),a)
				#resL.append((Path(root).as_posix(),a))	
	if self:
		#redis_state_notifier(state_name='medialib-job-folder-progress', action='progress')
		progress_recorder.set_progress(i, i, description=progress_recorder_descr)
	return

def find_new_music_folder_simple(self,init_dirL,*args):
	# similar to find_new_music_folder but more simple withou db filter and pickle
	logger.info('in find_new_music_folder_simple - start')
	folders_list = tuple(bulld_subfolders_list(None,dirL,'verbose'))	
	t = time.time()
	print()
	print('Passed:',time.time()-t)
	joined_folder_list = list(set([join(a[0],a[1]) for a in folders_list]))
	joined_folder_list.sort()
	t = time.time()
	music_folderL = collect_media_files_in_folder_list(self,joined_folder_list,'verbose')
	print()
	print('Passed:',int(time.time() - t))
	logger.debug('in find_new_music_folder_simple found[%s]- finished'%str(len(music_folderL)))
	return {'folder_list':folders_list,'NewFolderL':joined_folder_list,'music_folderL':music_folderL}
	
#@JobInternalStateRedisKeeper(state_name='medialib-job-folder-progress', action='init')		
def find_new_music_folder(self,init_dirL, prev_folderL, DB_folderL,*args):
	# по умолчанию ищет музыкальную папку в пересечении множеств исходного дерева папок (сохраненного в ml_folder_tree_buf_path)и узла,
	# который содержит новые данные + если запрошено по наличию папки в таблице album из DB_folderL
	
	#print args
	logger.info('in find_new_music_folder - start')
	f_l = []
	new_folderL = []
	resBuf_save_file_name = ''
	f_name = ''
	
	creation_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
	
	# Новый сценарий получение списка части дерева папок относительно искомого узла (init_dirL) из БД
	
	
	if args != ():
		if type(args[0]) == dict:
			if 'resBuf_save' in args[0]:
				resBuf_save_file_name = args[0]['resBuf_save']
				f_name = cfgD['ml_folder_tree_buf_path']
	
	print('resBuf_save_file_name',resBuf_save_file_name)
	for init_dir in init_dirL:
		if not isinstance(init_dir, str):
			print('Not string:',init_dir)
			init_dirL[init_dirL.index(init_dir)] = init_dir.decode('utf8')
		else:
			if not os.path.exists(init_dir):
				print(init_dir, 'does not exists')
				return {'folder_list':[],'NewFolderL':[]}
	i = 0
	t = time.time()
	print("Folders scanning ...")
	
	f_l= tuple(bulld_subfolders_list(self,init_dirL))			
	print()
	time_stop_diff = time.time()-t
	print('Takes sec:',time_stop_diff)
	if prev_folderL == [] and not 'initial' in args:
		print('First run: Finished in %i sec'%(int(time_stop_diff)))
		if resBuf_save_file_name != '':
			f = open(f_name,'wb')
			d = pickle.dump({'folder_list':f_l,'NewFolderL':[],'music_folderL':[],'creation_time':creation_time},f)
			f.close()
			print('save buffer',f_name)
			logger.info('in find_new_music_folder - finished: Buff saved in:%s'%(f_name))
			return {'resBuf_save':f_name}
		else:
			return {'folder_list':f_l,'NewFolderL':[]}
	
	if DB_folderL != []:
		prev_folderL = list(set([join(a[0],a[1]) for a in DB_folderL]).difference(set([join(a[0],a[1]) for a in prev_folderL])))
	# Вычисление пересеченеия новых папок с последним сохраненным деревом папок
	new_folderL = list(set([join(a[0],a[1]) for a in f_l]).difference(set([join(a[0],a[1]) for a in prev_folderL])))
	#print(new_folderL[0])
	#new_folderL = list(set(f_l).difference(set(prev_folderL)))
	new_folderL.sort()

	if len(new_folderL) == 0:
		print('No Change: Finished')
	elif len(new_folderL) > 0:
		print('Changes found!', len(new_folderL))
		#print(new_folderL)
	# Collect music folders
	music_folderL = []
	
	music_folderL = collect_media_files_in_folder_list(self,new_folderL)
	
	# check if initial folder root folder itself containes media
	if not music_folderL:
		music_folderL = collect_media_files_in_folder_list(self, init_dirL)
						
	
	
	music_folderL = list(set(map(lambda x: x.replace('\\','/'),music_folderL)))	
	if resBuf_save_file_name != '':
		f = open(f_name,'wb')
		d = pickle.dump({'folder_list':f_l,'NewFolderL':new_folderL,'music_folderL':music_folderL,'creation_time':creation_time},f)
		f.close()
		print('save buffer',f_name)
		logger.info('in find_new_music_folder - finished: Buff saved in:%s'%(f_name))
		return {'resBuf_save':f_name}
	

	redis_state_notifier(state_name='medialib-job-folder-progress', action='progress-stop')
	logger.debug('in find_new_music_folder found[%s]- finished'%str(len(music_folderL)))
	return {'folder_list':f_l,'NewFolderL':new_folderL,'music_folderL':music_folderL}
	
def collect_media_files_in_folder_list(self, folderL,*args):
	music_folderL = []
	if self:
		progress_recorder = ProgressRecorder(self)
		progress_recorder_descr = 'medialib-job-folder-scan-progress-media_files'
	file_extL = ['.flac','.mp3','.ape','.wv','.m4a','.dsf']
	i = 0
		#print("new_folder:",[new_folder])
	for new_folder in folderL:	
		for root, dirs, files in os.walk(new_folder):
			for a in files:
				if os.path.splitext(a)[-1] in file_extL:
					if root not in music_folderL:
						music_folderL.append(Path(root).as_posix())
						break
		if 'verbose' in args:
			if i%100 == 0:
				print(i, end=' ',flush=True)				
		if self:
			if i%10 == 0:
				progress_recorder.set_progress(i + 1, len(folderL), description=progress_recorder_descr)				
		i+=1	
	if self:
		progress_recorder.set_progress(i, len(folderL), description=progress_recorder_descr)		
	return 	music_folderL				
					

def quick_check_medialib_utf8_issue(*args):
	# быстрая проверка таблиц на соответствие unicode
	mlDL = [{'table':'album','filedL':['path','album','search_term']},
			{'table':'track','filedL':['path','artist','album','title','cue_fname']},
			{'table':'artist','filedL':['artist','search_term','description']},
			{'table':'artist_cat_rel','filedL':['artist_name']},
			{'table':'category','filedL':['category_short_name','category_descr']},
			{'table':'category_type','filedL':['categ_type_name','categ_type_descr']},
			{'table':'GROUPS_PL','filedL':['descr','ref_folder','short_name']},
			{'table':'tag','filedL':['tag_name','tag_descr']},
			{'table':'track_tag','filedL':['tag_name']}
			]
	dbPath = cfgD['dbPath']
	db = sqlite3.connect(dbPath)	
	c = db.cursor()		
	#print 'db.text_factory:',db.text_factory
	exec_err_L = []
	fetch_err_L = []
	for table_item in mlDL:
		for fld_name in table_item['filedL']:
			req_data = (fld_name,table_item['table'])
			req = 'select %s from %s'%req_data
			#print [req]
			msg_str = 'Table [%20s] field (%25s):'%(req_data[1].upper(),req_data[0])
			print(msg_str, end=' ')
			msg_exec = msg_fetch ='Failed'
			try:
				c.execute(req)
				msg_exec = 'OK'
			except Exception as e:
				print(e)
				exec_err_L.append((req_data,msg_str,e))
			
			if msg_exec == 'OK':
				try:	
					r = c.fetchall()	
					msg_fetch = 'OK'
				except Exception as e:
					#print e	
					fetch_err_L.append((req_data,msg_str,e))	
				
			print('[exec: %s, fetch:%s]'%(msg_exec,msg_fetch))	
		
		print("*"*50)	
		
	fld_erL = []	
	if 'with_fetch_detailes' in args:
		tabl_set = set([a[0][1] for a in fetch_err_L])
		print([tabl_set])
		for table in tabl_set:
			if 'track' == table:
				req = 'select id_track from %s'%(table)
			elif 'artist' == table:
				req = 'select id_artist from %s'%(table)
			elif 'album' == table:
				req = 'select id_album from %s'%(table)	
			else:
				continue
			
			c.execute(req)
			try:
				r = c.fetchall()	
			except Exception as e:
				print(e)
				
			
			print('Table:',table)
			idL = [a[0] for a in r]	
			filedL = [itm['filedL'] for itm in mlDL if itm['table'] == table][0]
			err_cnt = utf_8_err_cnt = 0
			#print filedL
			for a in filedL:
				print('Processing field:',a,' of ',table.upper())
				i = 0
				err_cnt = utf_8_err_cnt = 0
				for id in idL:
					
					req = 'select %s from %s where id_%s = %s'%(a,table,table,str(id))
					exec_ok = True
					try:
						c.execute(req)
					except Exception as e:
						if 'utf-8' in e.message.lower():
							utf_8_err_cnt+=1
						fld_erL.append({'table':table,'field':a,'id':id,'error':e,'request':req})
						exec_ok = False
						err_cnt+=1
						
					if exec_ok:	
						try:
							r = c.fetchone()	
						except Exception as e:
							fld_erL.append({'table':table,'field':a,'id':id,'error':e})		
							if 'utf-8' in e.message.lower():
								utf_8_err_cnt+=1
							err_cnt+=1
						
					if i%1000 == 0:
						print('%i[%i]'%(i,err_cnt), end=' ')
					i+=1
				if utf_8_err_cnt == err_cnt and err_cnt > 0:
					print()
					print('All issues %s %s are UTF-8'%(table,a))
				elif utf_8_err_cnt == err_cnt and err_cnt == 0:
					print()
					print('No issues in %s %s --> OK'%(table,a))
				print()	
				len_fld_erL = len(fld_erL)
				print('fld_erL:%i, utf_8_err_cnt:%i'%(len_fld_erL,utf_8_err_cnt))
				
			
	c.close()
	db.close()
	return {'exec_err_L':exec_err_L,'fetch_err_L':fetch_err_L,'fld_erL':fld_erL}
	
def check_medialib_TRACK_utf8_issue(fs_folderL,erL,*args):
	# аналог функции check_medialib_TRACK_utf8_issue, но входящие параметры другие, т.к. сравнение на шаге 3 с полным именем файла
	# т.е использовать один и тотже список нельзя!
	t_start = time.time()
	# Сценарий миграции БД на unicode: формирования списка пересчета CRC32 на основе пересчета CRC32 для путей в unicode
	# все преобразования .decode('cp1251') сделаны из-за первичного сохранения объектов в БД НЕ в UNICODE!
	dbPath = cfgD['dbPath']
	# таблица TRACK (пока только эта таблица) - собираем все CRC32 для путей из БД
	req = "select path_crc32, id_track  from track"
	db_TRACK_pathL = db_request_wrapper(None,req)
	
	convL = []
	dublicatL = []
	er_tb_deleteL = []
	er_cueL = []
	er_titleL = []
	er_artistL = []
	i = 0
	if erL == []:
		print("1. MediaLib db scanning...")
		db = sqlite3.connect(dbPath)	
		c = db.cursor()		
		for a in db_TRACK_pathL:
			if i%10000 == 0:
				print(i, end=' ')
			i+=1
			# Get single ALBUM entry via path_crc32
			req = "select path from track where id_track = %s"%(str(a[1]))
			
			try:
				c.execute(req)
			except Exception as e:
				if 'UTF-8' in e.message: 
				# отбираем записи где появилась ошибка преобразования unicode связанная path
				#print '*',
					if a[0] not in erL:
						erL.append(a[0])
					else:
						# в процессе добавления альбомов появились дубликаты. Из-за некорректного алгоритма добавления
						# Дубликаты надо собрать и исправить отдельно в БД 
						dublicatL.append((a[0],a[1]))	
						print('=', end=' ')
					
					
			req = "select cue_fname from track where id_track = %s"%(str(a[1]))
			try:
				c.execute(req)
			except Exception as e:
			# отбираем записи где появилась ошибка преобразования unicode связанная path
				#print '*',
				if 'UTF-8' in e.message: 
					if a[0] not in er_cueL:
						er_cueL.append(a[0])
						
						
			req = "select title from track where id_track = %s"%(str(a[1]))
			try:
				c.execute(req)
			except Exception as e:
			# отбираем записи где появилась ошибка преобразования unicode связанная title
				#print '*',
				if 'UTF-8' in e.message: 
					if a[0] not in er_titleL:
						er_titleL.append(a[0])			
						
			
			req = "select artist from track where id_track = %s"%(str(a[1]))
			try:
				c.execute(req)
			except Exception as e:
			# отбираем записи где появилась ошибка преобразования unicode связанная artist
				#print '*',
				if 'UTF-8' in e.message: 
					if a[0] not in er_titleL:
						er_artistL.append(a[0])				
				
		c.close()			
		db.close()
		
		check_cue = False
		time_stop_diff = int(time.time()-t_start)	
		print()
		if set(er_cueL).issubset(set(erL)):
			check_cue = True
			print('Cue error list is subset of Path error list')
		else:
			print('Warning! Cue errors are is NOT subset of Path error list, check it separately!')
			
			
		check_title = False
		print()
		if set(er_titleL).issubset(set(erL)):
			check_title = True
			print('Title error list is subset of Path error list')
		else:
			print('Warning! Title errors are is NOT subset of Path error list, check it separately!')	
			
			
		check_artist = False
		print()
		if set(er_artistL).issubset(set(erL)):
			check_artist = True
			print('Artist error list is subset of Path error list')
		else:
			print('Warning! Artist errors are is NOT subset of Path error list, check it separately!')		
			print('er_artistL dif len:',len(set(erL).intersection(set(er_artistL))))
		
		print()		
		print("		MediaLib containes UTF8 decoding issues:",len(erL))	
		print("		MediaLib Album containes dublicates (dublicatL):",len(dublicatL))	
		print('Finished in %i sec.'%(time_stop_diff))

	# check path existence for failed path_crc32
	print()
	print("2. Checking path existence for failed path_crc32 from erL:",len(erL))
	i = 0
	
	t_2 = time.time()	
	db = sqlite3.connect(dbPath)	
	c = db.cursor()	
	# !! Первый проход с подключением к бд с db.text_factory = str
	if 'no_utf8' in args:
		db.text_factory = str	
	req = "select id_track, path_crc32, path, cue_fname,title,artist,cue_num from TRACK where path_crc32 in (%s)"%(str(erL)[1:-1])
	try:
		c.execute(req)
	except Exception as e:
		print(e)	
		
	try:	
		r = c.fetchall()	
	except Exception as e:
		print(e)	
		
	print('Pathes for erL retrieved in %i sec'%(int(time.time()-t_2)))  	
		
	track_path = ''
		
	for req_res_item in r:
			#print 'dublicat',req_res_item
			
		try:
			track_path = req_res_item[2]
		except	Exception as e:
			print(e)
			print('Error: request res: %s, req: %s'%(str(r),str(req)))
			return {"erL":erL,"er_tb_deleteL":er_tb_deleteL,'convL':convL,'matchL':[]} 
		if not os.path.exists(track_path):
			er_tb_deleteL.append((req_res_item[1],req_res_item[0]))
		else:
			#id_track, path, cue_fname
			convL.append((req_res_item[0],req_res_item[1],req_res_item[2],req_res_item[3],req_res_item[4],req_res_item[5],req_res_item[6]))
		if i%1000 == 0:
			print(i, end=' ')
		i+=1	
			
	c.close()			
	db.close()					
	
	print()		
	print("		Media lib album not exists and to be deleted issues:",len(er_tb_deleteL))	
	print("		Media lib album to be matched and ajusted (convL):",len(convL))	
	time_stop_diff = int(time.time()-t_2)
	print('Finished in %i sec.'%(time_stop_diff))
	
	if set(erL) == set([a[0] for a in er_tb_deleteL]):
		print('2.1 Success: erL  is in sync with er_tb_deleteL')
	else:
		print('2.1 Issue: erL  is NOT in sync with er_tb_deleteL')
	
	dirL = []
	if 'collect_dirs_for_preproc' in args:
		
		for a in convL:
			dir_name = os.path.dirname(a[1])
			if dir_name not in dirL:
				dirL.append(dir_name)
		print('convL with dirL substituted dirL:',len(dirL))		
	
	
	t_2 = time.time()	
	matchL = []
	real_fs_folder_path = ''
	pathD = {}
	
	if 'fast_convL_processing' in args:
		print('fast_convL_processing is on') 
		print("3. DB and FS track names matching only at convL:%i..."%(len(convL)))
		i = 0
		t_2 = time.time()
		for b in convL:
			
			db_fs_dir_name = os.path.dirname(b[2].decode('cp1251'))
			crc32_db_fs_dir_name = zlib.crc32(db_fs_dir_name.encode(BASE_ENCODING))
			
			fileL = []			
			if crc32_db_fs_dir_name not in pathD:
				pathD[crc32_db_fs_dir_name] = []
				if os.path.exists(db_fs_dir_name):
					fileL = scandir.listdir(db_fs_dir_name)
					
					for file_name in fileL:
						for frm in ['.mp3','.ape','.flac']:
							if frm in file_name.lower():
								pathD[crc32_db_fs_dir_name].append(join(db_fs_dir_name,file_name))			
						
						
					# Not CUE scenario
			for real_fs_file_path in pathD[crc32_db_fs_dir_name]:
				db_fs_folder_file_path = b[2].decode('cp1251')
				if not os.path.exists(db_fs_folder_file_path):
					print('Error with decoded path file name:[%s]'%(db_fs_folder_file_path))
			
				if real_fs_file_path == db_fs_folder_file_path:
					crc32_1 = zlib.crc32(db_fs_folder_file_path.encode(BASE_ENCODING))
				
						#print "*",
					if b[1] in er_cueL:
						
						db_fs_cue_file_path = b[3].decode('cp1251')
						crc32_1 = zlib.crc32((db_fs_cue_file_path + ',' + str(b[6])).encode(BASE_ENCODING))
						# проверить доступность нового поти
						if not os.path.exists(db_fs_cue_file_path):
							print('Error with decoded cue file name:[%s]'%(db_fs_cue_file_path))
					else:
						db_fs_cue_file_path = None
					
					new_title = None	
					if b[1] in er_titleL:
						new_title = b[4].decode('cp1251')
						
					new_artist = None	
					if b[1] in er_artistL:
						new_artist = b[4].decode('cp1251')	
						
						
					matchL_item = {'new_crc32':crc32_1,'old_crc32':b[1],'new_path':db_fs_folder_file_path,'id_track': b[0],'new_cue_fname':db_fs_cue_file_path,'new_title':new_title,'new_artist':new_artist}
					
					if matchL_item not in matchL:
						matchL.append(matchL_item)
								# Еще могут быть дубликаты с темже crc32 и разными 'id_album' поэтому надо дополнить matchL значиниями из списка дубликатов
					else:
						print(b[2])
			if i%1000 == 0:
				print('%i[%i]'%(i,len(matchL)), end=' ')	
			i+=1		
			
		print()				
		print("Converded and Decoded:",len(matchL))
		print("Media dirs found:",len(pathD))
		time_stop_diff = int(time.time()-t_2)	
		print()
		print('Finished in %i sec.'%(time_stop_diff))
		
		
		return {"erL":erL,"er_tb_deleteL":er_tb_deleteL,'convL':convL,'matchL':matchL,'dublicatL':dublicatL,'pathD':pathD,'check_cue':check_cue,'er_artistL':er_artistL}	
	
	if fs_folderL != []:
		print("3. DB and FS track names matching at %i folders..."%(len(fs_folderL)))
		i = 0
		fileL = []
		for a in fs_folderL:
			t_3 = time.time()
			
			real_fs_file_path = ''
			real_fs_file_pathL = []
			is_media = False
			
			
			real_fs_folder_path = join(a[0],a[1])
			crc32_real_fs_path = zlib.crc32(real_fs_folder_path.encode(BASE_ENCODING))
			if crc32_real_fs_path not in pathD:
				pathD[crc32_real_fs_path] = []
				if os.path.exists(real_fs_folder_path):
					fileL = scandir.listdir(real_fs_folder_path)
					is_media = False
					for file_name in fileL:
						for frm in ['.mp3','.ape','.flac']:
							if frm in file_name.lower():
								is_media = True
								pathD[crc32_real_fs_path].append(join(real_fs_folder_path,file_name))
					
					if not is_media:
						i+=1
						continue
					
				else:
					i+=1
					continue
					
			
			#print real_fs_folder_path
			for b in convL:
			
				dir_name = os.path.dirname(b[2].decode('cp1251'))
				
				if dir_name != real_fs_folder_path:
					continue
						
					# Not CUE scenario
				for real_fs_file_path in pathD[crc32_real_fs_path]:
					db_fs_folder_file_path = b[2].decode('cp1251')
				
					if real_fs_file_path == db_fs_folder_file_path:
						crc32_1 = zlib.crc32(db_fs_folder_file_path.encode(BASE_ENCODING))
				
						#print "*",
						matchL_item = {'new_crc32':crc32_1,'old_crc32':b[1],'new_path':db_fs_folder_file_path,'id_track': b[0]}
						if matchL_item not in matchL:
							matchL.append({'new_crc32':crc32_1,'old_crc32':b[1],'new_path':db_fs_folder_file_path,'id_track': b[0]})
								# Еще могут быть дубликаты с темже crc32 и разными 'id_album' поэтому надо дополнить matchL значиниями из списка дубликатов
						else:
							print(b[2])
		
			if i%100 == 0:
				print('%i[%i]'%(i,len(matchL)), end=' ')
				if i%1000 == 0:
					time_stop_diff = int(time.time()-t_3)
					print('Passed %i sec. len matchL: %i, pathD:%i'%(time_stop_diff,len(matchL),len(pathD)))	
				
				#print [real_fs_folder_path], type(real_fs_folder_path)
				#print [db_fs_folder_path], type(db_fs_folder_path)
			i+=1
		time_stop_diff = int(time.time()-t_2)	
		print()
		print('Finished in %i sec.'%(time_stop_diff))
		
	print("Matching found:",len(matchL))
	print("Matching media dirs found:",len(pathD))
		
	return {"erL":erL,"er_tb_deleteL":er_tb_deleteL,'convL':convL,'matchL':matchL,'dublicatL':dublicatL,'pathD':pathD,'check_cue':check_cue}	
		

def check_medialib_ALBUM_utf8_issue(fs_folderL,erL,*args):
	# Сценарий миграции БД таблицы ALBUM на unicode: формирования списка пересчета CRC32 на основе пересчета CRC32 для путей в unicode
	dbPath = cfgD['dbPath']
	t_start = time.time()
	# таблица ALBUM (пока только эта таблица) - собираем все CRC32 для путей из БД
	req = "select path_crc32, id_album  from ALBUM"
	db_ALBUM_pathL = db_request_wrapper(None,req)
	
	convL = []
	dublicatL = []
	er_tb_deleteL = []
	i = 0
	if erL == []:
		print("1. MediaLib db scanning...")
		db = sqlite3.connect(dbPath)	
		
		for a in db_ALBUM_pathL:
			if i%1000 == 0:
				print(i, end=' ')
			i+=1
			# Get single ALBUM entry via path_crc32
			r = getFolderAlbumD_fromDB(None,db,a[0],[],'folder_tree_nodes')
			# отбираем записи где появилась ошибка преобразования unicode связанная path
			if 'error_message' in r:
				#print '*',
				if a[0] not in erL:
					erL.append(a[0])
				else:
					# в процессе добавления альбомов появились дубликаты. Из-за некорректного алгоритма добавления
					# Дубликаты надо собрать и исправить отдельно в БД 
					dublicatL.append((a[0],a[1]))	
					#print '=',
		db.close()			
		print()		
		print("		MediaLib containes UTF8 decoding issues:",len(erL))	
		print("		MediaLib Album containes dublicates (dublicatL):",len(dublicatL))	
	
	time_stop_diff = int(time.time()-t_start)
	print('Finished DB scanning in %i sec.'%(time_stop_diff))
	# check path existence for failed path_crc32
	print()
	print("2. Checking path existence for failed path_crc32 from erL:",len(erL))
	i = 0
	t_2 = time.time()
	
	db = sqlite3.connect(dbPath)	
	c = db.cursor()	
	# !! Первый проход с подключением к бд с db.text_factory = str -> флаг 'no_utf8'
	if 'no_utf8' in args:
		print(' db.text_factory = str --> Activated')
		db.text_factory = str	
	else:
		print(' db.text_factory = Default')
	req = "select id_album, path, path_crc32 from ALBUM where path_crc32 in (%s)"%(str(erL)[1:-1])
	try:
		c.execute(req)
	except Exception as e:
		print(e)	
		
	try:	
		r = c.fetchall()	
	except Exception as e:
		print(e)	
		
	#print 'Pathes for erL retrieved in %i sec'%(int(time.time()-t_2)) 
	
	t_2 = time.time()
	for req_res_item in r:
		#print 'dublicat',req_res_item
		try:
			album_path = req_res_item[1]
		except	Exception as e:
			print(e)
			print('Error: request res: %s, req: %s'%(str(r),str(req)))
			return {"erL":erL,"er_tb_deleteL":er_tb_deleteL,'convL':convL,'matchL':[]} 
		if not os.path.exists(album_path):
			er_tb_deleteL.append((req_res_item[2],req_res_item[1],req_res_item[0]))
		else:
			convL.append((req_res_item[2],req_res_item[1],req_res_item[0]))
		if i%100 == 0:
			print(i, end=' ')
		i+=1	
	
	print()		
	print("		Media lib album not exists and to be deleted issues:",len(er_tb_deleteL))	
	print("		Media lib album to be matched and ajusted (convL):",len(convL))	
	
	c.close()			
	db.close()
	time_stop_diff = int(time.time()-t_2)
	print('Finished conversionL generation in %i sec.'%(time_stop_diff))
	
	if set(erL) == set([a[0] for a in er_tb_deleteL]):
		print('2.1 Success: erL  is in sync with er_tb_deleteL')
	else:
		print('2.1 Issue: erL  is NOT in sync with er_tb_deleteL')
		#print set(erL)
		#print set([a[0] for a in er_tb_deleteL])
	# delete from ALBUM, TRACK
	
	ignL = [a[0] for a in er_tb_deleteL]
	
	
	# match DB path and file system folder path	
	t_2 = time.time()
	matchL = []
	
	if 'fast_convL_processing' in args:
		print('fast_convL_processing is on') 
		print("3. DB folders names converted only at convL:%i..."%(len(convL)))
		i = 0
		t_2 = time.time()
		for b in convL:	
			db_fs_folder_path = b[1].decode('cp1251')
			crc32_2 = zlib.crc32(db_fs_folder_path.encode(BASE_ENCODING))
			matchL_item = {'new_crc32':crc32_2,'old_crc32':b[0],'new_path':db_fs_folder_path,'id_album': b[2]}
			if matchL_item not in matchL:
				matchL.append({'new_crc32':crc32_2,'old_crc32':b[0],'new_path':db_fs_folder_path,'id_album': b[2]})
				# Еще могут быть дубликаты с темже crc32 и разными 'id_album' поэтому надо дополнить matchL значиниями из списка дубликатов
				convL_found = True	
	
			if i%1000 == 0:
				print('%i[%i]'%(i,len(matchL)), end=' ')
			i+=1	
					
		
		time_stop_diff = int(time.time()-t_2)	
	
		print()
		print('Finished with fast mode in %i sec.'%(time_stop_diff))	
		print("Matching found:",len(matchL))
		return {"erL":erL,"er_tb_deleteL":er_tb_deleteL,'convL':convL,'matchL':matchL,'dublicatL':dublicatL}
	
	
	
	
	if fs_folderL != []:
		print("3. DB and FS folders names matching...")
		i = 0
		for a in fs_folderL:
			real_fs_folder_path = join(a[0],a[1])

			#print real_fs_folder_path
			convL_found = False
			for b in convL:
				db_fs_folder_path = b[1].decode('cp1251')
				
				if real_fs_folder_path == db_fs_folder_path:
					crc32_1 = zlib.crc32(real_fs_folder_path.encode(BASE_ENCODING))
					crc32_2 = zlib.crc32(db_fs_folder_path.encode(BASE_ENCODING))
					#print "*",
					matchL_item = {'new_crc32':crc32_1,'old_crc32':b[0],'new_path':db_fs_folder_path,'id_album': b[2]}
					if matchL_item not in matchL:
						matchL.append({'new_crc32':crc32_1,'old_crc32':b[0],'new_path':db_fs_folder_path,'id_album': b[2]})
						# Еще могут быть дубликаты с темже crc32 и разными 'id_album' поэтому надо дополнить matchL значиниями из списка дубликатов
						convL_found = True	
			
			# На всякий случай проверка, что хоть что-то нашли	
			#if not convL_found:			
			#	print '-',		
			#	pass
			#else:	
			#	print '+',		
				
			if i%1000 == 0:
				print('%i[%i]'%(i,len(matchL)), end=' ')
				#print [real_fs_folder_path], type(real_fs_folder_path)
				#print [db_fs_folder_path], type(db_fs_folder_path)
			i+=1	
					
		
		time_stop_diff = int(time.time()-t_2)	
		print()
		print('Finished in %i sec.'%(time_stop_diff))	
		print("Matching found:",len(matchL))
	return {"erL":erL,"er_tb_deleteL":er_tb_deleteL,'convL':convL,'matchL':matchL,'dublicatL':dublicatL}
	
def mass_album_track_artist_table_update_path_crc32_ajust(matchL,mode):
	# Функция исправления БД таблиц(ALBUM,..) на основании списка matchL
	# matchL[{'new_crc32':crc32_1,'old_crc32':b[0],'new_path':db_fs_folder_path,'id_album': b[2]},]
	# resBuf_ml_folder_tree_buf_path = cfgD['ml_folder_tree_buf_path']
	# f = open(resBuf_ml_folder_tree_buf_path,'r')
	# Obj = pickle.load(f)
	
	#res = myMediaLib_tools.check_medialib_utf8_issue(Obj['folder_list'],[])
	#ss = myMediaLib_tools.mass_album_table_update_path_crc32_ajust(res['matchL'])
	#>>> f = open(resDBS['resBuf_save'],'r')
	#>>> Obj = pickle.load(f)
	#>>> f.close()
	#>>> r.keys()
	t_2 = time.time()
	dbPath = cfgD['dbPath']
	db = sqlite3.connect(dbPath)
	requestD = {}
	if mode.lower() == 'album'  or mode.lower() == 'album_crc32':
		mode_dif = 100
		requestD['album'] = {'cursor':db.cursor(),'req':''}
		requestD['album_cat_rel'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_album_ref'] = {'cursor':db.cursor(),'req':''}
		requestD['album_reference'] = {'cursor':db.cursor(),'req':''}
		requestD['album_reference_2'] = {'cursor':db.cursor(),'req':''}
		requestD['track'] = {'cursor':db.cursor(),'req':''}
	elif mode.lower() == 'artist' or mode.lower() == 'artist_crc32':	
		mode_dif = 100
		requestD['artist'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_album_ref'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_cat_rel'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_reference'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_reference_2'] = {'cursor':db.cursor(),'req':''}
		requestD['track'] = {'cursor':db.cursor(),'req':''}
			
	elif mode.lower() == 'track' or mode.lower() == 'track_crc32':
		
		mode_dif = 1000
		requestD['track'] = {'cursor':db.cursor(),'req':''}
		requestD['track_tag'] = {'cursor':db.cursor(),'req':''}
		
		if mode.lower() == 'track':
			requestD['track_title'] = {'cursor':db.cursor(),'req':''}

		
	i=0
	resL=[]
	reqL = []
	res = ''
	print('matchL:',len(matchL))
	for a in matchL:
		# update ALBUM
		if mode.lower() == 'album' or mode.lower() == 'album_crc32':
			if mode.lower() == 'album':
				rec_m = (a['new_path'],a['new_crc32'],a['id_album'])
				requestD['album']['req'] = """update album set path = "%s", path_crc32 = %s where id_album = %s"""%rec_m
			
			if mode.lower() == 'album_crc32':
				rec_m = (a['new_crc32'],a['id_album'])
				requestD['album']['req'] = """update album set path_crc32 = %s where id_album = %s"""%rec_m
			
			
			# update album_cat_rel
			rec_m = (a['new_crc32'],a['id_album'])
			requestD['album_cat_rel']['req'] = """update album_cat_rel set album_crc32 = %s where id_album = %s"""%rec_m
			#reqL.append(req)
			
			# update artist_album_ref
			requestD['artist_album_ref']['req'] = """update artist_album_ref set album_crc32 = %s where id_album = %s"""%rec_m
			#reqL.append(req)
			
			# update ALBUM_REFERENCE
			requestD['album_reference']['req'] = """update ALBUM_REFERENCE set album_crc32 = %s where id_album = %s"""%rec_m
			#reqL.append(req)
			requestD['album_reference_2']['req'] = """update ALBUM_REFERENCE set album_crc32_ref = %s where id_album_ref = %s"""%rec_m
			#reqL.append(req)
			
			rec_m = (a['new_crc32'],a['old_crc32'])
			requestD['track']['req'] = """update track set album_crc32 = %s where album_crc32 = %s"""%rec_m
		
		elif mode.lower() == 'artist' or mode.lower() == 'artist_crc32':
			if mode.lower() == 'artist':
				rec_m = (a['new_crc32'],a['id_artist'])
				requestD['artist']['req'] = """update artist set artist_crc32 = %s where id_artist = %s"""%rec_m
			
			if mode.lower() == 'artist_crc32':
				rec_m = (a['new_crc32'],a['id_artist'])
				requestD['artist']['req'] = """update artist set artist_crc32 = %s where id_artist = %s"""%rec_m
			
			
			# update artist_cat_rel
			rec_m = (a['new_crc32'],a['id_artist'])
			requestD['artist_cat_rel']['req'] = """update artist_cat_rel set artist_crc32 = %s where id_artist = %s"""%rec_m
			#reqL.append(req)
			
			# update artist_album_ref
			requestD['artist_album_ref']['req'] = """update artist_album_ref set artist_crc32 = %s where id_artist = %s"""%rec_m
			#reqL.append(req)
			
			rec_m = (a['new_crc32'],a['old_crc32'])
			# update artist_REFERENCE
			requestD['artist_reference']['req'] = """update artist_REFERENCE set artist_crc32 = %s where artist_crc32 = %s"""%rec_m
			#reqL.append(req)
			requestD['artist_reference_2']['req'] = """update artist_REFERENCE set ref_artist_crc32 = %s where ref_artist_crc32 = %s"""%rec_m
			#reqL.append(req)
			
			rec_m = (a['new_crc32'],a['old_crc32'])
			requestD['track']['req'] = """update track set artist_crc32 = %s where artist_crc32 = %s"""%rec_m
		
		elif mode.lower() == 'track' or mode.lower() == 'track_crc32':
			if mode.lower() == 'track':
				if a['new_cue_fname'] == None:
					rec_m = (a['new_path'],a['new_crc32'],a['id_track'])
					requestD['track']['req'] = """update track set path = "%s", path_crc32 = %s  where id_track = %s"""%rec_m
				else:
					rec_m = (a['new_path'],a['new_crc32'],a['new_cue_fname'],a['id_track'])
					requestD['track']['req'] = """update track set path = "%s", path_crc32 = %s, cue_fname = "%s" where id_track = %s"""%rec_m
					
				
				if a['new_title'] != None:
					rec_m = (a['new_title'],a['id_track'])
					requestD['track_title']['req'] = """update track set title = "%s" where id_track = %s"""%rec_m
			elif mode.lower() == 'track_crc32':		
				rec_m = (a['new_crc32'],a['id_track'])
				requestD['track']['req'] = """update track set path_crc32 = %s  where id_track = %s"""%rec_m
			
			rec_m = (a['new_crc32'],a['id_track'])
			requestD['track_tag']['req'] = """update track_tag set path_crc32 = %s where id_track = %s"""%rec_m	
			
				
			
				
		#reqL.append(req)
		
		for tabl_key in requestD:
			try:
				requestD[tabl_key]['cursor'].execute(requestD[tabl_key]['req'])
				#res = c.fetchall()
			except Exception as e:
				print('\n',e,'\n')
				print(requestD[tabl_key]['req'])
				for tabl_key in requestD:
					requestD[tabl_key]['cursor'].close()
				db.close()				
				logger.critical('Exception: %s'%(str(e)))
				return res
				
		#res = c.fetchall()
		#resL.append(res)	
				
		if i%mode_dif == 0:
			print(i, end=' ')
			
		i+=1
	for tabl_key in requestD:
		requestD[tabl_key]['cursor'].close()
	
	db.commit()
	db.close()	
	time_stop_diff = int(time.time()-t_2)
	print()
	print('Finished in %i sec.'%(time_stop_diff))	
	return resL
	
def mass_album_track_table_delete_path_not_existed(del_path_crc32L,mode,*args):
	#del_path_crc32L-album_item->(path_crc32,path,id_album)
	#res = myMediaLib_tools.check_medialib_utf8_issue(Obj['folder_list'],[])
	#ss = myMediaLib_tools.mass_album_table_update_path_crc32_ajust(res['matchL'])
	#>>> f = open(resDBS['resBuf_save'],'r')
	#>>> r = pickle.load(f)
	#>>> f.close()
	#>>> r.keys()
	
	dbPath = cfgD['dbPath']
	db = sqlite3.connect(dbPath)
	requestD = {}
	if mode.lower() == 'album':
		requestD['album'] = {'cursor':db.cursor(),'req':''}
		requestD['album_cat_rel'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_album_ref'] = {'cursor':db.cursor(),'req':''}
		requestD['album_reference'] = {'cursor':db.cursor(),'req':''}
		requestD['album_reference_2'] = {'cursor':db.cursor(),'req':''}
		requestD['track'] = {'cursor':db.cursor(),'req':''}
	elif mode.lower() == 'artist':	
		requestD['artist'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_album_ref'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_cat_rel'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_reference'] = {'cursor':db.cursor(),'req':''}
		requestD['artist_reference_2'] = {'cursor':db.cursor(),'req':''}
		requestD['track'] = {'cursor':db.cursor(),'req':''}
		
	elif mode.lower() == 'track':
		requestD['track'] = {'cursor':db.cursor(),'req':''}
		requestD['track_tag'] = {'cursor':db.cursor(),'req':''}
		
	i=0
	resL=[]
	reqL = []
	res = ''
	for a in del_path_crc32L:
		# delete from ALBUM
		if mode.lower() == 'album':	
			requestD['album']['req'] = """delete from album where id_album = %s"""%(a[2])
			
			# delete from album_cat_rel
			requestD['album_cat_rel']['req'] = """delete from album_cat_rel where id_album = %s"""%(a[2])
			
			# delete from artist_album_ref
			requestD['artist_album_ref']['req'] = """delete from artist_album_ref  where id_album = %s"""%(a[2])
			#reqL.append(req)
			
			# delete from  ALBUM_REFERENCE
			requestD['album_reference']['req'] = """delete from  ALBUM_REFERENCE where id_album = %s"""%(a[2])
			
			requestD['album_reference_2']['req'] = """delete from ALBUM_REFERENCE  where id_album_ref = %s"""%(a[2])
			#reqL.append(req)
			
			requestD['track']['req'] = """delete from track where album_crc32 = %s"""%(a[0])
			
			
			#reqL.append(req)
		elif mode.lower() == 'artist':	
			requestD['artist']['req'] = """delete from artist where id_artist = %s"""%(a[0])
			
			requestD['artist_cat_rel']['req'] = """delete from artist_cat_rel where id_artist = %s"""%(a[0])
			
			# delete from artist_album_ref
			requestD['artist_album_ref']['req'] = """delete from artist_album_ref  where id_artist = %s"""%(a[0])
			#reqL.append(req)
			
			# delete from  ARTIST_REFERENCE
			requestD['artist_reference']['req'] = """delete from  ARTIST_REFERENCE where artist_crc32 = %s"""%(a[2])
			
			requestD['artist_reference_2']['req'] = """delete from ARTIST_REFERENCE  where ref_artist_crc32 = %s"""%(a[2])
			#reqL.append(req)
			
			requestD['track']['req'] = """delete from track where artist_crc32 = %s"""%(a[2])
			
			#reqL.append(req)
		elif mode.lower() == 'track':
			
			requestD['track']['req'] = """delete from track where id_track = %s"""%(a[1])
			requestD['track_tag']['req'] = """delete from track_tag where id_track = %s"""%(a[1])
			
		
		for tabl_key in requestD:
			try:
				requestD[tabl_key]['cursor'].execute(requestD[tabl_key]['req'])
				if "res_log" in args:
					resL.append((requestD[tabl_key]['cursor'].rowcount,a,requestD[tabl_key]['req']))
					
				#res = c.fetchall()
			except Exception as e:
				print(e)
				print(requestD[tabl_key]['req'])
				logger.critical('Exception: %s'%(str(e)))
				return res
				
		#res = c.fetchall()
		#resL.append(res)	
				
		if i%10 == 0:
			print(i, end=' ')
			
		i+=1
	for tabl_key in requestD:
		requestD[tabl_key]['cursor'].close()
	
	db.commit()
	db.close()	
	return resL	
	
def unicode_migration_scenario():
	cfgD = readConfigData(mymedialib_cfg)
	resBuf_ml_folder_tree_buf_path = cfgD['ml_folder_tree_buf_path']
	f = open(resBuf_ml_folder_tree_buf_path,'r')
	#Obj = pickle.load(f)
	f.close()
	
	t = time.time()
	check_res_before_migrationD = quick_check_medialib_utf8_issue('with_fetch_detailes')
	print()
	print('*'*50)
	print('Unicode issues ALBUM check')
	print('*'*50)
	
	#res_check_album = check_medialib_ALBUM_utf8_issue(Obj['folder_list'],[],'no_utf8','fast_convL_processing')
	res_check_album = check_medialib_ALBUM_utf8_issue([],[],'no_utf8','fast_convL_processing')
	print('*'*50)
	if res_check_album['er_tb_deleteL'] == []:
		print('Nothing to delete from album')
	else:	
		print('Unicode issues ALBUM not existed delete')
		res_del_albumD   = mass_album_track_table_delete_path_not_existed(res_check_album['er_tb_deleteL'],'album')
		
	print()	
	print('*'*50)	
	if res_check_album['matchL'] == []:	
		print('Nothing to ajust from album')
	else:	
		print('Unicode issues ALBUM ajusting')
		res_ajustD = mass_album_track_artist_table_update_path_crc32_ajust(res_check_album['matchL'],'album')	
	
	# check TRACK
	print('*'*50)
	print('Unicode issues TRACK check')
	print('*'*50)
	res_check_track = check_medialib_TRACK_utf8_issue([],[],'no_utf8','fast_convL_processing')
	print('*'*50)
	if res_check_track['er_tb_deleteL'] == []:
		print('Nothing to delete from track')
	else:	
		print('Unicode issues TRACK not existed delete')
		res_delD = mass_album_track_table_delete_path_not_existed(res_check_track['er_tb_deleteL'],'track')
		
	print()	
	print('*'*50)
	if res_check_track['matchL'] == []:
		print('Nothing to ajust from album')
	else:	
		print('Unicode issues TRACK ajusting')
		res_ajustD = mass_album_track_artist_table_update_path_crc32_ajust(res_check_track['matchL'],'track')	
		
	print('*'*50)	
	print("Ajusting scenario finished in %i sec"%(int(time.time()-t)))
	check_after_migrationD = quick_check_medialib_utf8_issue('with_fetch_detailes')
	
def get_parent_folder_stackL(path,stop_nodeL):
	
	if not os.path.isabs(path):
		return([])	
	nodesL =[]
	
	for a in range(20):
		parent_dir = os.path.dirname(path)
		if path == parent_dir:
			break
		path = parent_dir
		if path in stop_nodeL:
			break
		nodesL.append(path)
	return(nodesL)

def path_to_posix(f_path):
	return Path(f_path).as_posix()

def update_album_track_path(path_conv_func,*args):
	# Фунция для разового вызова изменений path в таблицах ALBUM и TRACK
	# послее ее запуска необходимо пересчитать CRC32 всех объектов через mass_album_track_artist_table_update_path_crc32_ajust
	# tobe_removed_substr = "G:\\MUSIC\\"
	cfgD = readConfigData(mymedialib_cfg)
	dbPath = cfgD['dbPath']
	db = sqlite3.connect(dbPath)
	if "album" in args:
		mode_dif = 100
		i = 0
		l = db_request_wrapper(db,"select id_album, path from album")

		for a in l:
			path_converted = path_conv_func(a[1])
			print(a[1],path_converted)
			if not path_converted:
				if i%mode_dif == 0:
					print("-", end=' ')
				i+=1
				continue
			rec = (path_converted,a[0])
			req = """update album set path = "%s" where id_album = %s"""%rec
			if 'modi' in args:
				db_request_wrapper(db,req,'modi')
		
			if i%mode_dif == 0:
				print(i, end=' ')
			i+=1
		print("Album path is updated")
		
	if "track" in args:
		mode_dif = 1000
		l = db_request_wrapper(db,"select id_track, path, cue_fname from track where path not like '%http%'")
		i = 0
		for a in l:
			if a[2]:
				if '.cue' in a[2].lower():
					path_converted = path_conv_func(a[1])
					path_converted_cue_fname = path_conv_func(a[2])
					if not path_converted  and  not path_converted_cue_fname:
						if i%mode_dif == 0:
							print("-", end=' ')
							i+=1
							continue
					if i%mode_dif == 0:
						print("*", end=' ')
					rec = (path_converted, path_converted_cue_fname,a[0])
					req = """update track set path = "%s", cue_fname = "%s" where id_track = %s"""%rec
					if 'modi' in args:
						db_request_wrapper(db,req,'modi')
			else:
				path_converted = path_conv_func(a[1])
				if not path_converted:
					if i%mode_dif == 0:
						print("-", end=' ')
						i+=1
						continue

				rec = (path_converted,a[0])
				req = """update track set path = "%s" where id_track = %s"""%rec
				if 'modi' in args:
					db_request_wrapper(db,req,'modi')
			if i%mode_dif == 0:
				print(i, end=' ')
			i+=1
		print("track path is updated")
	db.close()
	
def get_not_exists_album_pathL(music_path_root,mode):
	# music_path_root = "\\\\GOFLEX_HOME\\внешняя память\\Seagate\\Music\\"
	cfgD = readConfigData(mymedialib_cfg)
	dbPath = cfgD['dbPath']
	
	mode_dif = 1000
	not_existsL = []
	errorL = []
	t_all_start = time.time()
	if mode.lower() == 'album':
		req = "select id_album, path, path_crc32 from ALBUM where album_type <> 'RADIO'"
	elif mode.lower() == 'track':	
		req = "select id_track, path, path_crc32,  cue_fname,title,artist,cue_num from TRACK where path not like '%http%'"
	db = sqlite3.connect(dbPath)
	resL = db_request_wrapper(db,req)
	db.close()
	i = 0
	for a in resL:
		try:
			if not Path(music_path_root+a[1]).exists():
				not_existsL.append((a[2],a[1],a[0]))
		except Exception as e:
			errorL.append((a,resL.index(a),e))
		if i%mode_dif == 0:
			print(i, '[',len(not_existsL),']', end=' ')
		i+=1
		
	print('track finished in:',int(time.time()-t_all_start))
	return {"not_existsL":not_existsL,"errorL":errorL}
	
def relative_path_migration_scenario(music_path_root):
	# music_path_root = "\\\\GOFLEX_HOME\\внешняя память\\Seagate\\Music\\"
	#matchL[{'new_crc32':crc32_1,'old_crc32':b[0],'new_path':db_fs_folder_path,'id_album': b[2]},]
	match_albumL = []
	match_trackL = []
	res_ajust_albumD = res_ajust_trackD = {}
	
	cfgD = readConfigData(mymedialib_cfg)
	dbPath = cfgD['dbPath']
	
	mode_dif = 1000
	not_existsL = []
	errorL = []
	t_all_start = time.time()
	db = sqlite3.connect(dbPath)
	req = "select id_album, path, path_crc32 from ALBUM where album_type <> 'RADIO'"
	res_albumL = db_request_wrapper(db,req)
	
	print("1. Calculating new album crc32 list")
	i = 0
	
	for a in res_albumL:
		#ниже формула расчета CRC32 для альбома
		crc32_1 = zlib.crc32(a[1].encode(BASE_ENCODING))
		rec = {'new_crc32':crc32_1,'old_crc32':a[2],'id_album': a[0]}

		match_albumL.append(rec)
		if i%mode_dif == 0:
			print(i, end=' ')
		i+=1
	print()
	print("2. Updating album crc32 DB")
	res_ajust_albumD = mass_album_track_artist_table_update_path_crc32_ajust(match_albumL,"album_crc32")
		
	print('Album finished in:',int(time.time()-t_all_start))
		
	#	return {"match_trackL":match_trackL,"match_albumL":match_albumL,'res_ajust_albumD':res_ajust_albumD}
	print()
	print("2. Calculating new track crc32 list")
	t_all_start = time.time()
	
	req = "select id_track, path, path_crc32, cue_num from TRACK where path not like '%http%'"
	res_trackL = db_request_wrapper(db,req)
	db.close()
	
	mode_dif = 10000
	i = 0
	cue_cnt = 0
	for a in res_trackL:
		if a[3]:
			#ниже формула расчета CRC32 для трэка с CUE
			crc32_1 = zlib.crc32((a[1]+str(a[3])).encode(BASE_ENCODING))
			cue_cnt+=1
		else:
			#ниже формула расчета CRC32 для просто трэка в формате ape,flac,mp3
			crc32_1 = zlib.crc32(a[1].encode(BASE_ENCODING))
			
		rec = {'new_crc32':crc32_1,'old_crc32':a[2],'id_track': a[0]}
		
		match_trackL.append(rec)
		if i%mode_dif == 0:
			print(i, '[',cue_cnt,']', end=' ')
		i+=1
	
	print()
	print("2. Updating track crc32 DB")
	res_ajust_trackD = mass_album_track_artist_table_update_path_crc32_ajust(match_trackL,"track_crc32")	
	
	print('track finished in:',int(time.time()-t_all_start))
	return {"match_trackL":match_trackL,"match_albumL":match_albumL,'res_ajust_albumD':res_ajust_albumD,'res_ajust_trackD':res_ajust_trackD}
	
def remove_not_exists_objects_from_DB(music_path_root):
	# сценарий удаление объектов с путями к несуществующим медиа объектам. идем от альбомов и всех связанных с ними объектов, затем по трэкам
	# часть трэков удаляется по связи с альбомами, остальная напрямую в таблице трэка.
	# music_path_root = "\\\\GOFLEX_HOME\\внешняя память\\Seagate\\Music\\"
	track_substL = []
	print("1. Remooving from album and related tables")
	print()
	print("1.1 Colleacting from albums")
	r_not_exists_albumD = get_not_exists_album_pathL(music_path_root,'album')
	print("1.2 Remooving from albums, expected:%s"%str(len(r_not_exists_albumD['not_existsL'])))
	r_albumL = mass_album_track_table_delete_path_not_existed(r_not_exists_albumD['not_existsL'],'album',"res_log")
	
	print()
	print("Not deleted from track referencing from album: %s"%(str(len([a for a in r_albumL if 'delete from track ' in a[2] and a[0] == 0]))))
	print()
	print("2. Remooving from track and related tables")
	
	
	
	print()
	print("2.1 Colleacting trom tracks")
	r_not_existsD = get_not_exists_album_pathL(music_path_root,'track')
	
	print()
	print("2.2 Remooving from tracks, expected:%s"%str(len(r_not_existsD['not_existsL'])))
	for a in r_not_existsD['not_existsL']:
		track_substL.append((a[0],a[2]))
	r_trackL = mass_album_track_table_delete_path_not_existed(track_substL,'track',"res_log")
	
	return {"r_not_exists_albumD":r_not_exists_albumD,"r_not_existsD":r_not_existsD,'r_albumL':r_albumL,'r_trackL':r_trackL} 
	
def is_discId_release_in_FP_response(discId_MB_resp,acoustId_resp):
	recordingsL = []
	release_groupL = []
	releasesL = []
	mediumDL = []
	if 'disc' not in discId_MB_resp:
		print('Error key [disc] is missing in:',discId_MB_resp)
		return False
	releasesL_discId = [a['release-group']['id'] for a in discId_MB_resp['disc']['release-list']]
	if 'results' not in acoustId_resp:
		print('Error in:',acoustId_resp)
		return False

	releasesL_FP = collect_MB_release_from_FP_response(acoustId_resp)['release_groupL']
	#print('discId:',releasesL_discId)
	#print('FP:',releasesL_FP)
	
	for a in releasesL_discId:
		if a in releasesL_FP:
			return True
	return 	False	
	
def match_discId_release_in_FP_response(discId_MB_resp,acoustId_resp,Release_ReleaseGroupD):
	recordingsL = []
	
	release_groupL_FP = releases_FP = releases_discId = release_groupL_discId = []
	mediumDL = []
	release_groupL_discId = [a['release-group']['id'] for a in discId_MB_resp['disc']['release-list']]
	releases_discId = [a['id'] for a in discId_MB_resp['disc']['release-list']]
	
	if 'results' not in acoustId_resp:
		print('Error in:',acoustId_resp)
		return False
	release_groupL_FP = collect_MB_release_from_FP_response(acoustId_resp)['release_groupL']
	releases_FP = collect_MB_release_from_FP_response(acoustId_resp)['releasesL']
	#print('discId:',releasesL_discId)
	#print('FP:',releasesL_FP)
	
	for a in release_groupL_discId:
		if a in release_groupL_FP and a not in Release_ReleaseGroupD['release-group']:
			Release_ReleaseGroupD['release-group'].append(a)		
			
	for a in releases_discId:
		if a in releases_FP and a not in Release_ReleaseGroupD['release-list']:
			Release_ReleaseGroupD['release-list'].append(a)		
			
	return 	{'release-list':Release_ReleaseGroupD['release-list'],'release-group':Release_ReleaseGroupD['release-group']}

def build_FP_db_tracks_record(fpDL):
	# база FP - будет основой формирования метаданных медиатеки. формируется полностью автоматически, с возможностью добавления набора альбомов или единичных #альбомов. 
	# содержит статистику покрытия FP, discId, положительными резульатами запросов по FP к musicbrainz содержит ссылки по CRC32 на рабочую medialib.db3
	# даст оценку доли автоматического и ручного ведения метаданных для рабочей medialib.db3
	# должна содержать на начальном этапе потрэковую информацию "recording", альбомную "releases", артистов, работы "works"
	# подготовка записи в базе FP для последующего сохранения в БД
	# учитывать полное или частичное отсутствие FP для трэка - это позволит иметь статистику покрытия медиа коллекции FP, делать регулярный повторный расчет,
	# иметь снимок всей медиатеки
	for item in fpDL:
		if item['scenarioD']['cue_state']['only_tracks_wo_CUE']:
			for track in 'normal_trackL':
				pass
	return db_record	

def album_FP_discid_response_validate(fpDL):
	# валидация ответов MB и acoustId (далее просто ответы MB) для собранных потрэково и поальбомно acousticId fingerprints и discid
	# задача, по набору FP и discID однозначно идентифицироваь релиз. Чем больше критериев валидации исполнено, тем выше вероятность праильной идентификации
	# релиза альбома. наличие discID упрощает выбор правильного релиза. Если его нет, необходимо идентифицировать релиз только на основании набора FP всех трэков альбома.
	# когда нет данных  по discID или они не достоверны?: TOC не сформирован, ТОС не идентифицируется в ответе MB, результаты по TOC не совпдадают с результатами FP (различные релизы)
	# сценарии валидации:
	# 1. все FP трэков принадлежат одному релизу по этому релизу совпадает количество трэков в ответе MB = > альбом - accepted
	## 1.1для очень коротких трэков <20 сек acoustId не дает разультата. такой трэк надо просто пропустить. не считая его за ошибку. 
	## 1.2совпадение может быть только по части трэков. для остальной части FP не идентифицируется на сервисе, возможно некорректное формирование FP локально, что становиться критичным для коротких трэков.
	## 1.3возможны ошибки при получении результата, в этом случае отфильтровав по коду ошибки, заново запросить результат для FP
	# 2. при наличии TOC и положительной его идентификации соотв. релиз совпадает с результатами соотв. релизов по FP трэков. при наличии нескольких релизов связанных с FP трэков, момогает идентифицировать правильный релиз. Если релиз всего один и он совпал по всем FP и discId => альбом strongly accepted 
	# discId релиз
	index = 0
	release_id_checkL = []
	Release_ReleaseGroupD = {'release-list':[],'release-group':[]}
	ReleaseGroupL = []
	not_confirmed_cnt = confirmed_cnt = partly_confirmed_cnt = partly_fp_confirmed_cnt = hi_res_cnt = failed_cnt = 0
	
	for item in fpDL:
		Release_ReleaseGroupD = {'release-list':[],'release-group':[]}
		print('\n',index, '  ========== %s'%(item['album_path'] ))
		if 'convDL' not in item:
			print('Hi-res proc issue')
			hi_res_cnt +=1
			failed_cnt+=1
			index+=1
			continue
		
		
		#release_id = check_album_from_acoustId_resp_list(item['convDL'],len(item['convDL']))['release_id']
		#print('release_id:',release_id)
		# scenario without discId
		if 'MB_discID' not in item:
			print('i', end=' ')
			print('Error (2138) with fpDL index:',index,item['album_path'])
			return
			
		if item['MB_discID']:
			print('==== MB_discID scenario:')
			track_index = 1
			in_MB_discID_cnt = 0
			for trac_data in item['convDL']:
				if is_discId_release_in_FP_response(item['MB_discID'], trac_data['response']):
					print('*',end=' ')
					Release_ReleaseGroupD = match_discId_release_in_FP_response(item['MB_discID'], trac_data['response'],Release_ReleaseGroupD)
					in_MB_discID_cnt +=1
				else:
					if trac_data['fp'][0] < 20:
						print('\n very short track %i:[%i]sec'%(track_index,int(trac_data['fp'][0])))
					elif 'error' in trac_data['response']:
						print('\n with MB_discID scenario issue in track %i: FP service return error. Recall FP response'%(track_index))
					elif trac_data['response']['results'] == []:	
						print('\n with MB_discID scenario issue in track %i: FP service result is empty. Recalculate and recheck FP'%(track_index))
				
				try:	
					recordinds = collect_MB_release_from_FP_response( trac_data['response'])['recordingsL']		
					print('Recording id:',recordinds)
				except Exception as e:
					print('Error in recording extraction',str(e))

				track_index+=1	
			if in_MB_discID_cnt == len(item['convDL']):
				print('MB_discID and FP results successuly validated')
				confirmed_cnt+=1
				
			if in_MB_discID_cnt < len(item['convDL']) and in_MB_discID_cnt > 0:
				print('MB_discID and FP results only partly [%i of %i] validated'%(in_MB_discID_cnt,len(item['convDL'])))
				partly_confirmed_cnt+=1	
			elif in_MB_discID_cnt == 0:
				not_confirmed_cnt+=1
				
		else:
			print('		==== Only FP scenario:')
			release_id_checkL = []
			
			for trac_data in item['convDL']:
				release_id = get_release_from_acoustId_resp_list_via_track_number(item['convDL'],len(item['convDL']))
				if not release_id:
				#	failed_cnt+=1
					continue
					
				release_id_checkL.append(release_id)
				try:	
					recordinds = collect_MB_release_from_FP_response( trac_data['response'])['recordingsL']		
					print('Recording id:',recordinds)
				except Exception as e:
					print('Error in recording extraction',str(e))	
					
			if 	len(release_id_checkL) == len(item['convDL']) and len(list(set(release_id_checkL))) == 1:	
				print('		release from MB resp:', set(release_id_checkL))
				confirmed_cnt+=1
				Release_ReleaseGroupD['release-list'] = set(release_id_checkL).pop()
			elif len(release_id_checkL) != len(item['convDL']) and len(list(set(release_id_checkL))) > 1:
				print('		Wrong release from MB resp:',set(release_id_checkL))
				partly_fp_confirmed_cnt+=1
				Release_ReleaseGroupD['release-list'] = set(release_id_checkL).pop()
				#for trac_data in item['convDL']:
				#	return collect_MB_release_from_FP_response(trac_data['response'])
			else:
				failed_cnt+=1
		item['ReleasesD'] = Release_ReleaseGroupD		
		print('ReleasesD:',Release_ReleaseGroupD)
		index+=1			
	print('Confirmed: %i, Partly_confirmed: %i, Partly fp confirmed:%i, Total confirmed: %i, Failed %i'%(confirmed_cnt,partly_confirmed_cnt,partly_fp_confirmed_cnt,confirmed_cnt+partly_confirmed_cnt+partly_fp_confirmed_cnt,failed_cnt))	
	print('hi_res issue:',hi_res_cnt)
	print('Not confirmed:',not_confirmed_cnt)
	
	return release_id_checkL
	
def collect_MB_release_from_FP_response(acoustId_resp):
	recordingsL = []
	release_groupL = []
	releasesL = []
	mediumDL = []
	release_id = 0
	if 'results' not in acoustId_resp and 'error' in acoustId_resp:
		print('Error in response')
		return{'recordingsL':recordingsL,'release_groupL':release_groupL,'releasesL':releasesL,'mediumDL':mediumDL,'error':acoustId_resp['error']}
	for res_item in acoustId_resp['results']:
		if 'recordings' not in res_item:
			continue
		for rcrds in res_item['recordings']:
			if 'id' not in rcrds:
				#print('Error in FP response rec id',rcrds)
				return{'recordingsL':recordingsL,'release_groupL':release_groupL,'releasesL':releasesL,'mediumDL':mediumDL}
			#else:	
			recordingsL.append(rcrds['id'])
			#yield rcrds['id']
			if 'releasegroups' in rcrds:
				
				for rel_group in rcrds['releasegroups']:
					##if 'id' not in rel_group:
					#	print('Error in FP response rel_group id',rel_group)
					#	continue
					#else:	
					release_groupL.append(rel_group['id'])
					

					for release in rel_group['releases']:
						#if 'id' not in release:
						#	print('Error in FP response release id',release)
						#	continue
						#else:	
						releasesL.append(release['id'])
						
						for medium in release['mediums']:
							#print(medium)
							#if 'id' not in medium:
							#	print('Error in FP response medium id',medium)
							#	continue
							#else:	
							medium['release_id'] = release['id']
							#if track_num:
							#if medium['track_count'] == track_num:
							#		return{'recordingsL':recordingsL,'release_groupL':release_groupL,'releasesL':releasesL,'mediumDL':mediumDL,'release_id':release['id']}
								
							mediumDL.append(medium)


	return{'recordingsL':recordingsL,'release_groupL':release_groupL,'releasesL':releasesL,'mediumDL':mediumDL}
	
def get_release_from_acoustId_resp_list_via_track_number(acoustId_respL,track_number):
	
	try:

		mediumDL_List = [collect_MB_release_from_FP_response(a['response'])['mediumDL'] for a in acoustId_respL]
		for c in [b for b in mediumDL_List if b != []]:
			return set(e['release_id'] for e in c if e['track_count'] == track_number ).pop() 
		
	except Exception as e:
		
		print('error in get_release_from_acoustId_resp_list_via_track_number [%s]'%str(e))
			
	return 
		
def acoustID_lookup_celery_wrapper(self,*fp_args):
	scoreL = fp_item = []
	err_cnt = 0
	
	print('fp:',fp_args)
	API_KEY = 'cSpUJKpD'
	meta = ["recordings","recordingids","releases","releaseids","releasegroups","releasegroupids", "tracks", "compress", "usermeta", "sources"]
	response=acoustid.lookup(API_KEY, fp_args[1], fp_args[0],meta)
	print(response)
	
	# if 'error' in response:
		# err_cnt+=1
	# else:
		# if 'results' in response:
			# l = [item['score'] for item in response['results']  if 'score' in item]
			# if l != []:
				# scoreL.append(max(l))
	# if response == {'results': [], 'status': 'ok'}:
		# duration_init = fp_args[0]
		# fp_item = list(fp_args)
		# print('\n Empty FP response. duration [%s], trying to guess duration'%str(duration_init))
		# for i in range(1,10):
			# fp_item[0] = fp_item[0] - i
			# response=acoustid.lookup(API_KEY, fp_item[1], fp_item[0],meta)
			# if response != {'results': [], 'status': 'ok'}:
				# if 'results' in response:
					# print('Succeceed with duration:',fp_item['fp'][0])
					# l = [item['score'] for item in response['results']  if 'score' in item]
					# if l != []:
						# scoreL.append(max(l))
						
					# break
		# if response == {'results': [], 'status': 'ok'}:		
			# fp_item['fp'][0] = duration_init
					
		# fp_item['response'] = response
	
	
	
	
	
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

if __name__ == '__main__':
	import argparse
	job_list = []
	parser = argparse.ArgumentParser(description='media lib tools')
	parser.add_argument('ml_folder_tree', metavar='saves medialib folders as pickled object, taking the path from config',
                        help='ml_folder_tree')	
	args = parser.parse_args()	
	
	cfg_fp.read(medialib_fp_cfg)
	nas_path_prefix = cfg_fp['FOLDERS']['nas_path_prefix']
	ml_folder_tree_buf_path = cfg_fp['FOLDERS']['ml_folder_tree_buf_path']
	audio_files_path_list = cfg_fp['FOLDERS']['audio_files_path_list']
	
	dirL = json.loads(cfg_fp.get('FOLDERS',"audio_files_path_list"))
	
	creation_time = time.time()
	#res = bulld_subfolders_list(None,dirL,'verbose')
	folders_list_obj = find_new_music_folder_simple(None,dirL)
	print()
	print('Passed:', time.time()-creation_time)
	try:
		with open(ml_folder_tree_buf_path, 'wb') as f:
			d = pickle.dump({'folder_list':folders_list_obj['folder_list'],'NewFolderL':folders_list_obj['NewFolderL'],'music_folderL':folders_list_obj['music_folderL'],'creation_time':creation_time},f)
	except Exception as e:
		print('Error in pickle',e)				
	
	