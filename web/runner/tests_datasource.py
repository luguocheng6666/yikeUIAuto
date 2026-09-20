'''数据源适配层自动化测试 —— 保证「Web 模式读数据库」与「命令行模式读 Excel」行为一致。

这里的行是被 Frameword 与执行引擎之间的唯一契约层：
引擎拿到的每一行 dict，键必须与 Excel 表头 lower() 后完全一致，
回写也必须能落回 TestData 的正确字段。任一环节错位，执行结果就会静默丢失。
'''
from django.test import TestCase as DjangoTestCase
from keywordsDriver.excelKey import SuitSheet, StepSheet, DataSheet

from cases.models import TestCase, TestStep, TestData
from framework import datasource


class DBDataSourceTests(DjangoTestCase):

    def setUp(self):
        # 这条模块级状态会影响所有执行，用完必须复位
        datasource.clear_cancel()
        datasource.set_run_scope(None)

        self.ds = datasource.DBDataSource()
        self.case = TestCase.objects.create(tcid='t1', name='示例', need_run=True)
        self.step = TestStep.objects.create(
            case=self.case, step_no=1, keyword='input',
            locate_type='id', locate_expr='username', value='{input1}',
        )
        self.data = TestData.objects.create(
            case=self.case, data_name='d1', input1='admin', expected_result='OK',
        )

    def tearDown(self):
        datasource.clear_cancel()
        datasource.set_run_scope(None)

    # ---------------------------------------------------------------- 读取

    def test_step_rows_expose_locate_fields(self):
        """断言关键字的定位就取自步骤行的这两个字段（历史 bug 曾误读数据行）。"""
        row = self.ds._step_rows()[0]
        self.assertEqual(row['操作元素定位方式'], 'id')
        self.assertEqual(row['操作元素定位表达式'], 'username')
        self.assertEqual(row['关键字'], 'input')

    def test_step_rows_filtered_by_tcid(self):
        rows = list(self.ds.get_xls(StepSheet, TCID='t1'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(self.ds.get_xls(StepSheet, TCID='nope')), [])

    def test_data_rows_expected_result_key(self):
        row = self.ds._data_rows()[0]
        self.assertEqual(row['expectedresult'], 'OK')
        self.assertEqual(row['tcid'], 't1')

    def test_write_coordinates_are_pk_and_column_index(self):
        """Result/ErrMsg/StartTime/RunTime 四列是「pk,列号」坐标，供引擎回写。"""
        row = self.ds._data_rows()[0]
        self.assertEqual(row['result'], '%s,1' % self.data.pk)
        self.assertEqual(row['errmsg'], '%s,2' % self.data.pk)
        self.assertEqual(row['starttime'], '%s,3' % self.data.pk)
        self.assertEqual(row['runtime'], '%s,4' % self.data.pk)

    def test_unknown_sheet_raises(self):
        with self.assertRaises(ValueError):
            list(self.ds.get_xls('NoSuchSheet'))

    # ---------------------------------------------------------------- 回写

    def test_write_data_updates_all_four_fields(self):
        pk = self.data.pk
        self.ds.write_data(pk, 1, 'Passed')
        self.ds.write_data(pk, 2, 'boom')
        self.ds.write_data(pk, 3, '2026-09-10 10:00:00')
        self.ds.write_data(pk, 4, '1.25')

        self.data.refresh_from_db()
        self.assertEqual(self.data.result, 'Passed')
        self.assertEqual(self.data.errmsg, 'boom')
        self.assertEqual(self.data.start_time, '2026-09-10 10:00:00')
        self.assertEqual(self.data.run_time, '1.25')

    def test_write_result_syncs_to_parent_case(self):
        self.ds.write_data(self.data.pk, 1, 'Failed')
        self.case.refresh_from_db()
        self.assertEqual(self.case.last_result, 'Failed')

    def test_write_data_ignores_out_of_range_column(self):
        before = self.data.result
        self.ds.write_data(self.data.pk, 99, 'x')
        self.ds.write_data(self.data.pk, 0, 'y')
        self.data.refresh_from_db()
        self.assertEqual(self.data.result, before)

    def test_write_data_swallows_bad_pk(self):
        """回写失败不能中断整个执行流程。"""
        self.ds.write_data(999999, 1, 'Passed')   # 不存在的 pk
        self.ds.write_data('abc', 1, 'Passed')    # 非数字

    # ------------------------------------------------------------ 执行范围

    def test_run_scope_limits_rows(self):
        other = TestCase.objects.create(tcid='t2', name='另一条')
        TestStep.objects.create(case=other, step_no=1, keyword='input')
        TestData.objects.create(case=other, data_name='d2')

        datasource.set_run_scope(['t1'])
        self.assertEqual([r['tcid'] for r in self.ds.get_xls(SuitSheet)], ['t1'])
        self.assertEqual(len(list(self.ds.get_xls(StepSheet))), 1)
        self.assertEqual(len(list(self.ds.get_xls(DataSheet))), 1)

        datasource.set_run_scope(None)
        self.assertEqual(len(list(self.ds.get_xls(SuitSheet))), 2)

    # ------------------------------------------------------------ 停止标志

    def test_cancel_flag_lifecycle(self):
        self.assertFalse(datasource.is_cancel_requested())
        datasource.request_cancel()
        self.assertTrue(datasource.is_cancel_requested())
        datasource.clear_cancel()
        self.assertFalse(datasource.is_cancel_requested())
