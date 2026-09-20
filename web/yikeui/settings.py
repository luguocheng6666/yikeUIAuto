"""
yikeUIAuto Web 用例管理平台 - Django 配置
"""
from pathlib import Path
import os
import sys

# Web 平台执行用例时，强制让框架走「数据库」数据源（而非 Excel）。
# 命令行 TestRunner.py 不加载本配置，故默认仍是 Excel，原行为不受影响。
os.environ.setdefault('YIKEUI_DATA_SOURCE', 'db')

# .../yikeUIAuto/web
BASE_DIR = Path(__file__).resolve().parent.parent
# .../yikeUIAuto   —— 自动化框架所在的项目根
PROJECT_ROOT = BASE_DIR.parent

# 让 Django 能 import 上层目录里的执行引擎（framework / keywordsDriver / setting 等）
for _p in (str(PROJECT_ROOT), str(BASE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 生产密钥通过环境变量 YIKEUI_SECRET_KEY 注入；本地保留开发用默认值（切勿用于生产）
SECRET_KEY = os.environ.get(
    'YIKEUI_SECRET_KEY',
    'django-insecure-oo&+lr$dsv0f5zd8=_o(sb!9))hybzw5o891jskqgsh!b7-0j@')

# 本地默认 DEBUG=True 便于排查；生产部署设 YIKEUI_DEBUG=0 关闭
DEBUG = os.environ.get('YIKEUI_DEBUG', '1') == '1'

# 域名：默认 yikeui.com。本地先在 hosts 里映射，或直接用 127.0.0.1:8000
SITE_DOMAIN = os.environ.get('YIKEUI_DOMAIN', 'yikeui.com')
# testserver 供 Django 测试客户端使用
# 本地/开发环境保留 127/localhost/testserver；生产通过 YIKEUI_ALLOWED_HOSTS 注入真实域名/IP。
# 调试态(DEBUG=True)额外放行 0.0.0.0，方便 `runserver 0.0.0.0` 临时联调。
_extra_hosts = [h.strip() for h in os.environ.get('YIKEUI_ALLOWED_HOSTS', '').split(',') if h.strip()]
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver'] + _extra_hosts
if DEBUG:
    ALLOWED_HOSTS.append('0.0.0.0')
ALLOWED_HOSTS += [SITE_DOMAIN, 'www.' + SITE_DOMAIN]

# CSRF 可信源：本地 http 已含；生产 https 通过 YIKEUI_HTTPS_HOSTS 注入（逗号分隔域名）
CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:8000',
    'http://localhost:8000',
    'http://' + SITE_DOMAIN,
]
for _h in [h.strip() for h in os.environ.get('YIKEUI_HTTPS_HOSTS', '').split(',') if h.strip()]:
    CSRF_TRUSTED_ORIGINS.append('https://' + _h)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cases',
    'runner',
]

# whitenoise 只在生产（DEBUG=False）接管静态文件；本地 DEBUG=True 时由 Django 自带
# staticfiles 直接服务 /static/，无需该包，避免本地 .python3 未装 whitenoise 时 runserver 直接崩。
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
]
if not DEBUG:
    MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')
MIDDLEWARE += [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'yikeui.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'yikeui.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('YIKEUI_DB_NAME', 'yikeui'),
        'USER': os.environ.get('YIKEUI_DB_USER', 'root'),
        'PASSWORD': os.environ.get('YIKEUI_DB_PASSWORD', '123456'),
        'HOST': os.environ.get('YIKEUI_DB_HOST', '127.0.0.1'),
        'PORT': os.environ.get('YIKEUI_DB_PORT', '3306'),
        'OPTIONS': {'charset': 'utf8mb4'},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 登录相关
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# 复用自动化框架原有的目录
# 注意：报告统一放在 web/reports（与 executor 实际写入位置一致）。
# 项目根的 reports/ 是早期遗留目录，已不再使用（保留但不读写）。
REPORTS_DIR = BASE_DIR / 'reports'
SHOTS_DIR = REPORTS_DIR / 'shots'      # 报告截图（独立 png，不再 base64 内嵌）
BACKUP_DIR = PROJECT_ROOT / 'BackUP'
DATA_DIR = PROJECT_ROOT / 'Data'
SCREENSHOT_DIR = PROJECT_ROOT / 'Screenshot'

# ---- 执行相关 ----
RUN_TIMEOUT = 30 * 60        # 单轮执行超时上限（秒），超时自动请求停止并置为异常
PLANNER_TICK = 30            # 定时计划轮询间隔（秒），到点误差不超过这个值
CLEANUP_INTERVAL = 24 * 3600   # 产物清理间隔（秒）
CLEANUP_FIRST_DELAY = 3600     # 服务启动后多久执行首次清理（秒），留出反悔窗口
KEEP_REPORTS = 100             # 保留最近多少份报告
KEEP_BACKUP_DAYS = 100         # BackUP 保留多少天（超期的历史归档会被删除）

# ---- 上传限制（Excel 导入）----
# 默认 2.5MB 偏小，放宽到 25MB，避免大用例表被拒。
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
