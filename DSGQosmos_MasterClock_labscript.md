# DSGQosmos_MasterClock_labscript

本驱动程序将 Qosmos DSG 设备作为 labscript 实验控制系统的**主时钟（Master Pseudoclock）**，同时保留作为下游被触发设备（Secondary Pseudoclock）的能力。DSG 的 32 路 TTL 数字输出通道既可用作下游设备的硬件触发源，也可作为普通数字输出使用。

---

### 构造思路

#### 程序组成

- `__init__.py` + `register_classes.py`：完成设备类注册，使 BLACS 能加载 `DSGQosmosMasterClock` 和 `DSGQosmosDigitalSignalGenerator`（兼容别名）设备页
- `labscript_devices.py`：设备核心编译层。定义主时钟类 `DSGQosmosMasterClock`（继承 `PseudoclockDevice`），内部构建 `Pseudoclock → ClockLine → IntermediateDevice（DigitalOut/Trigger bank）` 层次结构。负责：
  - 管理 32 路数字输出通道（`DigitalOut` / `Trigger`）的连接和去重
  - 通过 `generate_code()` 收集所有通道的 timeseries，编译为 DSG 的 `STREAM_PROGRAM`（`(reps: uint32, state: uint32)` 压缩格式）
  - 时间网格对齐验证、指令数限制检查
  - Master / Secondary 模式自动识别（根据 `is_master_pseudoclock`），写入对应 `trigger_source` 元数据
- `blacs_tabs.py`：提供 32 通道数字前面板手动控制（BLACS `DeviceTab`），每通道为独立 checkbox
- `blacs_workers.py`：BLACS `Worker` 实现，负责：
  - buffered 模式：从 HDF5 读取 `STREAM_PROGRAM`，初始化设备、下载指令流、配置触发的就绪/启动
  - manual 模式：diff 驱动的手动 overwrite——只修改用户勾选/取消的通道，不影响其余通道（读-改-写保护）
  - 实验完成判定（状态轮询 + 超时回退）与中止
- `sdk_adapter.py`：封装 vendor DSG SDK，提供设备初始化、流指令下发、软/硬触发、mix-mode 手动通道控制（`update_manual_channels` 读-改-写）、状态读取等统一接口
- `runviewer_parsers.py`：解析 HDF5 中的 `STREAM_PROGRAM`，还原每路 TTL 通道的时序 trace 供 runviewer 显示
- `vendor_dsg/`：设备 SDK 分层实现
  - `user/dsgQosmos.py`：用户接口层（设备类、时间轴、数字通道代理）
  - `api/dsg_deviceAPI.py`：指令接口层（封装协议命令为高层方法）
  - `protocol/dsg_protocol.py` + `device_data.py`：协议层（命令码定义、字节打包/解析、指令流生成）
  - `transport/dsg_executor.py` + `dsg_udp.py`：通信执行层（UDP 收发、命令执行、分包重传）

整体数据流：

```
实验脚本 API (start/wait/DigitalOut.go_high/Trigger.trigger …)
    │
    ▼
labscript_devices.py
    DSGQosmosMasterClock.generate_code()
    → 收集所有子设备 timeseries → bitfield → (reps, state) → STREAM_PROGRAM
    → 写入 HDF5 + 元数据 (trigger_source, dt, active_mask …)
    │
    ▼
blacs_workers.py
    transition_to_buffered() → 读取 HDF5 → adapter.program_stream()
    start_run()             → adapter.start_buffered()（master 模式）
    program_manual()        → adapter.update_manual_channels()（manual overwrite）
    │
    ▼
sdk_adapter.py
    → vendor_dsg.api.send_stream() / manual_channels() / send_strat_signal() …
    │
    ▼
vendor_dsg（协议编码 → UDP 下发 → DSG 硬件执行）
```

#### 触发逻辑

DSG 作为主时钟时，支持两种角色模式：

**Master Pseudoclock（主时钟模式）**：
- 实验脚本中调用 `start()` / `wait()` 时，labscript 自动将 DSG 标记为主时钟（`is_master_pseudoclock=True`）
- HDF5 元数据写入 `trigger_source='software'`
- `transition_to_buffered()` 下载 STREAM_PROGRAM 但不启动（仅发送 `send_setdone_signal` + `enable_channelsLED`）
- BLACS 在**所有设备就绪后**调用 `start_run()` → `adapter.start_buffered()` → `send_strat_signal(0)`（软件触发命令 CMD_SWR），DSG 开始输出实验序列
- DSG 的各通道输出可作为下游设备（ASG、DDS 等）的硬件触发源

**Secondary Pseudoclock（下游被触发模式）**：
- 在连接表中通过 `trigger_device=<上游设备输出>` 指定触发源
- 实验脚本中不调用 `wait()` → `is_master_pseudoclock=False`
- HDF5 元数据写入 `trigger_source='external'`
- `finalise_buffered()` 中调用 `send_hwstrat_signal(0)`（硬件触发就绪命令 CMD_RUN），DSG 等待上游硬件触发信号
- `start_run()` 中不发送软件触发

