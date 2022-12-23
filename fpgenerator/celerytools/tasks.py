import os

import logging

from celery import Celery
from celery import group
from celery import Task
from celery import shared_task
from celery.utils.log import get_task_logger

from celery_progress.backend import ProgressRecorder
import sys
print('\n', "in worker: sys_path:", sys.path)

from celery import current_app as app

from .. import BASE_ENCODING


from medialib.myMediaLib_fp_tools import FpGenerator 
from medialib.myMediaLib_fp_tools import acoustID_lookup_celery_wrapper
from medialib.myMediaLib_fp_tools import MB_get_releases_by_discid_celery_wrapper
from medialib.myMediaLib_fp_tools import get_FP_and_discID_for_album
from medialib.myMediaLib_fs_util import Media_FileSystem_Helper as mfsh

logger = get_task_logger(__name__)

class ProgressTask(Task):
	_progress = None
	@property
	def progress(self):
		print('in ProgressTask:progress:',self._progress)
		self._progress = ProgressRecorder(self)
		return self._progress
		


class Media_FileSystem_Helper_Progress(mfsh):
    def __init__(self):
        super().__init__()
        self.progress_recorder = None
        self.progress_recorder_descr = ""
        self._EXT_CALL_FREQ = 10

    def set_progress_recorder(self,progress_recorder, descr):
        self.progress_recorder = progress_recorder
        self.progress_recorder_descr = descr
        
    def get_progress(self):
        return self._current_iteration
		
    def find_new_music_folder(self,*args):
        result = None
        print('in find_new_music_folder helper progress  args:',args)
        logger.debug(f'in find_new_music_folder helper progress  args:{args}')
        if self.progress_recorder:
            self.progress_recorder.set_progress(1, 2, description=self.progress_recorder_descr)
            # here we call original parent find_new_music_folder
            resD = super().find_new_music_folder(*args)
            
            if 'music_folderL' in resD:
                if not resD['music_folderL']:
                    result = {'error': "No audio data found"}    
                else:    
                    result = list(map(lambda x: bytes(x+'/',BASE_ENCODING),resD['music_folderL']))
            if 'error' in resD:
                result = {'error': resD['error']}    
            # Update final progress to get 100%   
            print('last progress:',self._current_iteration)
            logger.debug(f'in find_new_music_folder helper progress:  last progress val:{self._current_iteration}')
            self.progress_recorder.set_progress(self._current_iteration, self._current_iteration,\
                                                    description=self.progress_recorder_descr)
        return result
		
    def iterrration_extention_point(self, *args):
        """ iterrration_extention_point redefine with celery progress_recorder"""
        if self._current_iteration%self._EXT_CALL_FREQ == 0 and self.progress_recorder:
            if self._current_iteration > 2200:
                total = self._current_iteration+1000
            elif self._current_iteration > 1200:   
                total = self._current_iteration+500
            elif self._current_iteration > 200:   
                total = self._current_iteration+100
            else:
                total = self._current_iteration+10
                
                
            self.progress_recorder.set_progress(self._current_iteration, total, description=self.progress_recorder_descr)	
            
            

@shared_task(base=ProgressTask, name='find_new_music_folder-new_recogn_name',serializer='json',bind=True)
def find_new_music_folder_task(self, *args):
    # get instance of Media_FileSystem_Helper_Progress
    mfsh_obj = Media_FileSystem_Helper_Progress()
    # set progress recorder with ProgressTask.progress -> self.progress
    mfsh_obj.set_progress_recorder(self.progress,"medialib-job-folder-scan-progress-media_files")
    # call redefined method
    return {'result': mfsh_obj.find_new_music_folder(*args), 'total_proceed': mfsh_obj.get_progress()}
    

@shared_task(name="tasks.callback_acoustID_request")
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
	
@shared_task(name="tasks.callback_MB_get_releases_by_discid_request")
def callback_MB_get_releases_by_discid_request(result):
	if 'discID' not in result:
		return {'RC':-4}
		
	wrapper_args = ((result['discID'],))	
	response = app.send_task('MB_get_releases_by_discid_celery_wrapper',(wrapper_args))
	print('MB call:',response)
	return response	


@shared_task(base=ProgressTask, name='worker_ffmpeg_and_fingerprint_task',serializer='json',bind=True)
def worker_ffmpeg_and_fingerprint_task(self, *args):
    return {'result': FpGenerator().worker_ffmpeg_and_fingerprint(*args)}
    
@shared_task(base=ProgressTask, name='worker_fingerprint_task',serializer='json',bind=True)
def worker_fingerprint_task(self, *args):
    return {'result': FpGenerator().worker_fingerprint(*args)}    

