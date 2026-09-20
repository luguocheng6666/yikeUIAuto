import configparser
from configparser import DuplicateSectionError,NoSectionError,NoOptionError,DuplicateOptionError
import os
from framework.logger import Logger

mylog = Logger(logger='readconfig').getlog()

# 读取配置文件，获取启动的浏览器和请求我的URL
# filepath = os.path.dirname(os.path.abspath('')) + '/config/config.ini'
config = configparser.ConfigParser()
proDir = os.path.split(os.path.realpath(__file__))[0]
filepath = os.path.join(proDir, 'config.ini')
mylog.info(r'The configfile path is \'%s!\''%filepath)
sum=1
def read(section,option):
    '''read()方法不能和其他方法一起调用'''
    #configread = configparser.ConfigParser()

    mylog.info('调用的方法是：read(),参数为：%s,%s' % (section, option))
    try :
        config.read(filepath,encoding='utf-8')
        browser = config.get(section,option)
        return browser
    except NoSectionError as e:
        mylog.error('该section不存在！！！')
    except NoOptionError as e:
        mylog.error('该option不存在！！！')

    except DuplicateSectionError as e:
        mylog.error('该seciton(%s)在配置表中存在多个！！！'%section)
    except DuplicateOptionError as e:
        mylog.error('该option(%s)在配置表中的section(%s)存在多个！！！'%(option,section))




def addoption(section,optionname,optionvalue):
    mylog.info('调用的方法是：addoption(),参数为：%s,%s,%s' % (section, optionname,optionvalue))

    try:
        config.set(section,optionname,optionvalue)
        mylog.info('即将更新section(%s)中的optionname(%s)值为:%s！没有则创建'% (section,optionname,optionvalue))
        writesave(config)
    except NoSectionError as e:
        mylog.error('该section不存在！！！')


def addsection(section):
    mylog.info('调用的方法是：addsection(),参数为：%s' % section)
    if section=='':
        raise TypeError('不能为空！ ')
    else:
        try:
            config.add_section(section)
            mylog.info('即将新增的section为%s'%section)
            writesave(config)
        except DuplicateSectionError as e :
            mylog.error('即将新增的section：%s已存在！！！'%section)


def writesave(configA):
    mylog.info('调用的方法是：writesave()')
    try:
        configA.write(open(filepath,'a'))
        mylog.info('新增的已保存！！！')
    except DuplicateSectionError as e:
        mylog.error('该section已存在，保存失败！！！')

