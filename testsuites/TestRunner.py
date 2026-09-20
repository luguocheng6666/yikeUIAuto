'''
Author: luguocheng luguocheng@moyi365.com
Date: 2023-09-05 15:50:13
LastEditors: luguocheng luguocheng@moyi365.com
LastEditTime: 2023-09-13 14:10:23
FilePath: \yikeUIAuto\testsuites\TestRunner.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
import unittest
# -*- coding: utf-8 -*-
# from tools import HTMLTestRunner_PY3 as HTMLTestRunner

import sys
import os

sys.path.append("../")

curPath = os.path.abspath(os.path.dirname(__file__))
rootPath = os.path.split(curPath)[0]
sys.path.append(rootPath)
from tools import HTMLTestRunner_cn_echarts2 as HTMLTestRunner
from config import readconfig
import os
from framework.upload import upload, backup
from framework.send_email import send_email
import setting
from framework.keywordsFrameword import __generateTestCases


__generateTestCases()
# 必须显式传 top_level_dir=rootPath：否则 discover 默认以 start_dir('framework') 作为顶层目录，
# 会把 keywordsFrameword 以「无包名」方式二次导入，拿到的 Keyword 类上没有 __generateTestCases()
# 动态注入的 test_* 方法，导致收集到 0 个用例（静默失败，报告显示 run=0）。
suite = unittest.TestLoader().discover(
    "framework", "keywordsFrameword.py", top_level_dir=rootPath
)
# suite.addTest(aa('test1'))

# suite=unittest.TestLoader().discover('config','testt.py')


if __name__ == "__main__":
    # runner=unittest.TextTestRunner()
    # runner.run(suite)
    # 用绝对值而非 config.ini 里的相对路径 '../reports/'，避免从非项目根启动时在上级目录建空文件夹
    reports_path = setting.reports_dir
    if not os.path.exists(reports_path):
        os.makedirs(reports_path)
    report_file_path = os.path.join(setting.reports_dir, "result.html")
    fp = open(report_file_path, "wb")
    runner = HTMLTestRunner.HTMLTestRunner(
        stream=fp,
        title="自动化测试报告,测试结果如下：",
        description="用例执行情况：",
        retry=0,  # 失败循环次数
        verbosity=2,
    )

    result = runner.run(suite)
    print(result)
    print(result.error_count,result.failure_count)
    print(result.errors,result.failures)
    # if result.failure_count > 0 or result.error_count > 0:
        # send_email(report_file_path, result)
    fp.close()
    # upload()#上传到服务器中
    backup(report_file_path)