**下游设备自动触发调度**：
- 下游设备（ASG、DDS）通过 `trigger_device=<dsg通道对象>` 指定触发源时，其驱动程序自动在 DSG 对应通道上调用 `go_high(t)` / `go_low(t + duration)` 或 `trigger(t, duration)`
- DSG 的 `generate_code()` 遍历 `dsg.outputs.child_devices`，自动将所有通道事件编译进 `STREAM_PROGRAM`
- 用户无需在实验脚本中手动编写触发命令

**手动模式（Mix Mode）**：
- BLACS GUI 中手动操控时，使用 `update_manual_channels(high_mask, low_mask)` 方法
- 采用读-改-写保护：先从硬件同步当前 `manual_en`/`manual_val`，只修改用户变更的通道，其余通道保持原有状态
- 底层使用 DSG 硬件的 `manual_channels(manual_en, manual_val)` 命令（CMD_MAN 双 uint32 变体），只将指定通道置于手动模式，其他通道继续执行 stream program
- 这意味着**即使 DSG 正在按实验脚本输出，也可以在 BLACS GUI 中 overwrite 特定通道**，不影响其余通道的流模式输出

---

### 使用说明

#### 连接表 connection_table

在 labscript 的连接表 `connection_table.py` 中添加 Qosmos DSG 主时钟设备，需参考以下规范：

**作为 Master Pseudoclock（主时钟）使用：**

```python
# labscript 运行的脚本中不能出现中文注释，以下注释仅作说明

from labscript import DigitalOut, Trigger
from user_devices.DSGQosmos_MasterClock_labscript.labscript_devices import (
    DSGQosmosMasterClock,
)

# ============================================================
# 1. 实例化 DSG 主时钟（不需要 trigger_device，即为 master）
# ============================================================
dsg = DSGQosmosMasterClock(
    name='dsg',
    ip='192.168.1.10',      # DSG 设备 IP
    port=5001,              # DSG UDP 端口（默认 5001）
    local_port=0,           # 本地监听端口（0 = 自动分配）
    dt=10e-9,               # 时钟分辨率（默认 10 ns）
    use_external_clk=False, # 是否使用外部时钟源
    trig_mode=0,            # 触发模式（0:上升沿, 1:下降沿, 2:高电平, 3:低电平, 4:脉冲）
    led_enable=True,        # 是否启用通道 LED 指示灯
    exec_mode=1,            # 执行模式（1:循环执行）
    trigger_duration=10e-6, # 触发脉冲最小宽度（10 μs）
    max_instructions=65535, # 最大指令数
)

# ============================================================
# 2. 创建 DSG 的输出通道
# ============================================================

# 方式 A：显式创建（推荐，符合 labscript 连接表规范）
# 用作下游设备触发源的通道 —— 推荐使用 Trigger 类
trig_asg = Trigger(
    name='trig_asg',
    parent_device=dsg.outputs,
    connection='do0',               # 物理通道 do0
    trigger_edge_type='rising',     # 上升沿触发
)
trig_dds = Trigger(
    name='trig_dds',
    parent_device=dsg.outputs,
    connection='do1',               # 物理通道 do1
    trigger_edge_type='rising',
)

# 普通 TTL 输出通道 —— 使用 DigitalOut
ttl_spare = DigitalOut(
    name='ttl_spare',
    parent_device=dsg.outputs,
    connection='do2',               # 物理通道 do2
)

# 方式 B：便捷预创建（适合简单脚本，不需要显式创建每个通道对象）
# dsg = DSGQosmosMasterClock(
#     name='dsg', precreate_channels=True, ...
# )
# 预创建后可直接使用 dsg.CH0 ~ dsg.CH31 或 dsg.do0 ~ dsg.do31
# 注意：不能与方式 A 在同一物理通道上混用

# ============================================================
# 3. 连接下游设备到 DSG 的触发通道
# ============================================================
from user_devices.ASGQosmos.labscript_devices import ASGQosmosSignalGenerator
from user_devices.DDSQosmos_labscript.labscript_devices import (
    DDSQosmosDDS,
    DDSQosmosSignalGenerator,
)

asg = ASGQosmosSignalGenerator(
    name='asg',
    trigger_device=trig_asg,
    trigger_connection='external_trigger',
    connection_mode='udp',
    local_ip='192.168.1.102',
    target_ip='192.168.1.103',
)

dds = DDSQosmosSignalGenerator(
    name='dds',
    connection_mode='udp',
    local_ip='192.168.1.102',
    target_ip='192.168.1.104',
    buffered_trigger_source='external',
)

dds_ch1 = DDSQosmosDDS(
    name='dds_ch1',
    parent_device=dds,
    channel=1,
    trigger_device=dsg.outputs,     # 对于 DDS，直接传 dsg.outputs
    trigger_connection='do1',       # 和通道名即可，不需要先实例化 Trigger
)
```

