from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from cases.models import TestCase, TestStep
from runner.models import TaskRun


@login_required
def index(request):
    """首页：用例概况 + 最近执行"""
    total = TestCase.objects.count()
    enabled = TestCase.objects.filter(need_run=True).count()
    step_total = TestStep.objects.count()
    recent_runs = TaskRun.objects.all()[:5]

    # 最近一次执行结果分布
    last_run = TaskRun.objects.filter(status__in=['passed', 'failed', 'error']).first()
    result_stat = TestCase.objects.exclude(last_result='').values('last_result')

    return render(request, 'index.html', {
        'total': total,
        'enabled': enabled,
        'step_total': step_total,
        'recent_runs': recent_runs,
        'last_run': last_run,
    })
