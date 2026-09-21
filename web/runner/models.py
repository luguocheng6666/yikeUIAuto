"""执行任务与报告记录 —— Excel 里没有对应表，是 Web 化之后新增的能力。"""
import os

from django.conf import settings
from django.db import models


class TaskRun(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_PASSED = 'passed'
    STATUS_FAILED = 'failed'
    STATUS_ERROR = 'error'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, '等待中'),
        (STATUS_RUNNING, '执行中'),
        (STATUS_PASSED, '全部通过'),
        (STATUS_FAILED, '存在失败'),
        (STATUS_ERROR, '执行异常'),
        (STATUS_CANCELLED, '已停止'),
    ]

    status = models.CharField('状态', max_length=20,
                              choices=STATUS_CHOICES, default=STATUS_PENDING)
    case_filter = models.CharField('执行范围', max_length=500, blank=True, default='全部启用用例')
    total = models.IntegerField('用例总数', default=0)
    passed = models.IntegerField('通过', default=0)
    failed = models.IntegerField('失败', default=0)
    error = models.IntegerField('异常', default=0)

    current_step = models.CharField('当前步骤', max_length=300, blank=True, default='')
    log_tail = models.TextField('日志尾部', blank=True, default='')
    # 异常摘要：失败/异常时写入一行行「大概说明」（异常类型 + 消息 + 出错的用例），
    # 在执行列表/详情页直接展示；完整堆栈另落项目日志文件 Logs/run_errors.log。
    error_summary = models.TextField('异常摘要', blank=True, default='')
    cancel_requested = models.BooleanField('已请求停止', default=False)

    started_at = models.DateTimeField('开始时间', null=True, blank=True)
    finished_at = models.DateTimeField('结束时间', null=True, blank=True)
    duration = models.FloatField('耗时(秒)', default=0)

    # 只存「相对于报告目录的文件名」（如 result_12.html），换机器/换目录也不会失效；
    # 历史数据里可能仍是绝对路径，读取时用 report_abspath 兼容。
    report_path = models.CharField('报告文件', max_length=500, blank=True, default='')
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, verbose_name='执行人')
    created_at = models.DateTimeField(auto_now_add=True)

    # 邮件通知结果：notified 保证同一轮只发一次（避免异常重入、或重复结束时重发）
    notified = models.BooleanField('已发通知', default=False)
    notified_at = models.DateTimeField('通知时间', null=True, blank=True)
    notify_error = models.TextField('通知失败原因', blank=True, default='')

    class Meta:
        verbose_name = '执行记录'
        verbose_name_plural = '执行记录'
        ordering = ['-created_at']

    def __str__(self):
        return '#%s %s' % (self.pk, self.get_status_display())

    @property
    def is_finished(self):
        return self.status in (self.STATUS_PASSED, self.STATUS_FAILED,
                               self.STATUS_ERROR, self.STATUS_CANCELLED)

    @property
    def is_active(self):
        return self.status in (self.STATUS_PENDING, self.STATUS_RUNNING)

    @property
    def report_abspath(self):
        """报告的绝对路径：兼容历史库里存过的绝对路径。"""
        p = (self.report_path or '').strip()
        if not p:
            return ''
        if os.path.isabs(p):
            return p
        return os.path.join(str(settings.REPORTS_DIR), p)

    @property
    def failure_names(self):
        """从日志尾部解析出失败/异常的步骤标签（最多 10 条）。

        执行明细没有单独落表（刻意不为之首做趋势记录），日志里每完成一步就写一行
        「[失败] xxx」，这里按行前缀挑出来，够邮件正文用。
        """
        out = []
        for line in (self.log_tail or '').splitlines():
            s = line.strip()
            if s.startswith('[失败] ') or s.startswith('[异常] '):
                out.append(s.split(' ', 1)[1].strip())
        return [x for x in dict.fromkeys(out)][:10]


