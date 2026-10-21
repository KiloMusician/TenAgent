from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol
from uuid import UUID, uuid4


# ============================================================================
# DOMAIN ENUMS
# ============================================================================

class VehicleOperationalStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DISPATCHING = "DISPATCHING"
    RENTAL_IN_PROGRESS = "RENTAL_IN_PROGRESS"
    TEST_BENCH_ACTIVE = "TEST_BENCH_ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class AutonomyLevel(str, enum.Enum):
    LEVEL_0 = "LEVEL_0"
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"
    LEVEL_5 = "LEVEL_5"


class HardwareComponentType(str, enum.Enum):
    LIDAR = "LIDAR"
    RADAR = "RADAR"
    CAMERA = "CAMERA"
    ULTRASONIC = "ULTRASONIC"
    COMPUTE_UNIT = "COMPUTE_UNIT"
    IMU = "IMU"
    GNSS_V2X = "GNSS_V2X"
    ACTUATOR_STEERING = "ACTUATOR_STEERING"
    ACTUATOR_BRAKING = "ACTUATOR_BRAKING"


class RentalStatus(str, enum.Enum):
    PENDING_DISPATCH = "PENDING_DISPATCH"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


# ============================================================================
# DOMAIN ENTITIES & VALUE OBJECTS
# ============================================================================

class DomainException(Exception):
    """Base domain exception."""


class InvalidStateTransitionError(DomainException):
    """Raised when an illegal vehicle or rental status transition is attempted."""


class VehicleNotFoundError(DomainException):
    """Raised when a requested vehicle does not exist."""


@dataclass(frozen=True)
class HardwareComponent:
    component_id: UUID
    component_type: HardwareComponentType
    serial_number: str
    firmware_version: str
    healthy: bool


@dataclass
class Vehicle:
    id: UUID
    vin: str
    model: str
    autonomy_level: AutonomyLevel
    status: VehicleOperationalStatus
    battery_level_pct: float
    components: List[HardwareComponent] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_reserved(self) -> None:
        if self.status != VehicleOperationalStatus.AVAILABLE:
            raise InvalidStateTransitionError(
                f"Vehicle {self.id} cannot be reserved from state {self.status.value}"
            )
        self.status = VehicleOperationalStatus.RESERVED
        self.updated_at = datetime.now(timezone.utc)

    def transition_to_testbench(self) -> None:
        if self.status not in {VehicleOperationalStatus.AVAILABLE, VehicleOperationalStatus.RESERVED}:
            raise InvalidStateTransitionError(
                f"Vehicle {self.id} cannot enter test bench from state {self.status.value}"
            )
        self._assert_hardware_healthy()
        self.status = VehicleOperationalStatus.TEST_BENCH_ACTIVE
        self.updated_at = datetime.now(timezone.utc)

    def release_to_available(self) -> None:
        if self.status in {VehicleOperationalStatus.DECOMMISSIONED}:
            raise InvalidStateTransitionError("Decommissioned vehicles cannot be released.")
        self.status = VehicleOperationalStatus.AVAILABLE
        self.updated_at = datetime.now(timezone.utc)

    def _assert_hardware_healthy(self) -> None:
        unhealthy = [c.component_type.value for c in self.components if not c.healthy]
        if unhealthy:
            raise DomainException(f"Hardware pre-check failed. Unhealthy: {', '.join(unhealthy)}")


@dataclass
class RentalSession:
    id: UUID
    vehicle_id: UUID
    user_id: UUID
    status: RentalStatus
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None


@dataclass(frozen=True)
class HealthStatus:
    status: str
    database_connected: bool
    version: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# REPOSITORY INTERFACES
# ============================================================================

class VehicleRepository(Protocol):
    def get_by_id(self, vehicle_id: UUID) -> Optional[Vehicle]: ...
    def list(self, status: Optional[VehicleOperationalStatus] = None) -> List[Vehicle]: ...
    def save(self, vehicle: Vehicle) -> None: ...


class HealthRepository(Protocol):
    def check_database_connection(self) -> bool: ...


