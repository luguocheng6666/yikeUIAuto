'''用例维护视图：列表 / 详情（步骤 + 数据）/ 增删改 / 启停 / 导入导出'''
import datetime
import os
import tempfile

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from django.db.models import Count, Q

from .importer import export_excel, import_excel
from openpyxl import Workbook
from .keywords import KEYWORD_GROUPS, KEYWORD_TIPS, LOCATE_TYPES
from .models import TestCase, TestStep, TestData, StepSnapshot
from .stepvalues import (INPUT_SLOTS, SELECTOR_SLOTS, NO_DATA_KIND,
                         step_kind as _step_kind, steps_with_values)
from .validate import (ASSERT_WITHOUT_EXPECTED, NO_LOCATE_KW, NUMERIC_VALUE_KW,
                       XY_VALUE_KW, check_steps, count_issues)

# 「操作值」列针对各关键字的占位提示：告诉用户这一格该填什么。
# 凡是能接收数据的关键字都在这里给个说法，剩下的一律显示为「操作值（可不填）」。
DATA_PLACEHOLDERS = {
    'input': '输入值',
    'selectbytext': '选择值（选项文本）',
    'selectbyindex': '选择值（序号，从 0 开始）',
    'selectbyvalue': '选择值（option 的 value）',
    'codeslide': '滑块坐标 x,y（如 300,0）',
    'open_browser': 'Chrome / Firefox / Ie',
    'open_url': '网址 URL',
    'sleep': '等待秒数',
    'sendkeys': '按键（如 ENTER）',
    'start_app': '程序 exe 路径',
    'swith_window_handle_by_index': '窗口序号',
    'swith_window_handle_by_title': '窗口标题',
    'swith_frame': 'frame 的 id 或序号',
    'mouse_click': '坐标 x,y',
    'Exeucejs': 'JS 脚本',
    'assert_number_between': '范围 最小值-最大值',
}


def _yn(request, key, default=False):
    v = request.POST.get(key)
    if v is None:
        return default
    return str(v).strip().lower() in ('y', 'yes', 'true', '1', 'on')


def _int(request, key, default=1, minimum=1):
    """取正整数；填了非数字或小于下限都退回默认值，避免把 0/负数写进循环次数。"""
    try:
        v = int(str(request.POST.get(key) or '').strip() or default)
    except (TypeError, ValueError):
        return default
    return v if v >= minimum else default


def _tags(request):
    """规范化标签串：「冒烟,回归 权限」 -> 「冒烟,回归,权限」，数量上限 10 个。"""
    raw = request.POST.get('tags', '') or ''
    picked = request.POST.getlist('tag_pick')  # 页面上勾选的常用标签
    parts = TestCase.split_tags(raw) + [p.strip() for p in picked if p.strip()]
    out = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return ','.join(out[:10])


def all_tags():
    """库里出现过的全部标签（去重、按首次出现顺序），供筛选下拉与编辑页勾选。"""
    out = []
    for raw in TestCase.objects.exclude(tags='').values_list('tags', flat=True):
        for t in TestCase.split_tags(raw):
            if t not in out:
                out.append(t)
    return out


def _back(request, fallback='cases:case_list'):
    """跳回列表页，并尽量保留当前的搜索/标签筛选。"""
    from django.urls import reverse
    nxt = (request.POST.get('next') or '').strip()
    # 只接受站内相对路径，挡掉 //evil.com 这类开放重定向
    if nxt.startswith('/') and not nxt.startswith('//'):
        return redirect(nxt)
    return redirect(reverse(fallback))


def _apply_enabled(request):
    """把列表页勾选框的状态落盘成「是否需要执行」，返回被勾选的 tcid 列表。

    表单里每行都带一个 row_pk 隐藏域 —— 未勾选的 checkbox 不会提交，
    只有知道「本次页面上出现过哪些行」，才能把取消勾选的用例置为停用。
    同理，处于筛选状态时只会更新列表里出现的那些用例。
    """
    row_pks = [p for p in request.POST.getlist('row_pk') if str(p).isdigit()]
    enabled_pks = set(p for p in request.POST.getlist('enabled') if str(p).isdigit())
    for c in TestCase.objects.filter(pk__in=row_pks):
        want = str(c.pk) in enabled_pks
        if c.need_run != want:
            c.need_run = want
            c.save(update_fields=['need_run'])
    if not enabled_pks:
        return []
    return list(TestCase.objects.filter(pk__in=list(enabled_pks))
                .order_by('tcid').values_list('tcid', flat=True))


