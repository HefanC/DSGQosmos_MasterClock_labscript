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
        self._gui_state_mask = 0     # last GUI state for smart-programming diff
        self.buffered_start_time = None
        self.buffered_stop_time = 0.0
        self.buffered_armed = False
        self.buffered_trigger_source = 'external'

        # ---- throttled status polling ----
        self._last_status_query_time = 0.0   # timestamp of last CMD_STATUS query
        self._min_query_interval = 1.0        # minimum interval between hw queries (1 Hz)
        self._completion_buffer = 0.2         # extra time for CMD_SWR UDP latency before
                                              # the first hardware status confirmation
        self._hard_timeout_extra = 30.0       # max extra wait beyond stop_time if DSG
                                              # never confirms idle (e.g. UDP broken)

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

        # Extract initial output state from the stream program for the
        # smart-programming GUI so that the front-panel checkboxes reflect
        # the actual first state of the stream (skip SEGMENT_MARKER rows).
        initial_state = 0
        for row in program:
            reps = int(row['reps'])
            state = int(row['state'])
            if reps == 0xFFFFFFFF and state == 0:
                continue
            initial_state = state
            break
        self._gui_state_mask = initial_state
        self.manual_high_mask = 0   # reset manual overrides for the new shot
        return self._mask_to_front_panel_values(initial_state)

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
        # Put every channel into full manual mode with its last known
        # GUI state (handles both high and low correctly, unlike the
        # old path which only set high_mask).
        self.adapter.set_channels_manual(
            manual_en=0xFFFFFFFF,
            manual_val=self._gui_state_mask,
        )
        self.manual_high_mask = self._gui_state_mask
        return self._mask_to_front_panel_values(self._gui_state_mask)

    def program_manual(self, values):
        new_mask = self._front_panel_values_to_mask(values)
        old_mask = self._gui_state_mask
        newly_high = new_mask & ~old_mask   # user just checked these
        newly_low  = old_mask & ~new_mask   # user just unchecked these

        if newly_high or newly_low:
            self.adapter.update_manual_channels(
                high_mask=newly_high, low_mask=newly_low,
            )
        self._gui_state_mask = new_mask
        self.manual_high_mask = new_mask    # keep in sync for transition_to_manual
        return values

    def get_status_text(self):
        return self.adapter.get_status_text()

    def abort_buffered(self):
        self.adapter.abort()
        self.buffered_armed = False
        return True

    def abort_transition_to_buffered(self):
        return self.abort_buffered()

    def check_if_done(self, force_query=False):
        """Return True when the buffered shot has finished.

        Strategy (avoid overwhelming the DSG embedded UDP stack):

        * Before *stop_time + buffer*  — no hardware query at all; the DSG
          FPGA executes the stream for a deterministic duration known at
          compile time, so we can safely return False without touching the
          network.
        * After *stop_time + buffer*  — throttled hardware confirmation at
          most once per ``_min_query_interval`` (default 1 Hz).  Once the
          DSG reports STATUS_IDLE we return True.
        * If the DSG never confirms idle (UDP broken / firmware stuck), a
          hard timeout (``_hard_timeout_extra`` beyond stop_time) forces
          completion so that BLACS is not blocked forever.

        Parameters
        ----------
        force_query : bool
            When True, bypass the throttle interval in phase 2 so that a
            hardware status query is issued immediately (unless we are still
            in phase 1, where the experiment cannot possibly be done yet).
            Used after a GUI overwrite so that the completion check is not
            delayed by the 1-Hz window.
        """
        if self.buffered_start_time is None:
            return True

        elapsed = time.time() - self.buffered_start_time

        # ---- phase 1: before expected completion — no network I/O ----
        if elapsed < self.buffered_stop_time + self._completion_buffer:
            return False

        # ---- phase 2: near / after expected completion — throttled query ----
        now = time.time()
        if not force_query and (now - self._last_status_query_time < self._min_query_interval):
            return False   # within the throttle window

        self._last_status_query_time = now

        if self.buffered_armed:
            status_code = self.adapter.get_status_code()
            if status_code == self.adapter.STATUS_IDLE:
                return True
            if status_code is None:
                # UDP appears broken — fall back to time-based judgment.
                # DSG FPGA execution is deterministic in master mode;
                # the completion_buffer provides a conservative margin.
                return elapsed >= self.buffered_stop_time + self._completion_buffer

        # ---- phase 3: hard timeout — prevent infinite wait ----
        return elapsed >= self.buffered_stop_time + self._hard_timeout_extra

    def shutdown(self):
        self.adapter.disconnect()

    @staticmethod
    def _front_panel_values_to_mask(values):
        mask = 0
        for channel in range(32):
            if values[f'CH{channel:02d}']:
                mask |= 1 << channel
        return mask

    @staticmethod
    def _mask_to_front_panel_values(mask):
        return {
            f'CH{channel:02d}': bool(mask & (1 << channel))
            for channel in range(32)
        }


DSGQosmosDigitalSignalGeneratorWorker = DSGQosmosMasterClockWorker
