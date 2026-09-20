'''runner 应用自动化测试 —— 覆盖并发锁、停止计数、报告路径、产物清理、跨进程锁、视图入口。

设计原则：**不启动真实浏览器。** 真跑 UI 属于冒烟范畴（慢、依赖网络和被测系统），
这里只测「逻辑是否按预期工作」，所以整套跑下来在秒级。
'''
import datetime
import os
import shutil
import tempfile
import time
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from framework import datasource
from cases.models import TestCase as AutoCase
from . import executor, notifier, planner, scheduler
from .models import NotifyConfig, SchedulePlan, TaskRun


def now_iso():
    """今天是周几（1=周一 … 7=周日），用于构造每周计划。"""
    return timezone.localtime(timezone.now()).isoweekday()


class FakeTest(object):
    """最小的 unittest 用例替身，用于驱动 ProgressResult 的计数逻辑。"""

    _testMethodName = 'test_demo_case'
    # unittest 的错误格式化会读这个属性来判断「断言失败 vs 真正的错误」
    failureException = AssertionError

    def id(self):
        return 'framework.Keyword.test_demo_case'

    def shortDescription(self):
        return '演示用例'

    def __str__(self):
        return 'test_demo_case'


# --------------------------------------------------------------------------
# 并发锁
# --------------------------------------------------------------------------

class RunLockTests(TestCase):
    """同一时刻只允许一轮执行（优化项 #1）。"""

    def tearDown(self):
        executor.release_run_lock()

    def test_lock_is_exclusive(self):
        self.assertTrue(executor.acquire_run_lock())
        self.assertFalse(executor.acquire_run_lock(), '第二次必须拿不到锁')
        executor.release_run_lock()
        self.assertTrue(executor.acquire_run_lock())

    def test_release_without_holding_is_safe(self):
        executor.release_run_lock()
        executor.release_run_lock()          # 不应抛异常

    def test_start_run_rejected_when_busy(self):
        executor.acquire_run_lock()
        executor._STATE['pk'] = 777
        try:
            with self.assertRaises(executor.RunBusy):
                executor.start_run(None)
            self.assertEqual(TaskRun.objects.count(), 0, '被拒绝时不应留下执行记录')
        finally:
            executor._STATE['pk'] = None


class StaleRunTests(TestCase):

    def test_active_records_are_closed_on_startup(self):
        TaskRun.objects.create(status=TaskRun.STATUS_RUNNING)
        TaskRun.objects.create(status=TaskRun.STATUS_PENDING)
        TaskRun.objects.create(status=TaskRun.STATUS_PASSED)

        n = executor.mark_stale_runs()

        self.assertEqual(n, 2)
        self.assertEqual(TaskRun.objects.filter(status=TaskRun.STATUS_ERROR).count(), 2)
        self.assertEqual(TaskRun.objects.filter(status=TaskRun.STATUS_PASSED).count(), 1)
        self.assertTrue(
            TaskRun.objects.filter(status=TaskRun.STATUS_ERROR).first().finished_at
        )


# --------------------------------------------------------------------------
# 报告路径（优化项 #8）
# --------------------------------------------------------------------------

class TaskRunModelTests(TestCase):

    def test_filename_is_resolved_against_reports_dir(self):
        r = TaskRun.objects.create(report_path='result_12.html')
        self.assertEqual(r.report_abspath,
                         os.path.join(str(settings.REPORTS_DIR), 'result_12.html'))

    def test_legacy_absolute_path_still_works(self):
        legacy = os.path.join('D:', os.sep, 'old', 'reports', 'result_1.html')
        r = TaskRun.objects.create(report_path=legacy)
        self.assertEqual(r.report_abspath, legacy)

    def test_empty_report_path_returns_empty(self):
        self.assertEqual(TaskRun.objects.create().report_abspath, '')

    def test_status_flags(self):
        self.assertTrue(TaskRun.objects.create(status=TaskRun.STATUS_RUNNING).is_active)
        self.assertTrue(TaskRun.objects.create(status=TaskRun.STATUS_CANCELLED).is_finished)


# --------------------------------------------------------------------------
# 停止后不能把「未跑完」算成通过（优化项 #10）
# --------------------------------------------------------------------------

