'''
Author: luguocheng luguocheng@moyi365.com
Date: 2023-09-05 15:50:13
LastEditors: luguocheng luguocheng@moyi365.com
LastEditTime: 2023-09-07 15:53:53
FilePath: \yikeUIAuto\framework\exceltest.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
from framework.excelutil import excel_readWrite

# rw=excel_readWrite('testdata.xlsx')
# sheet=rw.setTable(rw.xls_path,"Sheet1")
# data=rw.getcelldata(sheet,0,0)
# xls=rw.get_xls("Sheet1")
# print(xls)

from tools import ddt, data, unpack
import unittest
from selenium import webdriver

datas = excel_readWrite("testdata.xlsx").get_xls("Sheet1")


@ddt
class test(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        self.driver = webdriver.Chrome()
        self.driver.get("https://www.ekwing.com/")

    @classmethod
    def tearDownClass(self):
        self.driver.close()

    @data(*datas)
    def testlogin(self, case_name):
        print(case_name)


#######

if __name__ == "__main__":
    unittest.main()
