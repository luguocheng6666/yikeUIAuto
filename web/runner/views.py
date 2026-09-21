'''执行记录相关视图：一键运行 / 列表 / 详情 / 进度轮询 / 报告查看 / 停止执行。'''
import datetime
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.functions import Coalesce

from cases.models import TestCase
from . import notifier, planner
from .executor import RunBusy, request_cancel, start_run
from .models import NotifyConfig, SchedulePlan, TaskRun

PAGE_SIZE = 20


def _start(request, tcid=None, tcids=None, case_filter=None):
    """统一的执行入口（只允许 POST）。"""
    try:
        task = start_run(request.user, scope_tcid=tcid, scope_tcids=tcids,
                         case_filter=case_filter)
    except RunBusy as e:
        messages.warning(request, '已有任务正在执行（#%s），请等它结束后再试。' % e.running_pk)
        return redirect('runner:run_list')
    return redirect('runner:run_detail', pk=task.pk)


@login_required
@require_POST
def run_start_case(request, pk):
    """只运行某一条用例（POST）。"""
    case = get_object_or_404(TestCase, pk=pk)
    return _start(request, tcid=case.tcid)


@login_required
@require_POST
def run_start_tag(request):
    """运行带某个标签的全部启用用例（POST: tag=xxx）。

    标签成员在执行开始时才换算成具体的 tcid 列表（见 executor._resolve_scope），
    所以给用例加/删标签后不用重跑历史记录。
    """
    tag = request.POST.get('tag', '').strip()
    if not tag:
        messages.error(request, '请先选择要执行的标签')
        return redirect('cases:case_list')
    return _start(request, case_filter='TAGS:%s' % tag)


@login_required
@require_POST
def run_start_selected(request):
    """运行在列表页勾选的若干条用例（POST: cids=多个用例 pk）。"""
    ids = [i for i in request.POST.getlist('cids') if str(i).isdigit()]
    if not ids:
        messages.error(request, '请先在列表页勾选要执行的用例')
        return redirect('cases:case_list')
    tcids = list(TestCase.objects.filter(pk__in=ids).values_list('tcid', flat=True))
    return _start(request, tcids=tcids)


RANGE_CHOICES = [
    ('today', '今天'),
    ('7d', '近 7 天'),
    ('30d', '近 30 天'),
]


def _parse_date(s):
    """把 YYYY-MM-DD 解析成本地时区的 aware datetime（当天 0 点）。"""
    s = (s or '').strip()
    if not s:
        return None
    try:
        d = datetime.datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None
    # create() 对已有时区的 naive datetime 直接使用（Django 4 不会告警）
    return timezone.make_aware(datetime.datetime.combine(d, datetime.time.min))


def _resolve_time_window(rng, since, until):
    """把快捷区间 / 手填起止日期换算成 (起点, 终点)。

    手填的优先级高于快捷区间 —— 用户既然打开了日期框，说明想要精确控制。
    终点按「当天 23:59:59」处理，否则截止日当天这一天会被漏掉。
    """
    now = timezone.localtime(timezone.now())
    today0 = timezone.make_aware(
        datetime.datetime.combine(now.date(), datetime.time.min))
    if since or until:
        start = _parse_date(since)
        end = _parse_date(until)
        if end:
            end = end + datetime.timedelta(days=1)
        return start, end
    if rng == 'today':
        return today0, None
    if rng == '7d':
        return today0 - datetime.timedelta(days=6), None
    if rng == '30d':
        return today0 - datetime.timedelta(days=29), None
    return None, None


