'''后台执行引擎 —— 把「数据库里的用例」交给原关键字框架跑，并实时把进度/结果回写 TaskRun。

设计要点
--------
- 复用 framework.keywordsFrameword 这套已验证可用的执行引擎，只切换数据源为数据库
  （通过环境变量 YIKEUI_DATA_SOURCE=db，settings 里已默认设置）。
- 执行放在后台线程里跑（真正的浏览器自动化，耗时且会占用 GUI），前端通过轮询
  /runs/<pk>/status/ 拿进度，跑完后在同页内嵌报告 iframe。
- 报告由 tools/HTMLTestRunner_cn_echarts2 生成，其中引用了已停服的
  cdn.bootcss.com/echarts，这里生成后做一次本地化替换，离线也能看图。

并发与中断
--------
- 全局锁：同一时刻只允许一轮执行在跑（引擎靠模块级 _RUN_SCOPE 与动态 test_* 方法
  工作，两轮并发会互相覆盖）。已有任务在跑时新请求会被拒绝，见 RunBusy。
- 停止：/runs/<pk>/cancel/ 会置位 datasource 的停止标志，引擎在每个步骤边界检查，
  当前用例跳过剩余步骤、后续用例不再启动，最终状态记为「已停止」。
- 超时：RUN_TIMEOUT 秒后自动触发一次停止请求；若届时仍未结束，状态记为「执行异常」。
'''
import logging
import os
import sys
import threading
import time
import datetime

import unittest

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.db import close_old_connections

from .models import TaskRun

logger = logging.getLogger(__name__)

