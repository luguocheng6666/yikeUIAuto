'''cases 应用路由'''
from django.urls import path

from . import views

app_name = 'cases'

urlpatterns = [
    path('', views.case_list, name='case_list'),
    path('enable/save/', views.case_enable_save, name='case_enable_save'),
    path('enable/run/', views.case_run_enabled, name='case_run_enabled'),
    path('new/', views.case_new, name='case_new'),
    path('<int:pk>/', views.case_detail, name='case_detail'),
    path('<int:pk>/edit/', views.case_edit, name='case_edit'),
    path('<int:pk>/delete/', views.case_delete, name='case_delete'),
    path('<int:pk>/steps/save/', views.steps_save, name='steps_save'),
    path('<int:pk>/steps/restore/<int:snap_pk>/', views.steps_restore, name='steps_restore'),
    path('<int:pk>/copy-from/', views.case_copy_from, name='case_copy_from'),
    path('import/', views.excel_import, name='excel_import'),
    path('export/', views.excel_export, name='excel_export'),
    path('export-template/', views.excel_export_template, name='excel_export_template'),
]
