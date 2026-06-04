import struct
from turtle import mode

from ..transport.dsg_executor import DSGExecutor

class DSGAPIError(Exception):
    pass

class DSGDeviceAPI:
    """
    对外设备 API 类
    封装高层设备操作，隐藏底层协议和通信细节
    """

    def __init__(self, executor: DSGExecutor):
        self._executor = executor  # 内部使用，不暴露给用户

    def get_version(self) -> str:
        """获取设备版本号"""
        try:
            resp = self._executor._send_cmd_raw(
                cmd=self._executor.protocol.CMD_VER,
                opcode=self._executor.protocol.OPCODE_READ
            )
            version_bytes = resp[1:].split(b'\x00', 1)[0]
            version_str = version_bytes.decode("utf-8").strip()
            # 检查前缀 
            if not version_str.startswith("QS-DSG"):
                raise DSGAPIError(f"Unexpected device version string: {version_str}")

            return version_str
        except Exception as e:
            raise DSGAPIError(f"Failed to get device version: {e}")

    def get_sn(self) -> str:
        """查询设备序列号"""
        try:
            resp = self._executor._send_cmd_raw(
                cmd=self._executor.protocol.CMD_SN,
                opcode=self._executor.protocol.OPCODE_READ
            )
            sn_bytes = resp[1:].split(b'\x00', 1)[0]
            sn = sn_bytes.decode("utf-8").strip()
            if not sn:
                raise DSGAPIError("Empty SN string")
            return sn
        except Exception as e:
            raise DSGAPIError(f"Failed to get device SN: {e}")

    def get_status(self) -> int:
        """查询设备状态，返回状态码"""
        try:
            resp = self._executor._send_cmd_raw(
                cmd=self._executor.protocol.CMD_STATUS,
                opcode=self._executor.protocol.OPCODE_READ
            )
            status_bytes = resp[1:].split(b'\x00', 1)[0]
            return status_bytes
        except Exception as e:
            raise DSGAPIError(f"Failed to get device status: {e}")

    def get_trig_mode(self) -> int:
        """查询设备触发模式"""
        try:
            resp = self._executor._send_cmd_raw(
                cmd=self._executor.protocol.CMD_TRIG_MODE,
                opcode=self._executor.protocol.OPCODE_READ
            )
            mode_bytes = resp[1:].split(b'\x00', 1)[0]
            return mode_bytes
        except Exception as e:
            raise DSGAPIError(f"Failed to get device status: {e}")

    def get_channels_status(self) -> bytes:
        """查询通道状态"""
        try:
            resp = self._executor._send_cmd_raw(
                cmd=self._executor.protocol.CMD_CHANNELS_STATUS,
                opcode=self._executor.protocol.OPCODE_READ
            )
            chasta_bytes = resp[1:]
            if len(chasta_bytes) != 8:
                raise DSGAPIError(
                    f"Invalid payload length {len(chasta_bytes)}, expect 8"
                )
            manual_en, manual_val = struct.unpack("<II", chasta_bytes)
            return manual_en, manual_val

        except Exception as e:
            raise DSGAPIError(f"Failed to get channels status: {e}")

    def get_clk_status(self) -> bytes:
        """查询时钟状态"""
        try:
            resp = self._executor._send_cmd_raw(
                cmd=self._executor.protocol.CMD_CLK_SOURCE,
                opcode=self._executor.protocol.OPCODE_READ
            )
            clksta_bytes = resp[1:]
            if len(clksta_bytes) != 8:
                raise DSGAPIError(
                    f"Invalid payload length {len(clksta_bytes)}, expect 8"
                )
            clk_source, outclk_stable = struct.unpack("<II", clksta_bytes)
            return clk_source, outclk_stable

        except Exception as e:
            raise DSGAPIError(f"Failed to get clock status: {e}")

    def send_restart_signal(self, reserved: int = 0):
        """发送重启设备信号命令"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_RST,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send restart signal: {e}")
              
    def send_operating_mode_signal(self, reserved: int = 0):
        """发送单次/循环执行信号命令"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_KEEP,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send keep signal: {e}")

    def send_cls_signal(self, reserved: int = 0):
        """发送清除信号命令"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_CLS,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send clear signal: {e}")
        
    def send_operating_status_signal(self, reserved: int = 0):
        """发送继续/暂停信号命令"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_INTERRUPT,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send interrupt signal: {e}")
        
    def send_setdone_signal(self, reserved: int = 0):
        """发送设置完成信号命令"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_SET,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send set signal: {e}")

    def send_hwstrat_signal(self, reserved: int = 0):
        """发送硬件触发信号命令"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_RUN,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send run signal: {e}")

    def send_strat_signal(self, reserved: int = 0):
        """发送软件触发信号命令"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_SWR,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send swr signal: {e}")

    def send_abt_signal(self, reserved: int = 0):
        """发送中断信号命令"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_ABT,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send abt signal: {e}")

    def send_trigmode_signal(self, trig_mode: int, reserved: int = 0):
        """发送触发模式命令"""
        payload = struct.pack("<B", trig_mode & 0xF)
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_TRIG_MODE,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved,
                payload=payload
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send trigmode signal: {e}")
        
    def enable_led(self, reserved: int = 0b11):
        """使能LED指示灯"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_LED_EN,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to enable LED: {e}")

    def disable_led(self, reserved: int = 0b00):
        """禁用LED指示灯"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_LED_EN,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to enable LED: {e}")     
              
    def enable_channelsLED(self, LED_mask: int, reserved: int = 0):
        """控制通道LED指示灯亮灭"""
        payload = struct.pack("<I", LED_mask & 0xFFFFFFFF)
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_CHx,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved,
                payload=payload
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to send channel mask command: {e}")

    def switch_extclk(self, reserved: int = 0b11):
        """切换为外部时钟"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_CLK,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to switch external clock: {e}")

    def switch_intclk(self, reserved: int = 0b00):
        """切换为内部时钟"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_CLK,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to switch internal clock: {e}")

    def switch_manual_mode(self, channel_mask: int, reserved: int = 0b11):
        payload = struct.pack("<I", channel_mask & 0xFFFFFFFF)
        """切换为全通道手动模式"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_MAN,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved,
                payload=payload
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to switch manual mode: {e}")    

    def manual_channels(self,  manual_en: int,manual_val: int, reserved: int = 0b01):
        """切换为部分通道手动模式"""
        try:
                payload = struct.pack(
                    "<II",
                    manual_en & 0xFFFFFFFF,
                    manual_val & 0xFFFFFFFF
                )

                self._executor._send_cmd(
                    cmd=self._executor.protocol.CMD_MAN,
                    opcode=self._executor.protocol.OPCODE_WRITE,
                    reserved=reserved,
                    payload=payload
                )
        except Exception as e:
            raise DSGAPIError(f"Failed to switch manual channels: {e}")

    def switch_stream_mode(self, reserved: int = 0b10):
        """切换为流模式"""
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_MAN,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to switch stream mode: {e}")    

    def set_specified_addr(self, specified_addr: int, outs: int, reps: int, reserved: int = 0):
        """设置指定地址的输出指令"""
        payload = struct.pack("<III", specified_addr, outs, reps)
        try:
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_SSA,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved,
                payload=payload
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to set specified address command: {e}")

    def send_stream(self,header: bytes, command_stream: bytes):
        """下发完整指令流"""
        try:
            self._executor._adm_batch(header, command_stream)
        except Exception as e:
            raise DSGAPIError(f"Failed to send command stream: {e}")
        
    def set_ip(self, ip: str, mask: str, gw: str, reserved: int = 0b11) -> None:
        """
        修改设备 IP 并写入 Flash
        :param ip: 字符串形式 IP，如 "192.168.1.99"
        :param mask: 子网掩码，如 "255.255.255.0"
        :param gw: 网关，如 "192.168.1.1"
        :param reserved: 协议保留位，默认 0
        """
        try:
            # 转换成 4 字节整数
            ip_bytes = bytes(map(int, ip.split(".")))
            mask_bytes = bytes(map(int, mask.split(".")))
            gw_bytes = bytes(map(int, gw.split(".")))

            # 按协议顺序打包 payload: ip[4]+mask[4]+gw[4] = 12 字节
            payload = struct.pack("<12B",
                                  ip_bytes[0], ip_bytes[1], ip_bytes[2], ip_bytes[3],
                                  mask_bytes[0], mask_bytes[1], mask_bytes[2], mask_bytes[3],
                                  gw_bytes[0], gw_bytes[1], gw_bytes[2], gw_bytes[3])

            # 发送写命令
            self._executor._send_cmd(
                cmd=self._executor.protocol.CMD_IP,
                opcode=self._executor.protocol.OPCODE_WRITE,
                reserved=reserved,
                payload=payload
            )
        except Exception as e:
            raise DSGAPIError(f"Failed to set device IP: {e}")
        
    # 使用用户定义的 IP   
    def use_userconfig_ip(self, reserved: int = 0b10) -> None:
        self._executor._send_cmd(
            cmd=self._executor.protocol.CMD_IP,
            opcode=self._executor.protocol.OPCODE_WRITE,
            reserved=reserved,
        )

    # 使用出厂设置的 IP
    def use_defaultconfig_ip(self, reserved: int = 0b01) -> None:
        self._executor._send_cmd(
            cmd=self._executor.protocol.CMD_IP,
            opcode=self._executor.protocol.OPCODE_WRITE,
            reserved=reserved,
        )











