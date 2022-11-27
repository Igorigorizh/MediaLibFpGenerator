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

from medialib.myMediaLib_fs_util import Media_FileSystem_Helper as mfsh
find_new_music_folder = mfsh().find_new_music_folder
find_new_music_folder_simple = mfsh().find_new_music_folder_simple

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

#redis_connection = Redis(host=cfg_fp['REDIS']['host'], port=cfg_fp['REDIS']['port'], db=0)

posix_nice_value = int(cfg_fp['FP_PROCESS']['posix_nice_value'])


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
# def get_FP_and_discID_for_album(self, album_path,fp_min_duration,cpu_reduce_num,*args):
	# hi_res = False
	# scenarioD = detect_cue_FP_scenario(album_path,*args)
	# print('Self:',type(self))

	# TOC_dataD = get_TOC_from_log(album_path)
	
	# guess_TOC_dataD = {}
	# if TOC_dataD['TOC_dataL']:
		# print("Log TOC is here!:", TOC_dataD['toc_string'])
	# else:
		# print("No Log TOC detected")
	# cueD = {}	
	# paramsL = []	
	# result = b''
	# convDL = []
	# prog = b''
	# MB_discID_result = ''		
	# API_KEY = 'cSpUJKpD'
	# meta = ["recordings","recordingids","releases","releaseids","releasegroups","releasegroupids", "tracks", "compress", "usermeta", "sources"]	
	# discID = log_discID = ''
	# if os.name == 'nt':
		# prog = b'ffmpeg.exe'
	# elif os.name == 'posix':
		# prog = b'ffmpeg'
	# t_all_start = time.time()
	# failed_fpL=[]
	# if 0 <= cpu_reduce_num < cpu_count():
		# cpu_num = cpu_count()-cpu_reduce_num
	# else:
		# cpu_reduce_num = 1
		# print("Wrong CPU reduce provided, changed to ",cpu_reduce_num)
		# cpu_num = cpu_count()-cpu_reduce_num
	# #redis_state_notifier('medialib-job-fp-albums-total-progress','progress')
	# #redis_state_notifier('medialib-job-fp-album-progress','init')
	
	# if scenarioD['cue_state']['single_image_CUE']:
		# print("\n\n-------FP generation for CUE scenario:  single_image_CUE-----------")
		# try:
			# print("Full cue parsing")
			# cueD = parseCue(scenarioD['cueD']['cue_file_name'],'with_bitrate')
		# except Exception as e:
				# print(e)
				# return {'RC':-1,'cueD':cueD}	
		# if 'multy' in args and ('FP' in  args or 'split_only_keep' in args):
			# print('--MULTY processing of FP --- on [%i] CPU Threads'%(cpu_num))
			# image_name = cueD['orig_file_pathL'][0]['orig_file_path']
			
			# command_ffmpeg = b'ffmpeg -y -i "%b" -t %.3f -ss %.3f "%b"'
			
			# # Get 4 iterators for image name,  total_sec, start_sec, temp_file_name
			# iter_image_name_1 = iter(image_name for i in range(len(cueD['trackD'])))
			# iter_params = iter(args for i in range(len(cueD['trackD'])))
			# iter_dest_tmp_name_4 = iter(join(album_path,b'temp%i.wav'%(num))  for num in cueD['trackD'])
			# #iter_dest_tmp_name_4 = iter(b'temp%i.wav'%(num)  for num in cueD['trackD'])
			# iter_dest_tmp_name_4, iter_dest_tmp_name = tee(iter_dest_tmp_name_4)
			# iter_start_sec_3 = iter(cueD['trackD'][num]['start_in_sec']  for num in cueD['trackD'])
			# if fp_min_duration > 10:
				# iter_total_sec_2 = iter(fp_time_cut(cueD['trackD'][num]['total_in_sec'],fp_min_duration)	for num in cueD['trackD'])
				# iter_total_sec_orig = iter(float('%.1f'%cueD['trackD'][num]['total_in_sec'])  for num in cueD['trackD'])
				# # get iterator for ffmpeg command
				# iter_command_ffmpeg = map(lambda x: command_ffmpeg%x,zip(iter_image_name_1,iter_total_sec_2,iter_start_sec_3,iter_dest_tmp_name_4))
			# else:
				# iter_total_sec_2 = iter(cueD['trackD'][num]['total_in_sec']  for num in cueD['trackD'])
				# # get iterator for ffmpeg command
				# iter_command_ffmpeg = map(lambda x: command_ffmpeg%x,zip(iter_image_name_1,iter_total_sec_2,iter_start_sec_3,iter_dest_tmp_name_4 ))
			
			
			# res = ''
			# if self:
				# progress_recorder = ProgressRecorder(self)
				# progress_recorder_descr = 'medialib-job-folder-FP-album:'+str(album_path)
				# progress_recorder.set_progress(0, len(cueD['trackD']), description=progress_recorder_descr)

			# start_t = time.time()
			# try:
				# with Pool(cpu_num) as p:
					# res = p.starmap_async(worker_ffmpeg_and_fingerprint, zip(iter_command_ffmpeg,iter_dest_tmp_name,iter_params,)).get()
			# except Exception as e:
				# print("Caught exception in map_async 1",str(e))
				# return {'RC':-1,'cueD':cueD}
				# #p.terminate()
			# #	p.join()
			# p.join()	
			# print('\n -----  album splite FP calc processing finished in [%i]sec'%(time.time()-start_t))
			# try:
				# if fp_min_duration > 10:
					# convDL_iter = zip(iter_total_sec_orig, res)
					# #a[1]:(fp,f_name,failed_fpL)
					# convDL = [{'fname':a[1][1],'fp':(a[0],a[1][0][1])} for a in convDL_iter]
				# else:
					# convDL = [{'fname':a[1],'fp':a[0]} for a in res]
					
				# failed_fpL = [a[2] for a in res if a[2] != []]
			# except Exception as e:
				# print('Error ar async get:',str(e))
				# convDL = []
				# failed_fpL = []
				
			
		# else:
			# cnt=1
			# image_name = cueD['orig_file_pathL'][0]['orig_file_path']
			# for num in cueD['trackD']:
				# new_name = b'temp%i.wav'%(cnt)
				# start_sec = int(cueD['trackD'][num]['start_in_sec'])
				# total_sec = int(cueD['trackD'][num]['total_in_sec'])
				# if 'FP' in  args:
					# print("Track extact from from:",image_name,start_sec, total_sec)	
					# ffmpeg_command = str(b'ffmpeg -y -i "%b" -aframes %i -ss %i "%b"'% (image_name,total_sec,start_sec,join(album_path,new_name)),BASE_ENCODING)
						
					# #b"\""+join(album_path,new_name)+b"\"")
						
					
					# print (ffmpeg_command)
					
					# if prog != '' and ffmpeg_command != ():	
						# try:
							# print("Decompressing partly with:",prog)
							# res = subprocess.Popen(ffmpeg_command, stderr=subprocess.PIPE ,stdout=subprocess.PIPE,shell=True)
							# out, err = res.communicate()
						# except OSError as e:
							# print('get_FP_and_discID_for_cue 232:', e, "-->",prog,ffmpeg_command)
							# return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':num,'errorL':['Error at decocmpression of [%i]'%(int(num))] }
						# except Exception as e:
							# print('Error in get_FP_and_discID_for_cue 235:', e, "-->", prog,ffmpeg_command)
							# return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':num,'errorL':['Error at decocmpression of [%i]'%(int(num))]}	
					# else:
						# print('Error in get_FP_and_discID_for_cue 243:', e, "-->", prog,cueD['orig_file_pathL'][0]['orig_file_path'])
						# return{'RC':-1,'cueD':cueD,'TOC_dataD':TOC_dataD,'scenarioD':scenarioD}		
					# fp = []
					# try:
						
						# fp = acoustid.fingerprint_file(str(join(album_path,new_name),BASE_ENCODING))
					# except  Exception as e:
						# print("Error in fp gen with:",new_name,e)
						
						# os.rename(join(album_path,new_name),join(album_path,bytes(str(time.time())+'_failed_','utf-8')+new_name))
						# failed_fpL.append((new_name,e))
						# cnt+=1
						# continue
						# #result = result + str(a,BASE_ENCODING) + str(fp)+"\n"
					# #result = result + a + bytes(str(fp),BASE_ENCODING)+b'\n'
					
					# convDL.append({"fname":new_name,"fp":fp})
					# print("*", end=' ')
				
					# os.remove(join(album_path,new_name))
					# cnt+=1
					
					
					# if self:
						# progress_recorder = ProgressRecorder(self)
						# progress_recorder_descr = 'medialib-job-folder-FP-album:'+str(album_path)
						# progress_recorder.set_progress(0, len(cueD['trackD']), description=progress_recorder_descr)
	# elif scenarioD['cue_state']['multy_tracs_CUE']:
		# print("\n\n FP generation for CUE scenario:  multy_tracs_CUE")
		# try:
			# print("Full cue parsing")
			# cueD = parseCue(scenarioD['cueD']['cue_file_name'],'with_bitrate')
		# except Exception as e:
				# print(e)
				# return {'RC':-1,'cueD':cueD}	
		# cnt=1
		
		# if 'multy' in args and 'FP' in  args:
			# #print('--MULTY---:',list(map(lambda x: str(join(album_path,x),BASE_ENCODING),scenarioD['normal_trackL'])))
			
			# print('--MULTY processing of FP --- on [%i] CPU Threads'%(cpu_num))
			
			
			# try:
				# with Pool(cpu_num) as p:
					# res = p.map_async(worker_fingerprint, [a['orig_file_path'] for a in cueD['orig_file_pathL']]).get()
					
			# except Exception as e:
				# print("Caught exception in map_async 2",e)
				# return {'RC':-1,'cueD':cueD}	
			# #	p.join()
			# p.join()	
			# #print(res)
			# #return res
			# try:	
				# convDL = [{'fname':a[1],'fp':a[0]} for a in res]
			# except Exception as e:
				# print('Error:',str(e))	
		# else:
			# for track_item in cueD['orig_file_pathL']:
				# track = track_item['orig_file_path']
				# if 'FP' in  args:
					# fp = []
					# try:
						# fp = acoustid.fingerprint_file(track)
					# except  Exception as e:
						# print("Error in fp gen with:",track)
						# continue
						# #result = result + str(a,BASE_ENCODING) + str(fp)+"\n"
					# #result = result + a + bytes(str(fp),BASE_ENCODING)+b'\n'
					
					# convDL.append({"fname":os.path.basename(track),"fp":fp})
					# print("*", end=' ')
		
		
	# elif scenarioD['cue_state']['only_tracks_wo_CUE']:
		# print("\n\n FP generation for scenario only_tracks_wo_CUE")	
		# scenarioD['normal_trackL'].sort()
		# trackL = []
		# for a in scenarioD['normal_trackL']:
			# trackL.append(str(album_path,BASE_ENCODING)+str(a,BASE_ENCODING))
		
		# try:	
			# guess_TOC_dataD = guess_TOC_from_tracks_list(trackL)
		# except Exception as e:
			# print('Error in guess_TOC_from_tracks_list:',e)	
		
		# sample_rate = guess_TOC_dataD['trackDL'][0]['sample_rate']
		# if sample_rate > 44100:
			# print('------------HI-RES check scenario details------------')
			# hi_res = True	
		
		# if 'multy' in args and 'FP' in  args:
			# #print('--MULTY---:',list(map(lambda x: str(join(album_path,x),BASE_ENCODING),scenarioD['normal_trackL'])))
			# print('--MULTY processing of FP --- on [%i] CPU Threads'%(cpu_num))
			
			
			# try:
				# with Pool(cpu_num) as p:
					# res = p.map_async(worker_fingerprint, list(map(lambda x: str(join(album_path,x),BASE_ENCODING),scenarioD['normal_trackL']))).get()
					
			# except Exception as e:
				# print("Caught exception in map_async 3",e)
				# return {'RC':-2,'normal_trackL':scenarioD['normal_trackL']}
				# #p.terminate()
			# #	p.join()
			# p.join()	
			# try:	
				# convDL = [{'fname':a[1],'fp':a[0]} for a in res]
			# except Exception as e:
				# print('Error:',str(e))	
				
				
			# if self:
				# progress_recorder = ProgressRecorder(self)
				# progress_recorder_descr = 'medialib-job-folder-FP-album:'+str(album_path)
				# progress_recorder.set_progress(0, len(trackL), description=progress_recorder_descr)	
		# else:
			# for track in  scenarioD['normal_trackL']:
				# fp = []
				# if 'FP' in  args:	
					# try:
						# fp = acoustid.fingerprint_file(str(join(album_path,track),BASE_ENCODING))
					# except  Exception as e:
						# print("Error in fp gen with:",track)
						# continue
							# #result = result + str(a,BASE_ENCODING) + str(fp)+"\n"
						# #result = result + a + bytes(str(fp),BASE_ENCODING)+b'\n'
					
					# convDL.append({"fname":track,"fp":fp})
					# print("*", end=' ')
					
					# if self:
						# progress_recorder = ProgressRecorder(self)
						# progress_recorder_descr = 'medialib-job-folder-FP-album:'+str(album_path)
						# progress_recorder.set_progress(0, len(cueD['trackD']), description=progress_recorder_descr)
		
			
	# time_stop_diff = time.time()-t_all_start	
	# if 'FP' in  args: 
		# print("\n********** Album FP takes:%i sec.***********************"%(int(time_stop_diff)))
		
	# #redis_state_notifier('medialib-job-fp-album-progress','progress-stop')
	
				
	# time_ACOUSTID_FP_REQ = time.time()
	# if 'ACOUSTID_FP_REQ' in args and 'LOCAL' in args:
		# print("\n Getting Album ACOUSTID_FP_REQ from https://acoustid.org/ **********************")
		# err_cnt = 0
		# scoreL = []
		# for fp_item in convDL: 	
			# response=asyncio.run(acoustID_lookup_wrapper_parent(fp_item['fp']))
			# #response = acoustid.lookup(API_KEY, fp_item['fp'][1], fp_item['fp'][0],meta)
			# if 'error' in response:
				# err_cnt+=1
			# else:
				# if 'results' in response:
					# l = [item['score'] for item in response['results']  if 'score' in item]
					# if l != []:
						# scoreL.append(max(l))
			# if response == {'results': [], 'status': 'ok'}:
				# duration_init = fp_item['fp'][0]
				# fp_item['fp'] = list(fp_item['fp'])
				# print('\n Empty FP response. duration [%s], trying to guess duration'%str(duration_init))
				# for i in range(1,10):
					# fp_item['fp'][0] = fp_item['fp'][0] - i
					# response=asyncio.run(acoustID_lookup_wrapper_parent(fp_item['fp']))
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
			
		# if err_cnt > 0 and err_cnt < len(convDL):
			# print('Errors %i in responses from %i'%(err_cnt,len(convDL)))
			# for fp_item in convDL: 	
				# if 'error' in fp_item['response']:
					# response=asyncio.run(acoustID_lookup_wrapper_parent(fp_item['fp']))
					# if 'error' not in  response:
						# fp_item['response'] = response
						# print('No more error in response %i'%(convDL.index(fp_item)))
						# if 'results' in response:
							# l = [item['score'] for item in response['results']  if 'score' in item]
							# if l != []:
								# scoreL.append(max(l))
					# else:
						# print('Error 2-nd time in response %i'%(convDL.index(fp_item)))
		# if 	convDL:			
			# if len(scoreL) == len(convDL):
				# print('FP score rate:',sum(scoreL)/len(convDL))
			# elif len(scoreL) < len(convDL) and len(scoreL) > 0:
				# print('FP score rate with skipped FP:',sum(scoreL)/len(scoreL),'%i of %i'%(len(scoreL),len(convDL)))
			# else:	
				# print('Wrong FP scoreL:',scoreL)
		# else:
			# print("Error: convDL is empty")
			
	
		# print("********** Album ACOUSTID_FP_REQ request takes:%i sec.***********************"%(int(time.time() - time_ACOUSTID_FP_REQ )))		
	
	# # Выделеить в отдельную функцию
	# TOC_src = ''
	
	# time_discid_MB_REQ = time.time()
	# if scenarioD['cue_state']['only_tracks_wo_CUE']:
		# print("Try guess TOC from tracks list")	
		# try:
			# discID = discid.put(guess_TOC_dataD['discidInput']['First_Track'],guess_TOC_dataD['discidInput']['Last_Track'],guess_TOC_dataD['discidInput']['total_lead_off'],guess_TOC_dataD['discidInput']['offsetL'])
			# print('Guess Toc:',discID.toc_string)
			# TOC_src = 'guess'
			# print("discId from guess - is OK")	
		# except Exception as e:
			# print("Issue with Guess TOC")
			# print(e)
	# else:
		# print("Try TOC from CUE")	
		# try:
			# discID = discid.put(1,cueD['cue_tracks_number'],cueD['lead_out_track_offset'],cueD['offsetL'])
			# print('Cue TOC:',discID.toc_string)
		# except Exception as e:
			# if 'offsetL' not in cueD: 
				# print('offsetL is missing in cueD')
			# else:	
				# print("Issue with CUE TOC len(offsetL)",len(cueD['offsetL']))
			# print(e)
	
	# if TOC_dataD['discidInput'] and discID:
		# if TOC_dataD['toc_string'] == discID.toc_string:
			# TOC_src = 'cue'
			# print("TOCs log and cue are identical")
		# else:
			# print("TOCs log and cue are NOT identical")
			# print((TOC_dataD['toc_string']))
			# TOC_src = 'log'
			# print((discID.toc_string))	
		
	# if TOC_dataD['discidInput']:
		# print("Try TOC from log")
		# try:
			# log_discID = discid.put(TOC_dataD['discidInput']['First_Track'],TOC_dataD['discidInput']['Last_Track'],TOC_dataD['discidInput']['total_lead_off'],TOC_dataD['discidInput']['offsetL'])
			# print('Log Toc:',log_discID.toc_string)
			# print("discId from log is taken for MB request")	
		# except Exception as e:
			# print("Issue with Log TOC")
			# print(e)
			
	# if log_discID:
		# discID = log_discID

	# if 'MB_DISCID_REQ' in args:	
		# if discID:
			
			# try:
				# MB_discID_result = musicbrainzngs.get_releases_by_discid(discID,includes=["artists","recordings","release-groups"])
			# except Exception as e:
				# print(e)
			# if 'disc' in MB_discID_result:	
				# print("DiskID MB - OK", MB_discID_result['disc']['id'],TOC_src) 	
				# MB_discID_result['TOC_src'] = TOC_src
			# else:
				# print("DiskID MB - NOT detected") 	
				
			# print("********** Album MB_DISCID_REQ MusicBrainz request takes:%i sec.***********************"%(int(time.time() - time_discid_MB_REQ )))		
	
	# print("********** Album process in total takes:%i sec.***********************"%(int(time.time() - t_all_start )))
	
	# return{'RC':len(convDL),'cueD':cueD,'TOC_dataD':TOC_dataD,'scenarioD':scenarioD,'MB_discID':MB_discID_result,'convDL':convDL,'discID':str(discID),'failed_fpL':failed_fpL,'guess_TOC_dataD':guess_TOC_dataD,'hi_res':hi_res,'album_path':album_path,'TOC_src':TOC_src}
