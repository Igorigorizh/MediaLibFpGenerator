import os
import time

from celery import Celery

app = Celery(__name__)

app.conf.imports = 'fpgenerator'
app.conf.task_serializer = 'pickle'
app.conf.result_serializer = 'pickle'
app.conf.accept_content = ['application/json', 'application/x-python-serialize']



if __name__ == '__main__':
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
	task_first_res = app.send_task('music_folders_generation_scheduler-new_recogn_name',(p3,[],[]),link=callback_FP_gen.s())
	path = '/home/fpgenerator/MediaLibManager/music/MUSIC/ORIGINAL_MUSIC'
	#task_first_res = app.send_task('find_new_music_folder-new_recogn_name',([path],[],[],'initial'))
	#task_folders_list = app.send_task('find_new_music_folder-new_recogn_name',([path],[],[],'initial'),link=callback_find_new_music_folder.s())
	print(task_first_res,type(task_first_res))