# DSGQosmos_MasterClock_labscript

将 Qosmos DSG 数字信号发生器作为 **labscript 实验控制系统主时钟（Master Pseudoclock）** 的驱动程序。

## 功能概览

- 作为 labscript 主时钟，为实验序列提供时间线和硬时序
- 32 路 TTL 数字输出，可同时用作下游设备硬件触发源和普通数字输出
- 向下兼容：DSG 也可作为下游被触发设备（Secondary Pseudoclock）
- BLACS GUI 手动控制，支持 mix-mode overwrite（流模式运行期间只覆盖指定通道）
- 通过 Qosmos 官方 Python SDK（UDP 通信）控制硬件

## 文件结构

| 文件 | 功能 |
|------|------|
| `labscript_devices.py` | 核心编译层：`DSGQosmosMasterClock(PseudoclockDevice)` |
| `blacs_tabs.py` | BLACS GUI 面板（32 通道手动控制） |
| `blacs_workers.py` | BLACS Worker：buffered/manual 模式切换与硬件通信 |
| `sdk_adapter.py` | Vendor SDK 封装：流指令、触发、mix-mode 手动控制 |
| `runviewer_parsers.py` | Runviewer 时序解析 |
| `register_classes.py` | 设备类注册 |
| `vendor_dsg/` | Qosmos DSG Python SDK（协议/传输/API 分层实现） |

## 快速开始

### 1. 连接表（作为主时钟）

```python
from labscript import Trigger, DigitalOut
from user_devices.DSGQosmos_MasterClock_labscript.labscript_devices import (
    DSGQosmosMasterClock,
)

dsg = DSGQosmosMasterClock(
    name='dsg',
    ip='192.168.1.10', port=5001,
)

# 触发源通道（推荐用 Trigger 类）
trig_dds = Trigger(name='trig_dds', parent_device=dsg.outputs,
                   connection='do0', trigger_edge_type='rising')

# 普通 TTL 通道
ttl = DigitalOut(name='ttl', parent_device=dsg.outputs, connection='do2')
```

### 2. 实验脚本

```python
from labscript import *

start()

ttl.go_high(0.5)
ttl.go_low(1.5)
ttl.pulse(2.0, duration=10e-6)

# 下游设备自动触发（无需手动写触发命令）
dds_ch1.setfreq(1e-3, 20e6)

stop(5e-3)
```

### 3. BLACS GUI

- 切换到 "Manual" 标签页，勾选/取消勾选通道 checkbox
- 只修改被操作的通道，不影响其余通道（即使正在按实验脚本输出）

## 详细文档

参见 [DSGQosmos_MasterClock_labscript.md](DSGQosmos_MasterClock_labscript.md)
