'''Excel 导入 / 导出 的自动化测试。

重点锁住两个历史上真实踩过的坑：
  1. 「导出 -> 再导入」之后，断言的期望值不能被清空（曾经清空过，导致执行时空断言）；
  2. 断言的「定位方式 / 定位表达式」已统一到步骤字段，数据行的 Type/Expression
     不再承载定位信息，批量导入数据时也不应写入这两列。
'''
import json
import os
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase as DjangoTestCase
from django.urls import reverse
from openpyxl import Workbook

from openpyxl import load_workbook

from .importer import (import_excel, export_excel,
                       SUIT_HEADER, STEP_HEADER, DATA_HEADER,
                       SUIT_SHEET, STEP_SHEET, DATA_SHEET)
from .models import TestCase, TestStep, TestData, StepSnapshot
from runner.models import TaskRun
import runner.executor as executor

# check_step / count_issues 这类模块级函数在 cases.validate 里，单独引一个短名，
# 免得和本文件里其他 helper 混淆。
from . import validate as validate_module


def _write(ws, header, rows):
    ws.append(list(header))
    for r in rows:
        ws.append([r.get(h, '') for h in header])


def build_xlsx(path, cases=(), steps=(), datas=()):
    """按 importer 期望的表头结构生成一份 xlsx。"""
    wb = Workbook()
    ws = wb.active
    ws.title = '测试用例'
    _write(ws, SUIT_HEADER, cases)
    _write(wb.create_sheet('TestSteps'), STEP_HEADER, steps)
    _write(wb.create_sheet('TestDatas'), DATA_HEADER, datas)
    wb.save(path)
    return path


class TmpDirMixin(object):
    def setUp(self):
        super(TmpDirMixin, self).setUp()
        self.tmp = tempfile.mkdtemp(prefix='yikeui_case_test_')

    def _p(self, name):
        return os.path.join(self.tmp, name)


def sample_case(tcid='case_a', need_run='y'):
    return {'TCID': tcid, '用例名称': '登录流程', '用例描述': '',
            '是否需要执行': need_run, '执行时间': '', '结果': ''}


def sample_steps(tcid='case_a'):
    return [
        {'TCID': tcid, '步骤序号': 1, '测试步骤描述': '输入账号', '关键字': 'input',
         '操作元素定位方式': 'id', '操作元素定位表达式': 'username',
         '操作值': '{input1}', '是否需要执行': 'y'},
        {'TCID': tcid, '步骤序号': 2, '测试步骤描述': '断言页面标题', '关键字': 'assertEqual',
         '操作元素定位方式': 'xpath', '操作元素定位表达式': '//title',
         '操作值': '', '是否需要执行': 'y'},
    ]


def sample_datas(tcid='case_a'):
    return [
        {'TCID': tcid, 'CaseId': tcid, 'Runmode': 'y', 'Data_name': '正常账号',
         'Summary': '正常登录', 'Input1': 'admin', 'Input2': '123456',
         'Type': '', 'Expression': '', 'ExpectedResult': '翼课网', 'Cycle': 1},
    ]


class ImportBasicTests(TmpDirMixin, DjangoTestCase):

    def test_import_creates_cases_steps_and_datas(self):
        xlsx = build_xlsx(self._p('a.xlsx'), [sample_case()], sample_steps(), sample_datas())
        stat = import_excel(xlsx)

        self.assertEqual(stat['cases'], 1)
        self.assertEqual(stat['steps'], 2)
        self.assertEqual(stat['datas'], 1)
        self.assertEqual(TestCase.objects.count(), 1)
        self.assertTrue(TestCase.objects.get(tcid='case_a').need_run)

        # 步骤的定位字段必须落库 —— 断言关键字就靠它组装「定位方式=>定位表达式」
        s2 = TestStep.objects.get(case__tcid='case_a', step_no=2)
        self.assertEqual(s2.keyword, 'assertEqual')
        self.assertEqual(s2.locate_type, 'xpath')
        self.assertEqual(s2.locate_expr, '//title')

        d = TestData.objects.get()
        self.assertEqual(d.expected_result, '翼课网')
        self.assertEqual(d.input1, 'admin')

    def test_missing_tcid_rows_are_skipped(self):
        steps = sample_steps() + [sample_steps()[0]]
        steps[-1]['TCID'] = 'ghost_case'          # 用例表里没有这个 TCID
        xlsx = build_xlsx(self._p('b.xlsx'), [sample_case()], steps, sample_datas())
        import_excel(xlsx)
        self.assertEqual(TestStep.objects.count(), 2)

    def test_reimport_rebuilds_steps_instead_of_appending(self):
        xlsx = build_xlsx(self._p('c.xlsx'), [sample_case()], sample_steps(), sample_datas())
        import_excel(xlsx)
        import_excel(xlsx)                        # 再导一次
        self.assertEqual(TestStep.objects.count(), 2, '重复导入不应让步骤翻倍')

    def test_clear_first_removes_old_data(self):
        xlsx = build_xlsx(self._p('d.xlsx'), [sample_case()], sample_steps(), sample_datas())
        import_excel(xlsx)

        other = build_xlsx(self._p('e.xlsx'), [sample_case('case_b')], [], [])
        import_excel(other, clear_first=True)

        self.assertEqual(list(TestCase.objects.values_list('tcid', flat=True)), ['case_b'])
        self.assertEqual(TestStep.objects.count(), 0)

    def test_missing_sheet_raises(self):
        from openpyxl import Workbook as WB
        p = self._p('f.xlsx')
        WB().save(p)
        with self.assertRaises(ValueError):
            import_excel(p)

    def test_nonexistent_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            import_excel(self._p('nope.xlsx'))


