import time

import labscript_utils.h5_lock  # Import before h5py to avoid locking issues.
import h5py
from blacs.tab_base_classes import Worker
from labscript_utils import properties

from .sdk_adapter import DSGSDKAdapter


class DSGQosmosMasterClockWorker(Worker):
    def init(self):
        self.adapter = DSGSDKAdapter(
            ip=self.ip,
            port=self.port,
            local_port=self.local_port,
        )
        self.adapter.connect()
        self.manual_high_mask = 0    # channels currently forced high by the user
        self.buffered_start_time = None
        self.buffered_stop_time = 0.0
        self.buffered_armed = False
        self.buffered_trigger_source = 'external'

    def transition_to_buffered(self, device_name, h5file, initial_values, fresh):
        with h5py.File(h5file, 'r') as hdf5_file:
            group = hdf5_file[f'devices/{device_name}']
            program = group['STREAM_PROGRAM'][:]
            active_mask = int(group.attrs['active_mask'])
            trigger_source = group.attrs.get('trigger_source', 'external')
            if isinstance(trigger_source, bytes):
                trigger_source = trigger_source.decode()
            device_props = properties.get(hdf5_file, device_name, 'device_properties')

        self.adapter.abort()
        self.adapter.initialise_device(
            use_external_clk=self.use_external_clk,
            trig_mode=self.trig_mode,
            led_enable=self.led_enable,
            exec_mode=self.exec_mode,
        )
        if len(program):
            self.adapter.program_stream(program)
        self.adapter.finalise_buffered(active_mask, trigger_source=trigger_source)

        self.buffered_stop_time = float(device_props.get('stop_time', 0.0))
        self.buffered_armed = bool(len(program))
        self.buffered_trigger_source = str(trigger_source).lower()
        self.buffered_start_time = None
        if self.buffered_armed and self.buffered_trigger_source != 'software':
            self.buffered_start_time = time.time()

        return self._mask_to_front_panel_values(self.manual_high_mask)

    def start_run(self):
        if self.buffered_armed and self.buffered_trigger_source == 'software':
            self.adapter.start_buffered()
            self.buffered_start_time = time.time()
        return True

    def transition_to_manual(self):
        self.buffered_start_time = None
        self.buffered_stop_time = 0.0
        self.buffered_armed = False
        self.buffered_trigger_source = 'external'
        if self.manual_high_mask:
            self.adapter.update_manual_channels(
                high_mask=self.manual_high_mask, low_mask=0,
            )
        else:
            self.adapter.release_manual_channels()
        return self._mask_to_front_panel_values(self.manual_high_mask)

    def program_manual(self, values):
        new_high_mask = self._front_panel_values_to_mask(values)
        old_high_mask = self.manual_high_mask
        newly_high = new_high_mask & ~old_high_mask   # user just checked these
        newly_low  = old_high_mask & ~new_high_mask   # user just unchecked these

        self.adapter.update_manual_channels(
            high_mask=newly_high, low_mask=newly_low,
        )
        self.manual_high_mask = new_high_mask
        return values

    def get_status_text(self):
        return self.adapter.get_status_text()

    def abort_buffered(self):
        self.adapter.abort()
        self.buffered_armed = False
        return True

    def abort_transition_to_buffered(self):
        return self.abort_buffered()

    def check_if_done(self):
        if self.buffered_start_time is None:
            return True
        if self.buffered_armed:
            status_code = self.adapter.get_status_code()
            if status_code is not None:
                return status_code == self.adapter.STATUS_IDLE
        elapsed = time.time() - self.buffered_start_time
        return elapsed >= self.buffered_stop_time

    def shutdown(self):
        self.adapter.disconnect()

    @staticmethod
    def _front_panel_values_to_mask(values):
        mask = 0
        for channel in range(32):
            if values[f'CH{channel}']:
                mask |= 1 << channel
        return mask

    @staticmethod
    def _mask_to_front_panel_values(mask):
        return {
            f'CH{channel}': bool(mask & (1 << channel))
            for channel in range(32)
        }


DSGQosmosDigitalSignalGeneratorWorker = DSGQosmosMasterClockWorker
