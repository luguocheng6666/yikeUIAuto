'''清理历史产物：报告（保留最近 N 份）、报告截图、BackUP（保留 N 天）。

用法：
    python manage.py cleanup_artifacts            # 按 settings 里的保留策略清理
    python manage.py cleanup_artifacts --dry-run  # 只看会删哪些，不真删
    python manage.py cleanup_artifacts --keep-reports 50 --keep-backup-days 30
'''
import os
import re
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from runner.models import TaskRun

REPORT_RE = re.compile(r'^result_(\d+)\.html$', re.I)
SHOT_RE = re.compile(r'^run_(\d+)_\d+\.png$', re.I)


class Command(BaseCommand):
    help = '清理历史报告与备份文件，避免产物无限增长。'

    def add_arguments(self, parser):
        parser.add_argument('--keep-reports', type=int, default=None,
                            help='保留最近多少份报告（默认 settings.KEEP_REPORTS）')
        parser.add_argument('--keep-backup-days', type=int, default=None,
                            help='BackUP 保留多少天（默认 settings.KEEP_BACKUP_DAYS）')
        parser.add_argument('--dry-run', action='store_true',
                            help='只列出将被删除的文件，不真正删除')

    def handle(self, *args, **opts):
        keep_reports = opts['keep_reports'] or getattr(settings, 'KEEP_REPORTS', 100)
        keep_days = opts['keep_backup_days'] or getattr(settings, 'KEEP_BACKUP_DAYS', 100)
        dry = opts['dry_run']

        n_reports = self._clean_reports(keep_reports, dry)
        n_shots = self._clean_shots(dry)
        n_backup = self._clean_backup(keep_days, dry)

        self.stdout.write(self.style.SUCCESS(
            '清理完成%s：报告 %s 个 / 截图 %s 个 / 备份 %s 个'
            % ('（演练，未删除）' if dry else '', n_reports, n_shots, n_backup)
        ))

    # ------------------------------------------------------------------ 报告
    def _clean_reports(self, keep, dry):
        d = str(settings.REPORTS_DIR)
        if not os.path.isdir(d):
            return 0
        files = []
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if os.path.isfile(p) and REPORT_RE.match(name):
                files.append((os.path.getmtime(p), p))
        files.sort(reverse=True)          # 最新的在前
        doomed = files[keep:]
        for _, p in doomed:
            self.stdout.write('  删除报告 %s' % p)
            if not dry:
                try:
                    os.remove(p)
                except OSError as e:
                    self.stdout.write(self.style.WARNING('    失败：%s' % e))
        # 报告文件没了，把还指向它的执行记录标记为「已清理」，避免详情页面 404
        if not dry and doomed:
            gone = [REPORT_RE.match(os.path.basename(p)).group(1) for _, p in doomed]
            TaskRun.objects.filter(pk__in=gone).exclude(report_path='').update(report_path='')
        return len(doomed)

    # ------------------------------------------------------------------ 截图
    def _clean_shots(self, dry):
        d = str(settings.SHOTS_DIR)
        if not os.path.isdir(d):
            return 0
        # 只清理「对应的执行记录已经不存在报告」的截图：
        # 报告还在 → 截图必须留着，否则报告里图片裂开。
        alive = set(
            TaskRun.objects.exclude(report_path='').values_list('pk', flat=True)
        )
        n = 0
        for name in os.listdir(d):
            m = SHOT_RE.match(name)
            if not m:
                continue
            run_pk = int(m.group(1))
            if run_pk in alive:
                continue
            p = os.path.join(d, name)
            self.stdout.write('  删除截图 %s' % p)
            if not dry:
                try:
                    os.remove(p)
                    n += 1
                except OSError as e:
                    self.stdout.write(self.style.WARNING('    失败：%s' % e))
            else:
                n += 1
        return n

    # ----------------------------------------------------------------- BackUP
    def _clean_backup(self, keep_days, dry):
        d = str(settings.BACKUP_DIR)
        if not os.path.isdir(d):
            return 0
        deadline = time.time() - keep_days * 86400
        n = 0
        for root, _dirs, files in os.walk(d):
            for name in files:
                p = os.path.join(root, name)
                try:
                    if os.path.getmtime(p) >= deadline:
                        continue
                except OSError:
                    continue
                self.stdout.write('  删除备份 %s' % p)
                if not dry:
                    try:
                        os.remove(p)
                        n += 1
                    except OSError as e:
                        self.stdout.write(self.style.WARNING('    失败：%s' % e))
                else:
                    n += 1
        return n
