import struct
from typing import List, Tuple, Dict

from .dsg_protocol import DSGProtocol


COMMAND_WORD_BYTES = 8
HEADER_BYTES = 7

class StreamBytesGenerator:
    """
    将压缩波形数据转换为设备可下发的字节流
    """

    @staticmethod
    def prepare_device_data_from_compressed(
        start_address: int,
        compressed: List[Tuple[int, int]],
    ) -> Tuple[bytes, bytes]:
        """
        生成发送给设备的两段数据：

        1) Header（7 字节）:
            - 1 byte : request_t (opcode=WRITE, cmd=CMD_ADM)
            - 4 bytes: start_address (uint32, little-endian)
            - 2 bytes: group_count   (uint16, little-endian)

        2) Command stream:
            - 每条命令 8 字节: duration_ticks(4B) + state_32bit(4B)
            - 设备要求发送顺序：高4字节（state）+低4字节（duration）

        参数:
            start_address: 写入设备的起始地址
            compressed: [(duration_ticks, state_32bit), ...]

        返回:
            header_bytes, command_bytes
        """

        # ---------- Header ----------
        reserved = 0
        request_byte = DSGProtocol.pack_req(
            cmd=DSGProtocol.CMD_ADM,
            opcode=DSGProtocol.OPCODE_WRITE,
            reserved=reserved
        )
        # for i, (duration_ticks, state) in enumerate(compressed):
        #     print(f"[CMD {i:02d}] duration={duration_ticks}, state=0x{state:08X}")
        group_count = len(compressed)
        header = bytearray(HEADER_BYTES)
        header[0] = request_byte[0]
        header[1:5] = struct.pack("<I", start_address & 0xFFFFFFFF)
        header[5:7] = struct.pack("<H", group_count & 0xFFFF)

        # ---------- Command stream ----------
        command_bytes = bytearray(group_count * COMMAND_WORD_BYTES)
        offset = 0

        for duration_ticks, state in compressed:
            # duration_ticks 和 state 各 4 字节 little-endian
            low4 = struct.pack("<I", state & 0xFFFFFFFF)
            high4 = struct.pack("<I", duration_ticks & 0xFFFFFFFF)

            # 设备要求：先高 4 字节（state），再低 4 字节（duration）
            command_bytes[offset:offset + 4] = high4
            command_bytes[offset + 4:offset + 8] = low4
            offset += COMMAND_WORD_BYTES

        return bytes(header), bytes(command_bytes)

 