@login_required
@require_POST
def case_enable_save(request):
    """只保存勾选状态（不执行）。

    列表上的勾选框本身就是启用开关，没有独立的「保存」按钮了 —— 一改动就由
    前端 fetch 提交到这里，所以除了整页回退，还要支持返回 JSON 的 ajax 分支。
    """
    enabled = _apply_enabled(request)
    total = len([p for p in request.POST.getlist('row_pk') if str(p).isdigit()])
    disabled = max(total - len(enabled), 0)
    if request.POST.get('ajax') == '1' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'enabled': len(enabled), 'disabled': disabled})
    messages.success(request, '已保存：%s 条启用 / %s 条停用' % (len(enabled), disabled))
    return _back(request)


@login_required
@require_POST
def case_run_enabled(request):
    """勾选状态先落盘，再执行被勾选（= 启用）的用例。

    之所以把「勾选」和「启用」合成同一个状态：列表上曾经有两套选择机制
    （临时勾选 + 启用/停用开关），勾了 A 却点「运行全部启用用例」会很误导。
    现在勾选框本身就是启用开关，按钮只认它。
    """
    tcids = _apply_enabled(request)
    if not tcids:
        messages.error(request, '请先在列表页勾选要执行的用例（勾选即代表启用）')
        return _back(request)
    # 延迟导入：runner.views 反过来要 import cases.models，模块级循环
    from runner.views import _start as _runner_start
    return _runner_start(request, tcids=tcids)


@login_required
def case_list(request):
    """用例列表：支持按关键词搜索、按标签筛选，并显示每条用例的「健康度」。

    健康度 = 静态校验出的问题数（cases/validate.py），
    让用户不必进详情页、更不必真的跑一轮，就知道哪些用例填得不完整。
    """
    q = request.GET.get('q', '').strip()
    tag = request.GET.get('tag', '').strip()
    # 健康度：'' 全部 / 'ok' 健康 / 'bad' 不健康（有阻断性问题）。
    # 旧的 ?bad=1 继续认，免得书签和历史链接失效。
    health = request.GET.get('health', '').strip()
    if not health and request.GET.get('bad') == '1':
        health = 'bad'
    only_bad = health == 'bad'
    only_ok = health == 'ok'
    # 引擎按「启用用例 × 该用例下 runmode=y 的数据行」展开测试项，
    # 所以列表上要能看到每组数据行数，避免"勾了 2 个却跑出 3 个"的困惑。
    qs = TestCase.objects.annotate(
        data_count=Count('datas'),
        run_data_count=Count('datas', filter=Q(datas__runmode__iexact='y')),
    ).prefetch_related('steps').order_by('tcid')
    if q:
        qs = qs.filter(tcid__icontains=q) | qs.filter(name__icontains=q)
    if tag:
        # 标签是逗号分隔字符串，这里用 tags 整体包含判断；
        # 误伤场景（某个标签名是另一个的子串）在几百条用例的规模下可以接受。
        qs = [c for c in qs if c.has_tag(tag)]

    rows = []
    total_bad = 0
    for c in qs:
        issues = check_steps(c.steps.all())
        err_n, warn_n = count_issues(issues)
        if err_n:
            total_bad += 1
        if only_bad and not err_n:
            continue
        if only_ok and err_n:
            continue
        c.err_count, c.warn_count = err_n, warn_n
        rows.append(c)

    # 全部标签（供筛选下拉）——去重后按出现顺序
    tag_list = all_tags()

    return render(request, 'cases/list.html', {
        'cases': rows, 'q': q, 'tag': tag, 'health': health,
        'all_tags': tag_list, 'only_bad': only_bad, 'total_bad': total_bad,
        'total': TestCase.objects.count(),
        'enabled': TestCase.objects.filter(need_run=True).count(),
    })


def step_rules_json():
    """把校验规则喂给前端 —— 免得 JS 里再抄一份、两边改不同步。"""
    import json
    return json.dumps({
        'noLocate': sorted(NO_LOCATE_KW),
        'numeric': NUMERIC_VALUE_KW,
        'xy': sorted(XY_VALUE_KW),
        'noExpectedAssert': sorted(ASSERT_WITHOUT_EXPECTED),
        # kind -> 该 kind 的步骤必须填「操作值」（'assert' 有例外，见 noExpectedAssert）
        'kindNeedValue': ['input', 'select', 'codeslide', 'assert'],
        'kwNeedValue': ['open_url', 'open_browser', 'start_app'],
    }, ensure_ascii=False)