class ExportRoundTripTests(TmpDirMixin, DjangoTestCase):
    """导出再导入必须无损 —— 这条测试专门防止「断言被清空」回归。"""

    def _seed(self):
        xlsx = build_xlsx(self._p('src.xlsx'), [sample_case()], sample_steps(), sample_datas())
        import_excel(xlsx)

    def test_roundtrip_keeps_expected_result(self):
        """导出再导入后，断言期望值不能丢 —— 现在它存在步骤的「操作值」里。"""
        self._seed()
        out = export_excel(self._p('out.xlsx'))
        import_excel(out, clear_first=True)

        # 旧格式里期望值躺在 TestDatas.ExpectedResult，导入时会被迁进步骤
        s2 = TestStep.objects.get(case__tcid='case_a', step_no=2)
        self.assertEqual(s2.value, '翼课网')
        # 步骤本来就有值的（input）保持原样，不被迁移逻辑覆盖
        s1 = TestStep.objects.get(case__tcid='case_a', step_no=1)
        self.assertEqual(s1.value, '{input1}')

    def test_roundtrip_keeps_step_locate_fields(self):
        self._seed()
        out = export_excel(self._p('out2.xlsx'))
        import_excel(out, clear_first=True)

        s2 = TestStep.objects.get(case__tcid='case_a', step_no=2)
        self.assertEqual((s2.locate_type, s2.locate_expr), ('xpath', '//title'))
        self.assertEqual(s2.keyword, 'assertEqual')

    def test_roundtrip_is_stable_over_two_generations(self):
        """第二代导出再导入，数据条数依然不变（防止逐代递增/递减）。"""
        self._seed()
        gen1 = export_excel(self._p('g1.xlsx'))
        import_excel(gen1, clear_first=True)
        gen2 = export_excel(self._p('g2.xlsx'))
        import_excel(gen2, clear_first=True)

        self.assertEqual(TestCase.objects.count(), 1)
        self.assertEqual(TestStep.objects.count(), 2)
        self.assertEqual(TestData.objects.count(), 1)
        # 值始终跟着步骤走，第二代之后依然是它
        self.assertEqual(
            TestStep.objects.get(case__tcid='case_a', step_no=2).value, '翼课网')


# --------------------------------------------------------------------------
# 步骤表 -> 数据行 的映射（CodeSlide 坐标 / selectby 选择值）
# --------------------------------------------------------------------------

class StepSaveMappingTests(TmpDirMixin, DjangoTestCase):
    """验证步骤表最后一列的值各自落到哪里。

    历史背景：CodeSlide 的坐标、selectby* 的选择值都属于「数据行的字段」，
    但场景 1 在界面上只能通过步骤表编辑，一旦某一类关键字没被映射，
    它的值就永远存不进去（CodeSlide 正是这样丢的）。
    """

    def setUp(self):
        super(StepSaveMappingTests, self).setUp()
        self.user = User.objects.create_user('tester', password='pwd12345')
        self.client.login(username='tester', password='pwd12345')
        self.case = TestCase.objects.create(tcid='map1', name='映射')
        self.url = reverse('cases:steps_save', args=[self.case.pk])

    def _post_steps(self, rows):
        """rows = [(描述, 关键字, 定位方式, 定位表达式, 最后一列的值)]"""
        data = {'s_desc': [], 's_kw': [], 's_type': [], 's_expr': [], 's_run': []}
        data['s_data'] = []
        for desc, kw, typ, expr, val in rows:
            data['s_desc'].append(desc)
            data['s_kw'].append(kw)
            data['s_type'].append(typ)
            data['s_expr'].append(expr)
            data['s_run'].append('y')
            data['s_data'].append(val)
        return self.client.post(self.url, data)

    def _primary(self):
        return TestData.objects.get(case=self.case)

    def test_codeslide_coordinate_written_to_data_row(self):
        self._post_steps([
            ('拖动滑块', 'CodeSlide', 'xpath', '//div[@class="slider"]', '300,0'),
        ])
        self.assertEqual(self._primary().verifiedcode_xy, '300,0')

    def test_selectby_written_to_both_step_value_and_selector(self):
        """双写：步骤值给引擎优先读，selector 给 Excel/存量用例兜底。"""
        self._post_steps([
            ('选省', 'selectbytext', 'xpath', '//select[@id="p"]', '广东'),
            ('选市', 'selectbytext', 'xpath', '//select[@id="c"]', '广州'),
        ])
        self.assertEqual(self._primary().selector1, '广东')
        self.assertEqual(self._primary().selector2, '广州')
        self.assertEqual(
            TestStep.objects.get(case=self.case, step_no=1).value, '广东')

    def test_third_selectby_is_not_dropped(self):
        """第 3 个 selectby* 超出 selector 槽位，但值仍在步骤里，不会被丢弃。"""
        self._post_steps([
            ('省', 'selectbytext', 'xpath', '//s1', '广东'),
            ('市', 'selectbytext', 'xpath', '//s2', '广州'),
            ('区', 'selectbytext', 'xpath', '//s3', '天河'),
        ])
        third = TestStep.objects.get(case=self.case, step_no=3)
        self.assertEqual(third.value, '天河')

    def test_existing_mapping_still_works(self):
        self._post_steps([
            ('账号', 'input', 'id', 'username', 'admin'),
            ('登录', 'click', 'id', 'btn', ''),
            ('断言', 'assertEqual', 'xpath', '//title', '翼课网'),
            ('等待', 'sleep', '', '', '2'),
        ])
        d = self._primary()
        self.assertEqual(d.input1, 'admin')
        self.assertEqual(d.expected_result, '翼课网')
        self.assertEqual(TestStep.objects.get(step_no=4).value, '2')

    def test_codeslide_absent_keeps_previous_coordinate(self):
        """没有 CodeSlide 步骤时不覆写旧值，避免又一次「数据被静默清空」。"""
        TestData.objects.create(case=self.case, verifiedcode_xy='300,0')
        self._post_steps([('输入', 'input', 'id', 'u', 'x')])
        self.assertEqual(self._primary().verifiedcode_xy, '300,0')

    def test_detail_page_renders_inputs_for_special_keywords(self):
        self._post_steps([
            ('拖动滑块', 'CodeSlide', 'xpath', '//div', '300,0'),
            ('选择', 'selectbytext', 'xpath', '//s', '广州'),
        ])
        html = self.client.get(
            reverse('cases:case_detail', args=[self.case.pk])).content.decode()
        self.assertIn('滑块坐标', html)
        self.assertIn('300,0', html)
        self.assertIn('广州', html)


# ---------------------------------------------------------------------------
# 单场景模式：所有关键字需要的数据，都写在步骤自身的「操作值」列
# ---------------------------------------------------------------------------