# def fp_time_cut(x,cut_sec):
	# if x > cut_sec:
		# return cut_sec
	# else:
		# return x

# #@JobInternalStateRedisKeeper(state_name='medialib-job-fp-album-progress',action='progress')		
# def worker_ffmpeg_and_fingerprint(ffmpeg_command, new_name, *args):
	# #command template b'ffmpeg -y -i "%b" -aframes %i -ss %i "%b"'( new_name )
	# failed_fpL = []
	# #print('in worker')				
	# f_name = os.path.basename(new_name)			
	# #print (ffmpeg_command)
	# prog = 'ffmpeg'				
	
	# #redis_state_notifier(state_name='medialib-job-fp-album-progress',action='progress')
	# #print("Worker before ffmmeg pid:",os.getpid())
	# if os.name == 'posix':
		# try:
			# nice_value = os.nice(posix_nice_value)	
		# except Exception as e:
			# print('Error in nice:',e)
	
	# try:
		# #print("Decompressing partly with:",prog)
		# res = subprocess.Popen(ffmpeg_command.decode(), stderr=subprocess.PIPE ,stdout=subprocess.PIPE,shell=True)
		# out, err = res.communicate()
	# except OSError as e:
		# print('get_FP_and_discID_for_cue 232:', e, "-->",prog,ffmpeg_command)
		# return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':num,'errorL':['Error at decompression of [%i]'%(int(num))] }
	# except Exception as e:
		# print('Error in get_FP_and_discID_for_cue 235:', e, "-->", prog,ffmpeg_command)
		# return {'RC':-1,'f_numb':0,'orig_cue_title_numb':0,'title_numb':num,'errorL':['Error at decompression of [%i]'%(int(num))]}
	
	# fp = []
	# #print("+", end=' ')
	
	# if len(args)>0:
		# if 'split_only_keep' in args[0]:
			# return (fp,f_name,failed_fpL)	
	
	# try:
		
		# fp = acoustid.fingerprint_file(str(new_name,BASE_ENCODING))
	# except  Exception as e:
		# print("Error in fp gen with:",new_name,e)
		# print('ffmpeg command:',ffmpeg_command)
		# f_name = os.path.basename(new_name)
		# os.rename(new_name,new_name.replace(f_name,bytes(str(time.time()).replace('.','_'),BASE_ENCODING)+f_name))
		# failed_fpL.append((new_name,e))

	# #print("*", end=' ')
		
	# os.remove(new_name)	
	
	# return (fp,f_name,failed_fpL)
	