def _data_placeholder(kw, kind=None):
    """该关键字在步骤行「操作值」列里的占位提示。"""
    kl = (kw or '').strip().lower()
    kind = kind or _step_kind(kw)
    if kind == 'assert':
        # 断言那一格填的是期望值；assert_Number_between 例外，它要「最小-最大」
        return DATA_PLACEHOLDERS.get(kl, '期望值')
    if kl in DATA_PLACEHOLDERS:
        return DATA_PLACEHOLDERS[kl]
    return {'input': '输入值', 'select': '选择值',
            'codeslide': '滑块坐标 x,y'}.get(kind, '操作值（可不填）')


@login_required
def case_detail(request, pk):
    """用例详情：一张步骤表写完整个用例 —— 所有关键字要用的数据都在本行的「操作值」列填。

    设计约定（重要）：
    1. 一个用例只维护一条数据行（内部仍叫「场景 1」），
       不再提供「一套步骤 × 多组数据反复执行」的模式 —— 页面上没有多场景这个概念。
    2. 值的真相放在「步骤自身」：每行右侧那一格写进 TestStep.value。
       引擎（framework/keywordsFrameword.py）已统一为「步骤 value 优先、数据行兜底」，
       所以页面上填什么、执行时就用什么，
       也不再受 Input1..8 / selector1..8 这些有限槽位的限制（写第 9 个 input 也不会丢）。
    3. 保存时仍会同步一份到数据行的对应字段，
       仅为让 Excel 导出与存量用例保持可读；执行时它的优先级低于步骤值。
    """
    case = get_object_or_404(TestCase, pk=pk)
    primary = case.datas.first()
    # 历史每一份都算出「这一次改了什么」：
    #   最新那份 —— 拿它的内容与「当前步骤」比（即最近一次保存产生的变化）
    #   其余各份 —— 与紧跟其后的那一版比
    # 快照存的是「操作前的样子」，所以这里的对比结果正好对得上本行的原因与时间。
    snaps = list(case.snapshots.all()[:StepSnapshot.KEEP_LAST])
    for i, snap in enumerate(snaps):
        newer = (StepSnapshot.dump_steps(case) if i == 0 else snaps[i - 1].payload)
        items = StepSnapshot.diff_steps(snap.payload, newer)
        snap.change_items = items[:8]
        snap.change_more = max(len(items) - 8, 0)

    issues = check_steps(case.steps.all())
    err_count, warn_count = count_issues(issues)
    # 行号(1-based) -> 该行的问题列表，页面据此给整行和具体某一格描红
    issues_by_row = {}
    for it in issues:
        issues_by_row.setdefault(it.step_no, []).append(it)

    steps_view = []
    # 步骤自身的值优先；只有它为空时，才回退显示数据行里的历史值（存量 Excel 用例）
    for idx, (s, kind, val) in enumerate(steps_with_values(case.steps.all(), primary), start=1):
        row_issues = issues_by_row.get(idx, [])
        steps_view.append({
            'step': s,
            'kind': kind,
            'data_val': val,
            'placeholder': _data_placeholder(s.keyword, kind),
            # 不需要数据的关键字（click / maxwindow …）不给输入框，保持表格清爽
            'editable': kind != NO_DATA_KIND,
            'issues': row_issues,
            'has_error': any(i.level == 'error' for i in row_issues),
            'bad': set(i.field for i in row_issues if i.level == 'error'),
        })

    return render(request, 'cases/detail.html', {
        'case': case,
        'steps_view': steps_view,
        'primary': primary,
        'other_cases': TestCase.objects.exclude(pk=case.pk).order_by('tcid'),
        'keyword_groups': KEYWORD_GROUPS,
        'locate_types': LOCATE_TYPES,
        'all_keywords': KEYWORD_TIPS.keys(),
        'issues': issues,
        'row_issues': issues_by_row,
        'err_count': err_count,
        'warn_count': warn_count,
        'vrules': step_rules_json(),
        'snapshots': snaps,
    })