class ProgressResultCountTests(TestCase):

    def setUp(self):
        datasource.clear_cancel()
        self.task = TaskRun.objects.create()

    def tearDown(self):
        datasource.clear_cancel()

    def _result(self):
        return executor.ProgressResult(1, 0, False, self.task)

    def _deliver(self, result, method):
        t = FakeTest()
        getattr(result, method)(t) if method != 'addSuccess' else result.addSuccess(t)

    def test_success_is_counted(self):
        r = self._result()
        r.addSuccess(FakeTest())
        self.task.refresh_from_db()
        self.assertEqual(self.task.passed, 1)
        self.assertEqual(r.success_count - r.cancelled_count, 1)

    def test_cancelled_success_is_not_counted_as_passed(self):
        """点停止后被跳过的用例，不能混进通过数里。"""
        datasource.request_cancel()
        r = self._result()
        r.addSuccess(FakeTest())

        self.assertEqual(r.cancelled_count, 1)
        self.assertEqual(r.success_count - r.cancelled_count, 0)
        self.task.refresh_from_db()
        self.assertEqual(self.task.passed, 0)
        self.assertIn('未执行完', self.task.log_tail)

    def test_failure_and_error_are_counted(self):
        r = self._result()
        r.addFailure(FakeTest(), (AssertionError, AssertionError('x'), None))
        r.addError(FakeTest(), (RuntimeError, RuntimeError('boom'), None))
        self.task.refresh_from_db()
        self.assertEqual((self.task.failed, self.task.error), (1, 1))

    def test_start_test_stops_the_suite_when_cancelled(self):
        datasource.request_cancel()
        r = self._result()
        r.startTest(FakeTest())
        self.assertTrue(r.shouldStop)


# --------------------------------------------------------------------------
# 产物清理（优化项 #7）
# --------------------------------------------------------------------------

class CleanupCommandTests(TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='yikeui_cleanup_'))
        self.reports = self.tmp / 'reports'
        self.shots = self.reports / 'shots'
        self.backup = self.tmp / 'BackUP'
        for d in (self.reports, self.shots, self.backup):
            d.mkdir(parents=True, exist_ok=True)
        self.opts = dict(REPORTS_DIR=self.reports, SHOTS_DIR=self.shots,
                         BACKUP_DIR=self.backup)

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def _touch(self, path, days_ago=0):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
        if days_ago:
            stamp = time.time() - days_ago * 86400
            os.utime(str(path), (stamp, stamp))
        return path

    def _run_cmd(self, **kwargs):
        out = StringIO()
        call_command('cleanup_artifacts', stdout=out, **kwargs)
        return out.getvalue()

    def _reports_of(self, n):
        runs = []
        for i in range(n):
            r = TaskRun.objects.create()
            r.report_path = 'result_%s.html' % r.pk
            r.save(update_fields=['report_path'])
            runs.append(r)
        return runs

    def test_dry_run_deletes_nothing(self):
        runs = self._reports_of(3)
        for i, r in enumerate(runs):
            self._touch(self.reports / ('result_%s.html' % r.pk), days_ago=3 - i)

        with override_settings(**self.opts):
            out = self._run_cmd(keep_reports=1, dry_run=True)

        self.assertEqual(len(list(self.reports.glob('result_*.html'))), 3)
        self.assertIn('演练', out)
        for r in runs:
            r.refresh_from_db()
            self.assertNotEqual(r.report_path, '', '演练不该改动执行记录')

    def test_keeps_only_newest_reports_and_clears_record(self):
        runs = self._reports_of(3)
        for i, r in enumerate(runs):
            self._touch(self.reports / ('result_%s.html' % r.pk), days_ago=3 - i)

        with override_settings(**self.opts):
            self._run_cmd(keep_reports=2)

        oldest = runs[0]
        self.assertFalse((self.reports / ('result_%s.html' % oldest.pk)).exists())
        self.assertTrue((self.reports / ('result_%s.html' % runs[1].pk)).exists())
        self.assertTrue((self.reports / ('result_%s.html' % runs[2].pk)).exists())

        oldest.refresh_from_db()
        self.assertEqual(oldest.report_path, '', '报告没了，记录里的路径也要清掉')

    def test_shots_kept_while_report_alive(self):
        with_report = TaskRun.objects.create()
        with_report.report_path = 'result_%s.html' % with_report.pk
        with_report.save(update_fields=['report_path'])
        without = TaskRun.objects.create()

        keep_png = self._touch(self.shots / ('run_%s_1.png' % with_report.pk))
        drop_png = self._touch(self.shots / ('run_%s_1.png' % without.pk))

        with override_settings(**self.opts):
            self._run_cmd(keep_reports=100)

        self.assertTrue(keep_png.exists(), '报告还在，截图不能删，否则报告里会裂图')
        self.assertFalse(drop_png.exists())

    def test_backup_removed_by_age(self):
        fresh = self._touch(self.backup / '2026' / 'new.xlsx', days_ago=0)
        old = self._touch(self.backup / '2023' / 'old.xlsx', days_ago=200)

        with override_settings(**self.opts):
            self._run_cmd(keep_backup_days=100)

        self.assertTrue(fresh.exists())
        self.assertFalse(old.exists())

    def test_unrelated_files_are_untouched(self):
        note = self._touch(self.reports / 'readme.txt')
        weird = self._touch(self.shots / 'not_a_shot.txt')

        with override_settings(**self.opts):
            self._run_cmd(keep_reports=0)

        self.assertTrue(note.exists())
        self.assertTrue(weird.exists())

    def test_missing_directories_are_tolerated(self):
        """目录被整个删掉时不能崩，否则定时任务会一直报错。"""
        gone = self.tmp / 'gone'
        with override_settings(REPORTS_DIR=gone, SHOTS_DIR=gone / 'shots',
                               BACKUP_DIR=gone):
            out = self._run_cmd()
        self.assertIn('清理完成', out)


