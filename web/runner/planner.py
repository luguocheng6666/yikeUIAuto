'''进程内定时调度：按 SchedulePlan 到点自动跑一轮。

为什么要自己写而不用 celery / APScheduler
------------------------------------------
本项目只需要「到点触发一次」，不需要分布式队列、任务结果持久化、重试策略这些，
引入一套中间件反而多一个要运维的进程。这里就一个守护线程 + 一张配置表，
行为和 Windows / Linux 上完全一致，也不依赖系统计划任务。

可靠性取舍
----------
- **单实例**：靠跨进程锁文件保证 runserver 自动重载出来的父子进程里只有一个在调度。
- **不做过期补跑**：服务停机期间的触发点在 grace 窗口外的会被跳过，
  否则开机瞬间可能一次性补跑几十轮。
- **忙则跳过**：同一时刻只允许一轮执行（executor 全局锁），错过了就等下一个点。
'''
import atexit
import logging
import os
import re
import sys
import tempfile
import threading
import time

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

TICK_SECONDS = 30            # 轮询间隔：够精细，又不会给数据库添负担
_LOCK_FILE = os.path.join(tempfile.gettempdir(), 'yikeui_planner.lock')
# 兜底阈值：持有者进程还在、但心跳超过这么久没刷新（卡死 / 机器睡眠）才允许别人接管。
# 主要判据是「持有者进程还活着吗」，这里只是进程还在但不动了的兜底，
# 所以取轮询间隔的 10 倍即可 —— 早先定成 2 小时，结果服务被强杀重启后
# 新进程要干等两小时才能接管，期间的计划全部静默不跑。
_LOCK_TTL = 300

_lock_path = None
_started = False
_start_lock = threading.Lock()


def _pid_alive(pid):
    """这个 pid 的进程还在吗 —— 判断锁是不是残留的关键。

    Windows 没有 os.kill(pid, 0)，用 OpenProcess 查询；Linux / macOS 用信号 0。
    """
    if not pid or pid <= 0:
        return False
    if os.name == 'nt':
        try:
            import ctypes
            # use_last_error=True 才能拿到 GetLastError()，不然访问被拒和不存在分不开
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                          False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            # 5 = ERROR_ACCESS_DENIED：进程存在但没权限查，也算活着
            return ctypes.get_last_error() == 5
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_lock_pid():
    """锁文件里记的持有者 pid（读不到 / 格式不对返回 None）。"""
    try:
        with open(_LOCK_FILE, 'r') as f:
            raw = f.read().strip()
    except OSError:
        return None
    m = re.match(r'^(\d+)', raw)
    return int(m.group(1)) if m else None


def _own_lock():
    """锁是不是本进程持有的 —— 每次心跳前都要确认，避免给别人做嫁衣。"""
    return _read_lock_pid() == os.getpid()


def _lock_age():
    """心跳（锁文件 mtime）距今多少秒；读不到返回 None。"""
    try:
        return time.time() - os.path.getmtime(_LOCK_FILE)
    except OSError:
        return None


def lock_info():
    """给页面用的诊断信息：谁持锁、心跳多久没动了。"""
    if not os.path.exists(_LOCK_FILE):
        return {'path': _LOCK_FILE, 'pid': None, 'alive': False, 'age': None}
    pid = _read_lock_pid()
    return {'path': _LOCK_FILE, 'pid': pid, 'alive': _pid_alive(pid),
            'age': _lock_age()}


def _acquire_process_lock():
    """拿到进程级锁；拿不到说明另一个进程已经在调度了（返回 None）。"""
    for _ in range(3):
        try:
            fd = os.open(_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode('utf-8'))
            os.close(fd)
            _touch_lock()
            atexit.register(_release_process_lock)
            return _LOCK_FILE
        except FileExistsError:
            owner = _read_lock_pid()
            if owner is None or not _pid_alive(owner):
                # 持有者进程已经不在了（服务被强杀 / 断电 / 任务管理器结束），
                # 那这个文件只是残留 —— 直接接管，不能再等 TTL。
                try:
                    os.remove(_LOCK_FILE)
                except OSError:
                    return None
                logger.info('接管残留的定时调度锁（原持有进程 %s 已不存在）', owner)
                continue
            age = _lock_age()
            if age is not None and age > _LOCK_TTL:
                try:
                    os.remove(_LOCK_FILE)
                except OSError:
                    return None
                logger.warning('进程 %s 持锁但心跳已停 %d 秒，判定卡死并接管',
                               owner, int(age))
                continue
            return None
        except OSError as e:
            logger.warning('定时调度锁创建失败：%s', e)
            return None
    return None