@login_required
@require_POST
def case_copy_from(request, pk):
    """从其他用例复制步骤到当前用例（追加，并重排步骤序号）。

    只复制步骤：一个用例固定一组数据，所有数据又都写在步骤自身的「操作值」列里，
    所以复制步骤就等于把数据一起带过来了。若再去复制 TestData 数据行，
    只会让目标用例多出一组数据、执行时平白多跑一个测试项（早期版本的老问题）。
    """
    case = get_object_or_404(TestCase, pk=pk)
    src_pk = request.POST.get('src_pk')
    if not src_pk:
        messages.error(request, '请选择来源用例')
        return redirect('cases:case_detail', pk=pk)
    src = get_object_or_404(TestCase, pk=src_pk)
    if src.pk == case.pk:
        messages.error(request, '不能从自身复制')
        return redirect('cases:case_detail', pk=pk)
    base = case.steps.count()
    # 覆盖前先留一份历史，复制错了还能还原
    StepSnapshot.take(case, StepSnapshot.REASON_COPY, request.user)
    n_steps = 0
    for i, s in enumerate(src.steps.all().order_by('step_no', 'id')):
        TestStep.objects.create(
            case=case, step_no=base + i + 1,
            description=s.description, keyword=s.keyword,
            locate_type=s.locate_type, locate_expr=s.locate_expr,
            value=s.value, need_run=s.need_run,
        )
        n_steps += 1
    messages.success(
        request,
        '已从 %s 复制 %s 条步骤（含每步的操作值）' % (src.tcid, n_steps),
    )
    return redirect('cases:case_detail', pk=pk)


@login_required
def case_new(request):
    if request.method == 'POST':
        tcid = request.POST.get('tcid', '').strip()
        name = request.POST.get('name', '').strip()
        ajax = request.POST.get('ajax') == '1'
        if not tcid or not name:
            if ajax:
                return JsonResponse({'ok': False, 'msg': 'TCID 与用例名称不能为空'})
            messages.error(request, 'TCID 与用例名称不能为空')
            return render(request, 'cases/edit.html',
                          {'mode': 'new', 'all_tags': all_tags()})
        if TestCase.objects.filter(tcid=tcid).exists():
            if ajax:
                return JsonResponse({'ok': False, 'msg': 'TCID 已存在：%s' % tcid})
            messages.error(request, 'TCID 已存在：%s' % tcid)
            return render(request, 'cases/edit.html',
                          {'mode': 'new', 'all_tags': all_tags()})
        case = TestCase.objects.create(
            tcid=tcid, name=name,
            description=request.POST.get('description', '').strip(),
            need_run=_yn(request, 'need_run'),
            cycle=_int(request, 'cycle'),
            tags=_tags(request),
        )
        # 每个用例都先建好「场景 1」主数据行，步骤表的输入值 / 断言才有归属
        TestData.objects.create(
            case=case, caseid=case.tcid, runmode='y',
            data_name='场景1', cycle=1,
        )
        if ajax:
            # 新建成功：把前端带到该用例的属性编辑页（仅一次落地），便于继续编辑详情
            return JsonResponse({'ok': True, 'pk': case.pk,
                                 'edit_url': reverse('cases:case_edit', kwargs={'pk': case.pk})})
        messages.success(request, '用例已创建，请补充测试步骤')
        return redirect('cases:case_detail', pk=case.pk)
    return render(request, 'cases/edit.html',
                  {'mode': 'new', 'all_tags': all_tags()})


@login_required
def case_edit(request, pk):
    case = get_object_or_404(TestCase, pk=pk)
    if request.method == 'POST':
        ajax = request.POST.get('ajax') == '1'
        case.tcid = request.POST.get('tcid', '').strip() or case.tcid
        case.name = request.POST.get('name', '').strip() or case.name
        case.description = request.POST.get('description', '').strip()
        case.need_run = _yn(request, 'need_run')
        case.cycle = _int(request, 'cycle')
        case.tags = _tags(request)
        case.save()
        if ajax:
            # 保存成功但停留在当前属性编辑页，不跳转
            return JsonResponse({'ok': True, 'pk': case.pk})
        messages.success(request, '已保存')
        return redirect('cases:case_detail', pk=case.pk)
    return render(request, 'cases/edit.html',
                  {'mode': 'edit', 'case': case, 'all_tags': all_tags()})


@login_required
@require_POST
def case_delete(request, pk):
    case = get_object_or_404(TestCase, pk=pk)
    case.delete()
    messages.success(request, '用例已删除')
    return redirect('cases:case_list')


# --------------------------------------------------------------------------
# 步骤：整表保存（先删后建，顺序以表格为准）
# --------------------------------------------------------------------------

