'''
Author: luguocheng luguocheng@moyi365.com
Date: 2023-09-05 17:30:42
LastEditors: luguocheng luguocheng@moyi365.com
LastEditTime: 2023-09-13 14:58:32
FilePath: \yikeUIAuto\test.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
'''
Author: luguocheng luguocheng@moyi365.com
Date: 2023-09-05 17:30:42
LastEditors: luguocheng luguocheng@moyi365.com
LastEditTime: 2023-09-07 18:23:01
FilePath: \yikeUIAuto\test.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
# from pywinauto import Application

# # 打开记事本应用程序
# app = Application().start("notepad.exe")

# # 选择记事本窗口
# window = app["无标题 - 记事本"]

# # 打印控件标识符
# # print(window.print_control_identifiers())


# # 输入文本
# window.Edit.type_keys("UI自动化")

# # 保存并退出
# window.menu_select("文件->保存")
# window.SaveEdit.type_keys(r"C:\Users\Administrator\Desktop\uitest.txt")
# print(window.print_control_identifiers())
# window.SaveButton.click()
# window.close()


import os
import time
from pywinauto import Desktop
from io import BytesIO
import base64
from pywinauto import Application
from pywinauto import mouse
from pywinauto.keyboard import send_keys
from selenium import webdriver
# web = webdriver.Chrome()
# web.get("https://www.example.com")

# # 执行其他自动化操作
# # ...
# print(web)
# print(type(web))
# # 关闭浏览器
# time.sleep(1)
# web.quit()

# app = Application().start(r"C:\智能英语教学系统（机房版）-监考机\Teacher.exe")
app = Application().start(r"C:\普通话分级考试系统-监考机\Teacher.exe")
time.sleep(2)  # 等待应用程序打开

# 断言应用程序已经打开
assert app.is_process_running()
time.sleep(1)
win = app["CLoginWnd"]
# win.print_control_identifiers()
#输入账号密码
# print(app)
# print(win)
# win = str(win)
# print(type(win))
# print("pywinauto" in win)
window_rect = win.Rectangle()
# print(window_rect)
# 定义相对于窗口的坐标
# x = 380
# y = 165
mouse.click(coords=(window_rect.left + 400, window_rect.top + 165))
send_keys("考务账号")
mouse.click(coords=(window_rect.left + 400, window_rect.top + 230))
send_keys("88888888")

mouse.click(coords=(window_rect.left + 480, window_rect.top + 320))
time.sleep(2)
win = app["CExamWnd"]
window_rect = win.Rectangle()
print(window_rect)
win.print_control_identifiers()


# 截图

# screenshot = win.capture_as_image()
# # 将图像转换为Base64编码的字符串
# bytes_io = BytesIO()
# screenshot.save(bytes_io, format='PNG')
# bytes_io.seek(0)
# base64_str = base64.b64encode(bytes_io.getvalue()).decode()
# # 打印Base64编码的字符串
# print(base64_str)


# print(image)
# time.sleep(1)
# win.close()
# mouse.click(coords=(735,327))
# send_keys("考务账号")
# mouse.click(coords=(735,395))
# send_keys("88888888")
# #点击确定
# mouse.click(coords=(735,480))
# time.sleep(1)
# win = app["CExamWnd"]
# win.print_control_identifiers()


# print(win.children()) #获取子元素
# print(win.get_properties()) #获取属性
# 截图
# pic = win.capture_as_image()
# pic.save('01.png')
# print(pic)

# 输入账号和密码
# account_input = win.child_window(control_type="Edit")
# password_input = win.child_window(control_type="Edit")
# account_input.set_focus()
# account_input.type_keys("your_username")
# password_input.set_focus()
# password_input.type_keys("your_password")

# 点击登录按钮
# login_button = win.child_window(title="Login", control_type="Button")
# login_button.click()
# time.sleep(10)
# 关闭应用程序
# app.kill()




# 打开记事本应用程序
# app = Application().start("notepad.exe")

# # 获取记事本窗口
# window = app["无标题 - 记事本"]

# # 输入文本
# window.type_keys("UI自动化")
# print(window.print_control_identifiers())

# 保存文件
# window.menu_select("文件->保存")
# save_dialog = app["另存为"]
# current_dir = os.path.dirname(os.path.abspath(__file__))
# # 构建新的文件路径
# file_path = os.path.join(current_dir, "UItest.txt")

# # save_dialog["文件名Edit"].type_keys(file_path)
# save_dialog["文件名Edit"].type_keys("uitest.txt")
# save_dialog["保存Button"].click()

# # 退出记事本
# window.menu_select("文件->退出")
