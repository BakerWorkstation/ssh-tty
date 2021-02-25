'''
Author: sdc
Date: 2020-08-03 17:17:32
LastEditTime: 2020-08-25 16:33:49
LastEditors: Please set LastEditors
Description: 模拟ssh 服务端工具
FilePath: /opt/socket/server_tty.py
'''

import os
import pty
import tty
import time
import json
import fcntl
import struct
import select
import signal
from socket import *
from queue import Queue, Full
from concurrent.futures import ThreadPoolExecutor

qlist = Queue(maxsize=10)
pool = ThreadPoolExecutor(max_workers=20)


'''   模拟ssh通道  服务端   '''
class sshServer(object):

    def __init__(self):
        self.ADDR=("0.0.0.0", 22999)
        self.BUFSIZ=1024
    

    '''   获取虚拟终端master, slave    '''
    def getPty(self):
        pty_num, tty_num = pty.openpty()
        print('pty(伪终端) -> ', os.ttyname(pty_num), ' 序号-> ', pty_num)
        print('tty(控制台) -> ', os.ttyname(tty_num), ' 序号-> ', tty_num)
        return pty_num, tty_num
 

    '''   捕获信号， kill + pid   '''
    def hup_handle(self, signum, frame):
        raise SystemExit


    '''   exec族函数， 用bash地址内容覆盖子进程地址内容  '''
    def execBash(self, tty_num):
        os.setsid()
        os.dup2(tty_num, 0)
        os.dup2(tty_num, 1)
        os.dup2(tty_num, 2)
        print('welcome !')
        # 设置终端窗口大小
        winsize = struct.pack("HHHH", 40, 145, 0, 0)
        fcntl.ioctl(0, tty.TIOCSWINSZ, winsize)
        # 用bash地址空间内容替换掉子进程地址空间内容
        data = os.execlp("/bin/bash", "/bin/bash")


    '''   监听程序  '''
    def listen(self):
        signal.signal(signal.SIGTERM, self.hup_handle)
        self.sock = socket(AF_INET, SOCK_STREAM)
        self.sock.setsockopt(SOL_SOCKET, SO_REUSEADDR , 1)
        self.sock.bind(self.ADDR)
        self.sock.listen(1)
        #self.sock.setblocking(0)


    '''   等待客户端连接   '''
    def accept(self):
        while 1:
            infds, outfds, errfds = select.select([self.sock, ], [], [], 3)
            # 如果infds状态改变,进行处理,否则不予理会
            if len(infds) != 0:
                conn, addr = self.sock.accept()
                break
            else:
                pass
                #print("未发现新连接")
        #conn.settimeout(10)
        return conn, addr

        #mode = tty.tcgetattr(self.tty_num)
        #tty.setraw(0)


    '''   发送客户端屏显内容   '''
    def onshow(self, read_tunnel, fds):
        pty_num = fds[0]
        conn = fds[-1]
        # 发送屏显
        if pty_num in read_tunnel:
            #print('pty -> %s' % self.pty_num)
            data = os.read(pty_num, self.BUFSIZ)
            #print('data ', data)
            if data:
                conn.send(data)
            else:
                fds.remove(pty_num)
        return True


    '''   获取客户端发送的指令   '''
    def command(self, read_tunnel, fds):
        pty_num = fds[0]
        conn = fds[-1]
        # 获取指令
        if conn in read_tunnel:
            #print('conn -> %s' % self.conn)
            data = conn.recv(self.BUFSIZ)
            #print('data ', data)
            if not data:
                fds.remove(conn)
                conn.close()
                return False
            if data:
                os.write(pty_num, data)
        return True

    
    '''   交互执行命令隧道: 父进程获取pty, 子进程获取tty  '''
    def pipe(self, clientconn, clientaddr):
        pty_num, tty_num = self.getPty()
        fds = [pty_num, clientconn]
        pid = os.fork()
        if pid == 0:
            print('子进程pid -> %s' % pid)
            os.close(pty_num)
            self.execBash(tty_num)
        else:
            print('父进程pid -> %s' % pid)
            os.close(tty_num)
            try:
                while True:
                    if not clientconn.connect_ex(clientaddr): raise Exception
                    r, w, e = select.select([pty_num, clientconn, ], [], [])
                    if not self.onshow(r, fds):
                        break
                    if not self.command(r, fds):
                        break
            except Exception as e:
                pass
            clientconn.close()
            os.close(pty_num)
            son_pid , result = os.wait()
            print('客户端: %s -> 已断开连接' % clientaddr[0])


    '''   接收数据，借用报头方式 避免粘包问题   '''
    def receive(self, clientconn):
        # 先接收报头长度
        head_length = clientconn.recv(4)
        if not head_length:
            return ''
        header_size = struct.unpack('i', head_length)[0]
        # 接收报头
        header_bytes = clientconn.recv(header_size)
        # 从报头中解析出数据的真实信息（报头字典）
        header_json = header_bytes.decode('utf-8')
        header_dic = json.loads(header_json)
        total_size = header_dic['total_size']
        recv_data = b''
        if total_size:
            while  total_size>0:
                res = clientconn.recv(self.BUFSIZ)
                total_size -= len(res)
                recv_data += res
            return str(recv_data, encoding="utf8")
        else:
            return ''


    '''   发送数据，借用报头方式 避免粘包问题   '''
    def send(self, message, clientconn):
        # 制作固定长度的报头
        header_dic = {
                      'total_size': len(message)
        }
        # 序列化报头, 序列化为byte字节流类型
        header_json = json.dumps(header_dic)
        header_bytes = header_json.encode('utf-8')
        # 先发送报头的长度, 将byte类型的长度打包成4位int
        clientconn.send(struct.pack('i', len(header_bytes)))
        # 再发报头
        clientconn.send(header_bytes)
        # 再发真实数据
        clientconn.sendall(bytes(message, encoding="utf8"))


