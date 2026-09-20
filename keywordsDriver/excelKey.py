#文件名称
excelname='testdata.xlsx'
#测试策略
SuitSheet='测试用例'
DataSheet='TestDatas'
StepSheet='TestSteps'


#测试策略sheet
TCID='TCID'.lower() #公用同一个TCID
AcaseName='用例名称'
AcaseDescribe='用例描述'
AcaseIsNeedDo='是否需要执行'
AcaseEndTime='执行时间'
AcaseResult='结果'

#测试步骤sheet

BstepNum='步骤序号'
BstepDescribe='测试步骤描述'
BstepKeyword='关键字'
BstepMethod='操作元素定位方式'
BstepExpression='操作元素定位表达式'
BstepValue='操作值'
BstepIsNeedDo='是否需要执行'

#测试用例sheet
CCaseId='CaseId'.lower()
Runmode='Runmode'.lower()
data_name='Data_name'.lower()
Summary='Summary'.lower()
CverifiedcodeXY='verifiedcodeXY'.lower()
CType='Type'.lower()
CExpression='Expression'.lower()
CExpectedResult='ExpectedResult'.lower()
CErrMsg='ErrMsg'.lower()
CResult='Result'.lower()
Cstarttime='StartTime'.lower()
CRunTime='RunTime'.lower()
CSelector='selector'.lower()
CInput='Input'.lower()
Cinput='input'.lower()
NeedXY=[CResult,CErrMsg,Cstarttime,CRunTime]
Cycle='Cycle'.lower()

