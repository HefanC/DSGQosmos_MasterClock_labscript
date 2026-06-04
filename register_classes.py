from labscript_devices import register_classes


register_classes(
    'DSGQosmosMasterClock',
    BLACS_tab=(
        'user_devices.DSGQosmos_MasterClock_labscript.blacs_tabs.'
        'DSGQosmosMasterClockTab'
    ),
    runviewer_parser=(
        'user_devices.DSGQosmos_MasterClock_labscript.runviewer_parsers.'
        'DSGQosmosMasterClockParser'
    ),
)

register_classes(
    'DSGQosmosDigitalSignalGenerator',
    BLACS_tab=(
        'user_devices.DSGQosmos_MasterClock_labscript.blacs_tabs.'
        'DSGQosmosMasterClockTab'
    ),
    runviewer_parser=(
        'user_devices.DSGQosmos_MasterClock_labscript.runviewer_parsers.'
        'DSGQosmosMasterClockParser'
    ),
)
