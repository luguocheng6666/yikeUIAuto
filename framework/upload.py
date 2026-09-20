import paramiko
from  paramiko.ssh_exception import AuthenticationException
import datetime
import os
from framework.logger import Logger
from keywordsDriver.excelKey import *
import getpass
import  setting
from keywordsDriver.excelKey import excelname
import shutil
mylog=Logger(logger=__name__).getlog()


#hostname=input('请输入上传服务器的地址(如果为空，则默认取配置文件中的119.23.63.108)：')
# if hostname=='':
#     hostname='119.23.63.108'



def backup(oldfile):

    excel_dir = os.path.join(setting.DATA_PATH , excelname)
    new_dir = setting.backup_dir

    now_time = datetime.datetime.now()
    mouth = now_time.strftime('%B')
    new_dir=os.path.join(new_dir,os.path.join(str(now_time.strftime('%Y')),mouth) )
    if  not os.path.exists(new_dir):
        os.makedirs(new_dir)

    extension=os.path.splitext(oldfile)[-1]
    #extension = os.path.splitext(new_retport_filename)[-1]

    new_report_file = os.path.join(new_dir,now_time.strftime('%Y_%m_%d_%H%M%S')  +extension)


    extension = os.path.splitext(excelname)[-1]

    new_data_file = os.path.join(new_dir,now_time.strftime('%Y_%m_%d_%H%M%S') + extension)


    shutil.copyfile(oldfile,new_report_file)
    shutil.copyfile(excel_dir, new_data_file)



def upload():
    hostname = setting.mysql_host
    port = setting.port
    username = setting.username
    pwd = setting.pwd

    # port=input('请输入上传服务器的端口(如果为空，则默认为22)：')
    # if port=='':
    #     port = 22
    #
    # username=input('请输入上传服务器的账号(如果为空，则默认为root)：')
    # if username=='':
    #     username='root'
    # #pwd=getpass.getpass("请输入上传服务器的密码(如果为空，则默认取配置文件密码)：")
    # pwd = getpass.getpass(prompt='请输入上传服务器的密码:')
    # # mylog.info("your password is %s" %pwd)

    local_dir = setting.reports_dir
    excel_dir = os.path.join(setting.reports_dir , excelname)
    remote_dir = setting.backup_dir
    try :
        t=paramiko.Transport(hostname,port)
        t.connect(username=username,password=pwd)
        sftp=paramiko.SFTPClient.from_transport(t)
        if os.path.exists(local_dir):
            nested = os.walk(local_dir)
            for root, dirs, file in nested:

                local_dir_path = os.path.join(root, file[0])
                now_time=datetime.datetime.now()
                mouth=now_time.strftime('%B')
                remote_dir_path =  os.path.join(root,'BackUP') + r'/' + str(
                    now_time.strftime('%Y')) + r'/' +mouth+ r'/'

                remote_file_path = remote_dir_path + now_time.strftime('%Y_%m_%d_%H%M%S') +'.'+ file[0].split('.')[-1]
                # remote_dir_path=remote_dir+str(time_tuple[2])+str(time_tuple[3])+str(time_tuple[4])+str(time_tuple[5])+'.'+file[0].split('.')[-1]
                try:
                    sftp.put(local_dir_path, remote_file_path)
                    sftp.put(excel_dir, remote_file_path.split('.')[0]+'.'+excel_dir.split('.')[-1])
                    t.close()
                except IOError as e:
                    command = 'mkdir -p ' + remote_dir_path
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(username=username, password=pwd, hostname=hostname, port=port)
                    ssh.exec_command(command)
                    ssh.close()
                    sftp.put(local_dir_path, remote_file_path)
                    sftp.put(excel_dir, remote_file_path.split('.')[0] + '.' + excel_dir.split('.')[-1])#因为用处不大， 所以暂时先这样简陋的写下
                    t.close()
            mylog.info('上传报告成功')
        else:
            mylog.error(local_dir+" 目录不存在,报告未能成功上传！")

        t.close()
    except AuthenticationException as e:
        import traceback
        traceback.print_exc()
        mylog.error('无法连接服务器，请检查配置!:'+e)
#
# if __name__ == '__main__':
#     upload()




