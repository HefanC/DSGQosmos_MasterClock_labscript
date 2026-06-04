from enum import Enum

class ChannelMode(Enum):
    AUTO = "AUTO"
    MANUAL_HIGH = "MANUAL_HIGH"
    MANUAL_LOW = "MANUAL_LOW"

class DSGProtocol:
    """DSG 设备协议定义"""

    OPCODE_READ  = 0
    OPCODE_WRITE = 1

    CMD_VER             = 0b00001
    CMD_SN              = 0b00010
    CMD_STATUS          = 0b00011
    CMD_CHANNELS_STATUS = 0b00100
    CMD_TRIG_MODE       = 0b00101
    CMD_CLK_SOURCE      = 0b00110
    
    CMD_CLS             = 0b00111
    CMD_SET             = 0b01000
    CMD_RUN             = 0b01001
    CMD_SWR             = 0b01010
    CMD_ABT             = 0b01011
    CMD_INTERRUPT       = 0b01100
    CMD_CLK             = 0b01101
    CMD_ADM             = 0b01110
    CMD_LED_EN          = 0b01111
    CMD_CHx             = 0b10000
    CMD_MAN             = 0b10001
    CMD_SSA             = 0b10010
    CMD_RST             = 0b10011
    CMD_KEEP            = 0b10100
    CMD_IP              = 0b10101

    RESULT_OK  = 0
    RESULT_ERR = 1

    TRIG_RISE = 0
    TRIG_FALL = 1
    TRIG_HIGH = 2
    TRIG_LOW  = 3
    TRIG_PULSE = 4

    TRIG_MODE_MAP = {
        TRIG_RISE:  "上升沿触发",
        TRIG_FALL:  "下降沿触发",
        TRIG_HIGH:  "高电平触发",
        TRIG_LOW:   "低电平触发",
        TRIG_PULSE: "脉冲触发"
    }
    
    STATUS_IDLE    = 0x01
    STATUS_LOADED  = 0x02
    STATUS_RUNNING = 0x04
    STATUS_MANUAL  = 0x08
    STATUS_INTERRUPT  = 0x10
    
    STATUS_MAP = {
        STATUS_MANUAL:  "手动模式",
        STATUS_IDLE:    "设备空闲",
        STATUS_LOADED:  "已载入命令",
        STATUS_RUNNING: "正在运行",
        STATUS_INTERRUPT: "暂停状态"    
    }

    MAX_PAYLOAD = 1026  # 单次UDP有效负载，1字节命令 + 1字节seq + 1024字节指令数据（128组）
    TIMEOUT = 1.0       # 等待设备回复的超时（秒）
    RETRY = 3           # 超时重发次数
    SEGMENT_MARKER = (0xFFFFFFFF, 0x00000000)

    @classmethod
    def status_to_string(cls, status: int) -> str:
        return cls.STATUS_MAP.get(status, f"未知状态({status})")

    @classmethod
    def trigmode_to_string(cls, trigmode: int) -> str:
        return cls.TRIG_MODE_MAP.get(trigmode, f"未知触发模式({trigmode})")


    @staticmethod
    def pack_req(*, cmd: int, opcode: int, reserved: int = 0) -> bytes:
        if not (0 <= cmd <= 0x1F):
            raise ValueError(f"cmd out of range (0..31): {cmd}")
        if not (0 <= opcode <= 0x01):
            raise ValueError(f"opcode out of range (0..1): {opcode}")
        if not (0 <= reserved <= 0x03):
            raise ValueError(f"reserved out of range (0..3): {reserved}")

        req = ((opcode & 0x01) << 7) | ((cmd & 0x1F) << 2) | (reserved & 0x03)
        return bytes([req])

    @staticmethod
    def parse_resp(resp_byte: int):
        b = resp_byte & 0xFF
        result   = (b >> 1) & 0x01
        var_cmd  = (b >> 2) & 0x1F
        opcode   = (b >> 7) & 0x01
        return result, var_cmd, opcode


