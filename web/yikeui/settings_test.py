'''测试专用配置 —— 跑自动化测试时不碰正式的 MySQL 库。

为什么单独一份配置
------------------
正式库是 MySQL 80（root/123456），Django 跑测试时会去 CREATE DATABASE test_yikeui，
一来依赖本机 MySQL 状态和建库权限，二来万一中断会留下脏库。
这里改用一个 SQLite 文件库（`web/db_test.sqlite3`），跑完随时可以删，
既不依赖外部服务，也保证测试之间完全隔离。

用法
----
    python manage.py test --settings=yikeui.settings_test
    或双击 scripts/run_tests.bat

注意：本配置只覆盖「跑测试需要改的那几项」，其余全部继承 yikeui.settings。
'''
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(BASE_DIR / 'db_test.sqlite3'),  # noqa: F405
    }
}

# 建用户时不要把时间浪费在慢哈希上
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
