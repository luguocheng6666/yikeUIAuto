'''
Author: luguocheng luguocheng@moyi365.com
Date: 2023-09-05 15:50:13
LastEditors: luguocheng luguocheng@moyi365.com
LastEditTime: 2023-09-12 16:07:51
FilePath: \yikeUIAuto\framework\browser_engine.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
from selenium import webdriver
import os
import sys
#import configparser
from framework.logger import Logger
from config import readconfig
import platform
from selenium.webdriver.chrome.options import Options
#from framework.basepage import BasicPage
import setting

# pywinauto 仅 Windows 可用。放在模块顶层 import 会让整个框架在 Linux 上启动即崩
# （Linux 装不了 pywin32/comtypes）。这里改为条件导入：非 Windows 平台置为 None，
# 桌面端关键字调用时再报明确的「当前平台不支持」错误，Web 用例不受影响。
IS_WINDOWS = sys.platform.startswith("win")
if IS_WINDOWS:
    try:
        from pywinauto import Application
    except ImportError:      # Windows 上没装 pywinauto 时也不该拖垮 Web 用例
        Application = None
else:
    Application = None



mylogger=Logger(logger='BrowserEngine').getlog()

class BrowserEngine(object):
    # 所有路径基于 setting.BASE_DIR（项目根，运行时推导）拼装，不依赖 CWD，
    # 也不在代码里写死盘符或分隔符，Windows / Linux 同一份代码可直接运行。
    # 原来读的 config.ini [filepath] driverpath='../tools/' 是相对 CWD 的，已弃用。
    dir = os.path.join(setting.BASE_DIR, "tools")
    # Linux 下的驱动没有 .exe 后缀
    _ext = ".exe" if IS_WINDOWS else ""
    chrome_driver_path = os.path.join(dir, "chromedriver" + _ext)
    fireofx_driver_path = os.path.join(dir, "geckodriver" + _ext)
    ie_driver_path = os.path.join(dir, "IEDriverServer" + _ext)
    # def __init__(self,driver):
    #     self.driver=driver
    def open_browser(self,browser): #此部分因为关键字框架改造，所以需要注释下方代码，启动浏览器配置不从配置文件读取，从excel读取
        #读取配置文件，获取启动的浏览器和请求我的URL
        # browser=readconfig.read('browserType','browserName')
        # mylogger.info('配置文件路径:%s'%browser)
        # #config.read(filepath)
        # #browser=config.get('browserType','browserType')
        # mylogger.info('当前所使用的浏览器是：%s' % browser)
        # url=readconfig.read('testserver','url')
        # mylogger.info('The test server url is：%s' % url)

        #根据读取的配置文件启动相应的浏览器
        currplatform=platform.platform() #获取当前系统

        if browser.lower()=='firefox':
            driver=webdriver.Firefox(executable_path=self.fireofx_driver_path)
            mylogger.info('启动%s 浏览器'%browser)
        elif browser.lower()=='chrome':

            if 'Linux' in currplatform:
                chrome_options = Options()
                chrome_options.add_argument('--headless')  # 无界面
                chrome_options.add_argument('--no-sandbox')  # 解决DevToolsActivePort文件不存在报错问题
                chrome_options.add_argument('--disable-gpu')  # 禁用GPU硬件加速。如果软件渲染器没有就位，则GPU进程将不会启动。
                chrome_options.add_argument('--disable-dev-shm-usage')
                chrome_options.add_argument('--window-size=1920,1080')  # 设置当前窗口的宽度和高度
                driver = webdriver.Chrome(executable_path=self.chrome_driver_path, chrome_options=chrome_options)
                mylogger.info('启动%s 浏览器'%browser)
            else:
                driver=webdriver.Chrome(executable_path=self.chrome_driver_path)
                mylogger.info('启动%s 浏览器'%browser)
        elif browser.lower()=='ie':
            driver=webdriver.Ie(executable_path=self.ie_driver_path)
            mylogger.info('启动%s 浏览器'%browser)
        elif 'C:'in browser :
            value = browser.split(",")
            print(value)
            driver=Application().start(value[0])[value[1]]
            mylogger.info('启动程序：%s，获取窗口：%s' % (value[0], value[1]))

        else:
            driver = webdriver.Chrome(executable_path=self.chrome_driver_path)
            mylogger.info('启动%s 浏览器'%browser)
        
        # 根据读取的配置文件请求相应的URL
        # basepage = BasicPage(driver)
        # basepage.maxwindow()
        # basepage.open_url(url)
        # driver.implicitly_wait(30)
        # mylogger.info('设置隐式等待30s...')
        return driver

    def quit_browser(self):
        self.driver.quit()
        
    def start_app(self,addr): 
        driver=Application().start(addr)
        mylogger.info('启动程序：%s' % (addr))
        return driver
    
    def get_win(self, win):
        self.driver[win]
        mylogger.info("获取窗口:%s " % win)
        mylogger.info(self.driver)
        return self.driver

    
if __name__ == '__main__':
    browserengine=BrowserEngine('driver')
    driver=browserengine.open_browser('driver')
    # browserengine=BrowserEngine('driver')
    # driver=browserengine.start_app('driver')
    driver.quit_browser()