'''Excel 导入 / 导出。

现在的 Excel 只有两张表（与 Web 页面一一对应）：
    测试用例：TCID / 用例名称 / 用例描述 / 是否需要执行 / 循环次数 /
              开始时间 / 执行时间 / 耗时 / 结果 / 错误信息
    TestSteps：TCID / 步骤序号 / 测试步骤描述 / 关键字 / 定位方式 / 定位表达式 / 操作值 / 是否需要执行

所有步骤要用的数据都写在 TestSteps 的「操作值」列里 —— 以前它们散落在
TestDatas 的 Input1..8 / selector1..8 / verifiedcodeXY / ExpectedResult 里，
槽位有限且难对应，现已全部整合，TestDatas sheet 不再导出。

导入仍兼容旧的三表文件（含 TestDatas sheet）：读到就把历史值迁进步骤的「操作值」，
并把 Cycle / StartTime / RunTime / Result / ErrMsg 归并到用例上，保证不丢数据。
'''
import os
from datetime import datetime

from django.conf import settings
from openpyxl import Workbook, load_workbook

from .models import TestCase, TestStep, TestData
from .stepvalues import INPUT_SLOTS, SELECTOR_SLOTS, migrate_data_row_to_steps, \
    steps_with_values

SUIT_SHEET = '测试用例'
STEP_SHEET = 'TestSteps'
DATA_SHEET = 'TestDatas'      # 仅用于读取历史文件，导出时不再生成

SUIT_HEADER = ['TCID', '用例名称', '用例描述', '是否需要执行', '标签',
               '循环次数', '开始时间', '执行时间', '耗时', '结果', '错误信息']
STEP_HEADER = ['TCID', '步骤序号', '测试步骤描述', '关键字', '操作元素定位方式',
               '操作元素定位表达式', '操作值', '是否需要执行']
# 旧文件 / 手工表格里可能出现的同义表头。
# 方向必须是「标准列名 -> 同义列名列表」：_aliased() 拿标准列名去反查同义列，
# 写反了会静默取不到值（现在统一叫「操作值」，但历史手工表里可能写成「数据值」）。
STEP_HEADER_ALIASES = {'操作值': ('数据值', '期望值', 'value')}

DATA_HEADER = ['TCID', 'CaseId', 'Runmode', 'Data_name', 'Summary',
               'Input1', 'Input2', 'Input3', 'Input4', 'Input5', 'Input6', 'Input7', 'Input8',
               'verifiedcodeXY',
               'selector1', 'selector2', 'selector3', 'selector4',
               'selector5', 'selector6', 'selector7', 'selector8',
               'Type', 'Expression', 'ExpectedResult', 'Cycle',
               'ErrMsg', 'Result', 'StartTime', 'RunTime']

_TIME_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M:%S',
                 '%Y/%m/%d %H:%M', '%Y-%m-%d')


def default_xlsx_path():
    return os.path.join(str(settings.DATA_DIR), 'testdata.xlsx')


def _cell(row, key):
    """按表头取值；空值统一转空串"""
    v = row.get(key)
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'y' if v else 'n'
    return str(v).strip() if isinstance(v, str) else v


def _yn(v):
    return str(v).strip().lower() in ('y', 'yes', 'true', '1')


def _bool_cell(row, key, default=True):
    v = row.get(key)
    if v is None or str(v).strip() == '':
        return default
    return _yn(str(v))


def _aliased(row, key, aliases=None):
    """按表头取值，支持同义表头（如「数据值」等价于「操作值」）。"""
    v = row.get(key)
    if (v is None or str(v).strip() == '') and aliases:
        for alias in aliases.get(key, ()):
            av = row.get(alias)
            if av is not None and str(av).strip() != '':
                return av
    return v


def _int_cell(row, key, default=1):
    try:
        return int(str(_cell(row, key) or '').strip() or default)
    except (TypeError, ValueError):
        return default


def _aware(dt):
    """naive datetime -> 当前时区的 aware datetime。

    USE_TZ=True 时直接把 naive 时间写进 DateTimeField，Django 会按 UTC 解释，
    导出时再转回本地就会平白差 8 小时（曾踩过：执行时间比开始时间早 8 小时）。
    """
    if dt is None:
        return None
    try:
        from django.utils import timezone
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone.get_default_timezone())
    except Exception:
        pass
    return dt


