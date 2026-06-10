from blacs.device_base_class import DeviceTab, define_state, MODE_BUFFERED


class DSGQosmosMasterClockTab(DeviceTab):
    def initialise_GUI(self):
        self.create_digital_outputs(
            {f'CH{channel:02d}': {} for channel in range(32)}
        )
        _, _, digital_widgets = self.auto_create_widgets()
        self.auto_place_widgets(('Digital Outputs', digital_widgets))

        self.supports_smart_programming(True)
        self.supports_remote_value_check(False)

    def get_child_from_connection_table(self, parent_device_name, port):
        return self.connection_table.find_child(
            f'{self.device_name}__outputs', port
        )

    def initialise_workers(self):
        props = self.settings['connection_table'].find_by_name(self.device_name).properties
        self.create_worker(
            'main_worker',
            'user_devices.DSGQosmos_MasterClock_labscript.blacs_workers.'
            'DSGQosmosMasterClockWorker',
            {
                'ip': props['ip'],
                'port': props['port'],
                'local_port': props['local_port'],
                'use_external_clk': props['use_external_clk'],
                'trig_mode': props['trig_mode'],
                'led_enable': props['led_enable'],
                'exec_mode': props['exec_mode'],
            },
        )
        self.primary_worker = 'main_worker'

    @define_state(MODE_BUFFERED, True)
    def start_run(self, notify_queue):
        """Start the DSG when it is BLACS' master pseudoclock."""
        yield self.queue_work(self.primary_worker, 'start_run')
        # Seed the GUI-change tracker so that wait_until_done can detect
        # widget changes made by the user during the shot.
        self._last_smart_values = self.get_front_panel_values()
        self.wait_until_done(notify_queue)

    @define_state(MODE_BUFFERED, True)
    def wait_until_done(self, notify_queue):
        # ---- poll for GUI overwrites (mix-mode) ----
        current = self.get_front_panel_values()
        if current != self._last_smart_values:
            yield self.queue_work(
                self.primary_worker, 'program_manual', current
            )
            self._last_smart_values = current.copy()
            # After a GUI overwrite, force an immediate completion check
            # so that the 1-Hz throttle in check_if_done does not add
            # extra delay after the last user interaction.
            done = yield self.queue_work(
                self.primary_worker, 'check_if_done', True
            )
            if done:
                notify_queue.put('done')
            else:
                self.wait_until_done(notify_queue)
            return

        # ---- no GUI change: normal throttled completion check ----
        done = yield self.queue_work(self.primary_worker, 'check_if_done')
        if done:
            notify_queue.put('done')
        else:
            self.wait_until_done(notify_queue)


DSGQosmosDigitalSignalGeneratorTab = DSGQosmosMasterClockTab
