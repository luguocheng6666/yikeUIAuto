'''数据源适配层 —— 让执行引擎可以在「Excel」与「数据库」之间无感知切换。

背景
----
framework/keywordsFrameword.py 只通过两个约定使用数据源：

    for row in ds.get_xls(sheetName, **conditions):   # yield dict，键为表头小写
        ...
    ds.write_data(rowno, colno, content, font=..., msg=...)

其中 DataSheet(TestDatas) 的 Result/ErrMsg/StartTime/RunTime 四列，
在 Excel 实现里被替换成 "行号,列号" 字符串，引擎据此回写结果。

本模块让数据库实现沿用同样的协议：
    - "行号" 用 TestData 主键 pk 承担
    - "列号" 用 WRITE_FIELDS 的下标（1-based）承担
于是 write_data(row, col, val) 可以反解成「更新某条 TestData 的某个字段」。

使用方式：设置环境变量 YIKEUI_DATA_SOURCE=db（默认 excel，保持原行为不变）。
'''
import os

# 可被后台线程改写，用于限定本次执行范围（tcid 列表）
_RUN_SCOPE = None

# 「停止执行」标志：Web 端点停止后由后台线程置位，引擎每执行一步检查一次，
# 置位后当前用例会跳过剩余步骤、后续用例不再启动（命令行模式永远为 False）。
_CANCEL_REQUESTED = False


def set_run_scope(tcids):
    """限定本次只执行这些 TCID 的用例；传 None 表示不限制。"""
    global _RUN_SCOPE
    _RUN_SCOPE = list(tcids) if tcids else None


def get_run_scope():
    return _RUN_SCOPE


def request_cancel():
    """请求停止当前执行（只置标志，真正中断由引擎在步骤边界处完成）。"""
    global _CANCEL_REQUESTED
    _CANCEL_REQUESTED = True


def clear_cancel():
    """开始新一轮执行前复位停止标志。"""
    global _CANCEL_REQUESTED
    _CANCEL_REQUESTED = False


def is_cancel_requested():
    return _CANCEL_REQUESTED


def source_mode():
    """当前数据源模式：'db' 或 'excel'"""
    return os.environ.get('YIKEUI_DATA_SOURCE', 'excel').strip().lower()


def use_db():
    return source_mode() == 'db'


def _s(v):
    """引擎会对字段调用 .lower()，所以所有值统一转成字符串。"""
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'y' if v else 'n'
    return str(v)


def _yn(v):
    """Excel 里 '是否需要执行' 是 y/n，数据库是 Boolean。"""
    s = _s(v).strip().lower()
    if s in ('y', 'yes', 'true', '1'):
        return 'y'
    return 'n'


def _bool(v):
    s = _s(v).strip().lower()
    return s in ('y', 'yes', 'true', '1')


# DataSheet 中会被回写的四个字段，顺序即「列号」（1-based）。
# 注意：键名必须与引擎读取时用的名字完全一致 —— 引擎是从 Excel 表头 lower() 来的，
# 即 result / errmsg / starttime / runtime（无下划线），而不是模型字段名 start_time/run_time。
# 真正的模型字段名通过 _FIELD_TO_MODEL 映射。
WRITE_FIELDS = ['result', 'errmsg', 'starttime', 'runtime']

_FIELD_TO_MODEL = {
    'result': 'result',
    'errmsg': 'errmsg',
    'starttime': 'start_time',
    'runtime': 'run_time',
}


def x(header, raw_value):
    """表头 -> 小写列名（中文 .lower() 无副作用，与原 Excel 行为一致）"""
    return header.lower(), raw_value