class SingleSceneValueTests(DjangoTestCase):
    """取消「一套步骤 x 多组数据」后：一个用例一条数据行，值存在 TestStep.value 上。"""

    def setUp(self):
        self.user = User.objects.create_superuser('tester', 't@example.com', 'pwd12345')
        self.client.force_login(self.user)
        self.case = TestCase.objects.create(tcid='case_s', name=u'单场景用例', need_run=True)
        TestData.objects.create(case=self.case, caseid='case_s', data_name=u'场景1', cycle=1)

    def _save(self, rows):
        """rows: [(描述, 关键字, 定位方式, 定位表达式, 操作值), ...]"""
        data = {'s_desc': [], 's_kw': [], 's_type': [], 's_expr': [], 's_run': [], 's_data': []}
        for desc, kw, lt, expr, val in rows:
            data['s_desc'].append(desc)
            data['s_kw'].append(kw)
            data['s_type'].append(lt)
            data['s_expr'].append(expr)
            data['s_run'].append('y')
            data['s_data'].append(val)
        return self.client.post(reverse('cases:steps_save', args=[self.case.pk]), data)

    def _html(self):
        return self.client.get(reverse('cases:case_detail', args=[self.case.pk])).content.decode('utf-8')

    def _step(self, kw):
        return TestStep.objects.get(case=self.case, keyword=kw)

    def test_every_keyword_value_is_stored_on_the_step(self):
        """不管什么关键字，这一格填的值都留在步骤自身。"""
        self._save([
            (u'输入账号', 'input', 'id', 'u1', 'admin'),
            (u'选择省份', 'selectbytext', 'id', 'p1', u'广东'),
            (u'拖滑块', 'CodeSlide', 'xpath', '//div', '300,0'),
            (u'点一下', 'click', 'id', 'btn', ''),
            (u'等待', 'sleep', '', '', '2'),
        ])
        self.assertEqual(self._step('input').value, 'admin')
        self.assertEqual(self._step('selectbytext').value, u'广东')
        self.assertEqual(self._step('CodeSlide').value, '300,0')
        self.assertEqual(self._step('sleep').value, '2')

    def test_values_are_also_synced_to_the_single_data_row(self):
        """同一份值同步到唯一的数据行，供 Excel 导出与存量引擎逻辑兜底。"""
        self._save([
            (u'输入账号', 'input', 'id', 'u1', 'admin'),
            (u'输入密码', 'input', 'id', 'u2', '123456'),
            (u'选择', 'selectbytext', 'id', 'p1', u'广东'),
            (u'拖滑块', 'CodeSlide', 'xpath', '//div', '300,0'),
            (u'断言', 'assertEqual', 'id', 't1', u'翼课网'),
        ])
        d = TestData.objects.get(case=self.case)
        self.assertEqual(d.input1, 'admin')
        self.assertEqual(d.input2, '123456')
        self.assertEqual(d.selector1, u'广东')
        self.assertEqual(d.verifiedcode_xy, '300,0')
        self.assertEqual(d.expected_result, u'翼课网')

    def test_redundant_data_rows_are_cleaned_up(self):
        """不再支持多组数据：保存步骤时多余的数据行被清掉，只留一条。"""
        TestData.objects.create(case=self.case, caseid='case_s', data_name=u'场景2')
        TestData.objects.create(case=self.case, caseid='case_s', data_name=u'场景3')
        self.assertEqual(TestData.objects.filter(case=self.case).count(), 3)
        self._save([(u'输入账号', 'input', 'id', 'u1', 'admin')])
        self.assertEqual(TestData.objects.filter(case=self.case).count(), 1)

    def test_page_has_no_multi_scene_module(self):
        """页面上不应再出现「更多测试场景」或任何多场景相关的东西。"""
        self._save([(u'输入账号', 'input', 'id', 'u1', 'admin'),
                    (u'拖滑块', 'CodeSlide', 'xpath', '//div', '300,0')])
        html = self._html()
        self.assertNotIn(u'更多测试场景', html)
        self.assertNotIn('sc_name', html)
        self.assertNotIn(u'新增场景列', html)
        # 表格主体里每个步骤恰好一个「操作值」输入框
        # （不能全页统计：页面底部 JS 的行模板里也带着同名字段）
        body = html.split('id="stepBody"', 1)[1].split('</tbody>')[0]
        self.assertEqual(body.count('name="s_data"'), 2)
        self.assertEqual(body.count('<tr data-kind='), 2)

    def test_step_value_wins_over_data_row_when_rendering(self):
        """回显以步骤自身的值为准，保证页面上所见即所得。"""
        TestStep.objects.create(case=self.case, step_no=1, keyword='input', value=u'新值')
        TestData.objects.filter(case=self.case).update(input1=u'旧值')
        html = self._html()
        self.assertIn(u'新值', html)

    def test_falls_back_to_data_row_for_legacy_cases(self):
        """存量用例（步骤没填值）仍能显示数据行里的历史值。"""
        TestStep.objects.create(case=self.case, step_no=1, keyword='input', value='')
        TestData.objects.filter(case=self.case).update(input1=u'旧值')
        self.assertIn(u'旧值', self._html())



# ---------------------------------------------------------------------------
# Excel 结构简化：只有「测试用例 / TestSteps」两张表
# ---------------------------------------------------------------------------