def _touch_lock():
    """刷新心跳。只动自己那把锁，别人的不碰。"""
    if not _own_lock():
        return False
    try:
        os.utime(_LOCK_FILE, None)
    except OSError:
        pass
    return True


def _release_process_lock():
    if _lock_path and _own_lock():
        try:
            os.remove(_LOCK_FILE)
        except OSError:
            pass


def is_running():
    """本进程是否持有调度锁（页面上用来提示「调度是否在跑」）。"""
    return bool(_lock_path) and _own_lock()


def fire(plan, now=None):
    """触发一次计划手里这一轮执行；返回 TaskRun 或 None（被拒绝）。"""
    from .executor import RunBusy, start_run
    now = now or timezone.now()
    plan.last_run_at = now
    try:
        task = start_run(None, case_filter=plan.case_filter())
    except RunBusy as e:
        plan.last_status = '跳过：已有任务在执行（#%s）' % e.running_pk
        plan.save(update_fields=['last_run_at', 'last_status'])
        logger.info('计划「%s」跳过：已有任务 #%s 在执行', plan.name, e.running_pk)
        return None
    except Exception as e:
        plan.last_status = '触发失败：%s' % e
        plan.save(update_fields=['last_run_at', 'last_status'])
        logger.warning('计划「%s」触发失败：%s', plan.name, e)
        return None
    plan.last_task = task
    plan.last_status = '已触发 #%s' % task.pk
    plan.save(update_fields=['last_run_at', 'last_status', 'last_task'])
    logger.info('计划「%s」已触发执行 #%s', plan.name, task.pk)
    return task


def tick():
    """扫一遍所有启用计划，到点的就触发。自身不抛异常 —— 调度线程不能死。"""
    from django.db import close_old_connections
    from .models import SchedulePlan
    now = timezone.now()
    for plan in SchedulePlan.objects.filter(enabled=True):
        slot = plan.is_due(now)
        if slot is None:
            continue
        try:
            fire(plan, now=now)
        except Exception as e:
            logger.warning('计划「%s」执行出错：%s', plan.name, e)
    close_old_connections()


def _loop(interval):
    """调度主循环。

    关键改动：**拿不到锁不再一走了之**。以前启动时抢不到锁就彻底不调度了，
    而锁文件恰好最常在「旧进程被强杀、新进程立刻顶上」这个场景残留 ——
    结果就是全站定时计划静默失效，必须再重启一次才恢复。
    现在改成每轮都重试，谁先接管谁负责，页面上也看得见状态。
    """
    global _lock_path
    # 启动稍等一会儿，让 migrations / 静态文件这些先就绪
    time.sleep(10)
    while True:
        try:
            if _lock_path is None:
                _lock_path = _acquire_process_lock()
                if _lock_path:
                    logger.info('定时调度已启动（本进程 PID %s），每 %s 秒检查一次计划',
                                os.getpid(), interval)
            if _lock_path:
                if not _own_lock():
                    logger.warning('调度锁已被其它进程接管，本进程停止调度')
                    _lock_path = None
                else:
                    _touch_lock()
                    tick()
        except Exception as e:
            logger.warning('定时调度轮询异常：%s', e)
        time.sleep(interval)


def start():
    """启动调度线程（幂等，且只在 Web 进程里启动）。"""
    global _started, _lock_path
    with _start_lock:
        if _started:
            return
        _started = True

    argv = ' '.join(sys.argv).lower()
    if 'runserver' not in argv and 'gunicorn' not in argv and 'uwsgi' not in argv:
        return

    # 先抢一次，抢不到也没关系 —— 主循环会一直重试，等别人松手
    if _lock_path is None:
        _lock_path = _acquire_process_lock()

    interval = int(getattr(settings, 'PLANNER_TICK', TICK_SECONDS))
    t = threading.Thread(target=_loop, args=(max(interval, 10),), daemon=True)
    t.start()