class NotifyConfig(models.Model):
    """邮件通知配置 —— 单例行（固定 pk=1），在 Web 上直接改。

    之所以做成配置行而不是写死 settings：SMTP 账号/收件人会随环境变，
    让人在页面上改完立刻点「发送测试邮件」验证，比改配置再重启省事得多。
    """

    ONLY_FAIL = 'fail'
    ALWAYS = 'always'
    NOTIFY_ON_CHOICES = [
        (ONLY_FAIL, '仅执行失败/异常时'),
        (ALWAYS, '每次执行结束都发'),
    ]

    enabled = models.BooleanField('启用邮件通知', default=False)
    notify_on = models.CharField('发送时机', max_length=10,
                                 choices=NOTIFY_ON_CHOICES, default=ONLY_FAIL)
    smtp_host = models.CharField('SMTP 服务器', max_length=200,
                                 blank=True, default='smtp.qq.com')
    smtp_port = models.IntegerField('端口', default=465)
    use_ssl = models.BooleanField('使用 SSL（465 端口通常开）', default=True)
    use_tls = models.BooleanField('使用 STARTTLS（587 端口通常开）', default=False)
    # 既是 SMTP 登录账号，也是发件人地址 —— 页面上一个字段搞定（早先拆成
    # 「登录账号 + 发件人邮箱」两个框，绝大多数邮箱二者一致，填两遍纯属负担）。
    username = models.CharField('发件人邮箱', max_length=200, blank=True, default='')
    password = models.CharField('密码 / 授权码', max_length=200, blank=True, default='')
    receivers = models.TextField('收件人（多个用英文逗号分隔）', blank=True, default='')
    attach_report = models.BooleanField('附上 HTML 报告附件', default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, verbose_name='最后修改人')

    class Meta:
        verbose_name = '邮件通知配置'
        verbose_name_plural = '邮件通知配置'

    def __str__(self):
        return '邮件通知（%s）' % ('已启用' if self.enabled else '未启用')

    @classmethod
    def get(cls):
        """取唯一的那一行业务配置（没有就建一份空的）。"""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def receiver_list(self):
        out = []
        for part in (self.receivers or '').replace(';', ',').split(','):
            p = part.strip()
            if p and p not in out:
                out.append(p)
        return out

    def smtp_password(self):
        """SMTP 密码：环境变量优先，其次才是库里存的那个。

        让正式环境可以完全不在数据库里落明文 —— 设了 YIKEUI_SMTP_PASSWORD 之后，
        页面上的密码框留空即可。
        """
        return os.environ.get('YIKEUI_SMTP_PASSWORD') or self.password

    @property
    def is_ready(self):
        return bool(self.enabled and self.smtp_host and self.username
                    and self.receiver_list)