@login_required
@require_POST
def steps_save(request, pk):
    """保存步骤整表。

    每行唯一的「操作值」格原样写进 TestStep.value —— 这就是该步骤真正使用的值，
    不再区分 input / select* / assert* / CodeSlide / open_url 各自存哪儿。
    同一份值另按关键字同步到唯一的数据行（供 Excel 导出与存量引擎逻辑兜底），
    但执行时步骤值的优先级更高。
    """
    case = get_object_or_404(TestCase, pk=pk)
    StepSnapshot.take(case, StepSnapshot.REASON_SAVE, request.user)

    descs = request.POST.getlist('s_desc')
    kws = request.POST.getlist('s_kw')
    types = request.POST.getlist('s_type')
    exprs = request.POST.getlist('s_expr')
    runs = request.POST.getlist('s_run')
    datas = request.POST.getlist('s_data')

    case.steps.all().delete()
    created = 0
    inputs, selectors, asserts, codeslide = [], [], [], []
    for i in range(len(descs)):
        kw = (kws[i] if i < len(kws) else '').strip()
        desc = (descs[i] if i < len(descs) else '').strip()
        if not kw and not desc:
            continue  # 跳过完全空白的行

        lv = (datas[i] if i < len(datas) else '').strip()
        kind = _step_kind(kw)
        if kind == 'input':
            inputs.append(lv)
        elif kind == 'select':
            selectors.append(lv)
        elif kind == 'codeslide':
            codeslide.append(lv)
        elif kind == 'assert':
            asserts.append(lv)

        TestStep.objects.create(
            case=case,
            step_no=created + 1,
            description=desc,
            keyword=kw,
            locate_type=(types[i] if i < len(types) else '').strip(),
            locate_expr=(exprs[i] if i < len(exprs) else '').strip(),
            # 无论什么关键字，这一格的值都留在步骤自身：
            # 引擎统一「读步骤值，没有再回退数据行」，页面上便永远是所见即所得。
            value=lv,
            need_run=str(runs[i] if i < len(runs) else 'n').strip().lower() == 'y',
        )
        created += 1

    # 数据行：只保留「场景 1」这一条。多余的会在下面清掉 —— 已不支持一套步骤跑多组数据，
    # 留着只会让执行时多跑出空的测试项。
    primary = case.datas.first() or TestData(case=case)
    redundant = max(case.datas.count() - 1, 0)

    # caseid 必须跟所属用例一致：它决定这行数据归属于哪条用例，
    # 页面上不暴露这个字段（避免填错导致「勾 2 个跑 3 个」的老问题）。
    primary.caseid = case.tcid
    primary.data_name = primary.data_name or '场景1'
    primary.runmode = 'y'
    # 循环次数的真相在用例层（case_edit 里改），数据行跟它保持一致，
    # 避免两处各存一份、执行时读用例、导出时又看到数据行的旧值。
    primary.cycle = case.cycle or primary.cycle or 1
    for n in INPUT_SLOTS:
        setattr(primary, 'input%d' % n, inputs[n - 1] if n - 1 < len(inputs) else '')
    for n in SELECTOR_SLOTS:
        setattr(primary, 'selector%d' % n, selectors[n - 1] if n - 1 < len(selectors) else '')
    # 期望值按断言步骤顺序逗号拼接；定位已在步骤字段，数据行的 Type/Expression 置空
    primary.expected_result = ','.join(asserts)
    primary.assert_type = ''
    primary.expression = ''
    if codeslide:
        primary.verifiedcode_xy = codeslide[0]
    primary.save()
    if redundant:
        case.datas.exclude(pk=primary.pk).delete()

    msg = '已保存 %s 条步骤' % created
    if redundant:
        msg += '，并清理了 %s 组多余的测试数据（现不支持一套步骤跑多组数据）' % redundant
    # 照惯例：内容先保住，问题另行提示 —— 保存后详情页会把有问题的行标红
    err_n, warn_n = count_issues(check_steps(case.steps.all()))
    if err_n:
        messages.warning(
            request, '%s；但有 %s 处填写问题（%s 处提示），详见页面上标红的行。'
            % (msg, err_n, warn_n))
    else:
        messages.success(request, msg)
    return redirect('cases:case_detail', pk=case.pk)


@login_required
@require_POST
def steps_restore(request, pk, snap_pk):
    """把某份历史快照还原成当前步骤。

    还原前会再给「当前这份」拍一张快照，所以还原本身也是可撤销的
    —— 误还原了就从历史里再选一次还原回去。
    """
    case = get_object_or_404(TestCase, pk=pk)
    snap = get_object_or_404(StepSnapshot, pk=snap_pk, case=case)
    StepSnapshot.take(case, StepSnapshot.REASON_RESTORE, request.user)
    snap.restore()
    n, _ = count_issues(check_steps(case.steps.all()))
    messages.success(
        request,
        '已还原到 %s 的历史版本（共 %s 步）%s'
        % (snap.created_at.strftime('%Y-%m-%d %H:%M:%S'), snap.step_count,
           '' if not n else '；注意该版本有 %s 处填写问题' % n),
    )
    return redirect('cases:case_detail', pk=case.pk)


