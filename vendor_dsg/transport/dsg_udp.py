import socket
import threading
import queue
import time


class UDPThread:
    """UDP 通信线程类
    用于管理 UDP socket、数据发送和接收，运行在独立线程中
    """

    def __init__(self, local_port, remote_ip, remote_port, buffer_size=4096):
        """初始化 UDP 通信线程

        Args:
            local_port: 本地监听端口
            remote_ip: 远端设备 IP
            remote_port: 远端设备端口
            buffer_size: 接收缓冲区大小
        """
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.buffer_size = buffer_size

        # socket 对象
        self.sock = None

        # 线程相关
        self.thread = None
        self.running = False

        # 数据队列
        self.send_queue = queue.Queue()
        self.receive_queue = queue.Queue()

        # 连接状态
        self.is_connected = False

        # 回调函数
        self.data_received_callback = None

    def open(self):
        """打开 UDP socket"""
        try:
            if self.sock:
                print("UDP socket 已经打开")
                return True

            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("", self.local_port))
            self.sock.settimeout(0.5)

            self.is_connected = True
            print(f"UDP socket 打开成功，本地端口 {self.local_port}")

            self.start_thread()
            return True

        except Exception as e:
            print(f"打开 UDP socket 失败: {e}")
            self.is_connected = False
            self.sock = None
            return False

    def close(self):
        """关闭 UDP socket"""
        try:
            self.stop_thread()

            if self.sock:
                self.sock.close()
                self.sock = None
                print("UDP socket 已关闭")

        except Exception as e:
            print(f"关闭 UDP socket 时发生错误: {e}")
        finally:
            self.is_connected = False
    def write(self, data: bytes):
        """
        SDK 标准接口：发送一帧原始字节数据（非阻塞）
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("UDPThread.write expects bytes")

        if not self.is_connected or not self.sock:
            raise RuntimeError("UDP socket is not open")

        try:
            self.send_queue.put(data, timeout=0.5)
        except Exception as e:
            raise RuntimeError(f"UDP write failed: {e}")

    def read(self, timeout=None, expected_len=None) -> bytes:
        """
        SDK 标准接口：读取一帧接收到的数据

        Args:
            timeout: 等待时间（秒），None 表示立即返回
            expected_len: 若指定，仅返回前 expected_len 字节

        Returns:
            bytes
        """
        if not self.is_connected:
            raise RuntimeError("UDP socket is not open")

        try:
            if timeout is None:
                data = self.receive_queue.get_nowait()
            else:
                data = self.receive_queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("UDP read timeout")

        if expected_len is not None:
            return data[:expected_len]

        return data
    
    def send_data(self, data):
        """发送数据到远端设备

        Args:
            data: bytes 类型数据

        Returns:
            bool: 成功 True，失败 False
        """
        if not self.is_connected or not self.sock:
            print("错误: UDP socket 未打开")
            return False

        try:
            self.send_queue.put(data)
            return True
        except Exception as e:
            print(f"UDP 发送数据失败: {e}")
            return False

    def get_received_data(self):
        """获取接收到的数据

        Returns:
            bytes: 接收到的数据，没有则返回 b''
        """
        try:
            return self.receive_queue.get_nowait()
        except queue.Empty:
            return b''

    def set_data_received_callback(self, callback):
        """设置数据接收回调函数

        Args:
            callback: 函数，参数为 bytes
        """
        self.data_received_callback = callback

    def start_thread(self):
        """启动 UDP 通信线程"""
        if self.thread and self.thread.is_alive():
            print("UDP 通信线程已在运行")
            return

        self.running = True
        self.thread = threading.Thread(target=self._communication_thread)
        self.thread.daemon = True
        self.thread.start()
        print("UDP 通信线程已启动")

    def stop_thread(self):
        """停止 UDP 通信线程"""
        if self.thread and self.thread.is_alive():
            self.running = False
            self.send_queue.put(b'')  # 唤醒线程
            self.thread.join(timeout=2.0)
            print("UDP 通信线程已停止")

    def _communication_thread(self):
        """UDP 通信线程主函数"""
        print("UDP 通信线程开始运行")

        while self.running:
            try:
                # 处理发送队列
                if not self.send_queue.empty():
                    data = self.send_queue.get(timeout=0.1)
                    if data:
                        # print(
                        #     "[UDP SEND]",
                        #     f"len={len(data)}",
                        #     data.hex()
                        # )
                        # print(f"SEND from thread={threading.current_thread().name}, data={data!r}")
                        self.sock.sendto(
                            data,
                            (self.remote_ip, self.remote_port)
                        )
                        # print(f"已发送 UDP 数据: {data.hex()}")

                # 接收数据
                try:
                    received_data, addr = self.sock.recvfrom(self.buffer_size)
                    if received_data:
                        self.receive_queue.put(received_data)

                        if self.data_received_callback:
                            self.data_received_callback(received_data)

                        # print(f"接收到 UDP 数据: {received_data.hex()}")

                except socket.timeout:
                    pass  # 正常超时，不处理

                time.sleep(0.01)

            except queue.Empty:
                continue
            except Exception as e:
                print(f"UDP 通信线程异常: {e}")
                self.is_connected = False
                break

        print("UDP 通信线程结束")

    def __del__(self):
        """析构函数"""
        self.close()
