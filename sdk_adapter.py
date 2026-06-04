from __future__ import annotations


class DSGSDKAdapter:
    """Thin wrapper around the vendor DSG SDK."""

    STATUS_IDLE = 0x01

    def __init__(self, *, ip: str, port: int, local_port: int = 0):
        self.ip = ip
        self.port = port
        self.local_port = local_port
        self.device = None

    def connect(self) -> None:
        if self.device is not None:
            return

        from .vendor_dsg.user.dsgQosmos import dsgQosmos

        self.device = dsgQosmos(
            name='DSG_Qosmos_MasterClock_Worker',
            ip=self.ip,
            port=int(self.port),
            local_port=int(self.local_port),
        )

    def initialise_device(
        self,
        *,
        use_external_clk: bool,
        trig_mode: int,
        led_enable: bool,
        exec_mode: int,
    ) -> None:
        self.device.init_device(
            use_external_clk=bool(use_external_clk),
            trig_mode=int(trig_mode),
            led_enable=bool(led_enable),
            exec_mode=int(exec_mode),
            clear_timeline=True,
            manual_mode=False,
        )

    def program_stream(self, program_rows) -> None:
        compressed = [
            (int(row['reps']), int(row['state']))
            for row in program_rows
        ]
        header, command_bytes = self.device.instructionGen.prepare_device_data_from_compressed(
            start_address=0,
            compressed=compressed,
        )
        self.device.api.send_stream(header, command_bytes)

    def finalise_buffered(self, active_mask: int, trigger_source: str = 'external') -> None:
        self.device.api.send_setdone_signal(0)
        self.device.api.enable_channelsLED(int(active_mask), 0)
        if str(trigger_source).lower() != 'software':
            self.device.api.send_hwstrat_signal(0)

    def start_buffered(self) -> None:
        self.device.api.send_strat_signal(0)

    # ------------------------------------------------------------------
    # Manual / mix-mode control (read-modify-write via CMD_MAN dual-uint32)
    # ------------------------------------------------------------------
    def sync_manual_state(self):
        """Read current ``(manual_en, manual_val)`` from the hardware."""
        return self.device.api.get_channels_status()

    def set_channels_manual(self, manual_en: int, manual_val: int) -> None:
        """Write ``manual_en`` / ``manual_val`` to the hardware.

        Uses the dual-uint32 ``CMD_MAN`` variant (reserved=0b01) that
        provides per-channel manual-enable / manual-value control.
        Channels with ``manual_en`` bit = 1 are in manual mode; their
        output follows the corresponding ``manual_val`` bit.
        Channels with ``manual_en`` bit = 0 stay in auto / stream mode.
        """
        self.device.api.manual_channels(
            int(manual_en) & 0xFFFFFFFF,
            int(manual_val) & 0xFFFFFFFF,
        )

    def update_manual_channels(self, high_mask: int, low_mask: int) -> None:
        """Read-modify-write: only touch the channels listed in *high_mask*
        or *low_mask*; all other channels keep their current hardware state.

        Parameters
        ----------
        high_mask : int
            Bitmask of channels that should be forced **high** (manual).
        low_mask : int
            Bitmask of channels that should be forced **low** (manual).
        """
        high_mask = int(high_mask) & 0xFFFFFFFF
        low_mask = int(low_mask) & 0xFFFFFFFF
        if high_mask & low_mask:
            raise ValueError(
                f'Channel conflict: {high_mask & low_mask:#010x} '
                f'appears in both high_mask and low_mask'
            )
        affect_mask = high_mask | low_mask
        if not affect_mask:
            return  # nothing to do

        manual_en, manual_val = self.sync_manual_state()
        manual_en |= affect_mask          # put affected channels into manual mode
        manual_val |= high_mask           # set high
        manual_val &= ~low_mask           # set low
        self.set_channels_manual(manual_en, manual_val)

    def release_manual_channels(self) -> None:
        """Release all manual control – every channel returns to auto / stream mode."""
        self.set_channels_manual(0, 0)

    # legacy alias – kept for compatibility with older callers
    def set_manual_mask(self, high_mask: int) -> None:
        high_mask = int(high_mask) & 0xFFFFFFFF
        if high_mask:
            self.update_manual_channels(high_mask=high_mask, low_mask=0)
        else:
            self.release_manual_channels()

    def abort(self) -> None:
        self.device.send_abort_signal()
        self.device.send_cls_signal()

    def get_status_text(self) -> str:
        return self.device.get_status_text()

    def get_status_code(self):
        try:
            raw = self.device.api.get_status()
        except Exception:
            return None
        return int.from_bytes(raw, byteorder='big')

    def disconnect(self) -> None:
        if self.device is not None:
            self.device.disconnect()
            self.device = None
