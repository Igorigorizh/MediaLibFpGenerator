import sys
#windows path trick
sys.path.insert(0,'./medialib')
from myMediaLib_CONST import medialib_fp_cfg
from configparser import ConfigParser

from redis import Redis
from rq import Queue, Worker

import myMediaLib_scheduler
import pickle
from time import sleep, time

import os

#dump_path = b'//192.168.1.66/OMVNasUsb/MUSIC/ORIGINAL_MUSIC/ORIGINAL_EASY/Los Incas - El Condor Pasa (1985)/fpgen_1652531874.dump'

from myMediaLib_CONST import BASE_ENCODING
from myMediaLib_CONST import mymedialib_cfg


from configparser import ConfigParser

import warnings
from myMediaLib_tools import get_FP_and_discID_for_album
from myMediaLib_tools import find_new_music_folder
from myMediaLib_tools import redis_state_notifier

from rq.job import Job
from functools import wraps


cfg_fp = ConfigParser()
cfg_fp.read(medialib_fp_cfg)


#redis_connection = Redis(host=cfg_fp['REDIS']['host'], port=cfg_fp['REDIS']['port'], db=0)
redis_connection = Redis(host='192.168.1.65', port=cfg_fp['REDIS']['port'], db=0)
q = Queue(connection=redis_connection,job_timeout=500,description='audio_folders_generation')

def wrap_queue(f):
    @wraps(f)
    def newqueue(*args, **kwargs):
        jobs = [a for a in args if isinstance(a, Job)] + [v for v in kwargs.values() if isinstance(v, Job)]
        args = [f"_reserved_{a.id}" if isinstance(a, Job) else a for a in args]
        kwargs = {k:f"_reserved_{v.id}" if isinstance(v, Job) else v for k,v in kwargs.items()}
        kwargs["depends_on"] = kwargs.get("depends_on", []) + jobs
        return f(*args, **kwargs)
    return newqueue
	
#new_enqueue = wrap_queue(q.enqueue)	

if __name__ == '__main__':
	import argparse
	job_list = []
	#parser = argparse.ArgumentParser(description='Create a ArcHydro schema')
	#parser.add_argument('--nas_path_prefix', metavar='path', required=True,
        #                help='nas path prefix like //192.168.1.12/folderUSB')	
	#args = parser.parse_args()
	nas_path_prefix = "//RPI-NAS-OMV/OMVNasUSB"
	nas_path_prefix = "/home/medialib/MediaLibManager/music"
	#path_cl = bytes(nas_path_prefix,'utf-8')+b'/MUSIC/ORIGINAL_MUSIC/ORIGINAL_RODINA/'	
	path_cl = bytes(nas_path_prefix,'utf-8')+b'/MUSIC/ORIGINAL_MUSIC/ORIGINAL_CLASSICAL/Vivaldi/Antonio Vivaldi - 19 Sinfonias and Concertos for Strings and Continuo/'	
	dump_path = bytes('//192.168.1.66/OMVNasUsb/MUSIC/ORIGINAL_MUSIC/ORIGINAL_RODINA/Федор Чистяков/2008 - Ноль - Лучшие песни/fpgen_1652646620.dump','utf-8')
	#with open(dump_path, 'rb') as f:
	#	sD_prev = pickle.load(f)
	
		#sD = myMediaLib_tools.do_mass_album_FP_and_AccId(path_cl,0,sD_prev['fpDL'],sD_prev['music_folderL'],'multy','FP','ACOUSTID_FP_REQ','MB_DISCID_REQ')
	#job_first = new_enqueue(myMediaLib_scheduler.music_folders_generation_scheduler, path_cl, [], [])
	job_first = q.enqueue(myMediaLib_scheduler.music_folders_generation_scheduler, path_cl, [], [])
	while not job_first.result:
		sleep(.1)
			
	print(job_first.result) 
	folderL = job_first.result
		#folderL = myMediaLib_scheduler.music_folders_generation_scheduler(path_cl,[],[])
	redis_state_notifier('medialib-job-fp-albums-total-progress','init')	
	for folder_name in folderL:
		#job = new_enqueue(myMediaLib_scheduler.get_FP_and_discID_for_album, folder_name, 0, 'multy', 'FP', 'ACOUSTID_FP_REQ', 'MB_DISCID_REQ',job_timeout='1h')
		job = q.enqueue(myMediaLib_scheduler.get_FP_and_discID_for_album, folder_name, 0, 'multy', 'FP', 'ACOUSTID_FP_REQ', 'MB_DISCID_REQ',job_timeout='1h')
		job_list.append(job)
	start_time = time()
	for job in job_list:	
		album_time = time()
		while not job.result:
			print('Album:',redis_connection.get('medialib-job-fp-albums-total-progress'), '  Tracks:',redis_connection.get('medialib-job-fp-album-progress'), 'Album passed:',int(time()-album_time),'Total passed:',int(time()-start_time))
			sleep(5)
			
		if 	job.is_finished:	
			print("job.finished",job.id,'RC:',job.result['RC'],'keys:',job.result.keys())				
		elif job.is_failed:	
			print("job.failed",job.id)
		else:
			print("job.other status",job.id,'res:',job.result)
		#sD = myMediaLib_scheduler.mass_FP_scheduler(folderL,0,'multy','FP','ACOUSTID_FP_REQ','MB_DISCID_REQ')
	
	#else:
	#	print('path failed')
	
	while input('type exit >>>') != 'exit': pass
		