class DBDataSource(object):
    '''数据库数据源，接口与 framework.excelutil.excel_readWrite 保持一致。

    注意：所有查询都延迟到 get_xls() 时才发生，
    因为本对象会在 keywordsFrameword 模块顶层被实例化，那时可能还没准备好。
    '''

    def __init__(self, xls_name=None, sheetName=None):
        self.xls_name = xls_name
        self.sheetName = sheetName

    # ---------- 读取 ----------

    def get_xls(self, sheetName, **conditions):
        """生成器，产出 dict。键与 Excel 表头 lowercase 后完全一致。"""
        from keywordsDriver.excelKey import SuitSheet, DataSheet, StepSheet

        rows = self._load(sheetName)
        # conditions 的键做 lower 处理，与 excelutil 一致
        cond = {}
        for k, v in conditions.items():
            cond[k.lower()] = _s(v).lower()

        for row in rows:
            if cond:
                hit = True
                for k, v in cond.items():
                    if k not in row or _s(row[k]).lower() != v:
                        hit = False
                        break
                if not hit:
                    continue
            yield row

    def _load(self, sheetName):
        from keywordsDriver.excelKey import SuitSheet, DataSheet, StepSheet
        if sheetName == SuitSheet:
            return self._suit_rows()
        if sheetName == StepSheet:
            return self._step_rows()
        if sheetName == DataSheet:
            return self._data_rows()
        raise ValueError('未知 sheet: %s' % sheetName)

    def _suit_rows(self):
        from cases.models import TestCase
        qs = TestCase.objects.all().order_by('tcid')
        scope = get_run_scope()
        if scope:
            qs = qs.filter(tcid__in=scope)
        return [dict(zip(
            ['tcid', '用例名称', '用例描述', '是否需要执行', '执行时间', '结果',
             '循环次数', '开始时间', '耗时', '错误信息'],
            [c.tcid, _s(c.name), _s(c.description), _yn(c.need_run),
             _s(c.last_run_time or ''), _s(c.last_result),
             _s(c.cycle or 1), _s(c.last_start_time), _s(c.last_duration),
             _s(c.last_errmsg)],
        )) for c in qs]

    def _step_rows(self):
        from cases.models import TestStep
        from keywordsDriver.excelKey import StepSheet
        scope = get_run_scope()
        qs = TestStep.objects.all().order_by('case__tcid', 'step_no', 'id')
        if scope:
            qs = qs.filter(case__tcid__in=scope)
        rows = []
        for s in qs:
            rows.append(dict(zip(
                ['tcid', '步骤序号', '测试步骤描述', '关键字',
                 '操作元素定位方式', '操作元素定位表达式', '操作值', '是否需要执行'],
                [s.case.tcid, _s(s.step_no), _s(s.description), _s(s.keyword),
                 _s(s.locate_type), _s(s.locate_expr), _s(s.value), _yn(s.need_run)],
            )))
        return rows


    @staticmethod
    def _case_cycle(d):
        """数据行对外暴露的循环次数：优先用例层，回退数据行自身的旧值。"""
        c = getattr(d, 'case', None)
        if c is not None and getattr(c, 'cycle', None):
            return c.cycle
        return d.cycle or 1

    def _data_rows(self):
        from cases.models import TestData
        scope = get_run_scope()
        qs = TestData.objects.all().order_by('case__tcid', 'id')
        if scope:
            qs = qs.filter(case__tcid__in=scope)
        rows = []
        for d in qs:
            row = {
                'tcid': d.case.tcid,
                'caseid': _s(d.caseid),
                'runmode': _s(d.runmode) or 'y',
                'data_name': _s(d.data_name),
                'summary': _s(d.summary),
                'input1': _s(d.input1), 'input2': _s(d.input2),
                'input3': _s(d.input3), 'input4': _s(d.input4),
                'input5': _s(d.input5), 'input6': _s(d.input6),
                'input7': _s(d.input7), 'input8': _s(d.input8),
                'verifiedcodexy': _s(d.verifiedcode_xy),
                'selector1': _s(d.selector1), 'selector2': _s(d.selector2),
                'selector3': _s(d.selector3), 'selector4': _s(d.selector4),
                'selector5': _s(d.selector5), 'selector6': _s(d.selector6),
                'selector7': _s(d.selector7), 'selector8': _s(d.selector8),
                'type': _s(d.assert_type),
                'expression': _s(d.expression),
                'expectedresult': _s(d.expected_result),
                # 循环次数已上移到用例层（导出的 Excel 不再有 TestDatas sheet），
                # 但引擎仍从数据行读 cycle，这里取所属用例的值，取不到再回退数据行。
                'cycle': _s(self._case_cycle(d)),
            }
            # 回写坐标：行=pk，列=WRITE_FIELDS 下标(1-based)
            for i, f in enumerate(WRITE_FIELDS, start=1):
                row[f] = '%s,%s' % (d.pk, i)
            rows.append(row)
        return rows

    # ---------- 回写 ----------

    def write_data(self, rowno, colno, content, font=None, msg=None):
        """rowno=TestData.pk, colno=WRITE_FIELDS 下标(1-based)。"""
        from django.db import connection
        from cases.models import TestData
        try:
            idx = int(colno) - 1
            if idx < 0 or idx >= len(WRITE_FIELDS):
                return
            field = WRITE_FIELDS[idx]
            model_field = _FIELD_TO_MODEL.get(field, field)
            obj = TestData.objects.get(pk=int(rowno))
            setattr(obj, model_field, '' if content is None else str(content))
            obj.save(update_fields=[model_field])
            # 同步一份到所属用例：导出的 Excel「测试用例」sheet 现在承载这些结果列，
            # 列表页也直接读用例字段，避免两份数据各说各话。
            tc = obj.case
            if tc is not None:
                pair = {
                    'result': ('last_result', obj.result),
                    'errmsg': ('last_errmsg', obj.errmsg),
                    'starttime': ('last_start_time', obj.start_time),
                    'runtime': ('last_duration', obj.run_time),
                }.get(field)
                if pair:
                    setattr(tc, pair[0], pair[1])
                    tc.save(update_fields=[pair[0]])
                # RunTime 是 finally 里写的，代表这条用例跑完了 —— 顺便记下执行时间
                if field == 'runtime':
                    from django.utils import timezone
                    tc.last_run_time = timezone.now()
                    tc.save(update_fields=['last_run_time'])
        except Exception as e:
            # 回写失败不能影响主流程，但要留痕
            try:
                print('[datasource] 回写失败: %s' % e)
            except Exception:
                pass
        finally:
            # 长跑时借这个调用顺手换掉被 MySQL 掐断的连接 —— 但它有个副作用：
            # 处在 atomic 块里（事务中）时 autocommit 与配置不一致，Django 会直接
            # close() 掉连接，于是当前事务被销毁，之后所有查询都会抛
            # TransactionManagementError（测试里最先暴露出来）。事务中不碰它。
            try:
                if not connection.in_atomic_block:
                    connection.close_if_unusable_or_obsolete()
            except Exception:
                pass

    def workbook_save(self, msg=None):
        """数据库是即时写入，无需显式保存。保留方法仅为接口兼容。"""
        return None

    def get_row(self, row):
        """接口兼容，数据库模式不使用。"""
        return []


# --------------------------------------------------------------------------
# 工厂函数：keywordsFrameword 模块顶层调用它们来获取全局 case_file / cases
# --------------------------------------------------------------------------

_shared_db = None


def _db_instance():
    global _shared_db
    if _shared_db is None:
        _shared_db = DBDataSource()
    return _shared_db


def open_case_source():
    """测试用例 / 步骤 sheet 的数据源"""
    if use_db():
        return _db_instance()
    from framework.excelutil import excel_readWrite
    from keywordsDriver.excelKey import excelname, SuitSheet
    return excel_readWrite(excelname, SuitSheet)


def open_data_source():
    """TestDatas sheet 的数据源"""
    if use_db():
        return _db_instance()
    from framework.excelutil import excel_readWrite
    from keywordsDriver.excelKey import excelname, DataSheet
    return excel_readWrite(excelname, DataSheet)
