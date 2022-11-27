import os
import time
import functools
import acoustid


from celery import Celery
from celery import group
from celery import Task
from celery_progress.backend import ProgressRecorder
import sys
print('\n',"in worker: sys_path:",sys.path)

from celerytools.scheduler import CeleryScheduler 
#from celerytools.scheduler import Media_FileSystem_Helper_Progress as mfsh_progress
from celerytools.tools import get_FP_and_discID_for_album
from celerytools.tools import acoustID_lookup_celery_wrapper
from celerytools.tools import MB_get_releases_by_discid_celery_wrapper


from medialib.myMediaLib_fs_util import Media_FileSystem_Helper as mfsh


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
descr = 'medialib-job-folder-scan-progress-media_files'	

class ProgressTask(Task):
	_progress = None
	@property
	def progress(self):
		#if self._progress is None:
		print('in ProgressTask:progress before init')
		self._progress = ProgressRecorder(self)
		print('in ProgressTask:progress after init',self._progress)
		#else:
		#	print('in ProgressTask:progress init strange bevaiour')
		return self._progress
		
from medialib.myMediaLib_fs_util import Media_FileSystem_Helper as mfsh

class Media_FileSystem_Helper_Progress(mfsh):
	def __init__(self):
		super().__init__()
		print(">>>>>>>>>> here construct --------------")
		self.progress_recorder = None
		self.progress_recorder_descr = ""
		self._EXT_CALL_FREQ = 10

	def set_progress_recorder(self,progress_recorder, descr):
		self.progress_recorder = progress_recorder
		self.progress_recorder_descr = descr
		
	def find_new_music_folder(self,*args):
		resL = []
		print('in find_new_music_folder helper progress  args:',args)
		#self.progress_recorder = ProgressRecorder(self)
		print('progress_recorder:',self.progress_recorder,dir(self.progress_recorder))
		if self.progress_recorder:
			self.progress_recorder.set_progress(2, 10, description='medialib-job')
			resL = super().find_new_music_folder(*args)
		return resL
		
	def iterrration_extention_point(self, *args):
		""" iterrration_extention_point redefine with celery progress_recorder"""
		#print('in iterrator:',self.progress_recorder)
		if self._current_iteration%self._EXT_CALL_FREQ == 0 and self.progress_recorder:
			print('in iterrator:',self.progress_recorder,id(self.progress_recorder),self._current_iteration)
			self.progress_recorder.set_progress(self._current_iteration, self._current_iteration+1, description=self.progress_recorder_descr)	

@app.task(base=ProgressTask, name='find_new_music_folder-new_recogn_name',serializer='json',bind=True)
def find_new_music_folder_task(self, *args):
	mfsh_obj = Media_FileSystem_Helper_Progress()
	
	print('duumy check with:',self.progress)
	mfsh_obj.progress_recorder = self.progress
	mfsh_obj.progress_recorder.set_progress(0, 1, description='medialib-job')
	
	print('Do setter cwith:',mfsh_obj.progress_recorder)
	mfsh_obj.set_progress_recorder(self.progress,"medialib-job-folder-scan-progress-media_files")
	mfsh_obj.find_new_music_folder(*args)

#find_new_music_folder = app.task(base=Progress, name='find_new_music_folder-new_recogn_name',serializer='json',bind=True)(Media_FileSystem_Helper_Progress.find_new_music_folder)


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
	# Тут также позже подключить прогресс ддля отслеживание всего прогресса поальбомно
	folderL = result
	#applicable  only for cue image scenario
	for folder_name in folderL:
		task_fp_res = app.send_task('get_FP_and_discID_for_album',(folder_name, 0, 1, 'multy', 'FP'), link=fp_post_processing_req)

		
		
music_folders_generation_scheduler = app.task(name='music_folders_generation_scheduler-new_recogn_name',serializer='json',bind=True)\
											(CeleryScheduler().music_folders_generation_scheduler)		

get_FP_and_discID_for_album = app.task(name='get_FP_and_discID_for_album',bind=True)(get_FP_and_discID_for_album)
acoustID_lookup_celery_wrapper = app.task(name='acoustID_lookup_celery_wrapper',bind=True)(acoustID_lookup_celery_wrapper)
MB_get_releases_by_discid_celery_wrapper = app.task(name='MB_get_releases_by_discid_celery_wrapper',bind=True)(MB_get_releases_by_discid_celery_wrapper)	

fp_post_processing_req = group(callback_MB_get_releases_by_discid_request.s(), callback_acoustID_request.s())

def main():
	app.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://192.168.1.65:6379")
	app.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://192.168.1.65:6379")
	app.control.purge()
	#acoustID_lookup_celery_wrapper(1,2)
	#exit(1)
	task_list = []
	p3 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_CLASSICAL/LArpeggiata - Christina Pluhar'
	p4 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_ROCK/Pink Floyd/1983 Pink Floyd - The Final Cut'
	p5 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_ROCK/Pink Floyd/_HI_RES/1975 - Wish You Were Here (SACD-R)'
	p2 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_CLASSICAL/Vivaldi/Antonio Vivaldi - 19 Sinfonias and Concertos for Strings and Continuo/'
	p6 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_ROCK/Pink Floyd/Pink Floyd - Dark Side Of The Moon (1973) [MFSL UDCD II 517]/'
	#task_first_res = app.send_task('music_folders_generation_scheduler-new_recogn_name',(p2,[],[]),link=callback_FP_gen.s())
	path = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC'
	task_first_res = app.send_task('find_new_music_folder-new_recogn_name',([path],[],[],'initial'))
	#task_folders_list = app.send_task('find_new_music_folder-new_recogn_name',([path],[],[],'initial'),link=callback_find_new_music_folder.s())
	print(task_first_res,type(task_first_res))
	

if __name__ == '__main__':
	main()