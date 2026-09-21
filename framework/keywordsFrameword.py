'''
Author: luguocheng luguocheng@moyi365.com
Date: 2023-09-05 15:50:13
LastEditors: luguocheng luguocheng@moyi365.com
LastEditTime: 2023-09-13 14:21:42
FilePath: \yikeUIAuto\framework\keywordsFrameword.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
from framework.logger import Logger
from config.readconfig import read
from framework.excelutil import excel_readWrite
# 数据源可在 Excel 与数据库之间切换：由 framework.datasource 决定，默认仍是 Excel，
# 与改造前行为完全一致（命令行跑 TestRunner.py 不受影响）。
from framework import datasource
import os
from selenium import webdriver
# pywinauto 仅 Windows 可用，放到模块顶层 import 会让整个框架在 Linux 上启动即崩
# （Linux 装不了 pywin32/comtypes）。改为条件导入：非 Windows 平台置为 None，
# 桌面端关键字调用时再报明确的「当前平台不支持」错误，Web 用例不受影响。
import sys as _sys
IS_WINDOWS = _sys.platform.startswith("win")
if IS_WINDOWS:
    try:
        from pywinauto import Application
    except ImportError:      # Windows 上没装 pywinauto 时也不该拖垮 Web 用例
        Application = None
else:
    Application = None
import unittest
import time
from config.readconfig import read
from keywordsDriver.keywordAction import Action
from keywordsDriver.excelKey import *
from keywordsDriver.keywordKey import *
from keywordsDriver.ColorKey import *
# import basepage

from inspect import isfunction
import sys


mylog = Logger(logger="keywordsFrameword").getlog()
# 原来这里直接实例化 excel_readWrite，现改为走数据源工厂：
# 默认还是 Excel；Web 平台执行时设 YIKEUI_DATA_SOURCE=db 则改为读数据库。
case_file = datasource.open_case_source()
cases = datasource.open_data_source()

# TCID -> 用例名称 映射：用例名称在「测试用例」sheet，而执行数据在「TestDatas」sheet，
# 故执行时先按 TCID 反查好名称，供 HTMLTestRunner 报告把「测试用例」列渲染成
# 「TCID · 用例名称」。data_name 已是脏数据，不再作为取值来源。
_CASE_NAME_MAP = {}

# 动态生成的 test 方法名（test_<CaseId>_<TCID>_<data_name>）-> (TCID, 用例名称) 映射，
# 供 Web 平台把内部方法名翻译成「TCID · 用例名称」形式展示（而非难看的 test_xxx）。
_GEN_META = {}

# 执行过程中「当前步骤」的描述（步骤描述+关键字），供 Web 平台异常摘要使用：
# executeCase 每一步开始前更新它，用例失败时异常摘要即可带上「具体步骤」。
CURRENT_STEP_DESC = ''


def _build_case_name_map():
    _CASE_NAME_MAP.clear()
    try:
        for _row in case_file.get_xls(SuitSheet):
            _tcid = _row.get(TCID)
            _name = _row.get(AcaseName)
            if _tcid and _name:
                _CASE_NAME_MAP[_tcid] = _name
    except Exception:
        pass


class Keyword(unittest.TestCase):
    # basepage.wait()
    # driver = action.driver
    # driver = action.open_browser('Chrome')
    # driver=getattr(action,'driver')

    def LoadAndRunTestCases_Keyword(self):
        # case_list=
        pass

    # 遍历"测试用例"这个sheet
    @classmethod
    def setUpClass(self):
        self.action = Action()
        # 将测试的excel复制到testresult里面，然后在这里加上测试的结果

        # self.xls_path = os.path.join(read('filepath', 'datapath'), xls_name)
        mylog.info("获取测试用例目录！！！")

        # 如果所有的用例只打开一次浏览器，则取消下列注释
        # self.action.open_browser('Chrome')
        # self.driver = getattr(self.action, 'driver')

    def getAllTestCase_keyword(self):
        """获取所有有效的testcases"""
        mylog.info("getAllTestCase")
        dataList = []

        suitList = [
            suit
            for suit in case_file.get_xls(SuitSheet)
            if suit[AcaseIsNeedDo].lower() == "y"
        ]

        all_rows_list = [
            case
            for case in case_file.get_xls(DataSheet)
            if case[Runmode].lower() == "y"
        ]

        for row in suitList:
            # 获取动作、定位方式、定位表达式、操作值
            caseNum = row[TCID]  # 测试case的序号（不重要）
            caseName = row[AcaseName]  # 用例名称
            caseDescribe = row[AcaseDescribe]  # 用例描述
            # caseDetailSheetSame = row['步骤sheet名']   # 步骤sheet名
            caseIsNeedDo = row[AcaseIsNeedDo]  # 用例是否需要执行
            caseEndTime = row[AcaseEndTime]  # 执行结束时间
            caseResult = row[AcaseResult]  # 结果
            # caseCycle=row[Cycle]

            if caseName == "" or caseDescribe == "":
                print(caseName, caseDescribe)
                mylog.error("用例名称或者用例描述为空！！！")

            if caseIsNeedDo.lower() == "y":
                for case in all_rows_list:
                    if (case[Runmode].lower() == "y") & (case[TCID] == caseNum):
                        try:
                            cycle = int(case[Cycle])
                            if cycle == 0:
                                mylog.warning("cycle 请勿设置为0，自动修正为：1，如果禁用该用例，则通过其它参数设置")
                                cycle = 1
                        except ValueError as e:
                            mylog.warning("cycle 参数为非正整数，采用默认循环次数：1")
                            cycle = 1

                        for i in range(cycle):
                            dataList.append(case)

        return dataList

    def getCaseStep(self, sheetName, TCID):
        """需要传入TCID"""
        mylog.info("getAllCaseStep for TCID :%s" % TCID)
        caseStepList = []
        all_rows_list = list(case_file.get_xls(sheetName, TCID=TCID))
        for row in all_rows_list:
            # 获取动作、定位方式、定位表达式、操作值
            stepNum = row[BstepNum]
            stepDescribe = row[BstepDescribe]
            stepKeyword = row[BstepKeyword]
            stepMethod = row[BstepMethod]
            stepExpression = row[BstepExpression]
            stepValue = row[BstepValue]
            stepIsNeedDo = row[BstepIsNeedDo]

            if stepIsNeedDo.lower() == "y":
                if stepDescribe == "" or stepKeyword == "":
                    mylog.error("测试步骤描述或者关键字为空！内容为：%s" % row)
                    raise Exception("测试步骤描述或者关键字为空！内容为：%s" % row)
                caseStepList.append(row)
                # mylog.debug('提取的执行步骤为：%s - %s'%(sheetName,row))
        return caseStepList

    def executeCase(self, testcase):
        """执行测试用例以及返回测试结果"""
        # action=Action()
        # mylog.info("【Run】" + testcase['用例名称'] + "：")
        # start 必须在 try 之前初始化：try 内第一条语句（write_data）就可能抛异常
        # （例如 Excel 被占用导致 PermissionError），否则 finally 中访问 start
        # 会触发 UnboundLocalError，把真实原因掩盖掉。
        start = time.time()
        try:
            cases.write_data(
                int(testcase[CErrMsg].split(",")[0]),
                int(testcase[CErrMsg].split(",")[1]),
                None,
                font=failedrgb,
                msg="清空errormsg",
            )

            caseStepInfoList = self.getCaseStep(StepSheet, TCID=testcase[TCID])
            start = time.time()
            starttime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start))
            a = 1
            b = 1
            assertnum = 0
            print("")
            print("操作步骤：------------")
            cases.write_data(
                int(testcase[Cstarttime].split(",")[0]),
                int(testcase[Cstarttime].split(",")[1]),
                starttime,
                msg="写入用例的starttime成功",
            )
            self.imgs = []
            stepKeywordsList = []

            for step in caseStepInfoList:
                if (
                    step[TCID] == testcase[TCID]
                ):  # 这个判断在getCaseStep 方法中添加过滤条件，过滤掉了，可不做此判断，但暂时保留
                    # 「停止执行」：Web 端点了停止就跳过本用例剩余步骤（后续用例由 ProgressResult 拦下）
                    if datasource.is_cancel_requested():
                        mylog.info("收到停止指令，中断用例 %s 的后续步骤" % testcase[TCID])
                        break
                    keyword = step[BstepKeyword].lower()
                    # 记录当前步骤，供 Web 平台异常摘要带上「具体步骤」
                    global CURRENT_STEP_DESC
                    CURRENT_STEP_DESC = '%s（%s）' % (
                        step[BstepDescribe] or '', step[BstepKeyword] or '')
                    stepKeywordsList.append(keyword)
                    stepMethod = step[BstepMethod]
                    stepExpression = step[BstepExpression]
                    stepMethodExpression = (
                        stepMethod + "=>" + stepExpression
                    )  # 匹配操作步骤中的表达式
                    stepValue = step[BstepValue]
                    stepstarttime = time.time()  # log the step start time
                    # 断言的期望值取自数据行 expected_result（按断言步骤出现顺序逗号拆分）；
                    # 断言的「定位方式 / 定位表达式」统一使用「步骤」自身的字段（见 assert 分支），
                    # 与其它关键字保持一致，不再从数据行的 Type/Expression 读取。
                    ExpectedResult_list = testcase[CExpectedResult].split(",")
                    print(
                        "------------"
                        + keyword
                        + "("
                        + step[BstepDescribe]
                        + ")------------"
                    )
                    # 如果所有的用例只打开一次浏览器，则将if keyword.lower()及下面进行注释
                    if keyword.lower() == open_browser.lower():
                        self.action.open_browser(stepValue)
                        self.driver = getattr(self.action, "driver")

                    elif keyword.lower() == Quite_browser.lower():
                        self.action.quite_browser()
                    elif keyword.lower() == Close_browser.lower():
                        self.action.close_browser()

                    elif keyword.lower() == Close_win.lower():
                        self.action.close_win()
                    
                    elif keyword.lower() == maxwindow.lower():
                        self.action.maxwindow()

                    elif keyword.lower() == open_url.lower():
                        self.action.open_url(stepValue)
            
                    elif keyword.lower() == start_app.lower():
                        self.action.start_app(stepValue)
                        # self.driver = getattr(self.action, "driver")
                    
                    elif keyword.lower() == get_win.lower():
                        self.action.get_win(stepValue)
                        self.driver = getattr(self.action, "driver")

                    elif keyword.lower() == Back.lower():
                        self.action.back()

                    elif keyword.lower() == Refresh.lower():
                        self.action.refresh()

                    elif keyword.lower() == sleep:
                        self.action.sleep(stepValue)

                    elif keyword.lower() == sendkeys:
                        print(stepValue)
                        self.action.send_keys(stepValue)

                    elif keyword.lower() == click.lower():
                        self.action.click(stepMethodExpression)

                    elif "select" in keyword.lower():
                        # 取值优先级：步骤自身的「选择值」 > 数据行 selectorN。
                        # 前者是 Web 端的写法 —— 值跟步骤走，不再受 selector1..8 槽位限制，
                        # 页面上填什么这里就用什么（所见即所得）；
                        # 后者是 Excel 模式与存量用例的写法，仅在步骤没填值时兜底。
                        selectdata = ''
                        if stepValue and str(stepValue).strip():
                            selectdata = str(stepValue).strip()
                        else:
                            try:
                                selectdata = testcase[CSelector + str(b)]
                            except KeyError as e:
                                mylog.error("无法找到该key: %s " % CSelector)
                        if keyword.lower() == selectbyindex.lower():
                            self.action.select_by_index(
                                stepMethodExpression, index=selectdata
                            )
                        if keyword.lower() == selectbytext.lower():
                            self.action.select_by_text(stepMethodExpression, selectdata)
                        if keyword.lower() == selectbyvalue.lower():
                            self.action.select_by_value(
                                stepMethodExpression, selectdata
                            )
                        b += 1
                    elif keyword.lower() == clear.lower():
                        self.action.clear(stepMethodExpression)

                    elif keyword.lower() == swith_window_handle_by_index.lower():
                        try:
                            stepValue = int(stepValue)
                        except ValueError:
                            mylog.error(
                                "%s的方法的参数值错误，应为int,当前为%s" % (keyword, stepValue)
                            )
                            continue
                        self.action.swith_window_handle_by_index(int(stepValue))

                    elif keyword.lower() == Input.lower():
                        # 取值优先级：步骤自身的「输入值」 > 数据行 InputN。
                        # 同 select*：步骤里有值就用它（不受 Input1..8 槽位限制，
                        # 一个用例写第 9 个 input 也不会丢值），步骤没填才回头取数据行。
                        if stepValue and str(stepValue).strip():
                            inputdata = str(stepValue).strip()
                        else:
                            try:
                                inputdata = testcase[CInput + str(a)]
                            except KeyError as e:
                                inputdata = testcase[Cinput + str(a)]
                        self.action.type(stepMethodExpression, inputdata)
                        a += 1
                    elif keyword.lower() == screenshots.lower():
                        
                        self.imgs.append(self.action.screenshots())
                        mylog.info(self.imgs)

                    elif keyword.lower() == Move_mouse_to_element.lower():
                        self.action.move_mouse_to_element(stepMethodExpression)

                    elif keyword.lower() == swith_window_handle_by_title.lower():
                        self.action.swith_window_handle_by_title(stepValue)
                    elif keyword.lower() == swith_frame.lower():
                        self.action.swith_frame(stepValue)
                    elif keyword.lower() == CodeSlide.lower():
                        # 取值优先级：步骤自身的「滑块坐标」 > 数据行 verifiedcodeXY。
                        # 步骤里的坐标形如 "300,0"；没填时才回退到数据行（Excel 模式的写法）。
                        _sv = str(stepValue or '').strip()
                        if _sv:
                            _xy = [p.strip() for p in _sv.split(",")]
                            mylog.info("滑块坐标取自步骤：%s" % _sv)
                            self.action.verificationCodeSliding(
                                stepMethodExpression,
                                _xy[0],
                                _xy[1] if len(_xy) > 1 else "0",
                            )
                        else:
                            keys = list(testcase)
                            for key in keys:
                                if key.lower() == CverifiedcodeXY.lower():
                                    mylog.info("找到列名为：verifiedcodexy (忽略大小写)")
                                    verifiedcodeXY = testcase[key].split(",")
                                    self.action.verificationCodeSliding(
                                        stepMethodExpression,
                                        verifiedcodeXY[0],
                                        verifiedcodeXY[1],
                                    )
                                    break
                            else:
                                mylog.error("未找到列名为：verifiedcodexy (忽略大小写)")
                                raise KeyError("无法在excel文件中到为：【verifiedcodexy】的列名")
                    elif keyword.lower() == mouse_click.lower():
                        # 坐标形如 "300,0"。没填时不能硬 split —— 空串会拆出 ['']，
                        # 取 value[1] 直接 IndexError，整条用例变成 Error 且看不出原因。
                        _mc = str(stepValue or '').strip()
                        if not _mc:
                            mylog.error(
                                "mouse_click 缺少坐标：请在「操作值」列填 x,y（如 300,0）"
                            )
                            continue
                        value = [p.strip() for p in _mc.split(",")]
                        self.action.reltowincoords(
                            value[0],
                            value[1] if len(value) > 1 else "0",
                        )
                        
                    #已将mouse_click的方法坐标的输入改到stepValue操作值输入
                    # elif keyword.lower() == mouse_click.lower():
                    #     keys = list(testcase)
                    #     for key in keys:
                    #         if key.lower() == CverifiedcodeXY.lower():
                    #             mylog.info("找到列名为：verifiedcodexy (忽略大小写)")
                    #             mylog.info(testcase[key])
                    #             mylog.info(type(testcase[key]))
                    #             verifiedcodeXY = testcase[key].split(",")
                    #             mylog.info(verifiedcodeXY)
                    #             self.action.reltowincoords(
                    #                 verifiedcodeXY[0],
                    #                 verifiedcodeXY[1],
                    #             )
                    #             break
                    #     else:
                    #         mylog.error("未找到列名为：verifiedcodexy (忽略大小写)")
                    #         raise KeyError("无法在excel文件中到为：【verifiedcodexy】的列名")

                    elif keyword.lower() == Exeucejs.lower():
                        self.action.exeuceJS(stepExpression, stepValue)

                    elif "assert" in keyword.lower():
                        # 断言定位统一用「步骤」自身的 定位方式 / 定位表达式 字段（与其它关键字一致）。
                        # stepMethodExpression 已由上方 step 的 定位方式=>定位表达式 拼接好。
                        # 期望值取值优先级：步骤自身的「期望值」 > 数据行 ExpectedResult（按断言顺序逗号拆分）。
                        # 前者是 Web 端写法（页面上第几个断言就用第几个值，不再受槽位限制），
                        # 后者兼容 Excel 模式与存量用例。
                        if stepValue and str(stepValue).strip():
                            ExpectedResult = (
                                str(stepValue).strip().replace("\n", "").replace("\r", "")
                            )
                        else:
                            try:
                                ExpectedResult = (
                                    ExpectedResult_list[assertnum]
                                    .replace("\n", "")
                                    .replace("\r", "")
                                )
                            except IndexError:
                                ExpectedResult = (
                                    ExpectedResult_list[-1].replace("\n", "").replace("\r", "")
                                    if ExpectedResult_list
                                    else ""
                                )
                        expectedTypeExpression = stepMethodExpression
                        mylog.info("定位方式为：%s" % expectedTypeExpression)
                        try:

                            actualresult = self.action.find_element(
                                expectedTypeExpression, text=True
                            )
                        except Exception as e:
                            actualresult = False
                            mylog.info("无法找到元素：%s（%s）" % (expectedTypeExpression, e))

                        mylog.info(
                            "["
                            + testcase[Summary]
                            + "]测试用例断言的期望结果为:【%s】,实际结果为:【%s】,断言方法为：%s"
                            % (ExpectedResult, actualresult, keyword)
                        )

                        assertnum += 1

                        try:
                            if keyword.lower() == AssertEqual.lower():
                                self.assertEqual(ExpectedResult, actualresult)
                            elif keyword.lower() == AssertNotEqual.lower():
                                self.assertNotEqual(ExpectedResult, actualresult)
                            elif keyword.lower() == AssertIn.lower():
                                self.assertIn(ExpectedResult, actualresult)
                            elif keyword.lower() == AssertNotIn.lower():
                                self.assertNotIn(ExpectedResult, actualresult)
                            elif keyword.lower() == AssertTrue.lower():
                                # 此分支待优化， Is_displayed 见下 Assert_Is_Display
                                # if stepValue.lower()==Is_displayed.lower():
                                #     actualresultEle = self.action.find_element(expectedTypeExpression)
                                #     actualresult = actualresultEle.is_displayed()
                                self.assertTrue(actualresult)
                            elif keyword.lower() == Assert_Is_Number.lower():
                                actualresult = self.action.assert_Is_Number(
                                    expectedTypeExpression
                                )
                                self.assertTrue(actualresult)
                            elif keyword.lower() == Assert_Is_Display.lower():
                                (
                                    actualresult,
                                    expectedResult,
                                ) = self.action.assert_Is_Display(
                                    expectedTypeExpression,
                                    expectedResult=ExpectedResult,
                                )
                                self.assertTrue(
                                    str(actualresult).lower()
                                    == str(expectedResult).lower()
                                )

                            elif keyword.lower() == Assert_Is_Enabled.lower():
                                (
                                    actualresult,
                                    expectedResult,
                                ) = self.action.assert_Is_Enabled(
                                    expectedTypeExpression,
                                    expectedResult=ExpectedResult,
                                )
                                self.assertTrue(
                                    str(actualresult).lower()
                                    == str(expectedResult).lower()
                                )

                            elif keyword == assert_Number_between:
                                first, last = ExpectedResult.split("-")
                                try:
                                    firstnumber = float(first)
                                    lastnumber = float(last)

                                except TypeError as e:
                                    raise TypeError(
                                        "assert_Number_between 方法中，first或last 不为数值"
                                    )

                                actualresult = self.action.assert_Number_between(
                                    expectedTypeExpression,
                                    firstnumber=firstnumber,
                                    lastnumber=lastnumber,
                                )
                                self.assertTrue(actualresult)

                            elif keyword.lower() == Assert_Is_Exist.lower():
                                actualresult = self.action.assert_Is_Exist(
                                    expectedTypeExpression
                                )

                                ExpectedResult = (
                                    False 
                                    if (
                                        ExpectedResult.lower() in ["null", "false", "0"]
                                    )
                                    else True
                                )

                                self.assertEqual(
                                    actualresult,
                                    ExpectedResult,
                                    msg="ExpectedResult：%s,actualresult：%s，Not Equal"
                                    % (ExpectedResult, actualresult),
                                )
                            elif keyword.lower() == Assert_Is_NotExist.lower():
                                actualresult = self.action.assert_Is_NotExist(
                                    expectedTypeExpression
                                )

                                ExpectedResult = (
                                    False # 断言元素不存在，期望结果不要填以下三个值
                                    if (
                                        ExpectedResult.lower() in ["null", "false", "0"]
                                    )
                                    else True
                                )

                                self.assertEqual(
                                    actualresult,
                                    ExpectedResult,
                                    msg="ExpectedResult：%s,actualresult：%s，Not Equal"
                                    % (ExpectedResult, actualresult),
                                )


                            cases.write_data(
                                int(testcase[CResult].split(",")[0]),
                                int(testcase[CResult].split(",")[1]),
                                "Passed",
                                font=passedrgb,
                                msg="断言通过！！！",
                            )

                        except AssertionError as e:  # 当断言失败时获取异常，写入相应的记录，再抛出失败异常
                            self.driver = getattr(self.action, "driver")

                            cases.write_data(
                                int(testcase[CResult].split(",")[0]),
                                int(testcase[CResult].split(",")[1]),
                                "Failed",
                                font=failedrgb,
                                msg="写入用例的Result成功",
                            )
                            cases.write_data(
                                int(testcase[CErrMsg].split(",")[0]),
                                int(testcase[CErrMsg].split(",")[1]),
                                str(e),
                                font=failedrgb,
                                msg="写入用例的ErrMsg成功",
                            )
                            runtime = int(time.time() - start)
                            cases.write_data(
                                int(testcase[CRunTime].split(",")[0]),
                                int(testcase[CRunTime].split(",")[1]),
                                runtime,
                                msg="写入用例的RunTime成功",
                            )
                            mylog.error("该步骤断言失败%s" % str(e))

                            self.imgs.append(self.action.screenshots())
                            raise self.failureException(e)

                    stepruntime = (
                        time.time() - stepstarttime
                    )  # log the step running time
                    print(
                        "Step running time:%ss" % "%.2f" % stepruntime
                    )  # 这个是写在测试报告中的每个步骤的时间

            if not self.action.has_assert(
                stepKeywordsList
            ):  # 如果没有进行断言且无报错，则认为是passed，之前stepKeywordsList 使用的是：[x[BstepKeyword] for x in caseStepInfoList]
                cases.write_data(
                    int(testcase[CResult].split(",")[0]),
                    int(testcase[CResult].split(",")[1]),
                    "Passed",
                    font=passedrgb,
                    msg="未设置断言写入为passed",
                )

        except self.failureException as e:
            raise self.failureException(e)
        except Exception as e:
            import traceback

            cases.write_data(
                int(testcase[CErrMsg].split(",")[0]),
                int(testcase[CErrMsg].split(",")[1]),
                traceback.format_exc(),
                font=errorrgb,
                msg="写入用例的ErrMsg成功",
            )
            cases.write_data(
                int(testcase[CResult].split(",")[0]),
                int(testcase[CResult].split(",")[1]),
                "Error",
                font=errorrgb,
                msg="写入用例的Result成功",
            )

            mylog.error(traceback.format_exc())
            self.imgs.append(self.action.screenshots())

            raise Exception
        finally:
            runtime = int(time.time() - start)
            cases.write_data(
                int(testcase[CRunTime].split(",")[0]),
                int(testcase[CRunTime].split(",")[1]),
                runtime,
                msg="写入用例的RunTime成功",
            )
            if "pywinauto" in str(getattr(self, "driver", None)):
                pass
            else:
                self.action.quite_browser()

    @classmethod
    def tearDownClass(self):
        # 用例可能还没执行到 open_browser 就失败，此时 driver 属性尚未创建
        if "pywinauto" in str(getattr(self.action, "driver", None)):
            pass
        else:
            self.action.quite_browser()

    def getTestFunc(self, **txt):
        def func(self):
            # 把 TCID 与用例名称挂到测试实例上，供 HTMLTestRunner 报告里
            # 把「测试用例」列渲染成「TCID · 用例名称」的形式（见 tools/HTMLTestRunner_cn_echarts2）。
            # 用例名称来自「测试用例」sheet（经 _CASE_NAME_MAP 按 TCID 反查），
            # data_name 已是脏数据，不再作为取值来源；都取不到时回退到 TCID 本身。
            self.tcid = txt.get(TCID)
            self.casename = (
                _CASE_NAME_MAP.get(self.tcid)
                or txt.get(AcaseName)
                or txt.get(data_name)
                or self.tcid
            )
            self.executeCase(txt)

        return func


def funcIsExist(text):
    i = 1

    isexist = text in dir(Keyword)
    if not isexist:
        text1 = text
    else:
        while isexist:
            text1 = text + "_" + str(i)
            isexist = text1 in dir(Keyword)
            i += 1
    return text1


def case_label(method_name):
    """把动态生成的 test 方法名（test_<CaseId>_<TCID>_<data_name>）翻译成
    「TCID · 用例名称」形式（如 open_baidu · 打开百度），供 Web 平台展示。

    翻译不到（方法名不在登记表里）就原样返回，不破坏既有逻辑。
    """
    meta = _GEN_META.get(method_name)
    if meta:
        tcid = meta.get('tcid') or ''
        name = meta.get('name') or ''
        if tcid and name:
            return '%s · %s' % (tcid, name)
        return tcid or name or method_name
    return method_name


def __generateTestCases():
    _build_case_name_map()
    keyword = Keyword()
    caseList = keyword.getAllTestCase_keyword()

    for case in caseList:
        title = "test_%s_%s_%s" % (case[CCaseId], case[TCID], case[data_name])
        text = funcIsExist(title)
        print(text)
        setattr(Keyword, text, keyword.getTestFunc(**case))
        # 登记「方法名 -> (TCID, 用例名称)」，供 Web 平台把 test_xxx 翻译成「TCID · 名称」
        _GEN_META[text] = {
            'tcid': case[TCID],
            'name': (_CASE_NAME_MAP.get(case[TCID])
                     or case.get(AcaseName)
                     or case.get(data_name)
                     or case[TCID]),
        }


if __name__ == "__main__":
    __generateTestCases()
    unittest.main()