# ============================================================================
# USE-CASE HANDLERS / APPLICATION SERVICES
# ============================================================================

class SystemHealthService:
    def __init__(self, health_repo: HealthRepository, api_version: str = "1.0.0") -> None:
        self._health_repo = health_repo
        self._version = api_version

    def get_health_status(self) -> HealthStatus:
        db_ok = self._health_repo.check_database_connection()
        return HealthStatus(
            status="UP" if db_ok else "DEGRADED",
            database_connected=db_ok,
            version=self._version,
        )


class FleetManagementService:
    def __init__(self, vehicle_repo: VehicleRepository) -> None:
        self._vehicle_repo = vehicle_repo

    def list_vehicles(self, status: Optional[VehicleOperationalStatus] = None) -> List[Vehicle]:
        return self._vehicle_repo.list(status=status)

    def assign_vehicle_to_testbench(self, vehicle_id: UUID) -> Vehicle:
        vehicle = self._vehicle_repo.get_by_id(vehicle_id)
        if not vehicle:
            raise VehicleNotFoundError(f"Vehicle {vehicle_id} not found.")

        vehicle.transition_to_testbench()
        self._vehicle_repo.save(vehicle)
        return vehicle

    def return_vehicle_to_fleet(self, vehicle_id: UUID) -> Vehicle:
        vehicle = self._vehicle_repo.get_by_id(vehicle_id)
        if not vehicle:
            raise VehicleNotFoundError(f"Vehicle {vehicle_id} not found.")

        vehicle.release_to_available()
        self._vehicle_repo.save(vehicle)
        return vehicle


# ============================================================================
# IN-MEMORY IMPLEMENTATIONS (FOR TESTS & BENCHMARKS)
# ============================================================================

class InMemoryVehicleRepository(VehicleRepository):
    def __init__(self) -> None:
        self._store: Dict[UUID, Vehicle] = {}

    def get_by_id(self, vehicle_id: UUID) -> Optional[Vehicle]:
        return self._store.get(vehicle_id)

    def list(self, status: Optional[VehicleOperationalStatus] = None) -> List[Vehicle]:
        if status is None:
            return list(self._store.values())
        return [v for v in self._store.values() if v.status == status]

    def save(self, vehicle: Vehicle) -> None:
        self._store[vehicle.id] = vehicle


class MockHealthRepository(HealthRepository):
    def __init__(self, is_healthy: bool = True) -> None:
        self.is_healthy = is_healthy

    def check_database_connection(self) -> bool:
        return self.is_healthy


if __name__ == "__main__":
    # Smoke Test Initialization
    vehicle_repo = InMemoryVehicleRepository()
    health_repo = MockHealthRepository(is_healthy=True)

    health_svc = SystemHealthService(health_repo)
    fleet_svc = FleetManagementService(vehicle_repo)

    # 1. Check Health
    assert health_svc.get_health_status().status == "UP"

    # 2. Add and list vehicles
    v_id = uuid4()
    test_car = Vehicle(
        id=v_id,
        vin="1FA6P8CF0H5123456",
        model="AutoDrive Model-Alpha",
        autonomy_level=AutonomyLevel.LEVEL_4,
        status=VehicleOperationalStatus.AVAILABLE,
        battery_level_pct=98.5,
        components=[
            HardwareComponent(
                component_id=uuid4(),
                component_type=HardwareComponentType.LIDAR,
                serial_number="LID-449-01",
                firmware_version="2.4.1",
                healthy=True,
            )
        ],
    )
    vehicle_repo.save(test_car)

    # 3. Transition into TestBench session
    fleet_svc.assign_vehicle_to_testbench(v_id)
    assert vehicle_repo.get_by_id(v_id).status == VehicleOperationalStatus.TEST_BENCH_ACTIVE

    # 4. Release back to fleet
    fleet_svc.return_vehicle_to_fleet(v_id)
    assert vehicle_repo.get_by_id(v_id).status == VehicleOperationalStatus.AVAILABLE
    print("Core domain entities and use-case handlers initialized successfully.")