'''  线程工作函数，出队列 响应客户端请求  '''
def work():
    data = qlist.get()
    try:
        clientconn = data["clientconn"]
        clientaddr = data["clientaddr"]
        connect = data["connect"]
        print('客户端: %s -> 已连接' % clientaddr[0])
    except Exception as e:
        clientconn.close()
        print('error -> ', str(e))
        return

    choose = connect.receive(clientconn)
    print('choose ->' , choose)
    if choose == "1":
        '''  开启命令交互模式  '''
        connect.pipe(clientconn, clientaddr)
    elif choose == "2":
        '''  上传文件 等待接收文件内容 '''
        message = connect.receive(clientconn)
        if message:
            try:
                message = json.loads(message)
                filename = message["filename"]
                data = message["data"]
            except:
                clientconn.close()
                return
        else:
            clientconn.close()
            return
        '''  发送上传文件操作结果 '''
        try:
            with open("/tmp/%s" % filename, "w") as ff:
                ff.write(data)
            connect.send(json.dumps({'success':'ok'}), clientconn)
            print('文件名 -> %s' % filename)
        except Exception as e:
            connect.send(json.dumps({'success':'fail', 'message': str(e)}), clientconn)
    elif choose == "3":
        '''  下载文件  等待接收要下载文件的绝对路径  '''
        filename = connect.receive(clientconn)
        print('文件名 -> %s' % filename)
        '''  发送下载文件内容  '''
        try:
            with open(filename, 'r') as ff:
                data = ff.read()
            connect.send(json.dumps({'success':'ok', 'message': data}), clientconn)
        except Exception as e:
            connect.send(json.dumps({'success':'fail', 'message': str(e)}), clientconn)
    else:
        pass


'''  主函数  '''
def main():
    connect = sshServer()
    connect.listen()
    while 1:
        conn, addr = connect.accept()
        # 放入Queue队列
        qlist.put(
                    {
                     "clientconn": conn,
                     "clientaddr": addr,
                     "connect": connect
                    }, 
                    timeout=1
        )
        # 线程池中拉取一个线程准备工作
        pool.submit(work)
        time.sleep(1)


if __name__ == "__main__":
    main()