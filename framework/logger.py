import os
import logging
from logging.handlers import TimedRotatingFileHandler
#from config import readconfig
import setting

class Logger(object):
    def __init__(self, logger):
        #self.LOG_PATH = readconfig.read('filepath', 'logsfilepath')r
        self.LOG_PATH=setting.LOG_PATH
        self.logger = logging.getLogger(logger)
        logging.root.setLevel(logging.NOTSET)
        self.log_file_name = 'logs.log'

        if not os.path.exists(self.LOG_PATH):
            os.mkdir(self.LOG_PATH)

        if not os.path.exists(os.path.join(self.LOG_PATH,self.log_file_name)):
            with open(os.path.join(self.LOG_PATH,self.log_file_name),'w'):
                pass

        self.backup_count = 5
        # 日志输出级别
        self.console_output_level = 'DEBUG'
        self.file_output_level = 'INFO'
        # 日志输出格式
        self.formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    def getlog(self):
        """在logger中添加日志句柄并返回，如果logger已有句柄，则直接返回"""
        if not self.logger.handlers:  # 避免重复日志
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(self.formatter)
            console_handler.setLevel(self.console_output_level)
            self.logger.addHandler(console_handler)

            # 每天重新创建一个日志文件，最多保留backup_count份
            file_handler = TimedRotatingFileHandler(filename=os.path.join(self.LOG_PATH, self.log_file_name),
                                                    when='D',
                                                    interval=1,
                                                    backupCount=self.backup_count,
                                                    delay=True,
                                                    encoding='utf-8'
                                                    )
            file_handler.setFormatter(self.formatter)
            file_handler.setLevel(self.file_output_level)
            self.logger.addHandler(file_handler)
        return self.logger

#logger = Logger().getlog()
