import os
import time
from config import readconfig
from framework.logger import Logger
from selenium.common.exceptions import (
    NoSuchElementException,
    ElementNotVisibleException,
    ElementNotInteractableException,
)
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select
from selenium import webdriver
# pywinauto 仅 Windows 可用（Linux 装不了 pywin32/comtypes），顶层 import 会让整个框架
# 在 Linux 上启动即崩。改为条件导入：非 Windows 平台置为 None，桌面关键字运行时再报错，
# Web 关键字（back/refresh/open_url 等）不依赖它们，不受影响。
import sys as _sys
IS_WINDOWS = _sys.platform.startswith("win")
if IS_WINDOWS:
    try:
        from pywinauto import mouse
        from pywinauto.keyboard import send_keys
        from pywinauto import Desktop
    except ImportError:
        mouse = send_keys = Desktop = None
else:
    mouse = send_keys = Desktop = None
from io import BytesIO
import base64
import setting


mylog = Logger(logger="BasePage").getlog()


class BasicPage(object):
    # def __init__(self,driver): #此初始化因为关键字整改，所以注释低调此部分
    #     self.driver=driver

    def back(self):
        self.driver.back()
        mylog.info("返回到上一页 ")

    # def open_brower(self):#暂时没有使用此方法
    #     from framework.browser_engine import BrowserEngine
    #     mylog.info('打开浏览器')

    def refresh(self):
        self.driver.refresh()

    def forward(self):
        self.driver.forward()

    def open_url(self, url):
        self.driver.get(url)
        mylog.info("打开链接:%s " % url)

    # def start_app(self, addr):
    #     self.driver.start(addr)
    #     mylog.info("地址打开应用:%s " % addr)

    def get_win(self, win):
        windows=self.driver[win]
        mylog.info("获取窗口:%s " % win)
        mylog.info(windows)
        return windows

    # 隐式等待10s
    def wait(self, driver):
        self.driver.implicitly_wait(10)
        mylog.info("设置隐式等待10s")

    def click(self, selector):
        element = self.find_element(selector)

        text = element.text

        try:
            element.click()
            mylog.info("The element '%s' was clicked ." % text)
        except NameError as e:
            mylog.error("Failed to click the element with %s" % e)
            self.take_screenshot()
        except ElementNotVisibleException as e:
            self.sleep(1)
            mylog.error("该元素无法点击:%s" % selector)

        except ElementNotInteractableException as e:
            self.sleep(1)
            mylog.error("该元素隐藏无法点击:%s" % selector)

    def maxwindow(self):
        self.driver.maximize_window()
        mylog.info("浏览器窗口最大化！！")

    def back(self):
        self.driver.back()
        mylog.info("返回到上一页面！！")

    def close_browser(self):
        self.driver.close()
        mylog.info("关闭窗口！！")

    def close_win(self):
        self.windows.close()
        mylog.info("关闭窗口！！")

    # 获取所有的window_handls（句柄）
    def get_window_handles(self):
        all_handle = self.driver.window_handles
        mylog.info("获取所有的windows句柄:%s！！" % all_handle)
        return all_handle

    # 获取当前的window句柄
    def get_current_handle(self):
        current_handle = self.driver.current_window_handle
        mylog.info("获取当前的windows句柄:%s！！" % current_handle)
        return current_handle

    # 切换windows句柄
    def swith_window_handle(self, handle):
        self.driver.switch_to.window(handle)
        mylog.info("切换句柄到:%s！！页面标题为:%s" % (handle, self.driver.title))

    def swith_window_handle_by_title(self, title):
        """通过页面标题来判断切换到哪个句柄"""
        all_handles = self.get_window_handles()
        for handle in all_handles:
            self.driver.switch_to.window(handle)
            pagetitle = self.get_page_title()
            if title in pagetitle:
                mylog.info("根据标题判断来切换到页面标题为“%s”的句柄" % title)
                break

    def swith_window_handle_by_index(self, index):
        """通过handls来判断切换到哪个句柄"""
        all_handles = self.get_window_handles()
        self.driver.switch_to.window(all_handles[index])
        print(self.driver.title)

        mylog.info("切换到index为%s的handle" % index)

    def swith_frame(self, stepvalue):
        self.driver.switch_to.frame(stepvalue)
        mylog.info("切换frame")

    def maxwindow(self):
        self.driver.maximize_window()
        mylog.info("浏览器窗口最大化！！")

    def back(self):
        self.driver.back()
        mylog.info("返回到上一页面！！")

    # def close_browser(self):
    #     self.driver.close()
    #     mylog.info("关闭窗口！！")

    def quite_browser(self):
        try:
            self.driver.quit()
            mylog.info("关闭浏览器！！")
        except NameError as e:
            mylog.error("Failed to quit the browser with %s" % e)

    def take_screenshot(self, *kw):
        # 用 os.path.join 拼路径，不直接字符串相加：
        # 原来 setting.Screenshot_Path + "Fail\\" 在 Windows 上会拼成 '...ScreenshotFail\'，
        # 在 Linux 上反斜杠还会变成文件名的一部分。这里统一按平台分隔符处理。
        rq = time.strftime("%Y%m%d%H%M%S", time.localtime(time.time()))
        sub = str(*kw) if kw else ""
        sub = sub.replace("\\", os.sep).replace("/", os.sep).strip(os.sep)
        screenshot_name = os.path.join(setting.Screenshot_Path, sub, rq + ".png")
        dic_path = os.path.split(screenshot_name)[0]
        if not os.path.exists(dic_path):
            os.makedirs(dic_path)
        try:
            # self.driver.get_screenshot_as_file(screenshot_name)
            # return self.driver.save_screenshot(screenshot_name)
            if 'selenium' not in str(self.driver):
                mylog.info("截图成功")
                image = self.windows.capture_as_image()
                bytes_io = BytesIO()
                image.save(bytes_io, format='PNG')
                bytes_io.seek(0)
                base64_str = base64.b64encode(bytes_io.getvalue()).decode()
                # mylog.info(base64_str)
                return base64_str
            else:
                mylog.info("截图成功")
                return self.driver.get_screenshot_as_base64()

             # mylog.info('截图文件为:%s' % screenshot_name)
        except NameError as e:
            mylog.error("Failed to take screenshot %s" % e)
            self.take_screenshot()

    def get_element_value(self, selector):
        if "=>" not in selector:
            return self.driver.find_element_by_id(selector)
        selector_by = selector.split("=>")[0].strip()
        selector_value = selector.split("=>")[1].strip()
        return [selector_by, selector_value]

    def find_element(self, selector, text=False):
        """
        这个地方为什么是根据=>来切割字符串，请看页面里定位元素的方法
        submit_btn = "id=>su"         l
        ogin_lnk = "xpath => //*[@id='u1']/a[7]"  # 百度首页登录链接定位
        如果采用等号，结果很多xpath表达式中包含一个=，这样会造成切割不准确，影响元素定位
        :param selector:
        :return: element
        """
        element = ""
        # if '=>' not in selector:
        #     return self.driver.find_element_by_id(selector)
        # selector_by=selector.split('=>')[0]
        # selector_value = selector.split('=>')[1]
        selector_by = self.get_element_value(selector)[0]
        selector_value = self.get_element_value(selector)[1]

        if selector_by.lower() == "i" or selector_by.lower() == "id":
            locatedType = By.ID
        elif selector_by.lower() == "n" or selector_by.lower() == "name":
            locatedType = By.NAME
        elif selector_by.lower() == "cn" or selector_by.lower() == "class_name":
            locatedType = By.CLASS_NAME
        elif selector_by.lower() == "lt" or selector_by.lower() == "link_text":
            locatedType = By.LINK_TEXT

        elif selector_by.lower() == "plt" or selector_by.lower() == "partial_link_text":
            locatedType = By.PARTIAL_LINK_TEXT
        elif selector_by.lower() == "tn" or selector_by.lower() == "tag_name":
            locatedType = By.TAG_NAME

        elif selector_by.lower() == "x" or selector_by.lower() == "xpath":
            locatedType = By.XPATH
        elif selector_by.lower() == "cs" or selector_by.lower() == "css_selector":
            locatedType = By.CSS_SELECTOR

        else:
            mylog.error("please enter a valid type of targeting elements.")
            mylog.error("type:%s,value:%s" % (selector_by, selector_value))
            raise NameError("please enter a valid type of targeting elements.")

        try:
            """两种显示等待方法"""
            # element = WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((locatedType, selector_value)))
            element = WebDriverWait(self.driver, 5).until(
                lambda x: x.find_element(locatedType, selector_value)
            )
            # element=self.driver.find_element(locatedType,selector_value)
            mylog.info(
                "Had find the element '%s' successful by %s via value:%s"
                % (element.text, selector_by, selector_value)
            )

            if text == True:
                contentText = element.text
                if contentText == "" or contentText == None:
                    contentText = element.get_attribute("textContent")
                return contentText.strip()

        except NoSuchElementException as e:
            mylog.error("NoSuchElementException:%s" % e)
            self.take_screenshot("Fail\\")

        old_style = element.get_attribute("style")
        self.driver.execute_script(
            "arguments[0].setAttribute('style',arguments[1]);",
            element,
            "background:green;" + old_style,
        )

        return element

        #        #'''旧的方法'''
        #
        # if selector_by.lower() =='i' or selector_by.lower()=='id':
        #     try:
        #         element=self.driver.find_element_by_id(selector_value)
        #         mylog.info('Had find the element \'%s\' successful by %s via value:%s'%(element.text,selector_by,selector_value))
        #
        #
        #     except NoSuchElementException as e:
        #         mylog.error('NoSuchElementException:%s'%e)
        #         self.take_screenshot('Fail\\')
        #
        #
        # elif selector_by.lower() =='n' or selector_by.lower()=='name':
        #     try:
        #         element=self.driver.find_element_by_name(selector_value)
        #         mylog.info('Had find the element \'%s\' successful by %s via value:%s'%(element.text,selector_by,selector_value))
        #
        #     except NoSuchElementException as e:
        #         mylog.error('NoSuchElementException:%s'%e)
        #         self.take_screenshot('Fail\\')
        #
        # elif selector_by.lower() =='cn' or selector_by.lower()=='class_name':
        #     try:
        #         element=self.driver.find_element_by_class_name(selector_value)
        #         mylog.info(element.text)
        #         mylog.info('Had find the element \'%s\' successful by %s via value:%s'%(element.text,selector_by,selector_value))
        #
        #     except NoSuchElementException as e:
        #         mylog.error('NoSuchElementException:%s'%e)
        #         self.take_screenshot('Fail\\')
        #
        # elif selector_by.lower() =='lt' or selector_by.lower()=='link_text':
        #     try:
        #         element=self.driver.find_element_by_link_text(selector_value)
        #         mylog.info('Had find the element \'%s\' successful by %s via value:%s'%(element.text,selector_by,selector_value))
        #
        #     except NoSuchElementException as e:
        #         mylog.error('NoSuchElementException:%s'%e)
        #         self.take_screenshot('Fail\\')
        #
        # elif selector_by.lower() =='plt' or selector_by.lower()=='partial_link_text':
        #     try:
        #         element=self.driver.find_element_by_partial_link_text(selector_value)
        #         mylog.info('Had find the element \'%s\' successful by %s via value:%s'%(element.text,selector_by,selector_value))
        #
        #     except NoSuchElementException as e:
        #         mylog.error('NoSuchElementException:%s'%e)
        #         self.take_screenshot('Fail\\')
        #
        #
        # elif selector_by.lower() =='tn' or selector_by.lower()=='tag_name':
        #     try:
        #         element=self.driver.find_element_by_tag_name(selector_value)
        #         mylog.info('Had find the element \'%s\' successful by %s via value:%s'%(element.text,selector_by,selector_value))
        #
        #     except NoSuchElementException as e:
        #         mylog.error('NoSuchElementException:%s'%e)
        #         self.take_screenshot('Fail\\')
        #
        # elif selector_by.lower() =='x' or selector_by.lower()=='xpath':
        #     try:
        #         element=self.driver.find_element_by_xpath(selector_value)
        #         mylog.info('Had find the element \'%s\' successful by %s via value:%s'%(element.text,selector_by,selector_value))
        #
        #     except NoSuchElementException as e:
        #         mylog.error('NoSuchElementException:%s'%e)
        #         self.take_screenshot('Fail\\')
        #
        # elif selector_by.lower() =='cs' or selector_by.lower()=='css_selector':
        #     try:
        #         element=self.driver.find_element_by_css_selector(selector_value)
        #         mylog.info('Had find the element \'%s\' successful by %s via value:%s'%(element.text,selector_by,selector_value))
        #
        #     except NoSuchElementException as e:
        #         mylog.error('NoSuchElementException:%s'%e)
        #         self.take_screenshot('Fail\\')
        # else:
        #     raise NameError("please enter a valid type of targeting elements.")
        #     mylog.error('please enter a valid type of targeting elements.')
        # return element

    def clear(self, selector):
        el = self.find_element(selector)
        el.clear()
        mylog.info("清空该元素中的内容")

    def type(self, selector, text):
        el = self.find_element(selector)
        # 这里的调用应该有问题，等待后面的调试！！！

        try:
            el.send_keys(text)
            mylog.info("Had type '%s' in inputBox" % text)
        except NameError as e:
            mylog.error("Failed to ytpe in inputBox with %s" % e)

    def select_by_index(self, selector, index=None):
        element = self.find_element(selector)
        try:
            if index is None or index == "":
                index = 1
                mylog.info("没有写入index值，取默认值：1")
            Select(element).select_by_index(index=index)
            mylog.info("通过index选择select选项 :%s" % index)
        except NameError as e:
            mylog.error("Failed to select in selector with %s" % e)

    def select_by_text(self, selector, text):
        element = self.find_element(selector)
        try:
            Select(element).select_by_visible_text(text)
            mylog.info("通过text选择select选项:%s" % text)
        except NameError as e:
            mylog.error("Failed to select in selector with %s" % e)

    def select_by_value(self, selector, value):
        element = self.find_element(selector)
        try:
            Select(element).select_by_value(value)
            mylog.info("通过value选择select选项: %s" % value)
        except NameError as e:
            mylog.error("Failed to select in selector with %s" % e)

    def violentCode(self, selector, rangeValue):
        element = self.find_element(selector)

    def click(self, selector):
        element = self.find_element(selector)

        text = element.text

        try:
            element.click()
            mylog.info("The element '%s' was clicked ." % text)
        except NameError as e:
            mylog.error("Failed to click the element with %s" % e)
            self.take_screenshot()
        except ElementNotVisibleException as e:
            self.sleep(1)
            mylog.error("该元素无法点击:%s" % selector)

        except ElementNotInteractableException as e:
            self.sleep(1)
            mylog.error("该元素隐藏无法点击:%s" % selector)

    def get_page_title(self):
        title = self.driver.title

        mylog.info("current page title is %s" % title)
        return title

    def pressTabKey(self):
        from selenium.webdriver.common.action_chains import ActionChains

        try:
            ActionChains(self).send_keys(Keys.ENTER).perform()
            mylog.info("Press ENTER Key.")
        except NameError as e:
            mylog.error("Failed to Press ENTER Key.")
            self.take_screenshot()

    def ctrl_A(self, selector):
        element = self.find_element(selector)
        element.send_keys(Keys.CONTROL, "a")

    def ctrl_C(self, selector):
        element = self.find_element(selector)
        element.send_keys(Keys.CONTROL, "c")

    def ctrl_V(self, selector):
        element = self.find_element(selector)
        element.send_keys(Keys.CONTROL, "v")

    def ctrl_X(self, selector):
        element = self.find_element(selector)
        element.send_keys(Keys.CONTROL, "x")
    
    def verificationCodeSliding(self, selector, x, y):
        from selenium.webdriver.common.action_chains import ActionChains

        element = self.find_element(selector)
        try:
            ActionChains(self.driver).drag_and_drop_by_offset(element, x, y).perform()
            mylog.info("滑动滑块的坐标区域为 X：%s ,Y:%s" % (x, y))
        except AttributeError as e:
            mylog.error("滑动失败！！")

    def reltowincoords(self, x, y):
        # mylog.info(self.windows)
        x= int(x)
        y= int(y)
        # window_rect =("L343", "T164", "1023", "B604")
    
        window_rect = self.windows.Rectangle()
        # mylog.info(window_rect)
        # 定义相对于窗口的坐标
        # mouse.click(coords=(x,y))
        mouse.click(coords=(window_rect.left + x, window_rect.top + y))

        #思路错误，应该把Rectangle放到需要调用的函数里面执行
        
    def has_assert(self, stepKeywordsList):
        for i in stepKeywordsList:
            if "assert" in i:
                return True
        else:
            return False

    # 注意：这里不要定义 assertEqual —— 它会与 unittest.TestCase.assertEqual 同名。
    # 关键字框架里 self 是 Keyword(unittest.TestCase) 实例，用的是 TestCase 的断言；
    # 若在本类再定义同名方法会覆盖父类实现并造成无限递归。
    def assert_Is_Enabled(self, selector, expectedResult=True):
        # 判断是否可点击
        element = self.find_element(selector)
        actualresult = element.is_enabled()
        return actualresult, expectedResult

    def assert_Is_Display(self, selector, expectedResult=True):
        element = self.find_element(selector)
        actualresult = element.is_displayed()
        return actualresult, expectedResult

    def assert_Is_Exist(self, selector):
        try:
            self.find_element(selector)
            actualresult = True
        except Exception as e:
            mylog.info("assert_Is_Exist 未找到元素 %s：%s" % (selector, e))
            actualresult = False

        return actualresult

    def assert_Is_NotExist(self, selector):
        try:
            self.find_element(selector)
            actualresult = False
        except Exception as e:
            mylog.info("assert_Is_NotExist 元素不存在（符合预期）%s：%s" % (selector, e))
            actualresult = True

        return actualresult

    def assert_Is_Number(self, selector, expectedResult="float"):
        # 断言是否是数字
        try:
            text = self.find_element(selector, text=True)
            float(text)
            actualresult = True
        except Exception as e:
            mylog.info("assert_Is_Number 取值/转换失败 %s：%s" % (selector, e))
            actualresult = False

        return actualresult

    def assert_Number_between(self, selector, firstnumber, lastnumber):
        try:
            actualnumber = self.find_element(selector, text=True)
            if lastnumber >= float(actualnumber) >= firstnumber:
                return True
            else:
                return False
        except Exception as e:
            mylog.info(
                "assert_Number_between 取值/比较失败 %s（%s~%s）：%s"
                % (selector, firstnumber, lastnumber, e)
            )
            return False

    def exeuceJS(self, id, attr):
        js = "document.getElementById('%s').removeAttribute('%s')" % (id, attr)
        self.driver.execute_script(js)

    def move_mouse_to_element(self, selector):
        element = self.find_element(selector)

        webdriver.ActionChains(self.driver).move_to_element(element).perform()
        mylog.info("移动鼠标到selector这个元素")

    def send_keys(self,Enter):
        # str_enter = str(Enter)
        send_keys(str(Enter))
        mylog.info("输入:%s " % Enter)

    @staticmethod
    def sleep(seconds):
        time.sleep(seconds)
        mylog.info("Sleep for %d seconds" % seconds)


page = BasicPage()
page.sleep(3)
