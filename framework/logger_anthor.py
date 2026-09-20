import logging
import os
import time
from config import readconfig

class Logger(object):
    def __init__(self,logger):
        self.logger=logging.getLogger(logger)
        self.logger.setLevel(logging.DEBUG)
        #创建一个时间，用于写入日志
        rq=time.strftime('%Y%m%d%H%M',time.localtime(time.time()))

        #获取日志文件存放位置
        log_path=readconfig.read('filepath','logsfilepath')
        if  not os.path.exists(log_path):
            os.makedirs(log_path)
        log_name=log_path+rq+'.log'
        fh=logging.FileHandler(log_name)
        fh.setLevel(logging.INFO)


        ch=logging.StreamHandler()
        ch.setLevel(logging.INFO)

        formatter=logging.Formatter('%(asctime)s-%(name)s-%(levelname)s-%(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

    def getlog(self):
        return self.logger