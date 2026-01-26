"""
Default machine spec builders — extracted from simulation_generator.py (behavior-preserving).
"""

from typing import Dict

from backend.scripts.simgen.constants import *  # noqa: F401, F403

__all__ = [
    "_create_default_hauler_spec",
    "_create_default_loader_spec",
]


def _create_default_hauler_spec(
    spec_id: int, model_name: str, is_electric: bool
) -> Dict:
    """Create a default hauler spec (fallback when no template file)."""
    hauler_machine = {
        "ID": spec_id,
        "Model": model_name,
        "Engine": "CAT 3516C HD EUI",
        "FlywheelPower": 1976.0,
        "TransType": "7SPD PS",
        "Capacity": 129.0,
        "Payload": 227000.0,
        "OwnOp": 0.0,
        "Availability": 0.0,
        "MachineType": 6,
        "IsLoader": 0,
        "IsHauler": 1,
        "IsExcavator": 0,
        "IsDozer": 0,
        "IsSupport": 0,
        "MachineCode": "",
        "LoaderType": 0,
        "StdBucketCapacity": 0.0,
        "StdBucketLoad": 0.0,
        "StdBucketMins": 0.0,
        "HaulExchTime": 0.0,
        "WheelBase": 0.0,
        "StdBucketSize": 0.0,
        "MaxBurnRate": 227.0,
        "IdleBurnPct": 15.0,
        "ManeuverBurnPct": 90.0,
        "RetardingBurnPct": 50.0,
        "LoadedFrontPct": 33.0,
        "LoadedRearPct": 67.0,
        "LoadedTrailPct": 0.0,
        "EmptyFrontPct": 45.0,
        "EmptyRearPct": 55.0,
        "EmptyTrailPct": 0.0,
        "TiresFront": 2,
        "TiresRear": 4,
        "TiresTrail": 0,
        "NumAxles": 2,
        "GrossPower": 1976.0,
        "Description": f"{model_name} Mining Truck",
        "Comments": "",
        "RimpullTireType": None,
        "RimpullTireSize": "46/90R57",
        "RimpullDLR": 1778.0,
        "RetardingBasis": 1,
        "RetardingPackage": "Standard",
        "TotalReduction": "35",
        "RetardingMax": None,
        "ArcType": 0,
        "ArcRpmMin": 0,
        "ArcRpmMax": 0,
        "ArcRpmDefault": 0,
        "Altitude7500": 1.0,
        "Altitude10000": 1.0,
        "Altitude12500": 1.0,
        "Altitude15000": 1.0,
        "IsCat": 1,
        "HasRimpullTail": 0,
        "DumpManeuver": 1.2,
        "ShiftLogic": 0,
        "FuelLogic": 0,
        "InletRestriction": 0.0,
        "IntakeTempRise": 0.0,
        "TrolleyVoltage": 0.0,
        "TrolleyConnectPct": 0.0,
        "TrolleyOnlinePct": 0.0,
        "TrolleyFuelPct": None,
        "TrolleyWeight": 0.0,
        "SecuredAccess": 0,
        "IsCompetitive": 0,
        "battery_type": "LFP" if is_electric else None,
        "battery_size": 2230.0 if is_electric else None,
        "GHGFreeConfig": "BEM" if is_electric else None,
        "HaulerMax": 392000.0,
        "EmptyWeight": 165000.0,
        "PayloadIndex": 227000.0,
        "Machine Fuel Tank Capacity (L)": 3785,
        "machine_type": {
            "power_source": "battery" if is_electric else "diesel",
            "driveline": "electric" if is_electric else "mechanical",
            "is_hauler": True,
            "is_loader": False,
            "det_capable": is_electric,
            "machine type": "Mining Truck",
        },
    }

    return {
        "machine": {
            "machine": hauler_machine,
            "tires": [
                {
                    "ID": spec_id,
                    "Order": 0,
                    "IsStandard": 1,
                    "Size": "46/90R57",
                    "Type": "E4",
                    "SpeedCorrection": 1.0,
                    "HaulerEmpty": 165000.0,
                    "HaulerMax": 392000.0,
                    "PayloadIndex": 227000.0,
                }
            ],
            "retarding": [],
            "rimpull": [],
            "shift_points": [],
            "fuel_consumption": [],
            "gear_ratios": [],
        },
        "has_fuel": not is_electric,
        "is_hybrid": False,
        "machine_type": "electric" if is_electric else "diesel",
    }


def _create_default_loader_spec() -> Dict:
    """Create a default loader spec (fallback when no template file)."""
    return {
        "loader": {
            "ID": 1,
            "Model": "994K HL",
            "Engine": "CAT 3516E",
            "FlywheelPower": 1296.0,
            "TransType": "3SPD PS",
            "Capacity": 0.0,
            "Payload": 0.0,
            "OwnOp": 0.0,
            "Availability": 0.0,
            "MachineType": 11,
            "IsLoader": 1,
            "IsHauler": 0,
            "IsExcavator": 0,
            "IsDozer": 0,
            "IsSupport": 0,
            "MachineCode": "",
            "LoaderType": 0,
            "StdBucketCapacity": 19.0,
            "HaulExchTime": 0.7,
            "GrossPower": 1377.0,
            "Description": "CAT 994K Wheel Loader",
            "DumpManeuver": 1.2,
            "IsCat": 1,
            "machine_type": {
                "power_source": "diesel",
                "driveline": "mechanical",
                "is_hauler": False,
                "is_loader": True,
                "det_capable": False,
                "machine type": "Wheel Loader",
            },
        },
        "buckets": [
            {
                "ID": 1,
                "Order": 0,
                "IsStandard": 1,
                "Type": "Rock Bucket",
                "Capacity": 19.0,
                "RatedLoad": 40823.0,
                "CycleTimeMin": 0.58,
                "FirstBucketMin": 0.1,
            }
        ],
        "has_fuel": True,
        "is_hybrid": False,
        "machine_type": "diesel",
        "tires": [],
        "retarding": [],
        "rimpull": [],
    }
