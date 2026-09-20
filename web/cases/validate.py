'''步骤保存前的静态校验 —— 让「要跑到那一步才炸」的问题，在保存时就看得见。

设计取舍
--------
1. **只做静态检查**：不启浏览器、不查数据库以外的东西，毫秒级返回，
   所以列表页可以对每条用例都跑一遍（用例健康度）。
2. **不阻塞保存**：后端永远照常保住用户填的内容，只在页面上把问题列出来。
   steps_save 是「先删后建」，一旦拒绝保存，用户在页面上编辑的内容就全丢了 ——
   丢数据比存下有问题的步骤严重得多。真正的拦截交给前端（点保存时先校验、让用户二次确认）。
3. 分两级：`error` 大概率执行失败；`warn` 可疑但可能是故意的（比如故意不断言）。
'''
from .stepvalues import step_kind

class Issue(object):
    """一条校验结论。

    field 指明问题出在哪一格（kw / locate / value / desc），
    页面据此只给那一格描红边，而不是整行糊成一团。
    """

    def __init__(self, level, step_no, keyword, message, field=''):
        self.level = level          # 'error' / 'warn'
        self.step_no = step_no      # 1-based，0 表示整条用例层面的问题
        self.keyword = keyword or ''
        self.message = message
        self.field = field

    def __repr__(self):
        return '<Issue %s #%s %s>' % (self.level, self.step_no, self.message)

    def as_dict(self):
        return {'level': self.level, 'step_no': self.step_no,
                'keyword': self.keyword, 'message': self.message,
                'field': self.field}


ROW = 0  # step_no 取值：整条用例层面的问题


# ---------------------------------------------------------------------------
# 关键字分类
# ---------------------------------------------------------------------------

# 不需要「定位方式 / 定位表达式」的关键字 —— 其余涉及元素操作的都要求填定位
NO_LOCATE_KW = {
    'open_browser', 'maxwindow', 'open_url', 'back', 'refresh',
    'close_browser', 'quite_browser',
    'swith_window_handle_by_title', 'swith_window_handle_by_index',
    'swith_frame', 'sleep', 'screenshots',
    # 桌面端（保留兼容，页面里归在「已不使用」组）
    'start_app', 'get_win', 'mouse_click', 'close_win',
    # send_keys 打给当前焦点、Exeucejs 的脚本写在定位表达式里，都不靠定位找元素
    'send_keys', 'exeucejs',
}

# 断言里不需要期望值的关键字：它们断言的是「实际值本身为真 / 是数字」
ASSERT_WITHOUT_EXPECTED = {'asserttrue', 'assert_is_number'}

# 「操作值」必须是单个数字
NUMERIC_VALUE_KW = {'sleep': '秒数（数字）', 'swith_window_handle_by_index': '窗口序号（数字）',
                    'selectbyindex': '下拉框序号（整数）'}

# 「操作值」必须是 x,y 两个数字
XY_VALUE_KW = {'codeslide': '滑块坐标 x,y', 'mouse_click': '点击坐标 x,y'}


def _lower(v):
    return (v or '').strip().lower()


