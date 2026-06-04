import labscript_utils.h5_lock
import h5py
import numpy as np


SEGMENT_REPS = 0xFFFFFFFF


class DSGQosmosMasterClockParser:
    def __init__(self, path, device):
        self.path = path
        self.name = device.name
        self.device = device

    def get_traces(self, add_trace, clock=None):
        with h5py.File(self.path, 'r') as hdf5_file:
            group = hdf5_file[f'devices/{self.name}']
            program = group['STREAM_PROGRAM'][()]
            dt = float(group.attrs['dt'])
            t_start = float(group.attrs.get('t_start', 0.0))

        times = []
        states = []
        t = t_start
        for row in program:
            reps = int(row['reps'])
            state = int(row['state'])
            if reps == SEGMENT_REPS:
                continue
            times.append(t)
            states.append(state)
            t += reps * dt

        if not times:
            times = [0.0]
            states = [0]

        times = np.asarray(times, dtype=float)
        states = np.asarray(states, dtype=np.uint32)
        traces = {}

        for channel in self.device.outputs.child_devices:
            connection = getattr(channel, 'parent_port', channel.connection)
            channel_index = int(''.join(char for char in connection if char.isdigit()))
            values = ((states >> channel_index) & 1).astype(np.uint8)
            trace = (times, values)
            traces[channel.name] = trace
            add_trace(channel.name, trace, self.name, connection)

        return traces


DSGQosmosDigitalSignalGeneratorParser = DSGQosmosMasterClockParser