# --------------------------------------------------------------------------
# 导入 / 导出
# --------------------------------------------------------------------------

@login_required
def excel_import(request):
    if request.method == 'POST':
        clear = request.POST.get('clear') == '1'

        # 导入前先把当前库备份一份到 BackUP/，误操作后还能从备份导回来
        backup_path = ''
        try:
            os.makedirs(str(settings.BACKUP_DIR), exist_ok=True)
            backup_path = os.path.join(
                str(settings.BACKUP_DIR),
                'db_before_import_%s.xlsx' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S'),
            )
            export_excel(backup_path)
        except Exception as e:
            backup_path = ''
            messages.warning(request, '导入前备份失败（已继续导入）：%s' % e)

        # 优先用上传的 Excel；没上传则退回到「服务器默认文件」
        upload = request.FILES.get('excel')
        src_path = None
        tmp_path = None
        if upload:
            name = upload.name or 'upload.xlsx'
            if not str(name).lower().endswith('.xlsx'):
                messages.error(request, '只支持 .xlsx 文件，当前文件：%s' % name)
                return redirect('cases:excel_import')
            # 大文件落盘，避免占满内存
            fd, tmp_path = tempfile.mkstemp(suffix='.xlsx')
            with os.fdopen(fd, 'wb') as f:
                for chunk in upload.chunks():
                    f.write(chunk)
            src_path = tmp_path
        else:
            messages.error(request, '请先选择要导入的 Excel 文件，再点击「开始导入」。')
            return redirect('cases:excel_import')

        try:
            stat = import_excel(src_path, clear_first=clear)
            msg = '导入完成：用例 %s 条 / 步骤 %s 条 / 数据 %s 条' % (
                stat['cases'], stat['steps'], stat['datas'])
            if backup_path:
                msg += '；导入前已备份到 %s' % backup_path
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, '导入失败：%s%s' % (e, ('（备份：%s）' % backup_path) if backup_path else ''))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        return redirect('cases:case_list')

    return render(request, 'cases/import.html', {})


@login_required
def excel_export(request):
    """导出 Excel —— 只导出列表页勾选的那些用例（?ids=1,2,3）。

    勾选状态只存在于页面的 checkbox 上，所以由前端 JS 收集成 ids 拼到 URL 里；
    不带 ids 时（直接访问 / 旧书签）仍导出全部，属于兜底而非推荐路径。
    """
    ids = [p for p in (request.GET.get('ids') or '').split(',') if p.isdigit()]
    qs = TestCase.objects.order_by('tcid')
    if ids:
        qs = qs.filter(pk__in=ids)
    fname = 'testdata_%s.xlsx' % datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = export_excel(cases=qs)
    f = open(path, 'rb')
    return FileResponse(f, as_attachment=True, filename=fname)


@login_required
def excel_export_template(request):
    """下载「导入模板」：默认用 open_baidu 用例作为样例，让下载者直接看到标准格式。

    open_baidu 不存在时（数据里没有该用例）降级：
      有其它用例 -> 导出第一条作为样例；全库为空 -> 导出仅含表头的空模板。
    """
    case = (TestCase.objects.filter(tcid='open_baidu').first()
            or TestCase.objects.filter(tcid__icontains='open_baidu').first()
            or TestCase.objects.order_by('tcid').first())

    fname = '用例导入模板.xlsx'
    os.makedirs(str(settings.BACKUP_DIR), exist_ok=True)
    if case is not None:
        path = export_excel(
            out_path=os.path.join(str(settings.BACKUP_DIR), fname), cases=[case])
    else:
        from .importer import SUIT_HEADER, STEP_HEADER, SUIT_SHEET, STEP_SHEET
        wb = Workbook()
        ws = wb.active
        ws.title = SUIT_SHEET
        ws.append(SUIT_HEADER)
        s = wb.create_sheet(STEP_SHEET)
        s.append(STEP_HEADER)
        path = os.path.join(str(settings.BACKUP_DIR), fname)
        wb.save(path)

    f = open(path, 'rb')
    return FileResponse(f, as_attachment=True, filename=fname)
