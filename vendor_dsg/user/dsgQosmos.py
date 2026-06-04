from typing import List, Tuple, Dict
from collections import defaultdict
from zlib import DEF_BUF_SIZE

from ..transport.dsg_udp import UDPThread
from ..protocol.dsg_protocol import DSGProtocol, ChannelMode
from ..protocol.device_data import StreamBytesGenerator
from ..transport.dsg_executor import DSGExecutor
from ..api.dsg_deviceAPI import DSGDeviceAPI

class Timeline:
    """全局时间轴：记录事件"""
    def __init__(self):
        self._events: Dict["DigitalOut", List[Tuple[float, int]]] = defaultdict(list)
        self._frozen = False

    def add_event(self, signal, t, value):
        if self._frozen:
            raise RuntimeError("Timeline is frozen")
        if t < 0:
            raise ValueError("t must be >= 0")
        if value not in (0, 1):
            raise ValueError("Digital value must be 0 or 1")
        self._events[signal].append((float(t), int(value)))

    def get_events(self):
        return dict(self._events)

    def freeze(self):
        self._frozen = True

    def clear(self):
        self._events.clear()
        self._frozen = False

class DigitalOut:
    """
    用户可调用数字输出
    绑定设备实例和固定通道号
    """
    def __init__(self, device: "dsgQosmos", channel: int, alias: str):
        if not 0 <= channel < 32:
            raise ValueError("Channel must be 0..31")
        self.device = device
        self.channel = channel
        self.alias = alias

        # 自动注册到设备
        device._register_digitalout(channel, self)

    # ===== 用户 API =====
    def high(self, t: float):
        self.device.timeline.add_event(self, t, 1)
        return self

    def low(self, t: float):
        self.device.timeline.add_event(self, t, 0)
        return self

    def set(self, t: float, value: int):
        self.device.timeline.add_event(self, t, value)
        return self

    def pulse(self, t0: float, width: float):
        if width <= 0:
            raise ValueError("pulse width must be > 0")
        self.high(t0)
        self.low(t0 + width)
        return self

    def events(self):
        return self.device.timeline.get_events().get(self, [])

    def __repr__(self):
        return f"<DigitalOut alias='{self.alias}' channel=do{self.channel}>"


