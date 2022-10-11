import sys
sys.path.insert(0, 'C:/My_projects/medialib/MediaLibManager/medialib')
print(sys.path)
from configparser import ConfigParser
from redis import Redis
from rq import Queue, Worker
#from myMediaLib_CONST import medialib_fp_cfg
from time import sleep, time
from configparser import ConfigParser

#cfg_fp = ConfigParser()
#cfg_fp.read(medialib_fp_cfg)

import warnings
#from myMediaLib_tools import get_FP_and_discID_for_album
#from myMediaLib_tools import find_new_music_folder
#from myMediaLib_tools import redis_state_notifier

#redis_connection = Redis(host='192.168.1.65', port=cfg_fp['REDIS']['port'], db=0)
redis_connection = Redis(host='192.168.1.65', port='6379', db=0)
q = Queue(connection=redis_connection,job_timeout=500,description='audio_folders_generation')

def job_create(path):
	job_list = []
	job_first = q.enqueue('myMediaLib_scheduler.music_folders_generation_scheduler', path, [], [])
	while not job_first.result:
		sleep(.1)
	job_list.append(job_first)
	print(job_first.result) 
	folderL = job_first.result
	job =''
	for folder_name in folderL:
		#job = new_enqueue(myMediaLib_scheduler.get_FP_and_discID_for_album, folder_name, 0, 'multy', 'FP', 'ACOUSTID_FP_REQ', 'MB_DISCID_REQ',job_timeout='1h')
		job = q.enqueue('myMediaLib_scheduler.get_FP_and_discID_for_album', folder_name, 0, 'multy', 'FP', 'ACOUSTID_FP_REQ', 'MB_DISCID_REQ',job_timeout='1h')
		if job:
			job_list.append(job)

	return job_list	