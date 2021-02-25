'''
Author: sdc
Date: 2020-08-03 17:18:42
LastEditTime: 2020-08-27 14:40:20
LastEditors: Please set LastEditors
Description: 模拟ssh 客户端工具
FilePath: /opt/socket/client_tty.py
'''

import os
import tty
import json
import fcntl
import signal
import struct
import socket
import argparse
from select import select


'''   模拟ssh通道  客户端   '''
class sshClient(object):

    def __init__(self):
        #self.ADDR=("10.255.175.109", 22999)
        self.ADDR=("10.255.175.121", 22999)
        self.BUFSIZ=1024
        self.terminal_size()


    '''  获取终端窗口  高度 + 宽度  '''
    def terminal_size(self):
        self.height, self.weight, hp, wp = struct.unpack('HHHH',
            fcntl.ioctl(0, tty.TIOCGWINSZ,
            struct.pack('HHHH', 0, 0, 0, 0)))


    '''  信号处理函数  kill + pid  '''
    def hup_handle(self, signum, frame):
        self.clear()
        print('quit')
        raise SystemExit


    '''  连接socket服务端  '''
    def connect(self):
        signal.signal(signal.SIGTERM, self.hup_handle)
        self.client_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.client_conn.connect(self.ADDR)
        except Exception as e:
            print('error -> ', str(e))
            raise SystemExit


    '''  工作函数: 接收指令，打印到屏显  '''
    def work(self):
        try:
            if not self.client_conn.connect_ex(self.ADDR): return False
            r, w, e = select([0, self.client_conn], [], [])
            if self.client_conn in r:
                data = self.client_conn.recv(self.BUFSIZ)
                if data:
                    os.write(1, data)
                else:
                    return False
            if 0 in r:
                self.client_conn.send(os.read(0, self.BUFSIZ))
            return True
        except:
            return False


    '''   接收数据，借用报头方式 避免粘包问题   '''
    def receive(self):
        # 先接收报头长度
        head_length = self.client_conn.recv(4)
        if not head_length:
            return ''
        header_size = struct.unpack('i', head_length)[0]
        # 接收报头
        header_bytes = self.client_conn.recv(header_size)
        # 从报头中解析出数据的真实信息（报头字典）
        header_json = header_bytes.decode('utf-8')
        header_dic = json.loads(header_json)
        total_size = header_dic['total_size']
        recv_data = b''
        if total_size:
            while  total_size>0:
                res = self.client_conn.recv(self.BUFSIZ)
                total_size -= len(res)
                recv_data += res
            return str(recv_data, encoding="utf8")
        else:
            return ''


    '''   发送数据，借用报头方式 避免粘包问题   '''
    def send(self, message):
        # 制作固定长度的报头
        header_dic = {
                      'total_size': len(message)
        }
        # 序列化报头, 序列化为byte字节流类型
        header_json = json.dumps(header_dic)
        header_bytes = header_json.encode('utf-8')
        # 先发送报头的长度, 将byte类型的长度打包成4位int
        self.client_conn
        self.client_conn.send(struct.pack('i', len(header_bytes)))
        # 再发报头
        self.client_conn.send(header_bytes)
        # 再发真实数据
        self.client_conn.sendall(bytes(message, encoding="utf8"))


    '''  断开连接，恢复终端设置  '''
    def clear(self):
        self.client_conn.close()
        winsize = struct.pack("HHHH", self.height, self.weight, 0, 0)
        fcntl.ioctl(0, tty.TIOCSWINSZ, winsize)
        tty.tcsetattr(0, tty.TCSAFLUSH, self.mode)


'''  主函数  '''
def main():
    parser = argparse.ArgumentParser(description='''
                    选择功能:
                            1 :   开启交互式命令窗口
                            2 :   上传文件
                            3 :   下载文件
    ''')
    # 定义必选参数 positionArg
    parser.add_argument("--choose", "-c", help="选择序号:  ssh<export TERM=linux>")
    args = parser.parse_args()  # 返回一个命名空间
    params = vars(args)  # 返回 args 的属性和属性值的字典
    choose = params["choose"]
    if not choose:
        print(' --help')
        return
    '''  连接ssh Server端  '''
    client = sshClient()
    client.connect()
    client.send(choose)
    if choose == "1":
        print('welcome')
        '''  阻塞连接，交互式发送命令并打印输出结果  '''
        client.mode = tty.tcgetattr(0)
        tty.setraw(0)
        while 1:
            '''  发送命令，打印屏显  '''
            if not client.work():
                '''  退出，恢复终端原始设置  '''
                client.clear()
                break
    elif choose == "2":
        '''  上传文件  '''
        filename = input("\n\t\tfilename ->  ")
        try:
            with open(filename, 'r') as ff:
                data = ff.read()
        except Exception as e:
            print(str(e))
            raise SystemExit
        client.send(json.dumps({"filename": filename.split('/')[-1], "data": data}))
        message = client.receive()
        if message:
            message = json.loads(message)
            if message["success"] == "ok":
                print('上传成功\nupload -> /tmp/%s' % filename.split('/')[-1])
            else:
                print(message["message"])
    elif choose == "3":
        '''  下载文件  '''
        filename = input("\n\t\tfilename ->  ")
        client.send(filename)
        message = client.receive()
        if message:
            message = json.loads(message)
            if message["success"] == "ok":
                with open('/tmp/%s' % filename.split('/')[-1], 'w') as ff:
                    ff.write(message["message"])
                print('下载成功\ndownload -> /tmp/%s' % filename.split('/')[-1])
            else:
                print(message["message"])
    else:
        print('没有此功能选项')


if __name__ == "__main__":
    main()