@login_required
def run_list(request):
    """执行记录：按状态 / 时间 / 范围关键字筛选，并分页。

    记录会随每天的执行不断堆积，不分页迟早变成一张几千行的表。
    时间按「开始时间」过滤；个别异常任务没写 started_at 时退回创建时间，
    保证它不会因为缺失字段就从筛选结果里凭空消失。
    """
    # Coalesce 让 started_at 为空的任务退回 created_at，排序/筛选口径统一
    runs = TaskRun.objects.annotate(_t=Coalesce('started_at', 'created_at'))
    status = request.GET.get('status', '').strip()
    q = request.GET.get('q', '').strip()
    rng = request.GET.get('range', '').strip()
    since = request.GET.get('since', '').strip()
    until = request.GET.get('until', '').strip()
    if status:
        runs = runs.filter(status=status)
    if q:
        runs = runs.filter(Q(case_filter__icontains=q))

    start, end = _resolve_time_window(rng, since, until)
    if start:
        runs = runs.filter(_t__gte=start)
    if end:
        runs = runs.filter(_t__lt=end)

    paginator = Paginator(runs, PAGE_SIZE)
    page = paginator.get_page(request.GET.get('page'))

    # 翻页链接要带上当前筛选条件，否则翻到第二页筛选就被重置了
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'runner/run_list.html', {
        'runs': page,
        'page_obj': page,
        'paginator': paginator,
        'status': status,
        'q': q,
        'range': rng,
        'since': since,
        'until': until,
        'range_choices': RANGE_CHOICES,
        'filter_qs': params.urlencode(),
        'status_choices': TaskRun.STATUS_CHOICES,
        'all_count': TaskRun.objects.count(),
    })


@login_required
def run_detail(request, pk):
    task = get_object_or_404(TaskRun, pk=pk)
    return render(request, 'runner/run_detail.html', {'task': task})


@login_required
def run_status_api(request, pk):
    """前端轮询用：返回当前进度快照。"""
    task = get_object_or_404(TaskRun, pk=pk)
    return JsonResponse({
        'pk': task.pk,
        'status': task.status,
        'status_display': task.get_status_display(),
        'total': task.total,
        'passed': task.passed,
        'failed': task.failed,
        'error': task.error,
        'current_step': task.current_step,
        'error_summary': task.error_summary,
        'log_tail': task.log_tail,
        'duration': task.duration,
        'finished': task.is_finished,
        'can_cancel': task.is_active,
        'has_report': bool(task.report_path),
    })


@login_required
@require_POST
def notify_test(request):
    """发送一封测试邮件，验证 SMTP 配置是否可用。"""
    cfg = NotifyConfig.get()
    to = request.POST.get('to', '').strip()
    try:
        got = notifier.send_test(cfg, to=to)
        messages.success(request, '测试邮件已发送到：%s' % '、'.join(got))
    except Exception as e:
        messages.error(request, '发送失败：%s' % e)
    return redirect('runner:notify_settings')


@login_required
def notify_settings(request):
    """邮件通知配置页。"""
    cfg = NotifyConfig.get()
    if request.method == 'POST':
        cfg.enabled = request.POST.get('enabled') == '1'
        cfg.notify_on = (NotifyConfig.ALWAYS
                         if request.POST.get('notify_on') == NotifyConfig.ALWAYS
                         else NotifyConfig.ONLY_FAIL)
        cfg.smtp_host = request.POST.get('smtp_host', '').strip()
        try:
            cfg.smtp_port = int(request.POST.get('smtp_port') or 465)
        except ValueError:
            cfg.smtp_port = 465
        cfg.use_ssl = request.POST.get('use_ssl') == '1'
        cfg.use_tls = request.POST.get('use_tls') == '1'
        # 页面上只有一个「发件人邮箱」框（name=sender），它同时是 SMTP 登录账号；
        # 兼容老表单里可能仍在提交 username 的情况。
        cfg.username = (request.POST.get('sender')
                        or request.POST.get('username') or '').strip()
        # 环境变量已提供密码时，页面留空不会把环境变量覆盖掉
        pwd = request.POST.get('password', '')
        if pwd or not os.environ.get('YIKEUI_SMTP_PASSWORD'):
            cfg.password = pwd
        cfg.receivers = request.POST.get('receivers', '').strip()
        cfg.attach_report = request.POST.get('attach_report') == '1'
        cfg.updated_by = request.user
        cfg.save()
        messages.success(request, '通知配置已保存%s'
                         % ('' if cfg.is_ready else '（但配置还不完整，暂时不会发出邮件）'))
        return redirect('runner:notify_settings')

    env_password_set = bool(os.environ.get('YIKEUI_SMTP_PASSWORD'))
    return render(request, 'runner/notify.html', {
        'cfg': cfg,
        'env_password_set': env_password_set,
    })