# --------------------------------------------------------------------------
# 跨进程文件锁
# --------------------------------------------------------------------------

class CleanupFileLockTests(TestCase):

    def tearDown(self):
        scheduler._release_file_lock(scheduler._acquire_file_lock()) \
            if os.path.exists(scheduler._LOCK_FILE) else None

    def _force_release(self):
        if os.path.exists(scheduler._LOCK_FILE):
            os.remove(scheduler._LOCK_FILE)

    def test_only_one_holder_at_a_time(self):
        self._force_release()
        try:
            first = scheduler._acquire_file_lock()
            self.assertIsNotNone(first)
            self.assertIsNone(scheduler._acquire_file_lock())
            scheduler._release_file_lock(first)
            self.assertIsNotNone(scheduler._acquire_file_lock())
        finally:
            self._force_release()

    def test_stale_lock_is_reclaimed(self):
        """上次进程异常退出留下的锁，超时后应能被回收，否则清理会永久停摆。"""
        self._force_release()
        try:
            holder = scheduler._acquire_file_lock()
            self.assertIsNotNone(holder)
            old = time.time() - (scheduler._LOCK_TTL + 60)
            os.utime(scheduler._LOCK_FILE, (old, old))
            self.assertIsNotNone(scheduler._acquire_file_lock(), '超期锁应被回收')
        finally:
            self._force_release()


# --------------------------------------------------------------------------
# 视图入口
# --------------------------------------------------------------------------

class ViewAccessTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('tester', password='pwd12345')
        self.client.login(username='tester', password='pwd12345')

    def test_index_and_run_list_ok(self):
        self.assertEqual(self.client.get(reverse('index')).status_code, 200)
        self.assertEqual(self.client.get(reverse('runner:run_list')).status_code, 200)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse('runner:run_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp['Location'])

    def test_run_entry_must_be_post(self):
        """优化项 #5：GET 不再能触发执行（刷新页面/预取都不会误跑）。"""
        self.assertEqual(
            self.client.get(reverse('cases:case_run_enabled')).status_code, 405)
        self.assertEqual(TaskRun.objects.count(), 0)

    def test_run_entry_when_busy_shows_warning(self):
        """占住锁模拟「已有任务在跑」，验证不会创建记录且给出提示。"""
        case = AutoCase.objects.create(tcid='busy_case', name='占锁用', need_run=True)
        executor.acquire_run_lock()
        executor._STATE['pk'] = 101
        try:
            resp = self.client.post(reverse('cases:case_run_enabled'),
                                    {'row_pk': [case.pk], 'enabled': [case.pk]},
                                    follow=True)
        finally:
            executor._STATE['pk'] = None
            executor.release_run_lock()

        self.assertEqual(TaskRun.objects.count(), 0)
        msgs = [str(m) for m in resp.context['messages']]
        self.assertTrue(any('正在执行' in m for m in msgs), msgs)

    def test_cancel_finished_task_is_harmless(self):
        task = TaskRun.objects.create(status=TaskRun.STATUS_PASSED)
        resp = self.client.post(reverse('runner:run_cancel', kwargs={'pk': task.pk}),
                                follow=True)
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertFalse(task.cancel_requested)

    def test_shot_rejects_other_runs_file(self):
        task = TaskRun.objects.create()
        resp = self.client.get(reverse('runner:run_shot',
                                       kwargs={'pk': task.pk, 'name': 'run_9999_1.png'}))
        self.assertEqual(resp.status_code, 404)

    def test_missing_report_returns_404(self):
        task = TaskRun.objects.create(report_path='result_not_exist.html')
        resp = self.client.get(reverse('runner:run_report', kwargs={'pk': task.pk}))
        self.assertEqual(resp.status_code, 404)

    def test_status_api_shape(self):
        task = TaskRun.objects.create(status=TaskRun.STATUS_RUNNING, total=5)
        data = self.client.get(
            reverse('runner:run_status_api', kwargs={'pk': task.pk})).json()
        self.assertEqual(data['pk'], task.pk)
        self.assertEqual(data['status'], 'running')
        self.assertTrue(data['can_cancel'])
        self.assertFalse(data['has_report'])


# ---------------------------------------------------------------------------
# 邮件通知（优化项 ⑧）
# ---------------------------------------------------------------------------

class NotifyTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('nt', 'nt@example.com', 'pwd12345')
        self.client.force_login(self.user)

    def _ready(self, **kw):
        cfg = NotifyConfig.get()
        cfg.enabled = True
        cfg.smtp_host = 'smtp.test'
        cfg.username = 'no-reply@test'
        cfg.receivers = 'ops@test'
        cfg.attach_report = False
        for k, v in kw.items():
            setattr(cfg, k, v)
        cfg.save()
        return cfg

    def test_disabled_by_default(self):
        task = TaskRun.objects.create(status=TaskRun.STATUS_FAILED, failed=1)
        self.assertFalse(notifier.notify_task(task))
        task.refresh_from_db()
        self.assertFalse(task.notified)

    def test_sends_on_failure(self):
        self._ready()
        task = TaskRun.objects.create(status=TaskRun.STATUS_FAILED, failed=2)
        with patch.object(notifier.smtplib, 'SMTP_SSL') as cls:
            cls.return_value.sendmail.return_value = {}
            self.assertTrue(notifier.notify_task(task))
        self.assertTrue(cls.return_value.sendmail.called)
        task.refresh_from_db()
        self.assertTrue(task.notified)
        self.assertIsNotNone(task.notified_at)

    def test_skipped_when_passed_and_only_fail(self):
        self._ready()
        task = TaskRun.objects.create(status=TaskRun.STATUS_PASSED, passed=3)
        with patch.object(notifier.smtplib, 'SMTP_SSL') as cls:
            self.assertFalse(notifier.notify_task(task))
        self.assertFalse(cls.called)
        task.refresh_from_db()
        self.assertFalse(task.notified)

    def test_always_mode_sends_even_when_passed(self):
        self._ready(notify_on=NotifyConfig.ALWAYS)
        task = TaskRun.objects.create(status=TaskRun.STATUS_PASSED, passed=3)
        with patch.object(notifier.smtplib, 'SMTP_SSL') as cls:
            cls.return_value.sendmail.return_value = {}
            self.assertTrue(notifier.notify_task(task))

    def test_same_task_is_not_notified_twice(self):
        self._ready()
        task = TaskRun.objects.create(status=TaskRun.STATUS_FAILED, failed=1,
                                      notified=True)
        with patch.object(notifier.smtplib, 'SMTP_SSL') as cls:
            self.assertFalse(notifier.notify_task(task))
        self.assertFalse(cls.called)

    def test_failure_swallowed_and_recorded(self):
        """通知是旁路能力：SMTP 炸了也不能让执行流程出错，原因要落到记录上。"""
        self._ready()
        task = TaskRun.objects.create(status=TaskRun.STATUS_ERROR, error=1)
        with patch.object(notifier.smtplib, 'SMTP_SSL', side_effect=TimeoutError('连不上')):
            self.assertIsNone(notifier.notify_task(task))
        task.refresh_from_db()
        self.assertFalse(task.notified)
        self.assertIn('连不上', task.notify_error)

    def test_failure_names_parsed_from_log(self):
        task = TaskRun.objects.create(
            log_tail='[失败] case_a\n[异常] case_b\n[通过] case_c\n[失败] case_a\n')
        self.assertEqual(task.failure_names, ['case_a', 'case_b'])

    def test_settings_page_and_test_mail(self):
        self.assertEqual(self.client.get(reverse('runner:notify_settings')).status_code, 200)
        self.client.post(reverse('runner:notify_settings'), {
            'enabled': '1', 'notify_on': NotifyConfig.ONLY_FAIL,
            'smtp_host': 'smtp.test', 'smtp_port': '465', 'use_ssl': '1',
            'username': 'u', 'password': 'p', 'sender': 'a@test',
            'receivers': 'x@test,y@test', 'attach_report': '1',
        })
        cfg = NotifyConfig.get()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.receiver_list, ['x@test', 'y@test'])
        # 页面只留一个「发件人邮箱」框：它同时是 SMTP 登录账号
        self.assertEqual(cfg.username, 'a@test')
        # 老的独立「发件人邮箱」字段已经从模型里去掉
        self.assertNotIn('sender', [f.name for f in NotifyConfig._meta.get_fields()])

        page = self.client.get(reverse('runner:notify_settings')).content.decode()
        self.assertIn('name="sender"', page)
        self.assertIn('type="password"', page)
        self.assertEqual(page.count('name="sender"'), 1)

        with patch.object(notifier.smtplib, 'SMTP_SSL') as cls:
            cls.return_value.sendmail.return_value = {}
            resp = self.client.post(reverse('runner:notify_test'),
                                    {'to': 'z@test'}, follow=True)
        self.assertTrue(any('测试邮件已发送' in str(m) for m in resp.context['messages']))

    def test_env_password_takes_precedence(self):
        cfg = NotifyConfig.get()
        cfg.password = 'db_value'
        cfg.save()
        with override_settings():
            os.environ['YIKEUI_SMTP_PASSWORD'] = 'env_value'
            try:
                self.assertEqual(cfg.smtp_password(), 'env_value')
                # 环境变量已提供时，页面提交空密码不应把库里的旧值抹掉
                self.client.post(reverse('runner:notify_settings'),
                                 {'smtp_host': 'h', 'sender': 's', 'receivers': 'r'})
                self.assertEqual(NotifyConfig.get().password, 'db_value')
            finally:
                del os.environ['YIKEUI_SMTP_PASSWORD']