def _time_cell(row, key):
    """解析时间列；已是 datetime 直接用（并补时区），字符串按常见格式尝试。"""
    v = row.get(key)
    if v is None or str(v).strip() == '':
        return None
    if isinstance(v, datetime):
        return _aware(v)
    s = str(v).strip()
    for fmt in _TIME_FORMATS:
        try:
            return _aware(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# 导入
# --------------------------------------------------------------------------

def _rows_of(ws):
    """返回 [{表头: 值}]，跳过空行"""
    rows = list(ws.rows)
    if not rows:
        return []
    header = [c.value for c in rows[0]]
    out = []
    for r in rows[1:]:
        vals = [c.value for c in r]
        if not any(v not in (None, '') for v in vals):
            continue
        d = {}
        for h, v in zip(header, vals):
            if h is None:
                continue
            d[str(h).strip()] = v
        out.append(d)
    return out


def import_excel(xlsx_path=None, clear_first=False):
    """把 Excel 里的三张表导入数据库。返回统计 dict。"""
    xlsx_path = xlsx_path or default_xlsx_path()
    if not os.path.exists(xlsx_path):
        raise FileNotFoundError('找不到文件: %s' % xlsx_path)

    wb = load_workbook(xlsx_path, data_only=True)
    if SUIT_SHEET not in wb.sheetnames:
        raise ValueError('缺少 sheet: %s（现有: %s）' % (SUIT_SHEET, wb.sheetnames))

    if clear_first:
        TestStep.objects.all().delete()
        TestData.objects.all().delete()
        TestCase.objects.all().delete()

    # 1) 用例（执行结果列也在这一张表里）
    case_map = {}
    suit_rows = _rows_of(wb[SUIT_SHEET])
    n_case = 0
    for row in suit_rows:
        tcid = str(_cell(row, 'TCID') or '').strip()
        if not tcid:
            continue
        obj = TestCase.objects.filter(tcid=tcid).first() or TestCase(tcid=tcid)
        obj.name = str(_cell(row, '用例名称') or tcid)
        obj.description = str(_cell(row, '用例描述') or '')
        obj.need_run = _bool_cell(row, '是否需要执行', default=False)
        obj.cycle = _int_cell(row, '循环次数', default=1) or 1
        obj.tags = str(_cell(row, '标签') or '').strip()
        obj.last_start_time = str(_cell(row, '开始时间') or '')
        obj.last_duration = str(_cell(row, '耗时') or '')
        obj.last_result = str(_cell(row, '结果') or '')
        obj.last_errmsg = str(_cell(row, '错误信息') or '')
        t = _time_cell(row, '执行时间')
        if t is not None:
            obj.last_run_time = t
        obj.save()
        case_map[tcid] = obj
        n_case += 1

    # 2) 步骤（先清旧步骤再重建，保证顺序可控）
    n_step = 0
    if STEP_SHEET in wb.sheetnames:
        seen = set()
        step_rows = _rows_of(wb[STEP_SHEET])
        for row in step_rows:
            tcid = str(_cell(row, 'TCID') or '').strip()
            case = case_map.get(tcid)
            if case is None:
                continue
            if tcid not in seen:
                case.steps.all().delete()
                seen.add(tcid)
            try:
                no = int(_cell(row, '步骤序号') or 0)
            except (TypeError, ValueError):
                no = 0
            raw_value = _aliased(row, '操作值', STEP_HEADER_ALIASES)
            TestStep.objects.create(
                case=case,
                step_no=no,
                description=str(_cell(row, '测试步骤描述') or ''),
                keyword=str(_cell(row, '关键字') or ''),
                locate_type=str(_cell(row, '操作元素定位方式') or ''),
                locate_expr=str(_cell(row, '操作元素定位表达式') or ''),
                value='' if raw_value is None else str(raw_value),
                need_run=_bool_cell(row, '是否需要执行', default=True),
            )
            n_step += 1

    # 3) 测试数据（旧格式兼容）
    #    新导出的文件没有这一张表；读到了就按旧规则入库，随后把值迁进步骤。
    n_data = 0
    if DATA_SHEET in wb.sheetnames:
        data_rows = _rows_of(wb[DATA_SHEET])
        # 旧格式是「先建后不管」的追加语义，同一个文件导两次就会把数据行翻倍，
        # 执行时表现为「勾了 1 个用例却跑出 2 个测试项」。
        # 这里改成与步骤一致：本次涉及的用例，旧数据行先清掉再重建，保证可重复导入。
        TestData.objects.filter(case__in=list(case_map.values())).delete()
        for row in data_rows:
            tcid = str(_cell(row, 'TCID') or '').strip()
            case = case_map.get(tcid)
            if case is None:
                continue
            caseid = str(_cell(row, 'CaseId') or '')
            try:
                cycle = int(_cell(row, 'Cycle') or 1)
            except (TypeError, ValueError):
                cycle = 1
            kw = {
                'case': case,
                'caseid': caseid,
                'runmode': str(_cell(row, 'Runmode') or 'y') or 'y',
                'data_name': str(_cell(row, 'Data_name') or ''),
                'summary': str(_cell(row, 'Summary') or ''),
                'verifiedcode_xy': str(_cell(row, 'verifiedcodeXY') or ''),
            }
            for n in INPUT_SLOTS:
                kw['input%d' % n] = str(_cell(row, 'Input%d' % n) or '')
            for n in SELECTOR_SLOTS:
                kw['selector%d' % n] = str(_cell(row, 'selector%d' % n) or '')
            TestData.objects.create(
                **kw,
                assert_type=str(_cell(row, 'Type') or ''),
                expression=str(_cell(row, 'Expression') or ''),
                expected_result=str(_cell(row, 'ExpectedResult') or ''),
                cycle=cycle,
                errmsg=str(_cell(row, 'ErrMsg') or ''),
                result=str(_cell(row, 'Result') or ''),
                start_time=str(_cell(row, 'StartTime') or ''),
                run_time=str(_cell(row, 'RunTime') or ''),
            )
            n_data += 1

    # 4) 收尾：保证每个用例有一条数据行；把历史值迁进步骤；结果列归并到用例
    n_migrated = 0
    for tcid, case in case_map.items():
        if not case.datas.exists():
            TestData.objects.create(
                case=case, caseid=case.tcid, runmode='y',
                data_name='场景1', cycle=case.cycle or 1,
            )
        d = case.datas.first()
        if d is not None:
            # 旧文件的 Cycle / 结果列在 TestDatas 里，用例上没有就补过来
            touched = False
            if not (case.cycle or 0) or case.cycle == 1:
                if d.cycle and d.cycle != 1:
                    case.cycle = d.cycle
                    touched = True
            for src, dst in (('start_time', 'last_start_time'),
                             ('run_time', 'last_duration'),
                             ('result', 'last_result'),
                             ('errmsg', 'last_errmsg')):
                if not (getattr(case, dst) or '').strip() and (getattr(d, src) or '').strip():
                    setattr(case, dst, str(getattr(d, src)))
                    touched = True
            if touched:
                case.save()
        n_migrated += migrate_data_row_to_steps(case)

    return {'cases': n_case, 'steps': n_step, 'datas': n_data,
            'migrated': n_migrated}


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------

def _write_rows(ws, header, rows):
    ws.append(header)
    for r in rows:
        ws.append(r)


def export_excel(out_path=None, cases=None):
    """导出两张表：测试用例 + TestSteps —— 与 Web 页面看到的内容一致。

    TestDatas sheet 不再导出：它原有的数据列已整合进步骤的「操作值」，
    结果列（Cycle / StartTime / RunTime / Result / ErrMsg）已整合进「测试用例」。

    cases：可传入指定用例的 queryset / 列表（列表页勾选导出用），
    不传则导出全部（命令行、备份等场景仍走这条）。
    """
    out_path = out_path or default_xlsx_path().replace('.xlsx', '_export.xlsx')
    wb = Workbook()
    ws = wb.active
    ws.title = SUIT_SHEET

    if cases is None:
        cases = TestCase.objects.all().order_by('tcid')
    cases = list(cases)
    _write_rows(ws, SUIT_HEADER, [_suit_row(c) for c in cases])

    s = wb.create_sheet(STEP_SHEET)
    step_rows = []
    for c in cases:
        steps = list(c.steps.all().order_by('step_no', 'id'))
        for st, _kind, val in steps_with_values(steps, c.datas.first()):
            step_rows.append([
                c.tcid, st.step_no, st.description, st.keyword,
                st.locate_type, st.locate_expr, val,
                'y' if st.need_run else 'n',
            ])
    _write_rows(s, STEP_HEADER, step_rows)

    wb.save(out_path)
    return out_path


def _local_time(dt):
    """把 UTC 存储的 datetime 转成本地时区再格式化（导出用）。"""
    if not dt:
        return ''
    try:
        from django.utils import timezone
        if timezone.is_aware(dt):
            dt = timezone.localtime(dt)
    except Exception:
        pass
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def _suit_row(c):
    """一条用例 -> 「测试用例」sheet 的一行（结果列优先用例层，回退数据行）。"""
    d = c.datas.first()
    return [
        c.tcid,
        c.name,
        c.description,
        'y' if c.need_run else 'n',
        c.tags or '',
        c.cycle or 1,
        c.last_start_time or (d.start_time if d else ''),
        # last_run_time 是 UTC 存储的 aware datetime，导出前先转回本地时区，
        # 否则表里会比「开始时间」早 8 小时，看着像错了。
        _local_time(c.last_run_time),
        c.last_duration or (d.run_time if d else ''),
        c.last_result or (d.result if d else ''),
        c.last_errmsg or (d.errmsg if d else ''),
    ]