def _plan_form(request, plan=None):
    """从 POST 里读出计划字段并保存（plan 为 None 表示新建）。"""
    from cases.models import TestCase
    plan = plan or SchedulePlan()
    plan.name = (request.POST.get('name') or '').strip() or (plan.name or '未命名计划')
    plan.enabled = request.POST.get('enabled') == '1'
    plan.freq = request.POST.get('freq') or SchedulePlan.FREQ_DAILY
    if plan.freq not in (SchedulePlan.FREQ_DAILY, SchedulePlan.FREQ_WEEKLY,
                         SchedulePlan.FREQ_HOURLY):
        plan.freq = SchedulePlan.FREQ_DAILY

    def _clamp(key, default, low, high):
        try:
            v = int(request.POST.get(key) or default)
        except ValueError:
            return default
        return low if v < low else (high if v > high else v)

    plan.interval_hours = _clamp('interval_hours', 2, 1, 23)
    plan.hour = _clamp('hour', 8, 0, 23)
    plan.minute = _clamp('minute', 0, 0, 59)
    if plan.freq == SchedulePlan.FREQ_WEEKLY:
        plan.weekdays = ','.join(
            request.POST.getlist('weekdays')) or '1'
    plan.scope_type = request.POST.get('scope_type') or SchedulePlan.SCOPE_ALL
    if plan.scope_type not in (SchedulePlan.SCOPE_ALL, SchedulePlan.SCOPE_TAG,
                               SchedulePlan.SCOPE_CASES):
        plan.scope_type = SchedulePlan.SCOPE_ALL
    plan.scope_value = (request.POST.get('scope_value') or '').strip()
    if plan.scope_type == SchedulePlan.SCOPE_CASES:
        # 「指定用例」在页面上是一组勾选框，没选任何一条时 POST 里只有空串，
        # 这里统一从 scope_cases（多个同名 checkbox）取值，免得被空字符串洗掉。
        picked = [t.strip() for t in request.POST.getlist('scope_cases') if t.strip()]
        if not picked and plan.scope_value:
            picked = [t.strip() for t in plan.scope_value.replace('，', ',').split(',')
                      if t.strip()]
        plan.scope_value = ','.join(picked)
    # 指定用例：页面上可以直接粘贴 TCID，也算ÓÃ例存在性的一次体检
    if plan.scope_type == SchedulePlan.SCOPE_CASES and plan.scope_value:
        tcids = [t.strip() for t in plan.scope_value.replace('，', ',').split(',') if t.strip()]
        missing = [t for t in tcids if not TestCase.objects.filter(tcid=t).exists()]
        if missing:
            messages.warning(request, '这些 TCID 在库里不存在，到时会跑不到：%s'
                             % '、'.join(missing[:8]))
        plan.scope_value = ','.join(tcids)
    if not plan.created_by and getattr(request.user, 'is_authenticated', False):
        plan.created_by = request.user
    plan.save()
    return plan


