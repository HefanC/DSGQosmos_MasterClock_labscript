from __future__ import annotations

import numpy as np
from labscript import (
    ClockLine,
    DigitalOut,
    IntermediateDevice,
    LabscriptError,
    Pseudoclock,
    PseudoclockDevice,
    Trigger,
    bitfield,
    set_passed_properties,
)


SEGMENT_MARKER = (0xFFFFFFFF, 0x00000000)
CHANNEL_COUNT = 32
CHANNEL_ALIASES = ('CH', 'do')


def _channel_number(connection: str) -> int:
    connection = str(connection)
    prefix = ''.join(char for char in connection if not char.isdigit())
    suffix = connection[len(prefix):]
    if prefix not in CHANNEL_ALIASES or not suffix:
        raise LabscriptError(
            'DSG channel connections must be named CH0..CH31 or do0..do31'
        )
    channel = int(suffix)
    if not 0 <= channel < CHANNEL_COUNT:
        raise LabscriptError(f'DSG channel index out of range: {connection}')
    return channel


class _DSGQosmosPseudoclock(Pseudoclock):
    def add_device(self, device):
        if not isinstance(device, _DSGQosmosClockLine) or self.child_devices:
            raise LabscriptError(
                f'{self.parent_device.name} supports exactly one internal clockline'
            )
        Pseudoclock.add_device(self, device)


class _DSGQosmosClockLine(ClockLine):
    def add_device(self, device):
        if not isinstance(device, _DSGQosmosDigitalOutputs) or self.child_devices:
            raise LabscriptError(
                f'{self.pseudoclock_device.name} supports exactly one internal '
                'digital output bank'
            )
        ClockLine.add_device(self, device)


class _DSGQosmosDigitalOutputs(IntermediateDevice):
    allowed_children = [DigitalOut, Trigger]
    clock_limit = None

    def __init__(self, name, parent_device, **kwargs):
        IntermediateDevice.__init__(self, name, parent_device, **kwargs)
        self.connected_channels = {}

    @property
    def pseudoclock_device(self):
        return self.parent_device.pseudoclock_device

    def add_device(self, device):
        channel = _channel_number(device.connection)
        existing = self.connected_channels.get(channel)
        if existing is not None:
            raise LabscriptError(
                f'{self.pseudoclock_device.name}: DSG channel {device.connection} '
                f'is already connected by {existing.name}'
            )
        self.connected_channels[channel] = device
        IntermediateDevice.add_device(self, device)


