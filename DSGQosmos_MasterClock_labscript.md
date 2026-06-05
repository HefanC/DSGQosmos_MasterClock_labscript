# DSGQosmos_MasterClock_labscript

本驱动程序将 Qosmos DSG 设备作为 labscript 实验控制系统的**主时钟（Master Pseudoclock）**，同时保留作为下游被触发设备（Secondary Pseudoclock）的能力。DSG 的 32 路 TTL 数字输出通道既可用作下游设备的硬件触发源，也可作为普通数字输出使用。

---

## 构造思路

### 程序组成

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

### 触发逻辑

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

## 使用说明

### 创建通道

DSG 除了实例化设备整体外，还需要实例化每一个通道；每个通道支持实例化为 `DigitalOut` 或 `Trigger` 类，二者区别在于：`Trigger` = `DigitalOut` + 触发能力；详细区别如下：

| 能力                                               |  `DigitalOut`  |       `Trigger`       |
| -------------------------------------------------- | :------------: | :-------------------: |
| `go_high(t)` / `go_low(t)`                           |       ✅        |       ✅（继承）       |
| `trigger(t, duration)` — 专用的触发脉冲方法        |       ❌        |           ✅           |
| `trigger_edge_type` — 边沿类型属性                 |       ❌        |           ✅           |
| `allowed_children`                                 | `[]`（空列表） | `[TriggerableDevice]` |
| 可作为下游 `PseudoclockDevice` 的 `trigger_device` |       ❌        |           ✅           |
| 可作为普通 TTL 输出                                |       ✅        |           ✅           |

最关键的差异是 `allowed_children`；在 labscript 框架中，当下游 `PseudoclockDevice` 连接到一个触发通道时，
框架内部会调用 `trigger_device.add_device(downstream_device)`，此调用检查 `trigger_device.allowed_children`，`DigitalOut` 无 `allowed_children`，下游无法注册

#### 通道创建方式

DSG 主时钟驱动提供**两种互斥**的通道创建方式；用户必须在连接表中选定一种，不能在同一个物理通道上混用

**方式 A：显式创建**

在连接表中显式创建 `DigitalOut` 或 `Trigger` 对象，挂在 `dsg.outputs` 下；`connection` 可以写 `CHX` 或 `doX`（X 为硬件通道号）

```python
trig = Trigger(name='trig', parent_device=dsg.outputs, connection='CH0',
               trigger_edge_type='rising')
ttl  = DigitalOut(name='ttl', parent_device=dsg.outputs, connection='do3')
```

- 用户完全控制哪些通道被创建、什么类型（`Trigger` vs `DigitalOut`）
- 未创建的通道不占用 `dsg.outputs.child_devices`，不会出现在 `generate_code()` 的遍历中
- 符合 labscript 连接表"显式声明所有设备"的规范

**方式 B：`precreate_channels=True`**

```python
dsg = DSGQosmosMasterClock(
    name='dsg', precreate_channels=True, ...
)
```

开启后，驱动在 `__init__` 中自动为全部 32 个通道（CH0~CH31）各创建一个 `Trigger` 对象：

| 属性 | 值 |
|------|----|
| 创建的对象类型 | `Trigger`（不是 `DigitalOut`） |
| 每个对象的 `name` | `'{dsg.name}_CH{N}'`（如 `'dsg_CH0'`） |
| 每个对象的 `connection` | `'CH{N}'`（如 `'CH0'`） |
| `trigger_edge_type` | 继承 DSG 的类属性 `trigger_edge_type`（默认 `'rising'`） |
| 对象挂载位置 | `dsg.outputs`（`_DSGQosmosDigitalOutputs`），加入 `child_devices` |
| 可访问属性 | `dsg.CH0`~`dsg.CH31` 和 `dsg.do0`~`dsg.do31`（同对象，两种别名） |
| 功能 | `go_high` / `go_low`（继承自 `DigitalOut`）+ `trigger()` 方法 + 可连接下游 `TriggerableDevice` |

