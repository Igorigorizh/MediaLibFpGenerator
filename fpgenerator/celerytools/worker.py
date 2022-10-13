import os
import time
import functools
import acoustid
import base64

from celery import Celery
from celery import group
from celery_progress.backend import ProgressRecorder

from fpgenerator.scheduler import music_folders_generation_scheduler
from fpgenerator.tools import get_FP_and_discID_for_album
from fpgenerator.tools import acoustID_lookup_celery_wrapper
from fpgenerator.tools import MB_get_releases_by_discid_celery_wrapper
from fpgenerator.tools import find_new_music_folder

app = Celery(__name__)
app.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379")
app.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379")
app.conf.imports = 'fpgenerator'
app.conf.task_serializer = 'pickle'
app.conf.result_serializer = 'pickle'
app.conf.accept_content = ['application/json', 'application/x-python-serialize']

@app.task(name="hello")
def hello():
	time.sleep(10)
	print("Hello there")
	return True
	

def base64_convert(func):
	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		val = func(*args, **kwargs)
		if type(val) == list:
			val = [base64.b64encode(a) for a in val]
		elif type(val) == bytes:
			val = base64.b64encode(val)
		elif type(val) == dict:
			val = [base64.b64encode(val[a]) for a in val]
		return val
	return wrapper	

	

	
#music_folders_generation_scheduler = app.task(name='music_folders_generation_scheduler-new_recogn_name',serializer='json',bind=True)(base64_convert(music_folders_generation_scheduler))
music_folders_generation_scheduler = app.task(name='music_folders_generation_scheduler-new_recogn_name',serializer='json',bind=True)(music_folders_generation_scheduler)


find_new_music_folder = app.task(name='find_new_music_folder-new_recogn_name',serializer='json',bind=True)(find_new_music_folder)

	

@app.task(name="worker.callback_acoustID_request")
def callback_acoustID_request(result):
	#acoustID.lookup(apikey, fingerprint, duration)
	API_KEY = 'cSpUJKpD'
	meta = ["recordings","recordingids","releases","releaseids","releasegroups","releasegroupids", "tracks", "compress", "usermeta", "sources"]
	reqL = []
	print('try acoustId call')
	if 'convDL' not in result:
		return {'RC':-4}
	for fp_item in result['convDL']:
		print('fp item fp:',fp_item['fp'],fp_item['fname'])
		wrapper_args = (fp_item['fp'][0],fp_item['fp'][1],fp_item['fname'],result['album_path'])
		response = app.send_task('acoustID_lookup_celery_wrapper',(wrapper_args))
		print('acoustId call:',response)	
		
	print('acoustId call - OK')	
	return result['convDL']
	
@app.task(name="worker.callback_MB_get_releases_by_discid_request")
def callback_MB_get_releases_by_discid_request(result):
	if 'discID' not in result:
		return {'RC':-4}
		
	wrapper_args = ((result['discID'],))	
	response = app.send_task('MB_get_releases_by_discid_celery_wrapper',(wrapper_args))
	print('MB call:',response)
	return response	

@app.task(name="worker.callback_FP_gen")
def callback_FP_gen(result):
	folderL = result
	#applicable  only for cue image scenario
	for folder_name in folderL:
		task_fp_res = app.send_task('get_FP_and_discID_for_album',(folder_name, 0, 1, 'multy', 'FP'), link=fp_post_processing_req)

		


get_FP_and_discID_for_album = app.task(name='get_FP_and_discID_for_album',bind=True)(get_FP_and_discID_for_album)
acoustID_lookup_celery_wrapper = app.task(name='acoustID_lookup_celery_wrapper',bind=True)(acoustID_lookup_celery_wrapper)
MB_get_releases_by_discid_celery_wrapper = app.task(name='MB_get_releases_by_discid_celery_wrapper',bind=True)(MB_get_releases_by_discid_celery_wrapper)	

fp_post_processing_req = group(callback_MB_get_releases_by_discid_request.s(), callback_acoustID_request.s())

def fp_multy_scheduler(app, path):
	task_list = []
	task_first_res = app.send_task('music_folders_generation_scheduler-new_recogn_name',(p2,[],[]))
	

if __name__ == '__main__':
	app.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://192.168.1.65:6379")
	app.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://192.168.1.65:6379")
	app.control.purge()
	#acoustID_lookup_celery_wrapper(1,2)
	#exit(1)
	task_list = []
	p3 = '/home/medialib/MediaLibManager/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_CLASSICAL/LArpeggiata - Christina Pluhar'
	p4 = '/home/medialib/MediaLibManager/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_ROCK/Pink Floyd/1983 Pink Floyd - The Final Cut'
	p5 = '/home/medialib/MediaLibManager/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_ROCK/Pink Floyd/_HI_RES/1975 - Wish You Were Here (SACD-R)'
	p2 = '/home/medialib/MediaLibManager/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_CLASSICAL/Vivaldi/Antonio Vivaldi - 19 Sinfonias and Concertos for Strings and Continuo/'
	p6 = '/home/medialib/MediaLibManager/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_ROCK/Pink Floyd/Pink Floyd - Dark Side Of The Moon (1973) [MFSL UDCD II 517]/'
	task_first_res = app.send_task('music_folders_generation_scheduler-new_recogn_name',(p3,[],[]),link=callback_FP_gen.s())
	path = '/home/medialib/MediaLibManager/music/MUSIC/ORIGINAL_MUSIC'
	#task_first_res = app.send_task('find_new_music_folder-new_recogn_name',([path],[],[],'initial'))
	#task_folders_list = app.send_task('find_new_music_folder-new_recogn_name',([path],[],[],'initial'),link=callback_find_new_music_folder.s())
	print(task_first_res,type(task_first_res))
	
	


	
	