class DSGQosmosMasterClock(PseudoclockDevice):
    """Qosmos DSG driver for use as a labscript master pseudoclock.

    The device owns one internal pseudoclock, one clockline and one 32-bit
    digital-output bank. Channels can be created explicitly with labscript
    ``DigitalOut``/``Trigger`` on ``dsg.outputs``. For convenience,
    ``precreate_channels=True`` pre-creates ``dsg.CH0``..``dsg.CH31`` as
    ``Trigger`` outputs; those objects support normal ``go_high``/``go_low``/
    ``pulse`` calls and can be passed directly to downstream drivers that
    accept an existing digital output as their trigger source.
    """

    description = 'DSG Qosmos Master Clock / 32-Channel Digital Output'
    allowed_children = [_DSGQosmosPseudoclock]

    trigger_edge_type = 'rising'
    trigger_delay = 0
    trigger_minimum_duration = 10e-6
    wait_delay = 0

    @set_passed_properties(
        property_names={
            'connection_table_properties': [
                'ip',
                'port',
                'local_port',
                'dt',
                'use_external_clk',
                'trig_mode',
                'led_enable',
                'exec_mode',
                'trigger_duration',
            ],
            'device_properties': [
                'clock_limit',
                'clock_resolution',
                'trigger_delay',
                'trigger_minimum_duration',
                'wait_delay',
                'max_instructions',
                'precreate_channels',
            ],
        }
    )
    def __init__(
        self,
        name,
        trigger_device=None,
        trigger_connection=None,
        *,
        ip='192.168.1.10',
        port=5001,
        local_port=0,
        dt=10e-9,
        use_external_clk=False,
        trig_mode=0,
        led_enable=True,
        exec_mode=1,
        trigger_duration=10e-6,
        max_instructions=65535,
        precreate_channels=False,
        **kwargs,
    ):
        self.dt = float(dt)
        if self.dt <= 0:
            raise LabscriptError(f'{name}: dt must be > 0')

        self.clock_resolution = self.dt
        self.clock_limit = 1 / self.dt
        self.trigger_duration = float(trigger_duration)
        if self.trigger_duration <= 0:
            raise LabscriptError(f'{name}: trigger_duration must be > 0')
        self.trigger_minimum_duration = self.trigger_duration
        self.max_instructions = int(max_instructions)
        self.precreate_channels = bool(precreate_channels)
        self._channels = {}

        PseudoclockDevice.__init__(
            self,
            name,
            trigger_device=trigger_device,
            trigger_connection=trigger_connection,
            **kwargs,
        )

        self._pseudoclock = _DSGQosmosPseudoclock(
            f'{name}__pseudoclock',
            self,
            'pseudoclock',
        )
        self._clockline = _DSGQosmosClockLine(
            f'{name}__clockline',
            self._pseudoclock,
            'clockline',
        )
        self.outputs = _DSGQosmosDigitalOutputs(f'{name}__outputs', self._clockline)

        if self.precreate_channels:
            for channel in range(CHANNEL_COUNT):
                output = Trigger(
                    f'{name}_CH{channel}',
                    self.outputs,
                    f'CH{channel}',
                    trigger_edge_type=self.trigger_edge_type,
                )
                self._channels[channel] = output
                setattr(self, f'CH{channel}', output)
                setattr(self, f'do{channel}', output)

        self.BLACS_connection = f'{ip}:{port}'

    @property
    def pseudoclock(self):
        return self._pseudoclock

    @property
    def clockline(self):
        return self._clockline

    def add_device(self, device):
        if isinstance(device, _DSGQosmosPseudoclock):
            PseudoclockDevice.add_device(self, device)
            return
        if isinstance(device, DigitalOut):
            raise LabscriptError(
                f'Digital outputs must be connected to {self.name}.outputs, '
                f'not directly to {self.name}'
            )
        raise LabscriptError(
            f'{device.name} ({device.__class__}) cannot be connected directly '
            f'to {self.name}'
        )

    def reserve_channel(self, channel: int):
        """Return the pre-created Trigger/DigitalOut for ``channel``.

        This is a convenience method for connection-table code that wants an
        explicit, named way to obtain a DSG trigger source.
        """
        channel = int(channel)
        try:
            return self._channels[channel]
        except KeyError as exc:
            raise LabscriptError(
                f'{self.name}: channel {channel} is not available. '
                'Set precreate_channels=True or create a DigitalOut on '
                f'{self.name}.outputs manually.'
            ) from exc

    def wait(self, t: float) -> None:
        self.trigger(float(t), self.trigger_duration, wait_delay=self.wait_delay)

    def generate_code(self, hdf5_file):
        PseudoclockDevice.generate_code(self, hdf5_file)

        group = self.init_device_group(hdf5_file)
        times = np.asarray(self._pseudoclock.times[self._clockline], dtype=float)
        clock = self._pseudoclock.clock

        if len(times) == 0:
            data = np.zeros(0, dtype=[('reps', np.uint32), ('state', np.uint32)])
            group.create_dataset('STREAM_PROGRAM', data=data)
            group.create_dataset('SEGMENT_START_TIMES', data=np.zeros(0, dtype=np.float64))
            self._write_metadata(group, 0.0, 0, 0, 0)
            return

        self._validate_time_grid(times)

        bits = [np.zeros(len(times), dtype=np.uint32) for _ in range(CHANNEL_COUNT)]
        active_mask = 0
        for output in self.outputs.child_devices:
            channel = _channel_number(output.connection)
            output.make_timeseries(times)
            bits[channel] = np.asarray(output.timeseries, dtype=np.uint32)
            if np.any(bits[channel]):
                active_mask |= 1 << channel

        states = np.asarray(bitfield(bits, dtype=np.uint32), dtype=np.uint32)

        if len(times) == 1:
            reps = np.array([1], dtype=np.uint32)
            interval_states = states
        else:
            reps = np.rint(np.diff(times) / self.dt).astype(np.uint32)
            interval_states = states[:-1]

        program = []
        wait_count = 0
        for index, (rep, state) in enumerate(zip(reps, interval_states)):
            if index < len(clock) and clock[index] == 'WAIT':
                program.append(SEGMENT_MARKER)
                wait_count += 1
            if int(rep) <= 0:
                continue
            state = int(state)
            if program and program[-1] != SEGMENT_MARKER and program[-1][1] == state:
                program[-1] = (int(program[-1][0]) + int(rep), state)
            else:
                program.append((int(rep), state))

        if len(program) > self.max_instructions:
            raise LabscriptError(
                f'{self.name}: instruction count {len(program)} exceeds '
                f'max_instructions ({self.max_instructions})'
            )

        data = np.array(program, dtype=[('reps', np.uint32), ('state', np.uint32)])
        group.create_dataset('STREAM_PROGRAM', data=data)
        group.create_dataset(
            'SEGMENT_START_TIMES',
            data=np.array(self.trigger_times, dtype=np.float64),
        )

        final_mask = next(
            (
                int(state)
                for reps_value, state in reversed(program)
                if (int(reps_value), int(state)) != SEGMENT_MARKER
            ),
            0,
        )
        stop_time = float(times[-1] - times[0] if len(times) > 1 else reps[-1] * self.dt)
        self._write_metadata(group, stop_time, wait_count, active_mask, final_mask)

    def _validate_time_grid(self, times):
        ticks = np.rint(times / self.dt)
        if not np.allclose(times, ticks * self.dt, rtol=0, atol=self.dt * 1e-6):
            bad = times[np.argmax(np.abs(times - ticks * self.dt))]
            raise LabscriptError(
                f'{self.name}: event time {bad} s is not aligned to the '
                f'{self.dt} s DSG grid'
            )

    def _write_metadata(self, group, stop_time, wait_count, active_mask, final_mask):
        trigger_source = 'software' if self.is_master_pseudoclock else 'external'
        group.attrs['schema_version'] = 2
        group.attrs['dt'] = self.dt
        group.attrs['t_start'] = float(self.trigger_times[0] if self.trigger_times else 0.0)
        group.attrs['wait_count'] = int(wait_count)
        group.attrs['active_mask'] = int(active_mask)
        group.attrs['final_mask'] = int(final_mask)
        group.attrs['trigger_source'] = trigger_source
        self.set_property('stop_time', float(stop_time), location='device_properties')
        self.set_property('final_mask', int(final_mask), location='device_properties')
        self.set_property('trigger_source', trigger_source, location='device_properties')


DSGQosmosDigitalSignalGenerator = DSGQosmosMasterClock