@app.task(name="tasks.callback_FP_gen_2")
def callback_FP_gen_2(result,*args):
	# Прогресс всего процесса поальбомно расчитывается на основе значения статуса запланированных задач.\
	# Ниже только формируется план
	# scheduler.get_fp_overall_progress(root_task=res.children[0]), где res = get_async_res_via_id('592027a3-2d10-4f27-934e-fc2f6b67dc1e')
    if 'error' in result['result']:
        error = result['result']['error']
        logger.warning(f'Error in callback_FP_gen_2:{error}')
        return {'result':[], 'error':'No fp process due to error on previouse step'}
        
    fp = FpGenerator()    
    folderL = result['result']
    print()
    print('args in callback_FP_gen_2:',args)
	
    if folderL:
        for folder_name in folderL:
            if 'ACOUSTID_MB_REQ' in args:
                pass
                #task_fp_res = app.send_task('fp.build_fp_task_param',(folder_name),\
                #                                link=fp_post_processing_req)
            else:
                scenario_result = fp.build_fp_task_param(folder_name)
                if scenario_result['scenario'] == 'single_image_CUE':
                    # call worker with splitting
                    for item_params in scenario_result['params']: 
                        res_fp = app.send_task('worker_ffmpeg_and_fingerprint_task',(item_params))
  
                else:
                    # call fp generator worker
                    for item_params in scenario_result['params']: 
                        logger.debug(f'in callback_FP_gen_2:{item_params}')
                        res_fp = app.send_task('worker_fingerprint_task',(item_params,))

                            
    else:
        print("Error in callback_FP_gen: None result")

@app.task(name="tasks.callback_FP_gen")
def callback_FP_gen(result,*args):
	# Прогресс всего процесса поальбомно расчитывается на основе значения статуса запланированных задач.\
	# Ниже только формируется план
	# scheduler.get_fp_overall_progress(root_task=res.children[0]), где res = get_async_res_via_id('592027a3-2d10-4f27-934e-fc2f6b67dc1e')
    if 'error' in result['result']:
        error = result['result']['error']
        logger.warning(f'Error in callback_FP_gen:{error}')
        return {'result':[], 'error':'No fp process due to error on previouse step'}
    folderL = result['result']
    print()
    print('args in callback_FP_gen:',args)
	
    if folderL:
        for folder_name in folderL:
            if 'ACOUSTID_MB_REQ' in args:
                task_fp_res = app.send_task('get_FP_and_discID_for_album',(folder_name, 0, 1, 'multy', 'FP'),\
                                                link=fp_post_processing_req)
            else:
                task_fp_res = app.send_task('get_FP_and_discID_for_album',(folder_name, 0, 1, 'multy', 'FP'))
    else:
        print("Error in callback_FP_gen: None result")
		
		
get_FP_and_discID_for_album = shared_task(name='get_FP_and_discID_for_album',bind=True)\
                                            (get_FP_and_discID_for_album)
acoustID_lookup_celery_wrapper = shared_task(name='acoustID_lookup_celery_wrapper',bind=True)\
                                            (acoustID_lookup_celery_wrapper)
MB_get_releases_by_discid_celery_wrapper = shared_task(name='MB_get_releases_by_discid_celery_wrapper',
                                                        bind=True)\
                                                        (MB_get_releases_by_discid_celery_wrapper)	

fp_post_processing_req = group(callback_MB_get_releases_by_discid_request.s(), callback_acoustID_request.s())

@shared_task()
def task_test_logger():
    logger.info("test fpgenerator logger")


def main():
	#app.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://192.168.1.65:6379")
	#app.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://192.168.1.65:6379")
	#app.control.purge()
	#acoustID_lookup_celery_wrapper(1,2)
	#exit(1)
	task_list = []
	p3 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_CLASSICAL/LArpeggiata - Christina Pluhar'
	p4 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_ROCK/Pink Floyd/1983 Pink Floyd - The Final Cut'
	p5 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_ROCK/Pink Floyd/_HI_RES/1975 - Wish You Were Here (SACD-R)'
	p2 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_CLASSICAL/Vivaldi/Antonio Vivaldi - 19 Sinfonias and Concertos for Strings and Continuo/'
	p6 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC/ORIGINAL_ROCK/Pink Floyd/Pink Floyd - Dark Side Of The Moon (1973) [MFSL UDCD II 517]/'
	task_first_res = app.send_task('find_new_music_folder-new_recogn_name',([p3],[],[],'initial'),link=callback_FP_gen.s())
	path = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/ORIGINAL_MUSIC'
	path2 = '/home/fpgenerator/MediaLibFpGenerator/music/MUSIC/MP3_COLLECTION'
	#task_first_res = app.send_task('find_new_music_folder-new_recogn_name',([path,path2],[],[],'initial'))
	
	#print(task_first_res,type(task_first_res))
	

if __name__ == '__main__':
    main()