# #@JobInternalStateRedisKeeper(state_name='medialib-job-fp-album-progress',action='progress')	
# def worker_fingerprint(file_path):
	# print("Worker acoustid.fingerprint pid:",os.getpid())
	# #redis_state_notifier(state_name='medialib-job-fp-album-progress',action='progress')
	
	# if os.name == 'posix':
		# try:
			# nice_value = os.nice(posix_nice_value)	
		# except Exception as e:
			# print('Error in nice:',e)
		
	# try:
		# fp = acoustid.fingerprint_file(file_path)
	# except  Exception as e:
		# print("Error [%s] in fp gen with:"%(str(e)),file_path)
		# return ((),os.path.split(file_path)[-1])
	# #print(fp[0],os.path.split(file_path)[-1])	

	# return (fp,os.path.split(file_path)[-1])	
	



# def guess_TOC_from_tracks_list(tracksL):
	# track_offset_cnt = 0
	# total_track_sectors = 0
	# first_track_offset = 150
	# pregap = 0
	# offset_mediaL = []
	# discidInputD = {}
	# next_frame = 0
	# trackDL = []
	# print('in guess_TOC_from_tracks_list')
	# track_num = 0
	# for track in tracksL:
		
		# fType = os.path.splitext(track)[1][1:]
		# try:
			# trackD = GetTrackInfoVia_ext(track,fType)
		# except Exception as e:
			# print('Error in guess_TOC_from_tracks_list:',e)
			# print('No TOC calculation possible')
			# return{'TOC_dataL':[],'discidInput':{},'toc_string':''}
		# full_length = trackD['full_length']
		
		# total_track_sectors = total_track_sectors + int(full_length *75)+1
		# if track_num == 0:
			# offset_mediaL.append(first_track_offset + pregap)	
			# next_frame = total_track_sectors - track_offset_cnt - pregap + first_track_offset - 1	
		# else:
			# offset_mediaL.append(next_frame)
		# #print('Sector:',next_frame)	
		# next_frame = total_track_sectors - track_offset_cnt - pregap + first_track_offset - 1		
		# track_offset_cnt+=1	
		# track_num +=1
		# trackDL.append(trackD)
		
		
	# lead_out_track_offset=next_frame	
	# toc_string = 	''		
	# if offset_mediaL:
		# discidInputD = {'First_Track':1,'Last_Track':len(tracksL),'offsetL':offset_mediaL,'total_lead_off':lead_out_track_offset}
		# toc_string = '%s %s %s %s'	%(discidInputD['First_Track'],discidInputD['Last_Track'],discidInputD['total_lead_off'],str(discidInputD['offsetL'])[1:-1].replace(',',''))
	
	# return{'discidInput':discidInputD,'toc_string':toc_string,'trackDL':trackDL}	
	