class SlimExcelTests(TmpDirMixin, DjangoTestCase):
    """导出的 Excel 与 Web 页面一致：两张表，TestDatas 已整合掉。"""

    def _seed(self, **case_extra):
        c = dict(sample_case())
        c.update(case_extra)
        xlsx = build_xlsx(self._p('src.xlsx'), [c], sample_steps(), sample_datas())
        import_excel(xlsx)
        return export_excel(self._p('out.xlsx'))

    def test_export_has_only_two_sheets(self):
        out = self._seed()
        wb = load_workbook(out)
        self.assertEqual(wb.sheetnames, [SUIT_SHEET, STEP_SHEET])
        self.assertNotIn(DATA_SHEET, wb.sheetnames)

    def test_suit_sheet_carries_result_columns(self):
        """Cycle / StartTime / RunTime / Result / ErrMsg 归并到用例表。"""
        out = self._seed()
        ws = load_workbook(out)[SUIT_SHEET]
        header = [c.value for c in ws[1]]
        for col in (u'循环次数', u'开始时间', u'执行时间', u'耗时', u'结果', u'错误信息'):
            self.assertIn(col, header)
        self.assertNotIn('Cycle', header)
        self.assertNotIn('ExpectedResult', header)

    def test_result_columns_survive_roundtrip(self):
        """用例层的结果列导出再导入不丢。"""
        case = TestCase.objects.create(tcid='case_r', name=u'结果列', need_run=True,
                                       cycle=3, last_start_time='2026-09-11 10:00:00',
                                       last_duration='12', last_result='Passed',
                                       last_errmsg='')
        TestData.objects.create(case=case, caseid='case_r', data_name=u'场景1')
        out = export_excel(self._p('r.xlsx'))
        import_excel(out, clear_first=True)

        c2 = TestCase.objects.get(tcid='case_r')
        self.assertEqual(c2.cycle, 3)
        self.assertEqual(c2.last_start_time, '2026-09-11 10:00:00')
        self.assertEqual(c2.last_duration, '12')
        self.assertEqual(c2.last_result, 'Passed')

    def test_step_values_are_written_into_operation_value_column(self):
        """所有关键字的数据都落在 TestSteps 的「操作值」列。"""
        TestCase.objects.create(tcid='case_v', name=u'值', need_run=True)
        out = self._seed()
        ws = load_workbook(out)[STEP_SHEET]
        header = [c.value for c in ws[1]]
        idx = header.index(u'操作值')
        vals = [[c.value for c in r][idx] for r in ws.iter_rows(min_row=2)]
        self.assertIn('{input1}', vals)
        self.assertIn(u'翼课网', vals)   # 期望值从 TestDatas 迁到了步骤里

    def test_legacy_three_sheet_file_is_still_importable(self):
        """旧的三表文件照样能导进来（值会被迁进步骤）。"""
        xlsx = build_xlsx(self._p('legacy.xlsx'), [sample_case()],
                          sample_steps(), sample_datas())
        stat = import_excel(xlsx)
        self.assertEqual(stat['cases'], 1)
        self.assertEqual(stat['steps'], 2)
        self.assertGreaterEqual(stat.get('migrated', 0), 1)
        self.assertEqual(
            TestStep.objects.get(case__tcid='case_a', step_no=2).value, u'翼课网')

    def test_import_without_datas_sheet_creates_one_data_row(self):
        """没有 TestDatas 的文件导入后，每个用例自动补一条数据行（引擎需要）。"""
        wb = Workbook()
        ws = wb.active
        ws.title = SUIT_SHEET
        _write(ws, SUIT_HEADER, [sample_case()])
        _write(wb.create_sheet(STEP_SHEET), STEP_HEADER, sample_steps())
        p = self._p('twosheets.xlsx')
        wb.save(p)

        import_excel(p)
        self.assertEqual(TestCase.objects.count(), 1)
        self.assertEqual(TestData.objects.count(), 1)
        self.assertEqual(TestStep.objects.count(), 2)


# ---------------------------------------------------------------------------
# 不需要数据的关键字：不给输入框
# ---------------------------------------------------------------------------

