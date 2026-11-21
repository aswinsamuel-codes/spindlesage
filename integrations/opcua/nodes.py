"""OPC UA address-space layout used by the simulator and the collector.

    Objects/
      SpindleSage/                (namespace urn:spindlesage:cnc-sim)
        cnc-sim-01/
          AirTemperature      Double, K
          ProcessTemperature  Double, K
          SpindleSpeed        Double, rpm
          Torque              Double, Nm
          ToolWear            Double, min
          ProductType         String, L/M/H
          SampleTime          DateTime (UTC) of the current values

Real machines expose different node names. VARIABLE_MAP is the single place
that maps OPC UA browse names to SpindleSage fields; a real deployment would
load its own mapping per machine model.
"""

from __future__ import annotations

NAMESPACE_URI = "urn:spindlesage:cnc-sim"
ROOT_FOLDER = "SpindleSage"
DEFAULT_ENDPOINT = "opc.tcp://127.0.0.1:4840/spindlesage/"

VARIABLE_MAP: dict[str, str] = {
    "AirTemperature": "air_temperature_k",
    "ProcessTemperature": "process_temperature_k",
    "SpindleSpeed": "rotational_speed_rpm",
    "Torque": "torque_nm",
    "ToolWear": "tool_wear_min",
    "ProductType": "product_type",
    "SampleTime": "timestamp",
}
