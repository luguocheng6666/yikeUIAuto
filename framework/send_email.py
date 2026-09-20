from smtplib import SMTP
from email.header import Header
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart


from email.utils import formataddr
import os
import re


def smtp_settings():
    """SMTP 参数 —— 全部走环境变量。

    历史版本这里写死过一个 QQ 邮箱授权码，属于把凭据提交进仓库，已移除。
    现在统一从环境变量读；Web 平台侧的邮件通知改走 web/runner/notifier.py
    （在页面上配置），命令行模式想发邮件就先 export 这几个变量：
        YIKEUI_SMTP_HOST / YIKEUI_SMTP_PORT / YIKEUI_SMTP_USER
        YIKEUI_SMTP_PASSWORD / YIKEUI_SMTP_SENDER / YIKEUI_SMTP_RECEIVERS
    """
    return {
        'smtpserver': os.environ.get('YIKEUI_SMTP_HOST', 'smtp.qq.com'),
        'port': int(os.environ.get('YIKEUI_SMTP_PORT', '465')),
        'sender': os.environ.get('YIKEUI_SMTP_SENDER', ''),
        'key': os.environ.get('YIKEUI_SMTP_PASSWORD', ''),
        'receiver': [x.strip() for x in
                     os.environ.get('YIKEUI_SMTP_RECEIVERS', '').split(',') if x.strip()],
    }


def send_email(report_path, result):
    success_count = str(result.success_count)
    failure_count = str(result.failure_count)
    error_count = str(result.error_count)

    errors = list(set([x[0]._testMethodName.split("_", 3)[-1] for x in result.errors]))
    failures = list(
        set([x[0]._testMethodName.split("_", 3)[-1] for x in result.failures])
    )

    # 创建一个带附件的邮件消息对象
    message = MIMEMultipart()
    # 创建文本内容
    # text_content = MIMEText(附件中有本月数据请查收, 'plain', 'utf-8')
    # message.attach(text_content)
    subject = 'UI自动化测试报错提醒'
    cfg = smtp_settings()
    smtpserver = cfg['smtpserver']
    sender = cfg['sender']
    key = cfg['key']
    senderheader = 'UI自动化测试报错提醒'
    receivers = cfg['receiver']
    if not (sender and key and receivers):
        raise RuntimeError(
            '未配置 SMTP：请设置 YIKEUI_SMTP_SENDER / YIKEUI_SMTP_PASSWORD / '
            'YIKEUI_SMTP_RECEIVERS 环境变量（Web 平台请在「通知设置」页配置）')
    
    mailcontent = """
    
    <!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
</head>
<body leftmargin="8" marginwidth="0" topmargin="8" marginheight="4"    offset="0">
<div>
<table cellpadding="0" cellspacing="0"
style="font-size: 11pt; font-family: Tahoma, Arial, Helvetica, sans-serif">
<tr>
<br /><td><b><font color="#0000FF">(Bingo自动化测试错误邮件，请及时处理！)</b></td>
</tr>
<tr>
<th align="center" colspan="2"><br />
<b><font color="#FF00FF">执行结果：</font></b>
<br>
成功数量：%s<br>
失败数量：%s<br>
%s
错误数量：%s<br>
%s
</th>
</tr>
<tr>
<td colspan="2" align="center"><br />
<h2 style="color:red">运行详情参考附件！！！</h2>
</td>
</tr>
</table>
</div>
</body>
</html>
""" % (
        success_count,
        failure_count,
        "<br>".join(failures) + "<br>",
        error_count,
        "<br>".join(errors) + "<br>",
    )

    message["Subject"] = Header(subject, "utf-8")
    # 将文本内容添加到邮件消息对象中

    # message.attach(MIMEText(aa, 'html', 'utf-8'))#发送html
    message.attach(MIMEText(mailcontent, "html", "utf-8"))  # 发送html

    # 读取文件并将文件作为附件添加到邮件消息对象中
    with open(report_path, "rb") as f:
        txt = MIMEText(f.read(), "base64", "utf-8")
        txt["Content-Type"] = "text/plain"
        # txt['Content-Disposition'] =  "attachment; filename*=utf-8''{}".format(escape_uri_path('AutoTestReport')+'.html')
        txt["Content-Disposition"] = "attachment; filename*=utf-8''{}".format(
            "AutoTestReport" + ".html"
        )
        message.attach(txt)

    # 创建SMTP对象（端口可配，默认 465 SSL）
    import smtplib
    smtper = (smtplib.SMTP_SSL(smtpserver, cfg['port'], timeout=30)
              if cfg['port'] == 465 else SMTP(smtpserver, cfg['port'], timeout=30))
    # 开启安全连接
    # smtper.starttls()
    sender = sender
    message["From"] = Header(senderheader)
    message["From"] = formataddr(["senderheader", sender])
    receivers = receivers

    # 登录到SMTP服务器
    # 请注意此处不是使用密码而是邮件客户端授权码进行登录
    # 对此有疑问的读者可以联系自己使用的邮件服务器客服
    smtper.login(sender, key)

    try:
        # 发送邮件
        smtper.sendmail(sender, receivers, message.as_string())
    except Exception:
        print("发送邮件失败")
    # 与邮件服务器断开连接
    smtper.quit()
