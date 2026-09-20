"""用例数据模型 —— 对应 Data/testdata.xlsx 的三张 sheet。

字段命名用 snake_case，与 Excel 表头的映射统一在
framework/datasource.py 里完成（测试用例/TestSteps 表头是中文，TestDatas 是英文）。
"""
from django.db import models

# 快照 payload 里的字段短名 -> 中文列名（变更对比、导出都按这个顺序展示）
STEP_FIELD_LABELS = [
    ('desc', '描述'), ('kw', '关键字'), ('type', '定位方式'),
    ('expr', '定位表达式'), ('value', '操作值'), ('run', '是否执行'),
]


class TestCase(models.Model):
    """对应「测试用例」sheet"""

    tcid = models.CharField('TCID', max_length=100, unique=True)
    name = models.CharField('用例名称', max_length=200)
    description = models.TextField('用例描述', blank=True, default='')
    need_run = models.BooleanField('是否需要执行', default=False)
    # 循环次数：原先在 TestDatas 的 Cycle 列，随「取消多场景」上移到用例层
    cycle = models.IntegerField('循环次数', default=1)
    last_run_time = models.DateTimeField('执行时间', null=True, blank=True)
    last_result = models.CharField('结果', max_length=50, blank=True, default='')
    # 以下三个原先在 TestDatas（StartTime / RunTime / ErrMsg），一并上移，
    # 这样导出的 Excel「测试用例」sheet 就是一张完整的结果表。
    last_start_time = models.CharField('开始时间', max_length=50, blank=True, default='')
    last_duration = models.CharField('耗时', max_length=50, blank=True, default='')
    last_errmsg = models.TextField('错误信息', blank=True, default='')
    # 标签：逗号/空格/顿号分隔，用于「按标签挑一批用例执行」。
    # 没单独建 Tag 表 —— 用例量级在几百条，用字符串切分足够，
    # 查询走 icontains 即可，省掉一次多对多关联。
    tags = models.CharField('标签', max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '测试用例'
        verbose_name_plural = '测试用例'
        ordering = ['tcid']

    def __str__(self):
        return '%s - %s' % (self.tcid, self.name)

    @staticmethod
    def split_tags(raw):
        """把「冒烟, 回归 权限」切成 ['冒烟','回归','权限']，去重并保持原顺序。"""
        import re
        out = []
        for part in re.split(r'[,，、\s]+', (raw or '').strip()):
            p = part.strip()
            if p and p not in out:
                out.append(p)
        return out

    @property
    def tag_list(self):
        return self.split_tags(self.tags)

    def has_tag(self, tag):
        return tag in self.tag_list


class TestStep(models.Model):
    """对应 TestSteps sheet"""

    case = models.ForeignKey(TestCase, on_delete=models.CASCADE,
                             related_name='steps', verbose_name='所属用例')
    step_no = models.IntegerField('步骤序号', default=1)
    description = models.CharField('测试步骤描述', max_length=300, blank=True, default='')
    keyword = models.CharField('关键字', max_length=100, blank=True, default='')
    locate_type = models.CharField('定位方式', max_length=50, blank=True, default='')
    locate_expr = models.CharField('定位表达式', max_length=500, blank=True, default='')
    value = models.TextField('操作值', blank=True, default='')
    need_run = models.BooleanField('是否需要执行', default=True)

    class Meta:
        verbose_name = '测试步骤'
        verbose_name_plural = '测试步骤'
        # 带上 id 兜底：从旧 Excel 导入时可能出现重复的步骤序号，
        # 只按 step_no 排序会让同序号的两步顺序随机漂移（每次查询可能不一样），
        # 表现为「保存前后步骤顺序自己变了」。
        ordering = ['case', 'step_no', 'id']

    def __str__(self):
        return '%s 步骤%s %s' % (self.case.tcid, self.step_no, self.keyword)


class TestData(models.Model):
    """对应 TestDatas sheet"""

    case = models.ForeignKey(TestCase, on_delete=models.CASCADE,
                             related_name='datas', verbose_name='所属用例')
    # 注意：不能叫 case_id，会与外键 case 的隐式列 case_id 冲突（models.E006）
    caseid = models.CharField('CaseId', max_length=100, blank=True, default='')
    runmode = models.CharField('Runmode', max_length=10, default='y')
    data_name = models.CharField('Data_name', max_length=200, blank=True, default='')
    summary = models.CharField('Summary', max_length=300, blank=True, default='')

    input1 = models.TextField('Input1', blank=True, default='')
    input2 = models.TextField('Input2', blank=True, default='')
    input3 = models.TextField('Input3', blank=True, default='')
    input4 = models.TextField('Input4', blank=True, default='')
    input5 = models.TextField('Input5', blank=True, default='')
    input6 = models.TextField('Input6', blank=True, default='')
    input7 = models.TextField('Input7', blank=True, default='')
    input8 = models.TextField('Input8', blank=True, default='')

    verifiedcode_xy = models.CharField('verifiedcodeXY', max_length=100, blank=True, default='')
    # 下拉选择值槽位，与 input1..8 对齐：第 N 个 selectby* 步骤对应 selectorN。
    # 早先只有 2 个槽位，第 3 个之后的 selectby* 值会被静默丢弃，故扩展到 8。
    selector1 = models.CharField('selector1', max_length=500, blank=True, default='')
    selector2 = models.CharField('selector2', max_length=500, blank=True, default='')
    selector3 = models.CharField('selector3', max_length=500, blank=True, default='')
    selector4 = models.CharField('selector4', max_length=500, blank=True, default='')
    selector5 = models.CharField('selector5', max_length=500, blank=True, default='')
    selector6 = models.CharField('selector6', max_length=500, blank=True, default='')
    selector7 = models.CharField('selector7', max_length=500, blank=True, default='')
    selector8 = models.CharField('selector8', max_length=500, blank=True, default='')

    # 断言三件套
    assert_type = models.TextField('Type', blank=True, default='')
    expression = models.TextField('Expression', blank=True, default='')
    expected_result = models.TextField('ExpectedResult', blank=True, default='')

    cycle = models.IntegerField('Cycle', default=1)

    # 执行回写字段
    errmsg = models.TextField('ErrMsg', blank=True, default='')
    result = models.CharField('Result', max_length=50, blank=True, default='')
    start_time = models.CharField('StartTime', max_length=50, blank=True, default='')
    run_time = models.CharField('RunTime', max_length=50, blank=True, default='')

    class Meta:
        verbose_name = '测试数据'
        verbose_name_plural = '测试数据'
        ordering = ['case', 'id']

    def __str__(self):
        return '%s / %s' % (self.case.tcid, self.data_name)


class StepSnapshot(models.Model):
    """步骤变更历史 —— steps_save 是「先删后建」，没有它就改错了没法还原。

    每次覆盖步骤之前，把当时的步骤整表序列化存一份；详情页可查看、可一键还原。
    只保留每个用例最近 KEEP_LAST 份，避免长期跑下来把表撑爆。
    """

    REASON_SAVE = 'save'
    REASON_COPY = 'copy'
    REASON_RESTORE = 'restore'
    REASON_IMPORT = 'import'
    REASON_CHOICES = [
        (REASON_SAVE, '保存步骤'),
        (REASON_COPY, '复制步骤前'),
        (REASON_RESTORE, '还原前'),
        (REASON_IMPORT, '导入覆盖前'),
    ]

    KEEP_LAST = 20  # 每个用例最多保留的历史份数

    case = models.ForeignKey(TestCase, on_delete=models.CASCADE,
                             related_name='snapshots', verbose_name='所属用例')
    reason = models.CharField('变更原因', max_length=20,
                              choices=REASON_CHOICES, default=REASON_SAVE)
    step_count = models.IntegerField('步骤条数', default=0)
    # [{'desc','kw','type','expr','value','run'}, ...] —— 字段用短名控制体积
    payload = models.JSONField('步骤快照', default=list, blank=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL,
                                   null=True, blank=True, verbose_name='操作人')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '步骤快照'
        verbose_name_plural = '步骤快照'
        ordering = ['-created_at']

    def __str__(self):
        return '%s @%s (%s步)' % (self.case.tcid,
                                  self.created_at.strftime('%m-%d %H:%M:%S'),
                                  self.step_count)

    @staticmethod
    def dump_steps(case):
        """把某用例当前的步骤序列化成快照 payload。"""
        return [{
            'desc': s.description, 'kw': s.keyword,
            'type': s.locate_type, 'expr': s.locate_expr,
            'value': s.value, 'run': 'y' if s.need_run else 'n',
        } for s in case.steps.all()]

    @classmethod
    def take(cls, case, reason=REASON_SAVE, user=None):
        """存一份快照，并裁掉超出 KEEP_LAST 的旧记录。"""
        from django.contrib.auth.models import AnonymousUser
        snap = cls.objects.create(
            case=case, reason=reason,
            step_count=case.steps.count(),
            payload=cls.dump_steps(case),
            created_by=None if (user is None or isinstance(user, AnonymousUser)
                                or not getattr(user, 'is_authenticated', False)) else user,
        )
        old_ids = list(cls.objects.filter(case=case)
                       .order_by('-created_at')[cls.KEEP_LAST:]
                       .values_list('pk', flat=True))
        if old_ids:
            cls.objects.filter(pk__in=old_ids).delete()
        return snap

    @staticmethod
    def _sig(row):
        """一条步骤的指纹：所有字段拼起来，用于两版之间做行级比对。"""
        return tuple(str(row.get(k, '') or '') for k, _ in STEP_FIELD_LABELS)

    @staticmethod
    def diff_steps(old_rows, new_rows, limit=200):
        """比对两版步骤，返回变更明细（用于历史里的「变更操作」列）。

        用 difflib 做行级比对而不是按下标硬比 —— 中间插入/删除一步时，
        后面所有步骤的下标都会平移，按下标比会出现「每一步都变了」的噪音。

        返回元素形如：
            {'type': 'add',  'no': 3, 'kw': 'input', 'desc': '输入账号'}
            {'type': 'del',  'no': 2, 'kw': 'click', 'desc': '点登录'}
            {'type': 'mod',  'no': 2, 'kw': 'input', 'field': '操作值',
             'old': 'admin', 'new': 'root'}
            {'type': 'rewrite', 'no': 3, 'count': 4}   # 连续多行整体改写
        """
        import difflib
        old = list(old_rows or [])
        new = list(new_rows or [])
        if old == new:
            return []

        out = []
        sm = difflib.SequenceMatcher(a=[StepSnapshot._sig(r) for r in old],
                                     b=[StepSnapshot._sig(r) for r in new],
                                     autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                continue
            if tag == 'insert':
                for j in range(j1, j2):
                    out.append({'type': 'add', 'no': j + 1,
                                'kw': new[j].get('kw', ''),
                                'desc': new[j].get('desc', '')})
            elif tag == 'delete':
                for i in range(i1, i2):
                    out.append({'type': 'del', 'no': i + 1,
                                'kw': old[i].get('kw', ''),
                                'desc': old[i].get('desc', '')})
            else:  # replace
                if (i2 - i1) == (j2 - j1):
                    for k in range(i2 - i1):
                        o, n = old[i1 + k], new[j1 + k]
                        for key, label in STEP_FIELD_LABELS:
                            ov, nv = (o.get(key, '') or ''), (n.get(key, '') or '')
                            if ov != nv:
                                out.append({'type': 'mod', 'no': j1 + k + 1,
                                            'kw': n.get('kw', ''),
                                            'field': label, 'old': ov, 'new': nv})
                else:
                    out.append({'type': 'rewrite', 'no': j1 + 1,
                                'count': max(i2 - i1, j2 - j1)})
            if len(out) >= limit:
                break
        return out

    def restore(self):
        """把快照写回用例：先删当前步骤，再按快照重建。"""
        from django.db import transaction
        with transaction.atomic():
            self.case.steps.all().delete()
            for i, row in enumerate(self.payload or [], start=1):
                TestStep.objects.create(
                    case=self.case, step_no=i,
                    description=row.get('desc', ''),
                    keyword=row.get('kw', ''),
                    locate_type=row.get('type', ''),
                    locate_expr=row.get('expr', ''),
                    value=row.get('value', ''),
                    need_run=str(row.get('run', 'y')).strip().lower() == 'y',
                )