def _is_number(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def check_step(index, step):
    """校验一条步骤，返回 Issue 列表。index 为 1-based 行号。

    step 可以是 TestStep 实例，也可以是带同名字段的 dict / 简单对象。
    """
    def get(name):
        if isinstance(step, dict):
            return step.get(name, '')
        return getattr(step, name, '')

    issues = []
    kw = (get('keyword') or '').strip()
    kl = _lower(kw)
    desc = (get('description') or '').strip()
    locate_type = (get('locate_type') or '').strip()
    locate_expr = (get('locate_expr') or '').strip()
    value = (get('value') or '').strip()
    kind = step_kind(kw)

    if not kw:
        return [Issue('error', index, '', '未选择关键字（这一行不会被执行）', 'kw')]

    # 1. 定位缺失 —— 执行时会直接抛「定位表达式为空」
    if kl not in NO_LOCATE_KW:
        if not locate_type and not locate_expr:
            issues.append(Issue('error', index, kw, '缺少定位方式与定位表达式', 'locate'))
        elif not locate_type:
            issues.append(Issue('error', index, kw, '缺少定位方式', 'locate'))
        elif not locate_expr:
            issues.append(Issue('error', index, kw, '缺少定位表达式', 'locate'))

    # 2. 该填的「操作值」没填
    need_value = False
    what = ''
    if kind == 'input':
        need_value, what = True, '输入值'
    elif kind == 'select':
        need_value, what = True, '选择值'
    elif kind == 'codeslide':
        need_value, what = True, '滑块坐标 x,y'
    elif kind == 'assert' and kl not in ASSERT_WITHOUT_EXPECTED:
        need_value, what = True, '期望值'
    elif kl == 'open_url':
        need_value, what = True, '网址 URL'
    elif kl == 'open_browser':
        need_value, what = True, '浏览器类型（Chrome / Firefox / Ie）'
    elif kl == 'start_app':
        need_value, what = True, '程序 exe 路径'
    if need_value and not value:
        issues.append(Issue('error', index, kw, '「操作值」为空，应填%s' % what, 'value'))

    # 3. 填了但格式不对
    if value:
        if kl in NUMERIC_VALUE_KW:
            if not _is_number(value):
                issues.append(Issue('error', index, kw,
                                    '「%s」应为数字，当前是「%s」' % (NUMERIC_VALUE_KW[kl], value),
                                    'value'))
        elif kl == 'selectbyindex' and not value.isdigit():
            issues.append(Issue('error', index, kw, '下拉框序号应为非负整数', 'value'))
        elif kl in XY_VALUE_KW:
            parts = [p.strip() for p in value.split(',')]
            bad = len(parts) != 2 or not all(_is_number(p) for p in parts)
            if bad:
                issues.append(Issue('error', index, kw,
                                    '应为 %s，当前是「%s」' % (XY_VALUE_KW[kl], value),
                                    'value'))
        elif kl == 'assert_number_between':
            parts = [p.strip() for p in value.split('-')]
            bad = len(parts) != 2 or not all(_is_number(p) for p in parts)
            if bad:
                issues.append(Issue('error', index, kw,
                                    '应为「最小值-最大值」，当前是「%s」' % value, 'value'))
        elif kind == 'assert' and kl in ('assert_is_display', 'assert_is_enabled',
                                         'assert_is_exist', 'assert_is_notexist'):
            if _lower(value) not in ('true', 'false'):
                issues.append(Issue('error', index, kw,
                                    '期望值应为 True 或 False，当前是「%s」' % value, 'value'))

    # 4. 提示级：描述为空不影响执行，但报告里看不出这一步在干嘛
    if not desc:
        issues.append(Issue('warn', index, kw, '步骤描述为空，报告里不易定位', 'desc'))

    return issues


def check_steps(steps):
    """校验一组步骤（顺序即行号），并按 (用例层面问题 + 各行问题) 汇总。"""
    issues = []
    rows = list(steps)
    if not rows:
        issues.append(Issue('error', ROW, '', '该用例还没有任何步骤'))
        return issues

    for i, s in enumerate(rows, start=1):
        issues.extend(check_step(i, s))

    # 用例层面：用了元素操作却从未打开浏览器 —— 多半是漏了 open_browser
    kws = [_lower(getattr(s, 'keyword', '') if not isinstance(s, dict) else s.get('keyword', ''))
           for s in rows]
    if kws and not any(k in ('open_browser', 'start_app') for k in kws):
        issues.append(Issue('warn', ROW, '',
                            '从未打开浏览器 / 启动程序，执行时可能因找不到页面而全部失败'))
    return issues


def count_issues(issues):
    return (sum(1 for i in issues if i.level == 'error'),
            sum(1 for i in issues if i.level == 'warn'))