内部实现（[labscript_devices.py:176-186](DSGQosmos_MasterClock_labscript/labscript_devices.py#L176-L186)）：

```python
if self.precreate_channels:
    for channel in range(CHANNEL_COUNT):
        output = Trigger(
            f'{name}_CH{channel}',              # labscript 对象名称
            self.outputs,                        # 父设备
            f'CH{channel}',                      # 物理连接名
            trigger_edge_type=self.trigger_edge_type,
        )
        self._channels[channel] = output         # 存入字典供 reserve_channel() 使用
        setattr(self, f'CH{channel}', output)     # dsg.CH0, dsg.CH1, ...
        setattr(self, f'do{channel}', output)     # dsg.do0, dsg.do1, ...
```

precreate 后可在实验脚本中直接使用：
```python
start()
dsg.CH0.go_high(1 * ms)
dsg.CH3.trigger(2 * ms, 100 * us)
dsg.do5.go_low(3 * ms)
stop(5 * ms)
```

**`reserve_channel()` 方法**

`precreate_channels=True` 时，还可以通过 `reserve_channel()` 方法获取预创建的通道对象，用于传给下游设备的 `trigger_device`：

```python
dsg = DSGQosmosMasterClock(name='dsg', precreate_channels=True, ...)

# 获取预创建的 CH0 Trigger 对象，传给 ASG 作为触发源
asg = ASGQosmosSignalGenerator(
    name='asg',
    trigger_device=dsg.reserve_channel(0),  # 返回 CH0 上的 Trigger
    trigger_connection='trigger',         # DSG 下的触发通道只接受 'trigger' 参数
    ...
)
```

若 `precreate_channels=False`（默认），调用 `reserve_channel()` 会抛出 `LabscriptError`，提示设置 `precreate_channels=True` 或手动创建 `DigitalOut`

**两种方式的冲突检测**

无论哪种方式，`_DSGQosmosDigitalOutputs.add_device()` 都维护一个 `connected_channels` 字典（key = 通道号 0~31，value = 已注册的 `DigitalOut`/`Trigger` 对象）。当尝试添加新设备时：

[labscript_devices.py:67-76](DSGQosmos_MasterClock_labscript/labscript_devices.py#L67-L76)：
```python
def add_device(self, device):
    channel = _channel_number(device.connection)
    existing = self.connected_channels.get(channel)
    if existing is not None:
        raise LabscriptError(
            f'{...}: DSG channel {device.connection} '
            f'is already connected by {existing.name}'
        )
    self.connected_channels[channel] = device
    IntermediateDevice.add_device(self, device)
```

这意味着以下场景**都会触发错误**：
- 重复创建同通道的实例（无关 `DigitalOut`/`Trigger`）
- 显式创建了两个指向同一物理通道的对象（如 `do0` 和 `CH0` 指向同一通道）
- DDS 内部创建的 `Trigger` 与预创建或显式创建的同通道对象冲突
---

### 连接表 connection_table

在 labscript 的连接表 `connection_table.py` 中添加 Qosmos DSG 主时钟设备，需参考以下规范：

**作为 Master Pseudoclock（主时钟）使用：**

```python
# labscript 运行的脚本中不能出现中文注释，以下注释仅作说明

from labscript import DigitalOut, Trigger, start, stop
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

# --- 用作 ASG 触发源的通道 ---
# ASG 驱动直接使用传入的 trigger_device 对象调用 go_high()/go_low()，
# 因此必须预先实例化 Trigger 或 DigitalOut
trig_asg = Trigger(
    name='trig_asg',
    parent_device=dsg.outputs,
    connection='CH0',               # 物理通道 CH0，`connection` 可以写 `CHX` 或 `doX`（X 为通道号）
    trigger_edge_type='rising',     # 上升沿触发
)

# --- 用作 DDS 触发源的通道 ---
# DDS 驱动在内部自行创建 Trigger 对象（见 DDSQosmosDDS.__init__），
# 因此不需要（也不能）预先实例化！直接将 dsg.outputs 和通道名传入即可。
# 若预先实例化 Trigger 再传入 DDS，会导致同一物理通道被两个 Trigger 对象占用，触发冲突错误。
# （详见下方"3. 连接下游设备"部分）

# 普通 TTL 输出通道 —— 使用 DigitalOut
ttl_spare = DigitalOut(
    name='ttl_spare',
    parent_device=dsg.outputs,
    connection='CH2',               # 物理通道 CH2
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
    trigger_connection='trigger',   # DSG 下的触发通道只接受 'trigger' 参数
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
    trigger_device=dsg.outputs,     # 直接传 dsg.outputs（IntermediateDevice）
    trigger_connection='do1',       # DDS 内部自行创建 Trigger 到此通道
    # 注意：不能预先实例化 Trigger(..., connection='do1') 再传入，
    # 否则 DDS 内部再创建一个 Trigger 到同一通道会导致冲突
)

# 以下仅用于独立编译测试；正常使用时由 runmanager 编译，无需 start/stop
if __name__ == '__main__':
    start()
    stop(1.0)
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

### 实验脚本

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
ttl_spare.go_high(t)
ttl_spare.go_low(t + 10*us)         # 在 2.0 s 输出 10 μs 脉冲

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
# dsg.CH3.trigger(1.0 * ms, 100 * us)

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

### BLACS GUI 手动控制

**手动模式（Manual Mode）**：
1. 在 BLACS 界面中选中 DSG 设备页
2. 点击 "Manual" 进入手动模式，显示 32 个通道的 checkbox
3. 勾选通道 → 对应通道立即输出高电平（手动 overwrite）
4. 取消勾选 → 对应通道拉低
5. **只修改被操作的通道**，其他通道保持原有状态
6. 点击 "Buffered" 返回流模式，所有手动控制释放，通道恢复自动模式

**实验运行期间实时 Overwrite（Mix Mode）**：
- 在 runmanager 提交实验脚本运行期间，BLACS 界面中的 DSG 通道 checkbox 保持可编辑状态
- 勾选/取消通道 → 对应通道立即进入手动模式（高/低电平），**其余通道继续按实验脚本输出**
- 底层使用 DSG 硬件的 mix mode（`manual_channels(manual_en, manual_val)`），只将指定通道切换到手动模式

### 注意事项

- DSG 设备硬件连接参考 Qosmos DSG 操作手册；设备默认 IP 为 `192.168.1.10`，UDP 端口 `5001`
- 如果出现连接不上的情况，可以尝试在连好网线后重启 DSG，等待一段时间后再尝试
- DSG 作为主时钟时，**必须**在实验脚本中调用 `start()` 和 `stop()`，确保 labscript 正确识别主时钟身份
- 推荐使用 `Trigger` 类（而非 `DigitalOut`）创建用作下游触发源的通道，以符合 labscript 规范
- `Trigger` 和 `DigitalOut` 两种创建方式**不能在同一物理通道上混用**（例如不能同时将 do0 创建为 Trigger 和 DigitalOut）
- `precreate_channels=True` 会预创建全部 32 个 `Trigger` 通道（`dsg.CH0`~`dsg.CH31`），适合简单脚本；显式创建方式适合需要精确控制哪些通道被使用的场景
- 若 `stop(t)` 设置过早，在波形还没有输出完实验就结束了，DSG 会在结束时根据当前状态输出终态电平
- Qosmos DSG 的时间分辨率为 10 ns（`dt=10e-9`），所有事件时间必须为 10 ns 的整数倍
- **DDS 连接 DSG 触发**：直接将 `dsg.outputs`（IntermediateDevice）和 `connection='doN'` 传入 DDS 通道。DDS 驱动在内部自行创建 `Trigger` 对象挂载到 `dsg.outputs`上。**不能预先实例化 Trigger**——否则同一物理通道会被两个 Trigger 占用，触发冲突错误
- **ASG 连接 DSG 触发**：必须预先实例化（`Trigger` 或 `DigitalOut` 挂在 `dsg.outputs` 上），再将对象传入 ASG。ASG 驱动直接使用该对象调用 `go_high()`/`go_low()`，不会内部再创建新对象
- **两种模式差异的原因**：取决于下游驱动如何消费 `trigger_device` 参数——DDS 将其作为 `Trigger` 的 `parent_device` 传入 `Trigger.__init__()`，而 ASG 直接通过 `hasattr(obj, "go_high")` 检查后调用方法
