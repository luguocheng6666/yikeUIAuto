'''步骤「操作值」的取值规则 —— Web 页面与 Excel 导入导出共用同一套。

背景
----
以前一个步骤要用什么值，取决于数据行里的槽位（input1..8 / selector1..8 /
verifiedcodeXY / ExpectedResult），槽位有限且容易串位。现在改为：

    值的真相 = TestStep.value（步骤自身那一格）
    数据行   = 仅作兜底，供存量 Excel 用例与导出兼容

本模块把这些规则集中定义，避免页面渲染、Excel 导出、导入迁移三处算法漂移。
'''

# 这些关键字的值取自「步骤自身的操作值」，而不是数据行的 inputN/selectorN。
# 与 framework/keywordsFrameword.py 的 executeCase 分支严格对应。
STEP_VALUE_KW = {
    'open_browser', 'open_url', 'start_app', 'get_win', 'sleep', 'sendkeys',
    'swith_window_handle_by_index', 'swith_window_handle_by_title', 'swith_frame',
    'mouse_click', 'Exeucejs',
}

# input / selector 的槽位数量，与模型字段 input1..8 / selector1..8 对齐
INPUT_SLOTS = tuple(range(1, 9))
SELECTOR_SLOTS = tuple(range(1, 9))

# 无数据关键字：不需要在「操作值」列出现输入框
NO_DATA_KIND = 'none'


def step_kind(kw):
    """判定一个步骤在「操作值」列里的语义类别。"""
    kl = (kw or '').strip().lower()
    if kl == 'input':
        return 'input'
    if kl in ('selectbytext', 'selectbyindex', 'selectbyvalue'):
        return 'select'
    if kl == 'codeslide':
        return 'codeslide'
    if 'assert' in kl:
        return 'assert'
    if kl in STEP_VALUE_KW:
        # 操作值属于步骤本身（open_url / sleep …）
        return 'value'
    return NO_DATA_KIND


def data_row_slots(d):
    """把一个数据行拆成「按步骤出现顺序排列」的取值列表。"""
    if d is None:
        return {'inputs': [], 'selectors': [], 'asserts': [], 'xy': ''}
    return {
        'inputs': [getattr(d, 'input%d' % i) or '' for i in INPUT_SLOTS],
        'selectors': [getattr(d, 'selector%d' % i) or '' for i in SELECTOR_SLOTS],
        'asserts': d.expected_result.split(',') if (d.expected_result or '').strip() else [],
        'xy': d.verifiedcode_xy or '',
    }


def steps_with_values(steps, data_row):
    """返回 [(step, kind, 显示值)]。

    取值优先级：**步骤自身的 value 优先，为空才回退数据行的历史值**。
    回退只为兼容存量 Excel 用例（那时值只存在数据行里）。
    """
    sv = data_row_slots(data_row)
    ii = si = ai = 0
    out = []
    for s in steps:
        kind = step_kind(s.keyword)
        fallback = ''
        if kind == 'input':
            fallback = sv['inputs'][ii] if ii < len(sv['inputs']) else ''
            ii += 1
        elif kind == 'select':
            fallback = sv['selectors'][si] if si < len(sv['selectors']) else ''
            si += 1
        elif kind == 'codeslide':
            fallback = sv['xy']
        elif kind == 'assert':
            fallback = sv['asserts'][ai] if ai < len(sv['asserts']) else ''
            ai += 1
        out.append((s, kind, (s.value or '') or fallback))
    return out


def migrate_data_row_to_steps(case):
    """存量用例迁移：步骤没填值时，把数据行里的历史值搬进 TestStep.value。

    这样导出的 Excel 与页面显示一致，不再依赖数据行的槽位。
    返回被填充的步骤数。
    """
    data_row = case.datas.first()
    steps = list(case.steps.all().order_by('step_no', 'id'))
    filled = 0
    for s, kind, val in steps_with_values(steps, data_row):
        if (s.value or '').strip():
            continue
        if val and kind != NO_DATA_KIND:
            s.value = val
            s.save(update_fields=['value'])
            filled += 1
    return filled