@login_required
def schedule_list(request):
    """定时计划列表：正在编辑的计划 pk 由 ?edit=<pk> 指定。"""
    plans = SchedulePlan.objects.all()
    now = timezone.now()
    for p in plans:
        p.next_run = p.next_slot(now)

    edit_pk = request.GET.get('edit', '').strip()
    editing = None
    if edit_pk.isdigit():
        editing = SchedulePlan.objects.filter(pk=int(edit_pk)).first()

    # 范围参数要在弹窗里做成选择控件（标签单选 / 用例多选），
    # 所以把可选值一次性喂给模板，别让人手打字符串。
    from cases.models import TestCase
    from cases.views import all_tags
    picked = []
    if editing and editing.scope_type == SchedulePlan.SCOPE_CASES:
        picked = [t.strip() for t in editing.scope_value.split(',') if t.strip()]

    return render(request, 'runner/schedules.html', {
        'plans': plans,
        'editing': editing,
        'all_tags': all_tags(),
        # 与用例列表页同一套排序（按 TCID），选项显示成「TCID·用例名称」
        'all_cases': TestCase.objects.order_by('tcid').values_list('tcid', 'name'),
        'picked_cases': picked,
        'lock': planner.lock_info(),
        'freq_choices': SchedulePlan.FREQ_CHOICES,
        'scope_choices': SchedulePlan.SCOPE_CHOICES,
        'weekday_choices': [(1, '周一'), (2, '周二'), (3, '周三'), (4, '周四'),
                            (5, '周五'), (6, '周六'), (7, '周日')],
        'planner_running': planner.is_running(),
    })


@login_required
@require_POST
def schedule_save(request, pk=None):
    plan = None
    if pk:
        plan = get_object_or_404(SchedulePlan, pk=pk)
    saved = _plan_form(request, plan=plan)
    messages.success(request, '定时计划已保存：%s' % saved.freq_text())
    return redirect('runner:schedule_list')


@login_required
@require_POST
def schedule_delete(request, pk):
    plan = get_object_or_404(SchedulePlan, pk=pk)
    plan.delete()
    messages.success(request, '定时计划已删除')
    return redirect('runner:schedule_list')


@login_required
@require_POST
def schedule_toggle(request, pk):
    plan = get_object_or_404(SchedulePlan, pk=pk)
    plan.enabled = not plan.enabled
    plan.save(update_fields=['enabled'])
    messages.info(request, '已%s计划：%s' % ('启用' if plan.enabled else '停用', plan.name))
    return redirect('runner:schedule_list')


@login_required
@require_POST
def schedule_run_now(request, pk):
    """不等到点，先跑一遍验证配置对不对。"""
    plan = get_object_or_404(SchedulePlan, pk=pk)
    task = planner.fire(plan)
    if task is None:
        messages.warning(request, '未触发：%s' % (plan.last_status or '已有任务在执行'))
    else:
        messages.success(request, '已手动触发，正在执行 #%s' % task.pk)
    return redirect('runner:schedule_list')


@login_required
def run_cancel(request, pk):
    """请求停止正在执行的任务。"""
    task = get_object_or_404(TaskRun, pk=pk)
    if request_cancel(task.pk):
        messages.info(request, '已发送停止指令，正在收尾…')
    else:
        messages.info(request, '该任务已结束，无需停止。')
    return redirect('runner:run_detail', pk=task.pk)


@login_required
@xframe_options_sameorigin
def run_report(request, pk):
    """查看本次执行的 HTML 报告（允许在同源 iframe 内渲染）。"""
    task = get_object_or_404(TaskRun, pk=pk)
    path = task.report_abspath
    if not path or not os.path.exists(path):
        return JsonResponse({'error': '报告尚未生成或已丢失'}, status=404)
    return FileResponse(open(path, 'rb'),
                        content_type='text/html; charset=utf-8')


@login_required
@xframe_options_sameorigin
def run_shot(request, pk, name):
    """报告里引用的截图（独立 png 文件）。只允许本次执行自己的截图。"""
    task = get_object_or_404(TaskRun, pk=pk)
    base = os.path.basename(name)
    if not base.startswith('run_%s_' % task.pk) or not base.endswith('.png'):
        raise Http404('截图不存在')
    from django.conf import settings
    path = os.path.join(str(settings.SHOTS_DIR), base)
    if not os.path.exists(path):
        raise Http404('截图不存在')
    return FileResponse(open(path, 'rb'), content_type='image/png')