class NoValueKeywordTests(DjangoTestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('tester2', 't2@example.com', 'pwd12345')
        self.client.force_login(self.user)
        self.case = TestCase.objects.create(tcid='case_k', name=u'关键字', need_run=True)
        TestData.objects.create(case=self.case, caseid='case_k', data_name=u'场景1')

    def _save(self, rows):
        data = {'s_desc': [], 's_kw': [], 's_type': [], 's_expr': [], 's_run': [], 's_data': []}
        for desc, kw, lt, expr, val in rows:
            data['s_desc'].append(desc)
            data['s_kw'].append(kw)
            data['s_type'].append(lt)
            data['s_expr'].append(expr)
            data['s_run'].append('y')
            data['s_data'].append(val)
        return self.client.post(reverse('cases:steps_save', args=[self.case.pk]), data)

    def _body(self):
        html = self.client.get(
            reverse('cases:case_detail', args=[self.case.pk])).content.decode('utf-8')
        return html.split('id="stepBody"', 1)[1].split('</tbody>')[0]

    def test_no_value_keywords_render_dash_instead_of_input(self):
        self._save([(u'点一下', 'click', 'id', 'btn', ''),
                    (u'最大化', 'maxwindow', '', '', ''),
                    (u'输入', 'input', 'id', 'u1', 'admin')])
        body = self._body()
        self.assertEqual(body.count('<tr data-kind='), 3)
        # 前两行不给文本框，只留隐藏域占位以维持行序
        self.assertEqual(body.count('type="hidden" name="s_data"'), 2)
        self.assertEqual(body.count('type="text" name="s_data"'), 1)
        self.assertIn(u'该关键字不需要数据', body)

    def test_every_row_still_posts_one_data_field(self):
        """无论是否显示输入框，每行都提交一个 s_data，保证与 s_desc 一一对应。"""
        self._save([(u'点一下', 'click', 'id', 'btn', ''),
                    (u'输入', 'input', 'id', 'u1', 'admin'),
                    (u'等待', 'sleep', '', '', '2')])
        self.assertEqual(
            list(TestStep.objects.filter(case=self.case).order_by('step_no')
                 .values_list('keyword', 'value')),
            [(u'click', u''), (u'input', u'admin'), (u'sleep', u'2')],
        )


# ---------------------------------------------------------------------------
# 复查时补的回归护栏：这几个坑都是「改完当时没炸、过一阵才发现」的类型
# ---------------------------------------------------------------------------

class ReimportIdempotentTests(TmpDirMixin, DjangoTestCase):
    """导入必须可重复执行 —— 导两次不能把数据行 / 步骤翻倍。"""

    def test_reimport_legacy_file_does_not_duplicate_data_rows(self):
        """旧三表文件导两次：数据行仍为 1 组，否则会「勾 1 个跑 2 个」。"""
        xlsx = build_xlsx(self._p('legacy.xlsx'), [sample_case()],
                          sample_steps(), sample_datas())
        import_excel(xlsx)
        self.assertEqual(TestData.objects.count(), 1)
        import_excel(xlsx)
        self.assertEqual(TestData.objects.count(), 1, '重复导入不应让数据行翻倍')
        self.assertEqual(TestCase.objects.count(), 1)
        self.assertEqual(TestStep.objects.count(), 2)

    def test_reimport_new_format_keeps_single_data_row(self):
        """新两表文件导两次同样只保留一组数据。"""
        wb = Workbook()
        ws = wb.active
        ws.title = SUIT_SHEET
        _write(ws, SUIT_HEADER, [sample_case()])
        _write(wb.create_sheet(STEP_SHEET), STEP_HEADER, sample_steps())
        p = self._p('new.xlsx')
        wb.save(p)

        import_excel(p)
        import_excel(p)
        self.assertEqual(TestData.objects.count(), 1)
        self.assertEqual(TestStep.objects.count(), 2)


class StepHeaderAliasTests(TmpDirMixin, DjangoTestCase):
    """手工表格里把「操作值」写成「数据值」也要能读进来。"""

    def test_data_value_header_is_recognized(self):
        wb = Workbook()
        ws = wb.active
        ws.title = SUIT_SHEET
        _write(ws, SUIT_HEADER, [sample_case()])
        alias_header = [u'数据值' if h == u'操作值' else h for h in STEP_HEADER]
        alias_steps = [{(u'数据值' if k == u'操作值' else k): v for k, v in s.items()}
                       for s in sample_steps()]
        _write(wb.create_sheet(STEP_SHEET), alias_header, alias_steps)
        p = self._p('alias.xlsx')
        wb.save(p)

        import_excel(p)
        s1 = TestStep.objects.get(case__tcid='case_a', step_no=1)
        self.assertEqual(s1.value, '{input1}', '「数据值」应等价于「操作值」')


class CopyCaseTests(DjangoTestCase):
    """复制用例只搬步骤，不能顺带复制出第二组数据。"""

    def setUp(self):
        self.user = User.objects.create_superuser('tester3', 't3@example.com', 'pwd12345')
        self.client.force_login(self.user)
        self.src = TestCase.objects.create(tcid='case_src', name=u'来源', need_run=True)
        TestData.objects.create(case=self.src, caseid='case_src', data_name=u'场景1')
        TestStep.objects.create(case=self.src, step_no=1, keyword='input',
                                locate_type='id', locate_expr='u1', value='admin')

        self.dst = TestCase.objects.create(tcid='case_dst', name=u'目标', need_run=True)
        TestData.objects.create(case=self.dst, caseid='case_dst', data_name=u'场景1')

    def test_copy_only_steps_and_single_data_row(self):
        resp = self.client.post(reverse('cases:case_copy_from', args=[self.dst.pk]),
                                {'src_pk': self.src.pk, 'copy_steps': '1'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(list(self.dst.steps.values_list('keyword', 'value')),
                         [('input', 'admin')])
        self.assertEqual(self.dst.datas.count(), 1, '复制不应增加数据组数')

    def test_steps_ordering_is_stable_with_duplicate_step_no(self):
        """步骤序号重复时，顺序也必须稳定（ordering 带 id 兜底）。"""
        TestStep.objects.create(case=self.src, step_no=1, keyword='sleep', value='1')
        first = [s.keyword for s in self.src.steps.all()]
        second = [s.keyword for s in self.src.steps.all()]
        self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# 静态校验（②保存前校验 / 用例健康度）
# ---------------------------------------------------------------------------

def V(keyword, **kw):
    """构造一条待校验的步骤（dict 形式，字段与 TestStep 同名）。"""
    row = {'description': '描述', 'keyword': keyword, 'locate_type': '',
           'locate_expr': '', 'value': ''}
    row.update(kw)
    return row


class StepValidateTests(DjangoTestCase):

    def _err_fields(self, step):
        issues = validate_module.check_step(1, step)
        return sorted(i.field for i in issues if i.level == 'error')

    def test_empty_keyword_is_error(self):
        self.assertIn('kw', self._err_fields(V('', locate_type='id')))

    def test_missing_locate_is_error_for_element_keywords(self):
        self.assertIn('locate', self._err_fields(V('click')))
        self.assertIn('locate', self._err_fields(V('input', value='admin')))
        # 不需要定位的关键字不该被误报
        self.assertEqual(self._err_fields(V('maxwindow')), [])
        self.assertEqual(self._err_fields(V('sleep', value='2')), [])

    def test_missing_value_is_error(self):
        self.assertIn('value', self._err_fields(
            V('input', locate_type='id', locate_expr='u1')))
        self.assertIn('value', self._err_fields(
            V('assertEqual', locate_type='xpath', locate_expr='//t')))
        # assertTrue / assert_Is_Number 断言的是实际值本身，不需要期望值
        self.assertEqual(self._err_fields(
            V('assertTrue', locate_type='xpath', locate_expr='//t')), [])

    def test_sleep_must_be_number(self):
        self.assertIn('value', self._err_fields(V('sleep', value='两秒')))
        self.assertEqual(self._err_fields(V('sleep', value='2')), [])
        self.assertEqual(self._err_fields(V('sleep', value='0.5')), [])

    def test_xy_value_format(self):
        ok = dict(locate_type='xpath', locate_expr='//slider')
        self.assertIn('value', self._err_fields(V('CodeSlide', value='300', **ok)))
        self.assertIn('value', self._err_fields(V('CodeSlide', value='a,b', **ok)))
        self.assertEqual(self._err_fields(V('CodeSlide', value='300,0', **ok)), [])

    def test_assert_number_between_format(self):
        ok = dict(locate_type='xpath', locate_expr='//span')
        self.assertIn('value', self._err_fields(V('assert_Number_between', value='5', **ok)))
        self.assertEqual(self._err_fields(V('assert_Number_between', value='1-9', **ok)), [])

    def test_bool_assert_needs_true_or_false(self):
        self.assertIn('value', self._err_fields(
            V('assert_Is_Display', locate_type='xpath', locate_expr='//a', value='是')))
        self.assertEqual(self._err_fields(
            V('assert_Is_Display', locate_type='xpath', locate_expr='//a', value='True')), [])

    def test_case_level_checks(self):
        self.assertTrue(validate_module.check_steps([]))  # 无步骤必定报错
        only_click = [V('click', locate_type='id', locate_expr='b1')]
        issues = validate_module.check_steps(only_click)
        self.assertEqual(validate_module.count_issues(issues), (0, 1),
                         '用了元素操作却没开浏览器，应给一条 warn')


# ---------------------------------------------------------------------------
# 标签（③用例标签 + 按标签执行）
# ---------------------------------------------------------------------------

class TagTests(DjangoTestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('tagger', 'tg@example.com', 'pwd12345')
        self.client.force_login(self.user)

    def test_split_tags_handles_mixed_separators(self):
        self.assertEqual(TestCase.split_tags('冒烟, 回归 权限、x'),
                         ['冒烟', '回归', '权限', 'x'])
        self.assertEqual(TestCase.split_tags('冒烟,冒烟'), ['冒烟'])   # 去重
        self.assertEqual(TestCase.split_tags(''), [])

    def test_list_page_filters_by_tag(self):
        TestCase.objects.create(tcid='a1', name='A', tags='冒烟,回归')
        TestCase.objects.create(tcid='b1', name='B', tags='权限')
        TestCase.objects.create(tcid='c1', name='C')

        resp = self.client.get(reverse('cases:case_list'), {'tag': '冒烟'})
        self.assertEqual([c.tcid for c in resp.context['cases']], ['a1'])
        resp = self.client.get(reverse('cases:case_list'))
        self.assertEqual(len(resp.context['cases']), 3)

    def test_list_page_only_bad_filter(self):
        good = TestCase.objects.create(tcid='good', name='正常')
        TestStep.objects.create(case=good, step_no=1, keyword='maxwindow')
        bad = TestCase.objects.create(tcid='bad', name='缺关键字')
        TestStep.objects.create(case=bad, step_no=1, keyword='')

        resp = self.client.get(reverse('cases:case_list'), {'bad': '1'})
        self.assertEqual([c.tcid for c in resp.context['cases']], ['bad'])
        self.assertEqual(resp.context['total_bad'], 1)

    def test_list_page_health_filter(self):
        """健康度下拉：'' 全部 / ok 健康 / bad 不健康，老的 ?bad=1 继续认。"""
        good = TestCase.objects.create(tcid='good', name='正常')
        TestStep.objects.create(case=good, step_no=1, keyword='maxwindow')
        bad = TestCase.objects.create(tcid='bad', name='缺关键字')
        TestStep.objects.create(case=bad, step_no=1, keyword='')

        self.assertEqual([c.tcid for c in self.client.get(
            reverse('cases:case_list'), {'health': 'ok'}).context['cases']], ['good'])
        self.assertEqual([c.tcid for c in self.client.get(
            reverse('cases:case_list'), {'health': 'bad'}).context['cases']], ['bad'])
        # 旧链接兼容
        self.assertEqual([c.tcid for c in self.client.get(
            reverse('cases:case_list'), {'bad': '1'}).context['cases']], ['bad'])
        # 不健康计数要能正确回传给标题
        self.assertEqual(self.client.get(
            reverse('cases:case_list'), {'health': 'ok'}).context['total_bad'], 1)

    def test_list_page_has_health_select(self):
        page = self.client.get(reverse('cases:case_list')).content.decode()
        self.assertIn('name="health"', page)
        self.assertIn('value="ok"', page)
        self.assertIn('value="bad"', page)

    def test_edit_saves_tags(self):
        c = TestCase.objects.create(tcid='tg1', name='加标签')
        self.client.post(reverse('cases:case_edit', args=[c.pk]),
                         {'tcid': 'tg1', 'name': '加标签', 'tags': '冒烟,回归',
                          'tag_pick': ['权限'], 'cycle': '1', 'need_run': 'y'})
        c.refresh_from_db()
        self.assertEqual(c.tag_list, ['冒烟', '回归', '权限'])

    def test_tags_survive_export_import(self):
        pass  # 见 SlimExcelTests 的往返用例，标签列已并入「测试用例」sheet


class ScopeResolveTests(DjangoTestCase):
    """执行范围的四种写法都要能翻译成 tcid 列表。"""

    def setUp(self):
        TestCase.objects.create(tcid='c_smoke1', need_run=True, tags='冒烟')
        TestCase.objects.create(tcid='c_smoke2', need_run=True, tags='冒烟,回归')
        TestCase.objects.create(tcid='c_disabled', need_run=False, tags='冒烟')
        TestCase.objects.create(tcid='c_other', need_run=True, tags='权限')

    def test_all_enabled(self):
        self.assertIsNone(executor._resolve_scope('全部启用用例'))

    def test_single_case(self):
        self.assertEqual(executor._resolve_scope('CASE:c_other'), ['c_other'])

    def test_case_list(self):
        self.assertEqual(executor._resolve_scope('CASES:c_smoke1,c_other'),
                         ['c_smoke1', 'c_other'])

    def test_tag_scope_skips_disabled(self):
        scope = executor._resolve_scope('TAGS:冒烟')
        self.assertEqual(sorted(scope), ['c_smoke1', 'c_smoke2'],
                         '带标签但未启用的用例不应被拉进来')


class RunByTagTests(DjangoTestCase):
    """点「运行某标签」要真的发出一轮带 TAGS: 范围的执行（线程用 mock 挡住）。"""

    def setUp(self):
        self.user = User.objects.create_superuser('runner1', 'r1@example.com', 'pwd12345')
        self.client.force_login(self.user)
        TestCase.objects.create(tcid='tagged', need_run=True, tags='冒烟')

    def tearDown(self):
        # 线程被 mock 挡住，execute() 不会跑，这里必须手动把全局锁放掉，
        # 否则后续再发起执行会误判「已有任务在跑」。
        import runner.executor as ex
        ex.release_run_lock()
        ex._STATE['pk'] = None

    def test_run_by_tag_creates_task(self):
        from unittest import mock
        from runner.models import TaskRun
        with mock.patch('runner.executor.threading.Thread') as fake:
            resp = self.client.post(reverse('runner:run_start_tag'), {'tag': '冒烟'})
        self.assertEqual(resp.status_code, 302)
        task = TaskRun.objects.order_by('-pk').first()
        self.assertEqual(task.case_filter, 'TAGS:冒烟')

    def test_empty_tag_is_rejected(self):
        from runner.models import TaskRun
        self.client.post(reverse('runner:run_start_tag'), {'tag': ''})
        self.assertEqual(TaskRun.objects.count(), 0)

    def test_run_selected_uses_cases_scope(self):
        from unittest import mock
        from runner.models import TaskRun
        c2 = TestCase.objects.create(tcid='tagged2', need_run=True, tags='回归')
        with mock.patch('runner.executor.threading.Thread'):
            resp = self.client.post(reverse('runner:run_start_selected'),
                                    {'cids': [c2.pk]})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(TaskRun.objects.order_by('-pk').first().case_filter,
                         'CASES:tagged2')


# ---------------------------------------------------------------------------
# 导出 Excel：只导出列表上勾选的那些
# ---------------------------------------------------------------------------

class ExportCheckedTests(DjangoTestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('exporter', 'ex@example.com', 'pwd12345')
        self.client.force_login(self.user)
        self.a = TestCase.objects.create(tcid='ea', name='A')
        self.b = TestCase.objects.create(tcid='eb', name='B')
        TestStep.objects.create(case=self.a, step_no=1, keyword='maxwindow')
        TestStep.objects.create(case=self.b, step_no=1, keyword='maxwindow')

    def _download(self, **params):
        resp = self.client.get(reverse('cases:excel_export'), params)
        self.assertEqual(resp.status_code, 200)
        fd, path = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        with open(path, 'wb') as f:
            for chunk in resp.streaming_content:
                f.write(chunk)
        try:
            wb = load_workbook(path)
            # 本机 openpyxl 较老，iter_rows 不支持 values_only，手动取 cell.value
            def col(sheet):
                return [row[0].value
                        for row in sheet.iter_rows(min_row=2) if row[0].value is not None]
            suite = col(wb[SUIT_SHEET])
            step_tcids = col(wb[STEP_SHEET])
        finally:
            os.remove(path)
        return suite, step_tcids

    def test_export_only_checked(self):
        """?ids= 只带勾选的 pk：用例表和步骤表都只出现这些。"""
        suite, step_tcids = self._download(ids='%d' % self.a.pk)
        self.assertEqual(suite, ['ea'])
        self.assertEqual(step_tcids, ['ea'])

    def test_export_multiple_checked(self):
        suite, step_tcids = self._download(ids='%d,%d' % (self.b.pk, self.a.pk))
        self.assertEqual(sorted(suite), ['ea', 'eb'])          # 导出内部按 tcid 排序
        self.assertEqual(sorted(set(step_tcids)), ['ea', 'eb'])

    def test_export_without_ids_still_exports_all(self):
        """不带 ids（直接访问 / 命令行）保持全量，属于兜底路径。"""
        suite, _ = self._download()
        self.assertEqual(sorted(suite), ['ea', 'eb'])

    def test_page_export_button_collects_checked_ids(self):
        page = self.client.get(reverse('cases:case_list')).content.decode()
        self.assertIn('exportChecked()', page)
        self.assertIn('checkedIds()', page)


# ---------------------------------------------------------------------------
# 步骤变更历史（⑤快照与还原）
# ---------------------------------------------------------------------------

class StepSnapshotTests(DjangoTestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('snapper', 'sp@example.com', 'pwd12345')
        self.client.force_login(self.user)
        self.case = TestCase.objects.create(tcid='snap_case', name='有历史的用例')
        TestData.objects.create(case=self.case, caseid='snap_case', runmode='y')

    def _save(self, *rows):
        """模拟页面整表提交：rows 为 [(描述, 关键字, 定位方式, 定位表达式, 操作值)]。"""
        post = {'s_desc': [], 's_kw': [], 's_type': [], 's_expr': [],
                's_data': [], 's_run': []}
        for desc, kw, t, e, v in rows:
            post['s_desc'].append(desc)
            post['s_kw'].append(kw)
            post['s_type'].append(t)
            post['s_expr'].append(e)
            post['s_data'].append(v)
            post['s_run'].append('y')
        return self.client.post(reverse('cases:steps_save', args=[self.case.pk]), post)

    def test_saving_keeps_content_even_when_invalid(self):
        """校验再严也不能丢用户输入 —— steps_save 是先删后建，拦下来就等于清空。"""
        resp = self._save(('点一下', 'click', '', '', ''))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.case.steps.count(), 1)
        self.assertEqual(self.case.steps.first().keyword, 'click')

    def test_each_save_takes_a_snapshot(self):
        # 第一次保存：拍到的是「空表」，说明快照确实是改动前的状态
        self._save(('输入', 'input', 'id', 'u1', 'admin'))
        self.assertEqual(self.case.snapshots.count(), 1)
        self.assertEqual(self.case.snapshots.first().step_count, 0)

        self._save(('输入', 'input', 'id', 'u1', 'root'),
                   ('点', 'click', 'id', 'btn', ''))
        self.assertEqual(self.case.snapshots.count(), 2)
        snap = self.case.snapshots.order_by('-created_at').first()
        self.assertEqual(snap.step_count, 1)
        self.assertEqual(snap.payload[0]['value'], 'admin')

    def test_restore_rolls_back_steps(self):
        self._save(('输入', 'input', 'id', 'u1', 'admin'))
        self._save(('改坏了', 'input', '', '', ''))
        snap = self.case.snapshots.order_by('-created_at').first()  # 改坏之前那版

        self.client.post(reverse('cases:steps_restore', args=[self.case.pk, snap.pk]))
        steps = list(self.case.steps.all())
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].value, 'admin')
        self.assertEqual(steps[0].locate_expr, 'u1')
        # 还原前又给「改坏了」那版留了档，所以还能再还原回来
        self.assertEqual(self.case.snapshots.count(), 3)

    def test_snapshot_keeps_only_last_n(self):
        for i in range(StepSnapshot.KEEP_LAST + 5):
            StepSnapshot.take(self.case)
        self.assertEqual(self.case.snapshots.count(), StepSnapshot.KEEP_LAST)


# ---------------------------------------------------------------------------
# 执行记录筛选与分页（⑨）
# ---------------------------------------------------------------------------

class RunListPageTests(DjangoTestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('viewer', 'v@example.com', 'pwd12345')
        self.client.force_login(self.user)
        for i in range(25):
            TaskRun.objects.create(status=TaskRun.STATUS_PASSED if i % 2 else
                                   TaskRun.STATUS_FAILED,
                                   case_filter='CASE:c%s' % i)

    def test_first_page_size_and_second_page(self):
        resp = self.client.get(reverse('runner:run_list'))
        self.assertEqual(len(resp.context['runs']), 20)
        self.assertTrue(resp.context['page_obj'].has_next())

        resp2 = self.client.get(reverse('runner:run_list'), {'page': 2})
        self.assertEqual(len(resp2.context['runs']), 5)

    def test_status_filter(self):
        resp = self.client.get(reverse('runner:run_list'),
                               {'status': TaskRun.STATUS_FAILED})
        self.assertEqual(resp.context['paginator'].count, 13)
        for r in resp.context['runs']:
            self.assertEqual(r.status, TaskRun.STATUS_FAILED)

    def test_keyword_filter(self):
        resp = self.client.get(reverse('runner:run_list'), {'q': 'c12'})
        self.assertEqual([r.case_filter for r in resp.context['runs']], ['CASE:c12'])


# ---------------------------------------------------------------------------
# 列表页「勾选 = 启用」：只留一种状态，勾了 A 却跑「全部启用」这种歧义不再存在
# ---------------------------------------------------------------------------

class EnabledCheckboxTests(DjangoTestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('editor', 'e@example.com', 'pwd12345')
        self.client.force_login(self.user)
        self.a = TestCase.objects.create(tcid='a', name='A', need_run=True)
        self.b = TestCase.objects.create(tcid='b', name='B', need_run=False)
        self.c = TestCase.objects.create(tcid='c', name='C', need_run=True)

    def test_save_enable_state(self):
        """提交里出现的全部 row_pk 参与结算，没勾选的置为停用。"""
        resp = self.client.post(reverse('cases:case_enable_save'), {
            'row_pk': [self.a.pk, self.b.pk, self.c.pk],
            'enabled': [self.b.pk],   # 只勾了 B
        })
        self.assertEqual(resp.status_code, 302)
        state = dict(TestCase.objects.values_list('tcid', 'need_run'))
        self.assertEqual(state, {'a': False, 'b': True, 'c': False})

    def test_save_keeps_cases_not_on_the_page(self):
        """筛选状态下提交，只有列表里出现的行会被改动。"""
        self.client.post(reverse('cases:case_enable_save'), {
            'row_pk': [self.a.pk], 'enabled': [],
        })
        self.assertFalse(TestCase.objects.get(tcid='a').need_run)
        self.assertTrue(TestCase.objects.get(tcid='c').need_run)

    def test_open_redirect_is_rejected(self):
        resp = self.client.post(reverse('cases:case_enable_save'), {
            'row_pk': [self.a.pk], 'next': '//evil.com/x',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/cases/', resp['Location'])

    def test_run_enabled_runs_only_checked(self):
        resp = self.client.post(reverse('cases:case_run_enabled'), {
            'row_pk': [self.a.pk, self.b.pk, self.c.pk],
            'enabled': [self.a.pk, self.c.pk],
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        task = TaskRun.objects.latest('pk')
        self.assertEqual(task.case_filter, 'CASES:a,c')
        # 「运行」是一次性动作：勾选状态本身也同步落盘了
        self.assertEqual(set(TestCase.objects.filter(need_run=True)
                             .values_list('tcid', flat=True)), {'a', 'c'})
        executor.release_run_lock()   # start_run 抢到的锁在这里释放，避免污染其它用例

    def test_list_header_has_select_all_and_invert(self):
        """表头两样都要有：全选 checkbox 控制全选/全不选，反选按钮翻转当前选择。"""
        page = self.client.get(reverse('cases:case_list')).content.decode()
        self.assertIn('id="selAll"', page)
        self.assertIn('selectAll(this.checked)', page)
        self.assertIn('invertSel()', page)
        # 半选态：只勾了一部分时表头框显示 indeterminate，而不是「已全选」
        self.assertIn('head.indeterminate', page)

    def test_save_enable_state_ajax_returns_json(self):
        """列表上已经没有「保存」按钮了 —— 勾选一变就 fetch 提交，这里要回 JSON。"""
        resp = self.client.post(reverse('cases:case_enable_save'), {
            'row_pk': [self.a.pk, self.b.pk, self.c.pk],
            'enabled': [self.b.pk, self.c.pk],
            'ajax': '1',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content.decode())
        self.assertEqual(data, {'ok': True, 'enabled': 2, 'disabled': 1})
        self.assertEqual(set(TestCase.objects.filter(need_run=True)
                             .values_list('tcid', flat=True)), {'b', 'c'})

    def test_run_enabled_without_selection(self):
        resp = self.client.post(reverse('cases:case_run_enabled'),
                                {'row_pk': [self.a.pk]}, follow=True)
        self.assertEqual(TaskRun.objects.count(), 0)
        self.assertTrue(any('先' in str(m) for m in resp.context['messages']))


# ---------------------------------------------------------------------------
# 变更历史的「变更操作」：要能说清楚改了哪一步、哪个字段
# ---------------------------------------------------------------------------

class SnapshotDiffTests(DjangoTestCase):

    @staticmethod
    def _row(desc, kw, value=''):
        return {'desc': desc, 'kw': kw, 'type': 'id', 'expr': 'u1',
                'value': value, 'run': 'y'}

    def test_detects_added_step(self):
        old = [self._row('输入', 'input', 'admin')]
        new = old + [self._row('点登录', 'click')]
        diff = StepSnapshot.diff_steps(old, new)
        self.assertEqual([(d['type'], d['no']) for d in diff], [('add', 2)])

    def test_detects_removed_step(self):
        old = [self._row('输入', 'input'), self._row('点登录', 'click')]
        diff = StepSnapshot.diff_steps(old, old[:1])
        self.assertEqual([(d['type'], d['no']) for d in diff], [('del', 2)])

    def test_modified_step_points_at_the_field(self):
        old = [self._row('输入', 'input', 'admin')]
        new = [self._row('输入', 'input', 'root')]
        diff = StepSnapshot.diff_steps(old, new)
        self.assertEqual(len(diff), 1)
        self.assertEqual((diff[0]['type'], diff[0]['field']), ('mod', '操作值'))
        self.assertEqual((diff[0]['old'], diff[0]['new']), ('admin', 'root'))

    def test_insert_in_the_middle_does_not_look_like_full_rewrite(self):
        """中间插一步时，后面的步骤不该被报告成「全都变了」。"""
        old = [self._row('1', 'input'), self._row('2', 'click'), self._row('3', 'sleep')]
        new = [old[0], self._row('新增', 'maxwindow')] + old[1:]
        diff = StepSnapshot.diff_steps(old, new)
        self.assertEqual([(d['type'], d['no']) for d in diff], [('add', 2)])

    def test_identical_versions_report_nothing(self):
        rows = [self._row('输入', 'input', 'admin')]
        self.assertEqual(StepSnapshot.diff_steps(rows, rows), [])

    def test_detail_page_shows_change_column(self):
        """详情页要能算出每一份快照相对上一版的变化。"""
        case = TestCase.objects.create(tcid='d', name='D')
        TestStep.objects.create(case=case, step_no=1, keyword='input',
                                locate_type='id', locate_expr='u1', value='admin')
        StepSnapshot.take(case, StepSnapshot.REASON_SAVE)
        step = case.steps.first()
        step.value = 'root'
        step.save()

        from django.test import Client
        c = Client()
        c.force_login(User.objects.create_superuser('v2', 'v2@example.com', 'pwd12345'))
        page = c.get(reverse('cases:case_detail', args=[case.pk]))
        snaps = page.context['snapshots']
        self.assertEqual(len(snaps), 1)
        self.assertEqual([(x['type'], x['field']) for x in snaps[0].change_items],
                         [('mod', '操作值')])