# def get_TOC_from_log(album_folder):
	# files = os.listdir(album_folder)
	# logs = [f for f in files if os.path.splitext(f)[1] == b'.log']
	# logs.sort()
	# TOC_dataL = []
	# discidInputD = {}
	# TOC_lineD= {}
	# for f in logs:
		# print(f)
		# # detect file character encoding
		# with open(os.path.join(album_folder,f),'rb') as fh:
			# d = chardet.universaldetector.UniversalDetector()
			# for line in fh.readlines():
				# d.feed(line)
			# d.close()
			# encoding = d.result['encoding']
			# print(encoding)
		# with codecs.open( os.path.join(album_folder,f),'rb', encoding=encoding) as fh:
			# lines = fh.readlines()
			# regex = re.compile(r'^\s+[0-9]+\s+\|.+\|\s+(.+)\s+\|\s+[0-9]+\s+|\s+[0-9]+\s+$')
			
		# matches = [tl for tl in map(regex.match,lines) if tl]

		# if matches:
			# start_offset = 150
			# offsetL = []
			# for tl in matches:
			     # TOC_line = tl.string.split('|')
			     # TOC_lineD = {'Track':int(TOC_line[0]),'Start':TOC_line[1],'Length':TOC_line[2],'Start_Sector':int(TOC_line[3]),'End_Sector':int(TOC_line[4])}
			     # TOC_dataL.append(TOC_lineD)
			     # offsetL.append(start_offset+int(TOC_line[3]))
			# break
	# toc_string = 	''		
	# if TOC_dataL:
		# discidInputD = {'First_Track':TOC_dataL[0]['Track'],'Last_Track':TOC_dataL[-1]['Track'],'offsetL':offsetL,'total_lead_off':1+start_offset+int(TOC_lineD['End_Sector'])}
		# toc_string = '%s %s %s %s'	%(discidInputD['First_Track'],discidInputD['Last_Track'],discidInputD['total_lead_off'],str(discidInputD['offsetL'])[1:-1].replace(',',''))
	# return{'TOC_dataL':TOC_dataL,'discidInput':discidInputD,'toc_string':toc_string}
	
		
	
		
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

			
	
	