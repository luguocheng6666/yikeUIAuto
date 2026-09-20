from django.apps import AppConfig


class RunnerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'runner'

    def ready(self):
        # ready() 在某些场景会被调用多次（如 runserver 的自动重载），
        # 两个 scheduler 内部各自用进程变量 + 文件锁保证只起一个线程
        from . import planner, scheduler
        scheduler.start()
        planner.start()