class dsgQosmos:
    """
    DSG Qosmos 设备类
    """
    # =========================================================
    # 初始化
    # =========================================================
    def __init__(self, name: str, ip: str, port: int, local_port: int = 0):
        self.name = name
        self.ip = ip
        self.port = port
        self.timeline = Timeline()
        self.channels: Dict[int, DigitalOut] = {}  # do0..do31

        # 1. 创建 UDP 通信线程
        self.udp = UDPThread(local_port=local_port, remote_ip=ip, remote_port=port)
        self.udp.open()

        # 2. 创建协议和执行器
        self.protocol = DSGProtocol()
        self.instructionGen = StreamBytesGenerator()
        self.executor = DSGExecutor(transport=self.udp, protocol=self.protocol)

        # 3. 创建设备 API 封装
        self.api = DSGDeviceAPI(executor=self.executor)

        # 4. 初始化 32 个 DigitalOut 通道
        for ch in range(32):
            alias = f"do{ch}"
            dout = DigitalOut(device=self, channel=ch, alias=alias)
            self.channels[ch] = dout
            setattr(self, alias, dout)

    # =========================================================
    # DigitalOut 注册 & 管理
    # =========================================================
    # ===== DigitalOut 注册 =====
    def _register_digitalout(self, channel: int, dout: DigitalOut):
        if channel in self.channels:
            raise ValueError(f"Channel do{channel} already registered")
        self.channels[channel] = dout

    # ===== 调试/查看事件 =====
    def show_events(self):

        print(f"=== {self.name} events ===")

        for ch, dout in sorted(self.channels.items()):

            evts = dout.events()
            if not evts:
                continue

            print(f"\n{dout.alias} (do{ch})")

            evts = sorted(evts, key=lambda x: x[0])

            pulse_id = 1

            for t, v in evts:

                if v == 1:  # 只显示 HIGH
                    ts = self._format_time(t)
                    print(f"  pulse {pulse_id:<2} @ {ts}")
                    pulse_id += 1

    # ===== 重命名 =====
    def rename_channel(self, old_alias: str, new_alias: str):
        """
        重命名数字通道 alias，并重新绑定设备属性。

        """
        # ----------- 合法性检查 -----------
        if not hasattr(self, old_alias):
            raise ValueError(f"No such channel alias: {old_alias}")

        if hasattr(self, new_alias):
            raise ValueError(f"Alias '{new_alias}' already exists on device")

        # ----------- 执行重命名 -----------
        dout = getattr(self, old_alias)

        # 修改 DigitalOut 内部 alias 字段
        dout.alias = new_alias

        # 删除旧属性
        delattr(self, old_alias)

        # 绑定新属性名
        setattr(self, new_alias, dout)

        return dout

    # =========================================================
    # 内部方法
    # =========================================================
    def _format_time(self, t: float) -> str:
        """自动时间单位缩放，用于系统显示"""
        if t == 0:
            return "0 s"

        abs_t = abs(t)

        if abs_t >= 1:
            return f"{t:.3g} s"
        elif abs_t >= 1e-3:
            return f"{t*1e3:.3g} ms"
        elif abs_t >= 1e-6:
            return f"{t*1e6:.3g} µs"
        else:
            return f"{t*1e9:.3g} ns"
        
    def _parse_channel_input(self, channels: str) -> int:
        """
        将用户输入的通道列表或范围字符串转换为 32 位掩码

        支持格式:
            "1,3,5" -> 通道 1,3,5
            "0-4"   -> 通道 0,1,2,3,4
            "0,2-4,7" -> 通道 0,2,3,4,7

        返回:
            int: 32 位通道掩码
        """
        mask = 0
        parts = channels.split(",")
        for part in parts:
            part = part.strip()
            if "-" in part:  # 范围
                start, end = part.split("-")
                start = int(start)
                end = int(end)
                if not (0 <= start <= end <= 31):
                    raise ValueError(f"Invalid channel range: {part}")
                for ch in range(start, end + 1):
                    mask |= (1 << ch)
            else:  # 单个通道
                ch = int(part)
                if not (0 <= ch <= 31):
                    raise ValueError(f"Channel out of range: {ch}")
                mask |= (1 << ch)
        return mask
    
    def _sync_manual_state(self):
        """
        从设备同步当前 manual_en / manual_val
        """
        self._manual_en, self._manual_val = self.api.get_channels_status()

    def _decode_channels_status(self, manual_en: int, manual_val: int) -> Dict[int, ChannelMode]:
        """
        将 manual_en / manual_val 解析为每个通道的状态
        """
        result = {}

        for ch in range(32):
            en = (manual_en >> ch) & 0x1
            val = (manual_val >> ch) & 0x1

            if en == 0:
                result[ch] = ChannelMode.AUTO
            else:
                result[ch] = ChannelMode.MANUAL_HIGH if val else ChannelMode.MANUAL_LOW

        return result

    def _normalize_pulse_start_events(self, events):
        """将只定义脉冲起点（高电平事件）的通道自动补齐低电平终点

        规则：当某通道全部事件为高电平且至少有两个事件时，
        在每对相邻起点中间插入低电平事件，作为前一脉冲的结束时间。
        例如 [t0, t1, t2] -> [t0 high, (t0+t1)/2 low, t1 high, (t1+t2)/2 low, t2 high]

        对于含显式低电平的事件保持不变（以优先用户明确终点）。
        """
        normalized = {}

        for signal, evts in events.items():

            if not evts:
                normalized[signal] = []
                continue

            evts = sorted(evts, key=lambda x: x[0])

            merged = []

            for i, (t, v) in enumerate(evts):

                merged.append((t, v))

                # 如果是 high
                if v == 1:

                    # 最后一个事件
                    if i + 1 >= len(evts):
                        merged.append((t + 10e-6, 0))
                        continue

                    next_t, next_v = evts[i + 1]

                    # high -> high   自动补低
                    if next_v == 1:
                        low_t = (t + next_t) / 2
                        merged.append((low_t, 0))

                    # high -> low    用户指定终点，不处理

            normalized[signal] = merged

        return normalized

    def _build_compressed_waveform(self,
        timeline: Timeline,
        dt: float,
        channel_map: Dict[int, int],
    ) -> List[Tuple[int, int]]:
        """
        - 全局时间轴
        - 每通道 timeseries
        - 位域 bit_sets
        - reps = diff(times) / dt
        """

        # ---------- Step 1: 收集所有事件，构建全局时间轴 ----------
        events = self._normalize_pulse_start_events(timeline.get_events())
        if not events:
            return []

        times_set = set()
        for evts in events.values():
            for t, _ in evts:
                times_set.add(float(t))

        times = sorted(times_set)
        if not times:
            return []

        # ---------- Step 2: 为每个通道生成 timeseries ----------
        # state[channel][i] = 0/1
        num_steps = len(times)
        channel_states: dict[int, list[int]] = {}

        for signal, evts in events.items():
            ch = channel_map[signal.channel]

            # 该通道的事件按时间排序
            evts = sorted(evts, key=lambda x: x[0])

            series = []
            cur = 0
            evt_idx = 0

            for t in times:
                while evt_idx < len(evts) and evts[evt_idx][0] <= t:
                    cur = evts[evt_idx][1]
                    evt_idx += 1
                series.append(cur)

            channel_states[ch] = series

        # ---------- Step 3: 合并为 32-bit bit_sets ----------
        bit_sets: list[int] = []

        for i in range(num_steps):
            bits = 0
            for ch, series in channel_states.items():
                if series[i]:
                    bits |= (1 << ch)
            bit_sets.append(bits)

        # ---------- Step 4: 生成 reps（duration ticks） ----------
        reps: list[int] = []
        for t0, t1 in zip(times[:-1], times[1:]):
            reps.append(int(round((t1 - t0) / dt)))

        # ---------- Step 5: 合并输出 ----------
        compressed = list(zip(reps, bit_sets))
        return compressed

    # =========================================================
    #  读取设备信息 
    # =========================================================
    # 获取版本信息
    def get_version(self) -> str:
        return self.api.get_version()

    # 获取序列号
    def get_sn(self) -> str:
        return self.api.get_sn()

    # 获取通道状态
    def get_channels_status(self) -> str:
        """
        查询并返回通道状态（字符串）
        """
        manual_en, manual_val = self.api.get_channels_status()
        status = self._decode_channels_status(manual_en, manual_val)

        groups = {
            ChannelMode.MANUAL_HIGH: [],
            ChannelMode.MANUAL_LOW: [],
            ChannelMode.AUTO: [],
        }

        for ch, mode in status.items():
            groups[mode].append(ch)

        def fmt(chs):
            if not chs:
                return "-"
            chs = sorted(chs)
            ranges = []
            start = prev = chs[0]
            for ch in chs[1:]:
                if ch == prev + 1:
                    prev = ch
                else:
                    ranges.append((start, prev))
                    start = prev = ch
            ranges.append((start, prev))
            return ",".join(
                f"{a}" if a == b else f"{a}-{b}"
                for a, b in ranges
            )

        lines = []
        for mode in (ChannelMode.MANUAL_HIGH,
                    ChannelMode.MANUAL_LOW,
                    ChannelMode.AUTO):
            lines.append(f"{mode.name:12}: {fmt(groups[mode])}")

        return "\n".join(lines)
    
    # 获取时钟状态    
    def get_clk_status(self) -> str:
        """
        查询并返回时钟状态（字符串）
        """
        clk_source, outclk_stable = self.api.get_clk_status()

        # 时钟源解释
        if clk_source == 0:
            clk_src_str = "INTERNAL"
        elif clk_source == 1:
            clk_src_str = "EXTERNAL"
        else:
            clk_src_str = f"UNKNOWN({clk_source})"

        # 外部时钟稳定性解释
        if outclk_stable == 0:
            stable_str = "UNSTABLE"
        elif outclk_stable == 1:
            stable_str = "STABLE"
        else:
            stable_str = f"UNKNOWN({outclk_stable})"

        lines = [
            f"{'Clock Source':12}: {clk_src_str}",
            f"{'Ext Clock':12}: {stable_str}",
        ]

        return "\n".join(lines)

    # 获取触发模式信息
    def get_trig_mode_text(self) -> str:
        """
        获取当前设备触发模式（可读文本）
        """
        trigmode = self.api.get_trig_mode()
        # 将字节串转换为整数
        trigmode_bytes = int.from_bytes(trigmode, byteorder='big')
        return self.protocol.trigmode_to_string(trigmode_bytes)    

    # 获取状态信息
    def get_status_text(self) -> str:
        """
        获取当前设备状态（可读文本）
        """
        status = self.api.get_status()
        # 将字节串转换为整数
        status_bytes = int.from_bytes(status, byteorder='big')
        return self.protocol.status_to_string(status_bytes)    
    
    # =========================================================
    # 触发、输出模式、LED、执行策略控制
    # =========================================================
    # 重启设备
    def restart_Device(self, reserved: int = 0):
        self.api.send_restart_signal(reserved)

    #打开LED指示灯
    def enable_channelsLED(self, channels: str, reserved: int = 0b00):
        mask = self._parse_channel_input(channels)
        self.api.enable_channelsLED(mask,reserved) 

    # 手动模式输入
    def set_channel_high(self, channels: str, reserved: int = 0b11):
        """
        用户调用：拉高指定通道（手动模式）
        channels: str, 通道字符串，例如 "0,2-4,7"
        """
        mask = self._parse_channel_input(channels)
        self.api.enable_channelsLED(mask,reserved) 
        self.api.switch_manual_mode(mask, reserved)
        
    # 退出手动模式，返回流模式
    def exit_manual_mode(self, reserved: int = 0b00):
        self.api.enable_channelsLED(
            LED_mask=0x00000000,
            reserved=reserved,
        )
        channel_mask = 0x00000000  # 切换手动模式时，通道输出全0
        self.api.switch_manual_mode(channel_mask, reserved)

    # 切换到流模式    
    def switch_to_stream_mode(self, reserved: int = 0b00):
        # 调用 exit_manual_mode
        self.exit_manual_mode(reserved)

    # 流模式下暂停输出
    def interrupt_output(self, reserved: int = 0b11):
        self.api.send_operating_status_signal(reserved)

    # 流模式下继续输出
    def continue_output(self, reserved: int = 0b00):
        self.api.send_operating_status_signal(reserved)

    # 切换触发模式
    def switch_trigmode(self, mode: int=0, reserved: int = 0):
        self.api.send_trigmode_signal(mode, reserved)

    # 切换外部时钟
    def switch_extclk(self, reserved: int = 0b11):
        self.api.switch_extclk(reserved)

    # 切换内部时钟
    def switch_intclk(self, reserved: int = 0b00):
        self.api.switch_intclk(reserved)

    # 启用LED指示灯
    def enable_led(self, reserved: int = 0b11):
        self.api.enable_led(reserved)

    # 禁用LED指示灯
    def disable_led(self, reserved: int = 0b00):
        self.api.disable_led(reserved)

    # 设置指令重复执行模式
    def exec_strategy(self, reserved: int = 0b01):
        self.api.send_operating_mode_signal(reserved)

    # 切换到手动模式,全通道手动输出
    def switch_to_manual_mode(self, reserved: int = 0b11):
        self.api.enable_channelsLED(
            LED_mask=0xFFFFFFFFF,
            reserved=reserved,
        )
        channel_mask = 0x00000000  # 切换手动模式时，通道输出全0
        self.api.switch_manual_mode(channel_mask, reserved)

    # =========================================================
    # 混合模式控制方法
    # =========================================================
    # 设置多通道手动输出
    def force_set(self, high_channels: str = "", low_channels: str = ""):
        """
        设置多通道手动输出（拉高 / 拉低）
        （读-改-写保护，不覆盖已有状态）
        """
        # 同步当前设备状态
        self._sync_manual_state()
        # 解析通道掩码
        high_mask = self._parse_channel_input(high_channels) if high_channels else 0
        low_mask  = self._parse_channel_input(low_channels)  if low_channels  else 0
        # 冲突检查
        conflict = high_mask & low_mask
        if conflict:
            raise ValueError(
                f"Channel conflict: channels {conflict:#010x} "
                f"are set in both high and low"
            )
        # 所有涉及的通道都进入手动模式
        affect_mask = high_mask | low_mask
        self._manual_en |= affect_mask
        # 拉高通道
        self._manual_val |= high_mask
        # 拉低通道
        self._manual_val &= ~low_mask
        # 写回设备
        self.api.manual_channels(self._manual_en, self._manual_val)

    # 设置多通道手动输出归零    
    def force_set_release(self):
        """
        释放所有手动通道，恢复为全自动模式
        manual_en / manual_val 全部清零
        """
        # 明确置零
        self._manual_en = 0
        self._manual_val = 0

        # 写回设备
        self.api.manual_channels(self._manual_en, self._manual_val)

    # =========================================================
    #  指令流下发
    # =========================================================
    def send_streambytes(self, dt: float = 1e-8, start_address: int = 0):
        
        compressed =  self._build_compressed_waveform(
            timeline=self.timeline,
            dt=dt,
            # channel_map={f"do{ch}": ch for ch in range(32)}
            channel_map={ch: ch for ch in range(32)}
        )
        if not compressed:
            print("No events to send")
            return

        header, command_bytes =  self.instructionGen.prepare_device_data_from_compressed(
            start_address=start_address,
            compressed=compressed
        )
        self.api.send_stream(header, command_bytes)

    # =========================================================
    # 控制信号
    # =========================================================
    # 发送清除信号  
    def send_cls_signal(self, reserved: int = 0):
        self.api.send_cls_signal(reserved)

    # 发送“设置完成”信号
    def set_done(self, reserved: int = 0):
        """
        发送“设置完成”信号，并同时发送通道使能掩码。
        通道是否使能取决于用户脚本中是否对该通道定义了波形。
        """
        # ---------- 1. 构建通道掩码 ----------
        # 如果该通道在 timeline 中有事件，则使能
        mask = 0
        for ch, dout in self.channels.items():
            events = dout.events()
            if events:  # 只要该通道有事件，就置1
                mask |= (1 << ch)
            
        # ---------- 2. 发送“设置完成”信号 ----------
        self.api.send_setdone_signal(reserved)

        # ---------- 3. 发送通道使能 ----------
        # 使用 CMD_CHx 命令发送掩码
        self.api.enable_channelsLED(
            LED_mask=mask,
            reserved=reserved,
        )

    # 发送硬件触发信号
    def send_hwstart_signal(self, reserved: int = 0):
        self.api.send_hwstrat_signal(reserved)

    # 发送软件触发信号
    def send_softstart_signal(self, reserved: int = 0):
        self.api.send_strat_signal(reserved)

    # 发送中断信号
    def send_abort_signal(self, reserved: int = 0):
        self.api.send_abt_signal(reserved)

    # 关闭网络 
    def disconnect(self):
        self.udp.close()

    # =========================================================
    # 快捷配置方法（结构化信息 + 打印 + 快捷配置设备）
    # =========================================================
    # 获取所有可获取的信息
    def get_all_info(self) -> Dict:
        """
        获取设备当前所有可获取的信息（结构化）
        适合调试、日志、GUI 使用
        """
        info = {}

        # ===== 基础信息 =====
        info["device"] = {
            "name": self.name,
            "ip": self.ip,
            "port": self.port,
            "version": self.get_version(),
            "sn": self.get_sn(),
        }

        # ===== 设备状态 =====
        info["status"] = {
            "trig_mode": self.get_trig_mode_text(),
            "device_status": self.get_status_text(),
        }

        # ===== 时钟状态 =====
        clk_source, outclk_stable = self.api.get_clk_status()

        info["clock"] = {
            "source": "INTERNAL" if clk_source == 0 else "EXTERNAL",
            "source_raw": clk_source,
            "external_stable": bool(outclk_stable),
        }

        # ===== 通道状态 =====
        manual_en, manual_val = self.api.get_channels_status()
        decoded = self._decode_channels_status(manual_en, manual_val)

        info["channels"] = {
            ch: decoded[ch].name for ch in range(32)
        }

        # ===== Timeline 状态 =====
        timeline_info = {}
        for ch, dout in self.channels.items():
            evts = dout.events()
            if evts:
                timeline_info[ch] = {
                    "alias": dout.alias,
                    "event_count": len(evts),
                    "events": evts,
                }

        info["timeline"] = {
            "has_events": bool(timeline_info),
            "channels": timeline_info,
        }

        return info
    
    # 一键打印所有信息
    def show_all_info(self):
        info = self.get_all_info()

        print("=== Device Info ===")
        for k, v in info["device"].items():
            print(f"{k:12}: {v}")

        print("\n=== Status ===")
        for k, v in info["status"].items():
            print(f"{k:12}: {v}")

        # ===== Clock =====
        print("\n=== Clock ===")
        clk = info["clock"]
        print(f"{'source':12}: {clk['source']}")
        if clk["source"] == "EXTERNAL":
            print(f"{'stable':12}: {clk['external_stable']}")

        print("\n=== Channels ===")
        print(self.get_channels_status())

        print("\n=== Timeline ===")
        if not info["timeline"]["has_events"]:
            print("No events defined")
        else:
            for ch, d in info["timeline"]["channels"].items():
                print(f"do{ch:02d} ({d['alias']}): {d['event_count']} events")

    #一键设备初始化配置
    def init_device(
        self,
        *,
        use_external_clk: bool = True,
        trig_mode: int = 0,
        led_enable: bool = True,
        exec_mode: int = 1,
        clear_timeline: bool = True,
        manual_mode: bool = False,
    ):
        """
        一键初始化设备到默认状态
        """
        # 1. 停止当前输出 / 中断
        self.send_abort_signal()

        # 2. 切换到流模式（退出手动）
        self.exit_manual_mode()

        # 3. 时钟源
        if use_external_clk:
            self.switch_extclk()
        else:
            self.switch_intclk()

        # 4. 触发模式
        self.switch_trigmode(trig_mode)

        # 5. LED
        if led_enable:
            self.enable_led(0b11)
        else:
            self.disable_led(0b00)

        # 6. 执行策略
        if exec_mode :
            self.exec_strategy(exec_mode)

        # 7. 手动模式
        if manual_mode:
            self.switch_to_manual_mode()
        else:
            self.exit_manual_mode()

        # 8. 清空本地 timeline
        if clear_timeline:
            self.timeline.clear()

        # 9. 清 CLS（设备侧）
        self.send_cls_signal()
        
    # 更改设备 IP 地址  
    def set_ip(self, ip: str, mask: str, gw: str):

        self.api.set_ip(ip, mask, gw)
        self.api.use_userconfig_ip()

    # 使用默认 IP 地址 
    def use_defconfig_ip(self) -> None:
        self.api.use_defaultconfig_ip()
        
