'''runner 应用路由'''
from django.urls import path

from . import views

app_name = 'runner'

urlpatterns = [
    path('', views.run_list, name='run_list'),
    path('start/case/<int:pk>/', views.run_start_case, name='run_start_case'),
    path('start/tag/', views.run_start_tag, name='run_start_tag'),
    path('start/selected/', views.run_start_selected, name='run_start_selected'),
    path('settings/notify/', views.notify_settings, name='notify_settings'),
    path('settings/notify/test/', views.notify_test, name='notify_test'),
    path('schedules/', views.schedule_list, name='schedule_list'),
    path('schedules/save/', views.schedule_save, name='schedule_save'),
    path('schedules/<int:pk>/save/', views.schedule_save, name='schedule_edit_save'),
    path('schedules/<int:pk>/toggle/', views.schedule_toggle, name='schedule_toggle'),
    path('schedules/<int:pk>/run/', views.schedule_run_now, name='schedule_run_now'),
    path('schedules/<int:pk>/delete/', views.schedule_delete, name='schedule_delete'),
    path('<int:pk>/', views.run_detail, name='run_detail'),
    path('<int:pk>/status/', views.run_status_api, name='run_status_api'),
    path('<int:pk>/report/', views.run_report, name='run_report'),
    path('<int:pk>/cancel/', views.run_cancel, name='run_cancel'),
    path('<int:pk>/shots/<str:name>', views.run_shot, name='run_shot'),
]
