'''轻量定时任务：随服务启动一个守护线程，周期性执行产物清理。

为什么不用系统计划任务：本项目跑在 Windows 上的 Django 开发服务器里，
服务本身就长期开着，放在进程内最简单可靠，也不依赖外部调度器。
如果更想交给系统计划任务，直接用 scripts/cleanup_artifacts.bat
（或者 `schtasks` 注册它）即可，两者互不影响。
'''
import logging
import os
import sys
import tempfile
import threading
import time

from django.conf import settings

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()

# 跨进程锁：runserver 带自动重载时会有父子两个进程各自启动清理线程，
# 用「锁文件是否存在」保证同一时刻只有一个进程真的在删文件。
_LOCK_FILE = os.path.join(tempfile.gettempdir(), 'yikeui_cleanup.lock')
_LOCK_TTL = 3600          # 锁文件超过 1 小时视为上次异常退出的残留，允许回收


def _acquire_file_lock(timeout=60):
    '''拿到锁返回锁文件路径，拿不到返回 None（说明别的进程正在清理）。'''
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode('utf-8'))
            os.close(fd)
            return _LOCK_FILE
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(_LOCK_FILE) > _LOCK_TTL:
                    os.remove(_LOCK_FILE)
                    continue
            except OSError:
                pass
            return None
        except OSError:
            return None
        time.sleep(1)
    return None


def _release_file_lock(path):
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _run_cleanup():
    holder = _acquire_file_lock()
    if not holder:
        logger.info('已有其它进程正在清理产物，本次跳过')
        return
    try:
        from django.core.management import call_command
        try:
            call_command('cleanup_artifacts')
        except Exception as e:
            logger.warning('定时清理失败：%s', e)
    finally:
        _release_file_lock(holder)


def _mark_stale():
    try:
        from .executor import mark_stale_runs
        n = mark_stale_runs()
        if n:
            logger.info('已将 %s 条遗留的“执行中”记录收尾为异常', n)
    except Exception as e:
        logger.warning('收尾遗留执行记录失败：%s', e)


def _loop(interval, first_delay):
    # 启动时先把上次服务中断留下的 running 记录收尾（不影响任何文件）
    time.sleep(3)
    _mark_stale()
    # 首次真正清理延后一段时间再执行，给人工反悔的机会（清理会删历史备份）
    time.sleep(max(first_delay, 0))
    _run_cleanup()
    while True:
        time.sleep(interval)
        _run_cleanup()


def start():
    '''启动清理线程（幂等）。'''
    global _started
    with _lock:
        if _started:
            return
        _started = True

    # 只在 runserver / 常规 Web 进程里启动，避免执行 migrate、check 之类的
    # 一次性命令时也去删文件。
    argv = ' '.join(sys.argv).lower()
    if 'runserver' not in argv and 'gunicorn' not in argv and 'uwsgi' not in argv:
        return

    interval = int(getattr(settings, 'CLEANUP_INTERVAL', 24 * 3600))
    first_delay = int(getattr(settings, 'CLEANUP_FIRST_DELAY', 3600))
    t = threading.Thread(target=_loop, args=(max(interval, 60), first_delay), daemon=True)
    t.start()
    logger.info('产物定时清理已启动：%s 秒后首次执行，之后每 %s 秒一次', first_delay, interval)