# 让执行线程能 import 上层的 framework / keywordsDriver / config
PROJECT_ROOT = settings.PROJECT_ROOT
for _p in (str(PROJECT_ROOT), str(settings.BASE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REPORTS_DIR = str(settings.REPORTS_DIR)
SHOTS_DIR = str(settings.SHOTS_DIR)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(SHOTS_DIR, exist_ok=True)

CDN_ECHARTS = 'https://cdn.bootcss.com/echarts/3.8.5/echarts.common.min.js'
LOCAL_ECHARTS = '/static/echarts.common.min.js'

from tools.HTMLTestRunner_cn_echarts2 import (  # noqa: E402
    HTMLTestRunner, _TestResult, PY3K, SHOT_FIX_SCRIPT,
)


# ---------------------------------------------------------------- 并发控制
# 同一时刻只允许一轮执行。非阻塞 acquire：拿不到就直接拒绝，而不是排队。
_RUN_LOCK = threading.Lock()
_STATE = {'pk': None, 'timed_out': False, 'timer': None}


class RunBusy(Exception):
    """已有任务正在执行，本次请求被拒绝。"""

    def __init__(self, running_pk):
        self.running_pk = running_pk
        super().__init__('已有任务正在执行（#%s）' % running_pk)


def current_run_id():
    """当前正在执行的 TaskRun pk，没有则 None。"""
    return _STATE['pk']


def is_busy():
    return _STATE['pk'] is not None


def acquire_run_lock():
    """尝试抢占全局执行锁：成功 True，已有任务在执行则 False（不排队、不阻塞）。"""
    return _RUN_LOCK.acquire(blocking=False)


def release_run_lock():
    """释放全局执行锁。未持有（如异常路径重复释放）时静默忽略。"""
    try:
        _RUN_LOCK.release()
    except RuntimeError:
        pass


def mark_stale_runs():
    """把「看起来还在跑」的历史记录收尾 —— 服务重启后它们不可能真的还在跑。"""
    n = TaskRun.objects.filter(status__in=[TaskRun.STATUS_PENDING,
                                           TaskRun.STATUS_RUNNING]).count()
    if n:
        TaskRun.objects.filter(
            status__in=[TaskRun.STATUS_PENDING, TaskRun.STATUS_RUNNING]
        ).update(status=TaskRun.STATUS_ERROR,
                 log_tail='服务重启，该执行已被中断。',
                 finished_at=timezone.now())
    return n


class ProgressResult(_TestResult):
    '''在 _TestResult 基础上，把进度实时写回 TaskRun。'''

    def __init__(self, verbosity, retry, save_last_try, task_run=None):
        super().__init__(verbosity, retry, save_last_try)
        self.skip_count = 0
        # 收到停止指令后，未真正跑完的用例不再计入「通过」
        self.cancelled_count = 0
        self.task_run = task_run

    def _save(self, **fields):
        if self.task_run is None:
            return
        try:
            for k, v in fields.items():
                setattr(self.task_run, k, v)
            self.task_run.save(update_fields=list(fields.keys()))
        except Exception:
            pass

    def _label(self, test):
        return getattr(test, '_testMethodName', '') or str(test)

    def startTest(self, test):
        super().startTest(test)
        # 收到停止指令：不再启动后续用例（unittest 的 shouldStop 会中断整个 suite）
        from framework import datasource
        if datasource.is_cancel_requested():
            self.stop()
            return
        self._save(current_step=self._label(test) or '—')

    def _bump(self, field, test, status):
        if self.task_run is None:
            return
        cur = getattr(self.task_run, field) or 0
        setattr(self.task_run, field, cur + 1)
        line = '[%s] %s\n' % (status, self._label(test))
        tail = (self.task_run.log_tail or '') + line
        self.task_run.log_tail = tail[-4000:]
        self._save(**{field: getattr(self.task_run, field), 'log_tail': self.task_run.log_tail})

    def addSuccess(self, test):
        super().addSuccess(test)
        # 停止后，引擎会跳过剩余步骤直接结束用例 —— 这种「通过」不算数
        from framework import datasource
        if datasource.is_cancel_requested():
            self.cancelled_count += 1
            line = '[已停止] %s（未执行完，不计入通过）\n' % self._label(test)
            tail = (self.task_run.log_tail if self.task_run else '') + line
            if self.task_run:
                self._save(log_tail=tail[-4000:])
            return
        self._bump('passed', test, '通过')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._bump('failed', test, '失败')

    def addError(self, test, err):
        super().addError(test, err)
        self._bump('error', test, '异常')


class LiveHTMLTestRunner(HTMLTestRunner):
    '''挂上 task_run，让 run() 使用 ProgressResult 以回写进度。'''

    def __init__(self, *args, **kwargs):
        self.task_run = kwargs.pop('task_run', None)
        super().__init__(*args, **kwargs)

    def run(self, test):
        self.startTime = datetime.datetime.now()
        result = ProgressResult(self.verbosity, self.retry, self.save_last_try, self.task_run)
        test(result)
        self.stopTime = datetime.datetime.now()
        self.generateReport(test, result)
        if PY3K:
            sys.stderr.write('\nTime Elapsed: %s' % (self.stopTime - self.startTime))
        return result


def _build_suite():
    '''清掉上一轮动态注入的 test_* 方法（避免重复执行），再按当前数据库重建套件。'''
    from framework import keywordsFrameword as kw
    for name in [n for n in dir(kw.Keyword) if n.startswith('test_')]:
        delattr(kw.Keyword, name)
    kw.__generateTestCases()
    return unittest.TestLoader().loadTestsFromTestCase(kw.Keyword)


def _localize_report(path):
    '''把报告里的死 CDN 链接 / 相对路径换成项目本地 /static/...，保证离线、iframe 内可看。

    另外把「截图查看器补丁」补进报告：老报告（本补丁上线前生成的）里的 show_img/hide_img
    关不掉弹层、重复点击还会叠加圆点，这里统一注入修复脚本覆盖掉旧实现。
    '''
    repls = [
        (CDN_ECHARTS, LOCAL_ECHARTS),
        ('src="js/echarts.common.min.js"', 'src="/static/echarts.common.min.js"'),
        ('href="http://cdn.bootcss.com/bootstrap/3.3.0/css/bootstrap.min.css"',
         'href="/static/bootstrap.min.css"'),
    ]
    try:
        with open(path, 'rb') as f:
            data = f.read()
        text = data.decode('utf-8', 'replace')
        changed = False
        for a, b in repls:
            if a and a in text:
                text = text.replace(a, b)
                changed = True
        # 截图查看器补丁：老报告没有，补一次；已有则跳过（幂等）
        if 'shot-mask' not in text and 'show_img' in text:
            text = text.replace('</body>', SHOT_FIX_SCRIPT + '\n</body>')
            changed = True
        if changed:
            with open(path, 'wb') as f:
                f.write(text.encode('utf-8'))
    except Exception:
        pass


def _on_timeout(pk):
    '''超时看门狗：先请求「软停止」，让引擎在步骤边界自己收尾。'''
    if _STATE['pk'] != pk:
        return
    _STATE['timed_out'] = True
    try:
        from framework import datasource
        datasource.request_cancel()
        t = TaskRun.objects.get(pk=pk)
        if not t.is_finished:
            t.cancel_requested = True
            t.log_tail = (t.log_tail or '') + \
                '\n[超时] 已超过 %s 秒，自动请求停止…\n' % settings.RUN_TIMEOUT
            t.save(update_fields=['cancel_requested', 'log_tail'])
    except Exception:
        pass


def request_cancel(pk):
    '''用户点「停止执行」：只对当前正在跑的那一轮生效。'''
    from framework import datasource
    if _STATE['pk'] != pk:
        return False
    datasource.request_cancel()
    try:
        t = TaskRun.objects.get(pk=pk)
        if not t.is_finished:
            t.cancel_requested = True
            t.log_tail = (t.log_tail or '') + '\n[停止] 收到停止指令，正在收尾…\n'
            t.save(update_fields=['cancel_requested', 'log_tail'])
    except Exception:
        pass
    return True


def _resolve_scope(case_filter):
    '''把 TaskRun.case_filter 翻译成具体的 tcid 列表（None = 不限，跑全部启用用例）。

    支持的写法：
        ''                  -> 全部启用用例
        'CASE:<tcid>'       -> 单条用例
        'CASES:<a>,<b>'     -> 指定的若干条
        'TAGS:<甲>+<乙>'     -> 带这些标签之一的全部启用用例（执行时现算，标签成员变了也跟着变）
    '''
    cf = (case_filter or '').strip()
    if not cf.startswith(('CASE:', 'CASES:', 'TAGS:')):
        return None
    if cf.startswith('CASE:'):
        return [cf.split(':', 1)[1]]
    if cf.startswith('CASES:'):
        return [t for t in cf.split(':', 1)[1].split(',') if t]
    tags = [t for t in cf.split(':', 1)[1].split('+') if t]
    if not tags:
        return None
    from cases.models import TestCase
    q = None
    for t in tags:
        cond = Q(tags__icontains=t)
        q = cond if q is None else (q | cond)
    # 只跑启用用例 —— 与「执行全部」的语义保持一致
    return list(TestCase.objects.filter(need_run=True)
                .filter(q).order_by('tcid').values_list('tcid', flat=True))


def execute(task_run):
    '''同步执行（在后台线程里被调用）。'''
    os.environ['YIKEUI_DATA_SOURCE'] = 'db'
    from framework import datasource
    close_old_connections()
    start_wall = time.time()

    timeout = getattr(settings, 'RUN_TIMEOUT', 30 * 60)
    timer = threading.Timer(timeout, _on_timeout, args=(task_run.pk,))
    timer.daemon = True
    _STATE['timer'] = timer
    timer.start()

    try:
        datasource.clear_cancel()

        # 执行范围：'' 表示不限（全部启用用例），其余见 _resolve_scope
        scope = _resolve_scope(task_run.case_filter)
        datasource.set_run_scope(scope)

        suite = _build_suite()
        total = suite.countTestCases()
        task_run.total = total
        task_run.status = TaskRun.STATUS_RUNNING
        task_run.started_at = timezone.now()
        task_run.log_tail = '套件已构建，共 %s 个用例，开始执行…\n' % total
        task_run.save(update_fields=['total', 'status', 'started_at', 'log_tail'])

        if total == 0:
            task_run.status = TaskRun.STATUS_ERROR
            task_run.log_tail = (task_run.log_tail or '') + \
                '未找到需要执行的用例（请确认已勾选“是否需要执行”，且存在测试数据）。\n'
            task_run.finished_at = timezone.now()
            task_run.duration = 0
            task_run.save(update_fields=['status', 'log_tail', 'finished_at', 'duration'])
            datasource.set_run_scope(None)
            return

        # 报告只存「文件名」，绝对路径由 TaskRun.report_abspath 计算（换机器也不失效）
        report_name = 'result_%s.html' % task_run.pk
        report_path = os.path.join(REPORTS_DIR, report_name)
        with open(report_path, 'wb') as fp:
            runner = LiveHTMLTestRunner(
                stream=fp,
                title='自动化测试报告',
                description=task_run.case_filter,
                verbosity=2,
                task_run=task_run,
                # 截图落盘：写成独立 png，报告里用 URL 引用，避免 base64 撑爆报告体积
                shots_dir=SHOTS_DIR,
                shots_url='/runs/%s/shots/' % task_run.pk,
                shots_prefix='run_%s' % task_run.pk,
            )
            result = runner.run(suite)

        _localize_report(report_path)

        # 停止后被跳过的用例会从 success_count 里扣除（见 ProgressResult.addSuccess）
        passed = result.success_count - getattr(result, 'cancelled_count', 0)
        failed = result.failure_count
        error = result.error_count
        status = TaskRun.STATUS_PASSED if (failed == 0 and error == 0) else TaskRun.STATUS_FAILED
        task_run.passed = passed
        task_run.failed = failed
        task_run.error = error
        task_run.status = status
        task_run.report_path = report_name
    except Exception as e:
        import traceback as _tb
        task_run.status = TaskRun.STATUS_ERROR
        task_run.log_tail = (task_run.log_tail or '') + \
            '\n[执行异常] %s\n%s' % (e, _tb.format_exc())
    finally:
        # 停止 / 超时优先于正常结果，避免被 passed 覆盖
        try:
            fresh = TaskRun.objects.get(pk=task_run.pk)
            cancelled = fresh.cancel_requested
        except Exception:
            cancelled = False
        if _STATE['timed_out']:
            task_run.status = TaskRun.STATUS_ERROR
            task_run.log_tail = (task_run.log_tail or '') + \
                '\n[超时] 单轮执行超过 %s 秒，已中止。\n' % timeout
        elif cancelled and task_run.status in (TaskRun.STATUS_PASSED,
                                               TaskRun.STATUS_FAILED,
                                               TaskRun.STATUS_RUNNING,
                                               TaskRun.STATUS_PENDING):
            task_run.status = TaskRun.STATUS_CANCELLED
            task_run.log_tail = (task_run.log_tail or '') + '\n[停止] 已手动停止本次执行。\n'

        task_run.finished_at = timezone.now()
        task_run.duration = round(time.time() - start_wall, 2)
        try:
            task_run.save()
        except Exception:
            pass

        # 邮件通知（旁路）：失败/异常时发一封，通知挂了不影响本轮结果
        try:
            from .notifier import notify_task
            notify_task(task_run)
        except Exception as e:
            logger.warning('通知钩子异常：%s', e)

        try:
            datasource.set_run_scope(None)
            datasource.clear_cancel()
        except Exception:
            pass

        if _STATE.get('timer'):
            _STATE['timer'].cancel()
        _STATE['timer'] = None
        _STATE['timed_out'] = False
        _STATE['pk'] = None
        release_run_lock()
        close_old_connections()


def start_run(user, scope_tcid=None, scope_tcids=None, case_filter=None):
    '''创建一条执行记录，并在后台线程启动执行，返回 TaskRun。

    执行范围三选一（优先级从高到低）：
        case_filter  —— 直接指定写进 TaskRun.case_filter 的原文（如 'TAGS:冒烟'）
        scope_tcid   —— 单条用例
        scope_tcids  —— 指定的若干条 tcid
    都不给就是「全部启用用例」。

    已有任务在跑时抛 RunBusy（同一时刻只允许一轮执行）。
    '''
    if not acquire_run_lock():
        raise RunBusy(_STATE['pk'])

    if case_filter is None:
        if scope_tcid:
            case_filter = 'CASE:%s' % scope_tcid
        elif scope_tcids:
            case_filter = 'CASES:%s' % ','.join(scope_tcids)
        else:
            case_filter = '全部启用用例'
    try:
        task = TaskRun.objects.create(
            status=TaskRun.STATUS_PENDING,
            case_filter=case_filter,
            triggered_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
        )
    except Exception:
        release_run_lock()
        raise

    _STATE['pk'] = task.pk
    _STATE['timed_out'] = False
    t = threading.Thread(target=execute, args=(task,), daemon=True)
    t.start()
    return task
