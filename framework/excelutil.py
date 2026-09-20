from framework.logger import Logger
from xlrd import open_workbook
from openpyxl import *
from openpyxl.styles import Font
from xlrd import biffh
import os
from config import readconfig
from framework.logger import Logger
from keywordsDriver.excelKey import *
import setting

mylog=Logger(logger='excel_readWrite').getlog() 

class excel_readWrite:
    def __init__(self, xls_name,sheetName,base_url=None, pagetitle=None):
        # self.base_url = base_url
        # self.pagetitle = pagetitle
        self.xls_name=xls_name
        #self.xls_path = os.path.join(readconfig.read('filepath', 'datapath'), self.xls_name)
        self.xls_path=os.path.join(setting.DATA_PATH, self.xls_name)
        mylog.info('读取的xlsl文件的路径为：%s' % self.xls_path)
        self.workbook=load_workbook(self.xls_path)
        self.sheet=self.workbook[sheetName]

        self.font=Font(color=None)
        self.colordict={'red':'FFFF3030','green':'FF008B00','black':'FF000000'}

    def get_xls(self,sheetName,**conditions):#**conditions 为以后扩展，增加筛选条件过滤数据
        """
        传入sheet名称，默认取全部
        可选择传入关键字参数，进行条件过滤
        """
        rows = []
        # open excel file
        # book = open_workbook(self.xls_path)
        # # get sheet by name
        # sheet = book.sheet_by_name(sheet_name)
        # 获取总行数
        try:
            self.sheet = self.workbook[sheetName]
            mylog.info('找到sheetName=%s' % sheetName)
            nrows = self.sheet.max_row
            ncols = self.sheet.max_column
            if nrows > 1:
                keys = list(map(lambda x:x.lower(),self.get_row(0)))


            a={x.lower():conditions[x].lower() for x in conditions if x.lower() in keys}
            for i in range(1,nrows):

                values= self.get_row(i)
                if sheetName==DataSheet:
                    for xy in NeedXY:
                        XYvalue = keys.index(xy)

                        values[XYvalue]=str(i+1)+','+str(XYvalue+1)

                ddt_dic=dict(zip(keys,values))
                for i in a:
                    if a[i].lower()!=ddt_dic[i].lower():
                        break
                else:
                    yield ddt_dic
                #rows.append(ddt_dic)之前该方法返回一个list，现在返回一个生成器
        except biffh.XLRDError as e:
            mylog.error('在%s无法找到sheetName=%s'%(self.xls_name,sheetName))
        #return rows

    def setTable(self,filepath,sheetname):
        """
        filepath:文件路径
        sheetname：Sheet名称
        """
        data = open_workbook(filepath)
        # 通过索引顺序获取Excel表
        sheet = data.sheet_by_name(sheetname)
        return sheet
    def getTabledata(self, filepath, sheetname):
        """
        filepath:文件路径
        sheetname：Sheet名称
        """
        table = self.setTable(filepath, sheetname)
        for args in range(1, table.nrows):
            # 使用生成器 yield
            yield table.row_values(args)

    def getcelldata(self, RowNum, ColNum):
        """
        sheetname:表格Sheets名称
        RowNum:行号 从0开始
        ColNum:列号 从0开始
        """
        #table = self.setTable(sheetname=sheetname)
        celldata = self.sheetname.cell_value(RowNum, ColNum)
        return celldata
    def write_data(self,rowno,colno,content,font=None,msg='保存excel成功'):

        cell=self.sheet.cell(row=rowno,column=colno)
        cell.value=content
        if font is not None:
            try:
                cell.font=Font(color=font)
            except ValueError as e:
                cell.font = Font(color='FF000000')
                mylog.error('color字典不存在该颜色，将采用默认颜色黑色')
        self.workbook_save(msg=msg)

    def workbook_save(self,msg=None):

        self.workbook.save(self.xls_path)
        mylog.info(msg)
    def get_row(self,row):

        #return list(map(lambda x :x.value ,list(self.sheet.rows)[row]))

        # rowslist=[]
        # for row in list(self.sheet.rows):
        #     rowlist = []
        #     for cell in row:
        #         cellValue=cell.value
        #         if cellValue==None:
        #             cellValue=''
        #         rowlist.append(cellValue)
        #     rowslist.append(rowlist)


        rowlist = []
        for cell in list(self.sheet.rows)[row]:
            cellValue=cell.value
            if cellValue==None:
                cellValue=''
            rowlist.append(cellValue)
        return rowlist






if __name__ == '__main__':
    print(excel_readWrite(excelname,DataSheet).get_xls(DataSheet))