**作为 Secondary Pseudoclock（下游被触发设备）使用：**

```python
# DSG 作为被触发设备（保留兼容原来的使用方法）
dsg = DSGQosmosMasterClock(
    name='dsg',
    trigger_device=master_pseudoclock.outputs,  # 上游触发源
    trigger_connection='some_trigger_channel',  # 上游触发端口
    ip='192.168.1.10',
    port=5001,
)

# DSG 通道仍可正常使用
ttl = DigitalOut(name='ttl', parent_device=dsg.outputs, connection='do0')
```

#### 实验脚本

**作为 Master Pseudoclock 时的实验脚本：**

```python
import runpy
from pathlib import Path
from labscript import *

# 引入 connection_table
CONNECTION_TABLE_PATH = Path(r'C:\Users\Yazi02\labscript-suite\userlib\labscriptlib\Yazi\connection_table.py')

if not CONNECTION_TABLE_PATH.is_file():
    raise RuntimeError(f'Cannot find connection_table.py: {CONNECTION_TABLE_PATH}')

connection_table_symbols = runpy.run_path(str(CONNECTION_TABLE_PATH))

for _name, _value in connection_table_symbols.items():
    if _name.startswith('__'):
        continue
    globals()[_name] = _value


start()
# start() 标志实验开始，DSG 作为主时钟，将在所有设备就绪后由 BLACS 软件触发启动

t = 0.0

# ----- 普通 TTL 输出 -----
ttl_spare.go_low(t)

t += 0.5
ttl_spare.go_high(t)     # 在 0.5 s 拉高

t += 1.0
ttl_spare.go_low(t)      # 在 1.5 s 拉低

t += 0.5
ttl_spare.pulse(t, duration=10*us)  # 在 2.0 s 输出 10 μs 脉冲

# ----- 下游设备自动触发 -----
# ASG 和 DDS 的输出命令会自动在对应的 DSG 触发通道上生成触发脉冲
# 用户不需要手动写 trig_asg.go_high() 等命令

trigger_t = 1 * ms
asg.SetChaStart(channel=[1], t=trigger_t)

dds_ch1.setfreq(trigger_t, 20e6)
dds_ch1.setamp(trigger_t, 0.25)
dds_ch1.setphase(trigger_t, 0.0)

# ----- 使用预创建通道（如果 precreate_channels=True）-----
# dsg.CH3.go_high(0.5 * ms)
# dsg.CH3.pulse(1.0 * ms, 100 * us)

t += 5.0
stop(t)
# stop() 标志实验结束
```

**作为 Secondary Pseudoclock 时的实验脚本：**

```python
# DSG 不作为主时钟时，由上游设备触发
# 实验脚本中不需要对 DSG 调用 wait()

start()  # 上游主时钟的 start

t = 0.0
ttl.go_high(t + 0.5)
ttl.go_low(t + 1.5)

stop(t + 3.0)
```

#### BLACS GUI 手动控制

1. 在 BLACS 界面中选中 DSG 设备页
2. 点击 "Manual" 进入手动模式，显示 32 个通道的 checkbox
3. 勾选通道 → 对应通道立即输出高电平（手动 overwrite）
4. 取消勾选 → 对应通道拉低
5. **只修改被操作的通道**，其他通道保持原有状态（即使正在按实验脚本输出也不受影响）
6. 点击 "Buffered" 返回流模式，所有手动控制释放，通道恢复自动模式

#### 注意事项

- DSG 设备硬件连接参考 Qosmos DSG 操作手册；设备默认 IP 为 `192.168.1.10`，UDP 端口 `5001`
- 如果出现连接不上的情况，可以尝试在连好网线后重启 DSG，等待一段时间后再尝试
- DSG 作为主时钟时，**必须**在实验脚本中调用 `start()` 和 `stop()`，确保 labscript 正确识别主时钟身份
- 推荐使用 `Trigger` 类（而非 `DigitalOut`）创建用作下游触发源的通道，以符合 labscript 规范
- `Trigger` 和 `DigitalOut` 两种创建方式**不能在同一物理通道上混用**（例如不能同时将 do0 创建为 Trigger 和 DigitalOut）
- `precreate_channels=True` 会预创建全部 32 个 `Trigger` 通道（`dsg.CH0`~`dsg.CH31`），适合简单脚本；显式创建方式适合需要精确控制哪些通道被使用的场景
- 若 `stop(t)` 设置过早，在波形还没有输出完实验就结束了，DSG 会在结束时根据当前状态输出终态电平
- Qosmos DSG 的时间分辨率为 10 ns（`dt=10e-9`），所有事件时间必须为 10 ns 的整数倍
- DDS 设备连接 DSG 触发时，无需先实例化触发通道对象，直接将 `dsg.outputs` 和 `connection='doN'` 传入 DDS 通道的 `trigger_device` 和 `trigger_connection` 即可
- ASG 设备连接 DSG 触发时，需要先实例化触发通道（`Trigger` 或 `DigitalOut`），再传入 ASG 的 `trigger_device`
