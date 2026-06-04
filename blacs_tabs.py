from blacs.device_base_class import DeviceTab


class DSGQosmosMasterClockTab(DeviceTab):
    def initialise_GUI(self):
        self.create_digital_outputs(
            {f'CH{channel}': {} for channel in range(32)}
        )
        _, _, digital_widgets = self.auto_create_widgets()
        self.auto_place_widgets(('Digital Outputs', digital_widgets))

        self.supports_smart_programming(False)
        self.supports_remote_value_check(False)

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


DSGQosmosDigitalSignalGeneratorTab = DSGQosmosMasterClockTab
