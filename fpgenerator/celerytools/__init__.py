import os
import sys
from yaml import load, Loader
from configparser import ConfigParser

BASE_ENCODING = 'UTF-8'
mymedialib_cfg = './config/mymedialib.cfg'
medialib_fp_cfg = './config/medialib_fp.cfg'

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
print("ini __init__: sys_path:",sys.path)
print(os.path.abspath(__file__))

#from medialib import BASE_ENCODING
