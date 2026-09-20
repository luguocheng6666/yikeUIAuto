"""把「登录账号 / 发件人邮箱」两个字段合并成一个：username 即发件人。

页面上原来要填两遍同一个邮箱，现在只留「发件人邮箱」。迁移先把老数据里
sender 的值回填进 username（仅在 username 为空时），再删掉 sender 字段。
"""
from django.db import migrations, models


def backfill_sender(apps, schema_editor):
    NotifyConfig = apps.get_model('runner', 'NotifyConfig')
    for cfg in NotifyConfig.objects.all().only('pk', 'username', 'sender'):
        if not (cfg.username or '').strip() and (cfg.sender or '').strip():
            cfg.username = cfg.sender.strip()
            cfg.save(update_fields=['username'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [('runner', '0004_scheduleplan')]

    operations = [
        migrations.RunPython(backfill_sender, noop),
        migrations.RemoveField(model_name='notifyconfig', name='sender'),
        migrations.AlterField(
            model_name='notifyconfig',
            name='username',
            field=models.CharField(blank=True, default='', max_length=200,
                                   verbose_name='发件人邮箱'),
        ),
    ]