class SchedulePlan(models.Model):
    """定时执行计划 —— 全部在 Web 上配置，调度线程跑在 Django 进程内。

    为什么不用系统计划任务（crontab / 任务计划程序）：那样每换一台部署机器都要
    重新配一遍，这里的目的就是让「什么时候跑」成为平台里的一条数据。
    调度逻辑放在 runner/planner.py，纯标准库实现，Windows / Linux 行为一致。
    """

    FREQ_DAILY = 'daily'
    FREQ_WEEKLY = 'weekly'
    FREQ_HOURLY = 'hourly'
    FREQ_CHOICES = [
        (FREQ_HOURLY, '每 N 小时'),
        (FREQ_DAILY, '每天'),
        (FREQ_WEEKLY, '每周'),
    ]

    SCOPE_ALL = 'all'
    SCOPE_TAG = 'tag'
    SCOPE_CASES = 'cases'
    SCOPE_CHOICES = [
        (SCOPE_ALL, '全部启用用例'),
        (SCOPE_TAG, '按标签'),
        (SCOPE_CASES, '指定用例'),
    ]

    name = models.CharField('计划名称', max_length=100)
    enabled = models.BooleanField('启用', default=True)
    freq = models.CharField('频率', max_length=10,
                            choices=FREQ_CHOICES, default=FREQ_DAILY)

    # 每 N 小时：interval_hours 间隔 + 在第几分钟触发
    interval_hours = models.IntegerField('间隔小时数', default=2)
    # 每天 / 每周：触发时刻；每周再看 weekdays
    hour = models.IntegerField('小时（0-23）', default=8)
    minute = models.IntegerField('分钟（0-59）', default=30)
    # 每周：1=周一 … 7=周日，逗号分隔
    weekdays = models.CharField('星期（1-7，逗号分隔）', max_length=30,
                                blank=True, default='1')

    scope_type = models.CharField('执行范围', max_length=10,
                                  choices=SCOPE_CHOICES, default=SCOPE_ALL)
    scope_value = models.CharField('范围参数（标签名或多个 TCID，逗号分隔）',
                                  max_length=500, blank=True, default='')

    last_run_at = models.DateTimeField('上次触发', null=True, blank=True)
    last_status = models.CharField('上次结果', max_length=100, blank=True, default='')
    last_task = models.ForeignKey(TaskRun, on_delete=models.SET_NULL, null=True,
                                  blank=True, related_name='scheduled_plans',
                                  verbose_name='上次执行记录')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, verbose_name='创建人')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '定时计划'
        verbose_name_plural = '定时计划'
        ordering = ['name']

    def __str__(self):
        return '%s（%s）' % (self.name, self.get_freq_display())

    # ------------------------------------------------------------ 范围
    @property
    def weekday_list(self):
        out = []
        for p in (self.weekdays or '').replace('，', ',').split(','):
            p = p.strip()
            if p.isdigit() and 1 <= int(p) <= 7:
                n = int(p)
                if n not in out:
                    out.append(n)
        return out

    def case_filter(self):
        """翻译成 TaskRun.case_filter 的写法（与 executor._resolve_scope 对应）。"""
        if self.scope_type == self.SCOPE_TAG and self.scope_value.strip():
            return 'TAGS:%s' % self.scope_value.strip()
        if self.scope_type == self.SCOPE_CASES and self.scope_value.strip():
            tcids = [t.strip() for t in self.scope_value.replace('，', ',').split(',')
                     if t.strip()]
            return 'CASES:%s' % ','.join(tcids)
        return '全部启用用例'

    def scope_text(self):
        if self.scope_type == self.SCOPE_TAG:
            return '标签 %s' % self.scope_value
        if self.scope_type == self.SCOPE_CASES:
            return '指定 %s 条' % len([x for x in self.scope_value.split(',') if x.strip()])
        return '全部启用用例'

    # ------------------------------------------------------------ 时间
    def freq_text(self):
        if self.freq == self.FREQ_HOURLY:
            return '每 %s 小时，第 %s 分钟' % (self.interval_hours, self.minute)
        clock = '%02d:%02d' % (self.hour, self.minute)
        if self.freq == self.FREQ_WEEKLY:
            names = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '日'}
            days = '、'.join('周%s' % names.get(d, d) for d in self.weekday_list) or '未选日'
            return '每周%s %s' % (days, clock)
        return '每天 %s' % clock

    def _slots_for_day(self, day):
        """某一天里本计划的全部触发时刻（本地时区 naive -> aware）。"""
        import datetime as _dt
        from django.utils import timezone as _tz
        slots = []
        if self.freq == self.FREQ_HOURLY:
            step = max(int(self.interval_hours or 1), 1)
            for h in range(0, 24, step):
                slots.append(_dt.datetime.combine(day, _dt.time(h, self.minute or 0)))
        elif self.freq == self.FREQ_DAILY or self.freq == self.FREQ_WEEKLY:
            if self.freq == self.FREQ_WEEKLY:
                iso = day.isoweekday()
                if self.weekday_list and iso not in self.weekday_list:
                    return []
            slots.append(_dt.datetime.combine(day, _dt.time(self.hour or 0, self.minute or 0)))
        return [_tz.make_aware(s) for s in slots]

    def last_slot(self, now):
        """<= now 的最近一个应触发时刻；没有则返回 None。往前最多找 7 天。"""
        import datetime as _dt
        for back in range(0, 8):
            day = (now - _dt.timedelta(days=back)).date()
            for slot in reversed(self._slots_for_day(day)):
                if slot <= now:
                    return slot
        return None

    def next_slot(self, now):
        """> now 的下一个触发时刻，供列表页展示「下次执行」。"""
        import datetime as _dt
        for fwd in range(0, 8):
            day = (now + _dt.timedelta(days=fwd)).date()
            for slot in self._slots_for_day(day):
                if slot > now:
                    return slot
        return None

    def grace_seconds(self):
        """迟到多久就不再补跑 —— 服务停机一整天，重启后不该把过期任务全跑一遍。"""
        if self.freq == self.FREQ_HOURLY:
            return max(int(self.interval_hours or 1), 1) * 1800
        return 2 * 3600

    def is_due(self, now):
        slot = self.last_slot(now)
        if slot is None:
            return None
        if (now - slot).total_seconds() > self.grace_seconds():
            return None
        if self.last_run_at and self.last_run_at >= slot:
            return None
        return slot
