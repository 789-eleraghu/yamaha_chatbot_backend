"""
Telemetry Services Package
Object-Oriented Industrial Telemetry Architecture:
- BaseTelemetryService & TelemetryCapability (Single point of calculation & capability gating)
- FacilityTelemetryService (Grid incomer, solar, transformers, PF, THD, steam)
- GeneratorsTelemetryService (Diesel generator run detection, runtime minutes, kWh generated)
- EquipmentsTelemetryService (8 equipment categories, exclusions, device telemetry)
- ZonesTelemetryService (17 organizational cost centers)
"""

from src.services.telemetry.base import (
    BaseTelemetryService,
    TelemetryCapability,
    UnsupportedCapabilityError,
)
from src.services.telemetry.facility import FacilityTelemetryService
from src.services.telemetry.generators import GeneratorsTelemetryService
from src.services.telemetry.equipments import EquipmentsTelemetryService
from src.services.telemetry.zones import ZonesTelemetryService

# Authoritative singletons for application-wide use
facility_telemetry = FacilityTelemetryService()
generators_telemetry = GeneratorsTelemetryService()
equipments_telemetry = EquipmentsTelemetryService()
zones_telemetry = ZonesTelemetryService()

__all__ = [
    "BaseTelemetryService",
    "TelemetryCapability",
    "UnsupportedCapabilityError",
    "FacilityTelemetryService",
    "GeneratorsTelemetryService",
    "EquipmentsTelemetryService",
    "ZonesTelemetryService",
    "facility_telemetry",
    "generators_telemetry",
    "equipments_telemetry",
    "zones_telemetry",
]
