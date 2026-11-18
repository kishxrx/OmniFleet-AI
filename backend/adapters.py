class SimulatedVehicleAdapter:
    """Safe default adapter. It only dispatches to the local toy simulator."""
    name="simulated"
    def dispatch(self, vehicle, action):
        from .core import dispatch
        return dispatch(vehicle,action)

class PX4SITLAdapter:
    """Integration boundary only; intentionally refuses real vehicle control.

    A production PX4 adapter needs a separately reviewed MAVSDK/MAVLink transport,
    SITL integration tests, failsafes, geofence validation and operator authorization.
    This placeholder never opens a socket or sends commands.
    """
    name="px4-sitl-placeholder"
    def dispatch(self, vehicle, action):
        raise RuntimeError("PX4 adapter is a non-operational placeholder; no MAVLink commands are sent")