# ---------------------------------------------------------------------------
# 定时执行（优化项 ⑥）—— 全部在 Web 配置，调度线程跑在进程里
# ---------------------------------------------------------------------------

class SchedulePlanTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('sc', 'sc@example.com', 'pwd12345')
        self.client.force_login(self.user)

    @staticmethod
    def _at(days=0, hour=8, minute=30):
        base = timezone.localtime(timezone.now()) - datetime.timedelta(days=days)
        return timezone.make_aware(datetime.datetime.combine(
            base.date(), datetime.time(hour, minute)))

    def test_daily_slot_and_next_run(self):
        plan = SchedulePlan(name='每天', freq=SchedulePlan.FREQ_DAILY, hour=9, minute=0)
        now = self._at(hour=10, minute=0)
        self.assertEqual(plan.last_slot(now), self._at(hour=9, minute=0))
        self.assertEqual(plan.next_slot(now), self._at(days=-1, hour=9, minute=0))

    def test_weekly_only_on_selected_weekdays(self):
        plan = SchedulePlan(name='每周', freq=SchedulePlan.FREQ_WEEKLY,
                            hour=8, minute=0, weekdays='%d' % now_iso())
        now = timezone.localtime(timezone.now())
        # 选了今天 -> 存在我今天 08:00 这个点（前提是现在已过 8 点）
        slots = plan._slots_for_day(now.date())
        self.assertEqual(len(slots), 1)

        plan.weekdays = '%d' % ((now_iso() % 7) + 1)   # 改成明天
        self.assertEqual(plan._slots_for_day(now.date()), [])

    def test_hourly_slots_are_evenly_spaced(self):
        plan = SchedulePlan(name='每3小时', freq=SchedulePlan.FREQ_HOURLY,
                            interval_hours=3, minute=15)
        now = self._at(hour=11, minute=0)
        self.assertEqual(plan.last_slot(now), self._at(hour=9, minute=15))
        self.assertEqual(plan.next_slot(now), self._at(hour=12, minute=15))

    def test_due_only_inside_grace_window(self):
        plan = SchedulePlan(name='每天', freq=SchedulePlan.FREQ_DAILY, hour=8, minute=0)
        just_after = self._at(hour=8, minute=5)
        self.assertIsNotNone(plan.is_due(just_after))
        # 晚太久不补跑（服务停机一天，开机不该把过期任务全跑一遍）
        way_late = self._at(hour=20, minute=0)
        self.assertIsNone(plan.is_due(way_late))

    def test_already_fired_slot_not_due_again(self):
        plan = SchedulePlan(name='每天', freq=SchedulePlan.FREQ_DAILY, hour=8, minute=0)
        plan.last_run_at = self._at(hour=8, minute=1)
        self.assertIsNone(plan.is_due(self._at(hour=8, minute=20)))

    def test_case_filter_translation(self):
        self.assertEqual(SchedulePlan(scope_type=SchedulePlan.SCOPE_ALL).case_filter(),
                         '全部启用用例')
        self.assertEqual(SchedulePlan(scope_type=SchedulePlan.SCOPE_TAG,
                                      scope_value='冒烟').case_filter(), 'TAGS:冒烟')
        self.assertEqual(SchedulePlan(scope_type=SchedulePlan.SCOPE_CASES,
                                      scope_value='a，b').case_filter(), 'CASES:a,b')

    def test_fire_creates_task_run(self):
        """触发一次就产生一条执行记录（真正的执行用替身，避免起浏览器）。"""
        plan = SchedulePlan.objects.create(name='每天', freq=SchedulePlan.FREQ_DAILY)
        with patch.object(executor, 'start_run',
                          return_value=TaskRun.objects.create()) as m:
            planner.fire(plan)
        self.assertEqual(m.call_count, 1)
        plan.refresh_from_db()
        self.assertIsNotNone(plan.last_run_at)
        self.assertIsNotNone(plan.last_task)

    def test_fire_when_busy_is_recorded_not_raised(self):
        plan = SchedulePlan.objects.create(name='每天', freq=SchedulePlan.FREQ_DAILY)
        with patch.object(executor, 'start_run', side_effect=executor.RunBusy(7)):
            self.assertIsNone(planner.fire(plan))
        plan.refresh_from_db()
        self.assertIn('跳过', plan.last_status)

    def test_crud_and_run_now_from_web(self):
        AutoCase.objects.create(tcid='c1', name='C1')
        resp = self.client.post(reverse('runner:schedule_save'), {
            'name': '每天冒烟', 'enabled': '1', 'freq': SchedulePlan.FREQ_DAILY,
            'hour': '8', 'minute': '30', 'scope_type': SchedulePlan.SCOPE_CASES,
            'scope_value': 'c1,nonexistent',
        }, follow=True)
        self.assertTrue(any('不存在' in str(m) for m in resp.context['messages']))
        plan = SchedulePlan.objects.get()
        self.assertEqual(plan.case_filter(), 'CASES:c1,nonexistent')

        # 编辑：改成按标签
        self.client.post(reverse('runner:schedule_edit_save', args=[plan.pk]), {
            'name': '每天冒烟', 'enabled': '1', 'freq': SchedulePlan.FREQ_WEEKLY,
            'weekdays': ['1', '3'], 'hour': '9', 'minute': '0',
            'scope_type': SchedulePlan.SCOPE_TAG, 'scope_value': '冒烟',
        })
        plan.refresh_from_db()
        self.assertEqual(plan.weekday_list, [1, 3])
        self.assertEqual(plan.case_filter(), 'TAGS:冒烟')

        # 立即执行
        with patch.object(executor, 'start_run',
                          return_value=TaskRun.objects.create()):
            resp = self.client.post(reverse('runner:schedule_run_now', args=[plan.pk]),
                                    follow=True)
        self.assertTrue(any('手动触发' in str(m) for m in resp.context['messages']))

        # 停用 / 删除
        self.client.post(reverse('runner:schedule_toggle', args=[plan.pk]))
        self.assertFalse(SchedulePlan.objects.get().enabled)
        self.client.post(reverse('runner:schedule_delete', args=[plan.pk]))
        self.assertEqual(SchedulePlan.objects.count(), 0)

    def test_list_page_renders(self):
        SchedulePlan.objects.create(name='x', freq=SchedulePlan.FREQ_DAILY)
        resp = self.client.get(reverse('runner:schedule_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context['plans'][0].next_run)

    def test_page_has_new_button_and_no_cross_links(self):
        """右上角只留「+ 新建定时计划」，通知设置 / 执行记录不再在这里堆按钮。

        只看标题那一段（导航栏里本来就有那两个入口，整页断言会误伤）。
        """
        page = self.client.get(reverse('runner:schedule_list')).content.decode()
        head = page.split('定时执行计划')[1][:600]
        self.assertIn('新建定时计划', head)
        self.assertNotIn('>通知设置<', head)
        self.assertNotIn('>执行记录<', head)

    def test_edit_link_opens_modal_with_plan(self):
        plan = SchedulePlan.objects.create(name='每天', freq=SchedulePlan.FREQ_DAILY)
        resp = self.client.get(reverse('runner:schedule_list'), {'edit': plan.pk})
        self.assertEqual(resp.context['editing'].pk, plan.pk)
        page = resp.content.decode()
        self.assertIn('openPlanModal()', page)          # 编辑时自动弹出
        self.assertIn(reverse('runner:schedule_edit_save', args=[plan.pk]), page)

    def test_hour_box_is_independent_from_weekly(self):
        """「每天」必须能看到小时控件 —— 曾经它被 weekly 的隐藏逻辑误关掉。"""
        page = self.client.get(reverse('runner:schedule_list')).content.decode()
        self.assertIn('id="hourBox"', page)
        self.assertIn("show('#hourBox', f === 'daily' || f === 'weekly')", page)
        self.assertIn("refreshFreq()", page)


# ---------------------------------------------------------------------------
# 范围参数：按标签单选 / 指定用例多选
# ---------------------------------------------------------------------------

class ScheduleScopeParamTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('sp', 'sp@example.com', 'pwd12345')
        self.client.force_login(self.user)

    def test_page_feeds_tag_and_case_options(self):
        AutoCase.objects.create(tcid='b_02', name='B2', tags='冒烟,回归')
        AutoCase.objects.create(tcid='a_01', name='A1', tags='冒烟')
        resp = self.client.get(reverse('runner:schedule_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['all_tags'], ['冒烟', '回归'])
        # 与用例列表页同一套排序（按 TCID）
        self.assertEqual(list(resp.context['all_cases']),
                         [('a_01', 'A1'), ('b_02', 'B2')])

    def test_save_from_case_checkboxes(self):
        """多选勾选框提交的是同名的 scope_cases 列表，不能只认单个 scope_value。"""
        AutoCase.objects.create(tcid='c1', name='C1')
        AutoCase.objects.create(tcid='c2', name='C2')
        self.client.post(reverse('runner:schedule_save'), {
            'name': '跑两条', 'enabled': '1', 'freq': SchedulePlan.FREQ_DAILY,
            'hour': '8', 'minute': '0',
            'scope_type': SchedulePlan.SCOPE_CASES,
            'scope_cases': ['c1', 'c2'],
        })
        plan = SchedulePlan.objects.get()
        self.assertEqual(plan.case_filter(), 'CASES:c1,c2')

    def test_save_keeps_legacy_scope_value_string(self):
        """老链接 / 无 JS 时仍可能只带一个逗号串，不能被空列表洗掉。"""
        AutoCase.objects.create(tcid='c1', name='C1')
        self.client.post(reverse('runner:schedule_save'), {
            'name': '跑一条', 'enabled': '1', 'freq': SchedulePlan.FREQ_DAILY,
            'hour': '8', 'minute': '0',
            'scope_type': SchedulePlan.SCOPE_CASES,
            'scope_value': 'c1',
        })
        self.assertEqual(SchedulePlan.objects.get().case_filter(), 'CASES:c1')

    def test_all_scope_clears_value(self):
        AutoCase.objects.create(tcid='c1', name='C1')
        self.client.post(reverse('runner:schedule_save'), {
            'name': '全跑', 'enabled': '1', 'freq': SchedulePlan.FREQ_DAILY,
            'hour': '8', 'minute': '0',
            'scope_type': SchedulePlan.SCOPE_ALL, 'scope_cases': ['c1'],
        })
        plan = SchedulePlan.objects.get()
        self.assertEqual(plan.scope_value, '')
        self.assertEqual(plan.case_filter(), '全部启用用例')

    def test_edit_page_preselects_cases(self):
        AutoCase.objects.create(tcid='c1', name='C1')
        AutoCase.objects.create(tcid='c2', name='C2')
        self.client.post(reverse('runner:schedule_save'), {
            'name': '跑一条', 'enabled': '1', 'freq': SchedulePlan.FREQ_DAILY,
            'hour': '8', 'minute': '0',
            'scope_type': SchedulePlan.SCOPE_CASES, 'scope_cases': ['c2'],
        })
        plan = SchedulePlan.objects.get()
        resp = self.client.get(reverse('runner:schedule_list'),
                               {'edit': str(plan.pk)})
        self.assertEqual(resp.context['picked_cases'], ['c2'])
        page = resp.content.decode()
        self.assertRegex(page, r'value="c2"\s+checked')
        self.assertNotRegex(page, r'value="c1"\s+checked')


# ---------------------------------------------------------------------------
# 调度锁：残留锁必须能自动接管（否则全站定时计划静默失效）
# ---------------------------------------------------------------------------

class PlannerLockTests(TestCase):

    def setUp(self):
        self._saved = planner._lock_path
        planner._lock_path = None
        self._force_release()

    def tearDown(self):
        planner._lock_path = self._saved
        self._force_release()

    def _force_release(self):
        if os.path.exists(planner._LOCK_FILE):
            try:
                os.remove(planner._LOCK_FILE)
            except OSError:
                pass

    def test_alive_holder_blocks_second_acquire(self):
        got = planner._acquire_process_lock()
        planner._lock_path = got          # 正常由 start() / 主循环赋值
        self.assertIsNotNone(got)
        self.assertTrue(planner.is_running())
        # 持有者就是本进程，还活着 —— 再抢一次应该拿不到
        self.assertIsNone(planner._acquire_process_lock())

    def test_orphan_lock_is_taken_over_immediately(self):
        """服务被强杀留下的锁：进程号已经不存在，必须立刻接管，不能干等 TTL。"""
        with open(planner._LOCK_FILE, 'w') as f:
            f.write('999999')          # 一个几乎不可能存在的 pid
        old = time.time() - 60         # 心跳只停了 1 分钟，远小于 TTL
        os.utime(planner._LOCK_FILE, (old, old))
        with patch.object(planner, '_pid_alive', return_value=False):
            self.assertIsNotNone(planner._acquire_process_lock())
        self.assertEqual(planner._read_lock_pid(), os.getpid())

    def test_lock_holder_is_not_deleted_by_others(self):
        with open(planner._LOCK_FILE, 'w') as f:
            f.write('999999')
        planner._lock_path = planner._LOCK_FILE
        planner._release_process_lock()          # 不是自己的锁，不该删
        self.assertTrue(os.path.exists(planner._LOCK_FILE))

    def test_lock_info_reports_owner(self):
        self.assertIsNone(planner.lock_info()['pid'])
        planner._acquire_process_lock()
        info = planner.lock_info()
        self.assertEqual(info['pid'], os.getpid())
        self.assertTrue(info['alive'])


# ---------------------------------------------------------------------------
# 执行记录的时间筛选（优化项 ⑨）
# ---------------------------------------------------------------------------

class RunListTimeFilterTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_superuser('rl', 'rl@example.com', 'pwd12345')
        self.client.force_login(self.user)
        now = timezone.now()
        old = TaskRun.objects.create(status=TaskRun.STATUS_PASSED, case_filter='old')
        TaskRun.objects.filter(pk=old.pk).update(
            started_at=now - datetime.timedelta(days=10))
        for i in range(3):
            TaskRun.objects.create(status=TaskRun.STATUS_FAILED, case_filter='new')

    def _count(self, **params):
        return self.client.get(reverse('runner:run_list'), params).context['paginator'].count

    def test_range_today(self):
        self.assertEqual(self._count(range='today'), 3)

    def test_range_7d_excludes_older(self):
        self.assertEqual(self._count(range='7d'), 3)

    def test_range_30d_includes_older(self):
        self.assertEqual(self._count(range='30d'), 4)

    def test_explicit_date_range(self):
        today = timezone.localtime(timezone.now()).date()
        self.assertEqual(self._count(since=str(today), until=str(today)), 3)

    def test_filter_survives_pagination(self):
        """翻到第 2 页时筛选条件不能丢。"""
        resp = self.client.get(reverse('runner:run_list'), {'range': '30d'})
        self.assertIn('range=30d', resp.context['filter_qs'])

    def test_bad_date_is_ignored(self):
        self.assertEqual(self.client.get(
            reverse('runner:run_list'), {'since': 'not-a-date'}).status_code, 200)

    def test_time_filter_comes_before_keyword_box(self):
        """筛选条的排布：状态 -> 时间 -> 执行范围关键词。"""
        page = self.client.get(reverse('runner:run_list')).content.decode()
        self.assertLess(page.index('name="since"'), page.index('name="q"'))


# ---------------------------------------------------------------------------
# 页面框架
# ---------------------------------------------------------------------------

class LayoutTests(TestCase):

    def test_navbar_stays_on_top(self):
        user = User.objects.create_superuser('lay', 'l@example.com', 'pwd12345')
        self.client.force_login(user)
        page = self.client.get(reverse('runner:run_list')).content.decode()
        self.assertIn('position: sticky', page)

    def test_password_input_shares_text_input_style(self):
        """密文框也要跟其它输入框同款样式（曾漏在 CSS 选择器外，宽窄边框都不一致）。"""
        user = User.objects.create_superuser('lay2', 'l2@example.com', 'pwd12345')
        self.client.force_login(user)
        page = self.client.get(reverse('runner:notify_settings')).content.decode()
        self.assertIn('input[type=text], input[type=password]', page)
