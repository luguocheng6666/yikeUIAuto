'''
Author: luguocheng luguocheng@moyi365.com
Date: 2023-09-05 15:50:13
LastEditors: luguocheng luguocheng@moyi365.com
LastEditTime: 2023-09-13 11:08:14
FilePath: \yikeUIAuto\keywordsDriver\keywordAction.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
from framework.basepage import BasicPage
from framework.browser_engine import BrowserEngine
from selenium import webdriver
from framework.logger import Logger

mylog = Logger(logger="BasePage").getlog()
class Action(BasicPage):#继承BasicPage类
    # def __init__(self):
    # #     self.driver=BrowserEngine(self).open_browser()
    #     browser = BrowserEngine()
    #     self.driver = browser.open_browser()
    browser = BrowserEngine()
    # def __init__(self):
    #     self.driver=self.browser.open_browser('Chrome')
    #     self.driver.get('http://baidu.com')

    def open_browser(self,browser):
        self.driver = self.browser.open_browser(browser)
        #     browser = BrowserEngine()
        #     self.driver = browser.open_browser()
        return self.driver
    
    def start_app(self,addr):
        self.driver = self.browser.start_app(addr)
        #     browser = BrowserEngine()
        #     self.driver = browser.open_browser()
        print(self.driver)
        return self.driver
        # super().start_app(addr)
    
    def get_win(self,win):
        self.windows=self.driver[win]
        mylog.info("获取窗口:%s " % win)
        mylog.info(self.windows)
        return self.windows


    def open_url(self,url):
        super().open_url(url)

    

    def maxwindow(self):
        
        super().maxwindow()

    def back(self):
        super().back()

    def sleep(self,sec):
        # DB 数据源把操作值存成文本，time.sleep 需要数值；这里统一尝试转 float，
        # 转不了就当成 0（不等待），避免 Web 跑 DB 用例时崩溃。Excel 路径数值本来就能转，无副作用。
        try:
            sec = float(sec)
        except (TypeError, ValueError):
            sec = 0
        super().sleep(sec)

    def send_keys(self,enter):
        super().send_keys(enter)

    def click(self,steptypeValue):
        super().click(steptypeValue)

    def screenshots(self):
        return self.take_screenshot()

    def input(self,selector,text):
        self.type(selector,text)

    def close_browser(self):
        super().close_browser()

    def close_win(self):
        super().close_win()

    def quite_browser(self):
        # 用 getattr 兜底：用例可能还没执行到 open_browser 就失败，此时没有 driver。
        # 桌面端（pywinauto）连接也不走 quit()。
        driver = getattr(self, "driver", None)
        if driver is None or "pywinauto" in str(driver):
            return
        try:
            driver.quit()
        except Exception as e:
            mylog.error("关闭浏览器失败：%s" % e)


    def select_by_index(self,selector,index):
        super().select_by_index(selector,index)
    def select_by_text(self,selector,text):
        super().select_by_text(selector, text)
    def select_by_value(self,selector,value):
        super().select_by_value(selector, value)



    def move_mouse_to_element(self,stepMethodExpression):
        super().move_mouse_to_element(stepMethodExpression)



