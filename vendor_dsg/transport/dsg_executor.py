import struct
import time

from ..protocol.dsg_protocol import DSGProtocol
from .dsg_udp import UDPThread

class DSGExecutorError(Exception):
    pass

class DSGExecutor:
    """
    设备命令执行器
    """
    def __init__(
        self,
        *,
        transport: UDPThread,
        protocol: DSGProtocol,
        timeout: float = 1.0,
        retry: int = 3,
        max_payload: int = 1024,
    ):
        self.transport = transport
        self.protocol = protocol
        self.timeout = timeout
        self.retry = retry
        self.max_payload = max_payload

    def _send_cmd(self, *, cmd: int, opcode: int, reserved: int = 0, payload: bytes = b''):
        """
        发送命令，并可附加 payload，校验 response
        """
        # 构造请求包
        req = self.protocol.pack_req(
            cmd=cmd,
            opcode=opcode,
            reserved=reserved,
        )

        # 如果有 payload，则追加
        if payload:
            req += payload

        # 发送
        self.transport.write(req)

        # 读取响应
        resp = self.transport.read(timeout=self.timeout)
        if not resp or len(resp) < 1:
            raise DSGExecutorError("Empty response")

        result, var_cmd, resp_opcode = self.protocol.parse_resp(resp[0])

        if var_cmd != cmd:
            raise DSGExecutorError(
                f"Response cmd mismatch (sent {cmd}, got {var_cmd})"
            )
        if resp_opcode != opcode:
            raise DSGExecutorError(
                f"Response opcode mismatch (sent {opcode}, got {resp_opcode})"
            )
        if result != self.protocol.RESULT_OK:
            raise DSGExecutorError(f"Command {cmd} failed")

    def _send_cmd_raw(self, *, cmd: int, opcode: int, reserved: int = 0):
        """
        发送 request_t 并返回完整 response
        """
        req = self.protocol.pack_req(
            cmd=cmd,
            opcode=opcode,
            reserved=reserved,
        )

        self.transport.write(req)

        resp = self.transport.read(timeout=self.timeout)
        if not resp:
            raise DSGExecutorError("No response received")

        return resp

    def _wait_ack(self):
        """
        等待 response_t ACK
        """
        resp = self.transport.read(timeout=self.timeout)
        if not resp or len(resp) < 1:
            raise DSGExecutorError("Empty ACK")

        result, _, _ = self.protocol.parse_resp(resp[0])
        if result != self.protocol.RESULT_OK:
            raise DSGExecutorError("ACK returned error")

    def _send_adm_stream(self, data: bytes):
        """
        使用 CMD_ADM 分包发送指令流
        """
        max_payload = self.max_payload - 2  # req + seq
        offset = 0
        seq = 0

        req_byte = self.protocol.pack_req(
            cmd=self.protocol.CMD_ADM,
            opcode=self.protocol.OPCODE_WRITE,
        )

        while offset < len(data):
            payload = data[offset: offset + max_payload]
            packet = (
                req_byte +
                struct.pack("<B", seq & 0xFF) +
                payload
            )

            for attempt in range(self.retry):
                self.transport.write(packet)
                try:
                    self._wait_ack()
                    break
                except DSGExecutorError:
                    if attempt == self.retry - 1:
                        raise

            offset += len(payload)
            seq += 1

    def _adm_batch(self, header: bytes, command_stream: bytes):
        """
        下发完整 ADM 
        """
        # 1. header
        for attempt in range(self.retry):
            self.transport.write(header)
            try:
                self._wait_ack()
                break
            except DSGExecutorError:
                if attempt == self.retry - 1:
                    raise DSGExecutorError("Header ACK failed")

        # 2. command stream
        self._send_adm_stream(command_stream)

 







 
