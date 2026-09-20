'''执行通知：邮件发送 + 正文组装。

设计取舍
--------
1. **整个模块对外吞异常。** 通知是旁路能力 —— 发不出去最多看不到邮件，
   绝不能反过来影响一轮已经跑完的执行（比如把 finally 里的收尾逻辑带崩）。
   失败原因会写进 TaskRun.notify_error，运维在页面上就能看到。
2. **不引入第三方库。** smtplib + email 都在标准库里，装依赖的收益配不上风险。
3. **密码可以走环境变量。** YIKEUI_SMTP_PASSWORD 优先于数据库里存的那个，
   正式环境可以完全不在库里落明文。
'''
import logging
import os
import smtplib
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from django.utils import timezone

logger = logging.getLogger(__name__)

# 需要发通知的任务状态
FAIL_STATUSES = ('failed', 'error')


def _escaped(s):
    return (str(s or '').replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


def build_mail(task):
    """组装一封「执行结果通知」的 (主题, HTML 正文, 附件路径列表)。"""
    status_text = task.get_status_display()
    failed = task.failure_names
    rows = ''.join('<li><code>%s</code></li>' % _escaped(n) for n in failed) or '<li>（无明细）</li>'

    subject = '【UI自动化】执行#%s %s（通过%d / 失败%d / 异常%d）' % (
        task.pk, status_text, task.passed, task.failed, task.error)

    scope = task.case_filter or '-'
    started = task.started_at.strftime('%Y-%m-%d %H:%M:%S') if task.started_at else '-'
    who = task.triggered_by.username if task.triggered_by else '系统（定时触发）'

    html = u'''<div style="font-family:Microsoft YaHei,Arial,sans-serif;font-size:14px;color:#2c2c2a">
  <h3 style="margin:0 0 12px">UI 自动化测试执行结果</h3>
  <table cellpadding="6" cellspacing="0" border="0" style="font-size:13px">
    <tr><td>任务编号</td><td><b>#%s</b></td></tr>
    <tr><td>执行结果</td><td><b>%s</b></td></tr>
    <tr><td>执行范围</td><td>%s</td></tr>
    <tr><td>统计</td><td>通过 %s / 失败 %s / 异常 %s（共 %s 条）</td></tr>
    <tr><td>开始时间</td><td>%s</td></tr>
    <tr><td>耗时</td><td>%s 秒</td></tr>
    <tr><td>执行人</td><td>%s</td></tr>
  </table>
  <p style="margin:14px 0 6px"><b>失败 / 异常明细：</b></p>
  <ul>%s</ul>
  <p style="color:#94938e;font-size:12px">
    本报告邮件由 yikeUIAuto 自动发出；详细报告请见附件，或登录平台查看执行记录。
  </p>
</div>''' % (task.pk, _escaped(status_text), _escaped(scope),
             task.passed, task.failed, task.error, task.total,
             started, task.duration, _escaped(who), rows)

    attachments = []
    path = task.report_abspath
    if path and os.path.exists(path):
        attachments.append(path)
    return subject, html, attachments


def send(task, cfg=None, subject=None, html=None, attachments=None):
    """真正发一封信。出错时抛出原始异常，由调用方决定怎么处理。"""
    if cfg is None:
        from .models import NotifyConfig
        cfg = NotifyConfig.get()
    receivers = cfg.receiver_list
    if not receivers:
        raise ValueError('没有配置收件人')

    if subject is None:
        subject, html, attachments = build_mail(task)

    msg = MIMEMultipart()
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = formataddr(('yikeUIAuto', cfg.username))
    msg['To'] = ','.join(receivers)
    msg.attach(MIMEText(html or '', 'html', 'utf-8'))

    for path in (attachments or []):
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, 'rb') as f:
                part = MIMEApplication(f.read())
        except OSError:
            continue
        part.add_header('Content-Disposition', 'attachment',
                        filename=os.path.basename(path))
        msg.attach(part)

    if cfg.use_ssl:
        server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
    try:
        server.ehlo()
        if cfg.use_tls and not cfg.use_ssl:
            server.starttls()
            server.ehlo()
        pwd = cfg.smtp_password()
        if cfg.username and pwd:
            server.login(cfg.username, pwd)
        refused = server.sendmail(cfg.username, receivers, msg.as_string())
        if refused:
            raise RuntimeError('部分收件人被拒收：%s' % list(refused.keys()))
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return len(receivers)


def send_test(cfg, to=None):
    """配置页的「发送测试邮件」——验证 SMTP 通不通，跟任务无关。"""
    if not cfg.smtp_host or not cfg.username:
        raise ValueError('请先填写 SMTP 服务器与发件人邮箱')
    receivers = [x.strip() for x in (to or '').replace(';', ',').split(',') if x.strip()]
    if not receivers:
        receivers = cfg.receiver_list
    if not receivers:
        raise ValueError('请填写至少一个收件人')

    html = (u'<div style="font-family:Microsoft YaHei,Arial;font-size:14px">'
            u'这是 yikeUIAuto 的<b>测试邮件</b>，收到说明 SMTP 配置正确。<br>'
            u'服务器：%s:%s（SSL=%s / STARTTLS=%s）<br>发送时间：%s</div>'
            % (_escaped(cfg.smtp_host), cfg.smtp_port,
               cfg.use_ssl, cfg.use_tls,
               timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')))

    msg = MIMEMultipart()
    msg['Subject'] = Header('【UI自动化】测试邮件 - 配置正确', 'utf-8')
    msg['From'] = formataddr(('yikeUIAuto', cfg.username))
    msg['To'] = ','.join(receivers)
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    if cfg.use_ssl:
        server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
    try:
        server.ehlo()
        if cfg.use_tls and not cfg.use_ssl:
            server.starttls()
            server.ehlo()
        pwd = cfg.smtp_password()
        if cfg.username and pwd:
            server.login(cfg.username, pwd)
        refused = server.sendmail(cfg.username, receivers, msg.as_string())
        if refused:
            raise RuntimeError('部分收件人被拒收：%s' % list(refused.keys()))
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return receivers


def notify_task(task):
    """执行结束后调用：按需发邮件，并把结果回写 TaskRun。

    返回值：True 已发送 / False 未发送（含被跳过）/ None 出错。
    无论如何都不抛出 —— 通知失败不应影响已经跑完的执行。
    """
    from .models import NotifyConfig
    try:
        cfg = NotifyConfig.get()
        if not cfg.is_ready:
            return False
        if cfg.notify_on == cfg.ONLY_FAIL and task.status not in FAIL_STATUSES:
            return False
        if task.notified:
            return False

        if cfg.attach_report:
            send(task, cfg)
        else:
            # 报告动辄几百 KB，有些邮箱有限制 —— 允许只发正文
            subject, html, _ = build_mail(task)
            send(task, cfg, subject=subject, html=html, attachments=[])

        task.notified = True
        task.notified_at = timezone.now()
        task.notify_error = ''
        task.save(update_fields=['notified', 'notified_at', 'notify_error'])
        logger.info('执行 #%s 的通知邮件已发出', task.pk)
        return True
    except Exception as e:  # 旁路能力：任何错误都不能往上冒
        logger.warning('执行 #%s 的邮件通知失败：%s', task.pk, e)
        try:
            task.notify_error = str(e)[:500]
            task.save(update_fields=['notify_error'])
        except Exception:
            pass
        return None
