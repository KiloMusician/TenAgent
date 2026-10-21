-- Production-grade 3NF Normalized SQL Schema
-- Target: PostgreSQL 14+
-- System: AutoDrive TestBench (Autonomous Rental Car & HIL/SIL Testing System)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- ENUM TYPES DEFINITIONS
-- ============================================================================

CREATE TYPE vehicle_operational_status AS ENUM (
    'AVAILABLE',
    'RESERVED',
    'DISPATCHING',
    'RENTAL_IN_PROGRESS',
    'TEST_BENCH_ACTIVE',
    'MAINTENANCE',
    'DECOMMISSIONED'
);

CREATE TYPE autonomy_level AS ENUM (
    'LEVEL_0',
    'LEVEL_1',
    'LEVEL_2',
    'LEVEL_3',
    'LEVEL_4',
    'LEVEL_5'
);

CREATE TYPE hardware_component_type AS ENUM (
    'LIDAR',
    'RADAR',
    'CAMERA',
    'ULTRASONIC',
    'COMPUTE_UNIT',
    'IMU',
    'GNSS_V2X',
    'ACTUATOR_STEERING',
    'ACTUATOR_BRAKING'
);

CREATE TYPE rental_status AS ENUM (
    'PENDING_DISPATCH',
    'ACTIVE',
    'COMPLETED',
    'CANCELLED',
    'EMERGENCY_HALTED'
);

CREATE TYPE test_execution_mode AS ENUM (
    'SIL_SIMULATION',
    'HIL_BENCH',
    'CONTROLLED_PROVING_GROUND',
    'SHADOW_FLEET_TEST'
);

CREATE TYPE test_outcome AS ENUM (
    'RUNNING',
    'PASSED',
    'FAILED_SAFETY_VIOLATION',
    'FAILED_SYSTEM_EXCEPTION',
    'ABORTED_BY_OPERATOR'
);

CREATE TYPE autonomy_mode_state AS ENUM (
    'MANUAL_OVERRIDE',
    'AUTONOMOUS_FULL',
    'AUTONOMOUS_DEGRADED',
    'REMOTE_TELEOPERATION',
    'EMERGENCY_STOP'
);

-- ============================================================================
-- UPDATED_AT TRIGGER FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION set_updated_at_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- CORE ENTITIES: GEOGRAPHIC & FLEET TOPOLOGY
-- ============================================================================

CREATE TABLE depots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    latitude NUMERIC(9, 6) NOT NULL,
    longitude NUMERIC(9, 6) NOT NULL,
    capacity INT NOT NULL CHECK (capacity > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_depot_lat CHECK (latitude BETWEEN -90.000000 AND 90.000000),
    CONSTRAINT chk_depot_lng CHECK (longitude BETWEEN -180.000000 AND 180.000000)
);

CREATE TRIGGER trg_depots_updated_at
BEFORE UPDATE ON depots
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE TABLE vehicles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vin VARCHAR(17) NOT NULL UNIQUE,
    license_plate VARCHAR(16) NOT NULL UNIQUE,
    make VARCHAR(64) NOT NULL,
    model VARCHAR(64) NOT NULL,
    model_year INT NOT NULL CHECK (model_year >= 2020),
    autonomy_level autonomy_level NOT NULL DEFAULT 'LEVEL_4',
    operational_status vehicle_operational_status NOT NULL DEFAULT 'AVAILABLE',
    current_depot_id UUID NULL,
    battery_capacity_kwh NUMERIC(5, 2) NOT NULL CHECK (battery_capacity_kwh > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_vehicles_current_depot FOREIGN KEY (current_depot_id) 
        REFERENCES depots(id) ON DELETE SET NULL
);

CREATE TRIGGER trg_vehicles_updated_at
BEFORE UPDATE ON vehicles
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE INDEX idx_vehicles_depot ON vehicles (current_depot_id);
CREATE INDEX idx_vehicles_status ON vehicles (operational_status);

-- ============================================================================
-- HARDWARE-IN-THE-LOOP (HIL) CONFIGURATION REGISTRY
-- ============================================================================

CREATE TABLE hardware_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    serial_number VARCHAR(128) NOT NULL UNIQUE,
    component_type hardware_component_type NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    firmware_version VARCHAR(64) NOT NULL,
    specification_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER trg_hardware_components_updated_at
BEFORE UPDATE ON hardware_components
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE TABLE vehicle_hardware_mounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vehicle_id UUID NOT NULL,
    hardware_component_id UUID NOT NULL,
    mount_position VARCHAR(64) NOT NULL,
    calibrated_at TIMESTAMPTZ NULL,
    uninstalled_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_mounts_vehicle FOREIGN KEY (vehicle_id) 
        REFERENCES vehicles(id) ON DELETE RESTRICT,
    CONSTRAINT fk_mounts_hardware FOREIGN KEY (hardware_component_id) 
        REFERENCES hardware_components(id) ON DELETE RESTRICT,
    CONSTRAINT uq_active_hardware_mount UNIQUE (vehicle_id, hardware_component_id, uninstalled_at)
);

CREATE TRIGGER trg_vehicle_hardware_mounts_updated_at
BEFORE UPDATE ON vehicle_hardware_mounts
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE INDEX idx_mounts_vehicle ON vehicle_hardware_mounts (vehicle_id);
CREATE INDEX idx_mounts_hardware ON vehicle_hardware_mounts (hardware_component_id);

-- ============================================================================
-- USERS & ACCESS MANAGEMENT
-- ============================================================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    full_name VARCHAR(128) NOT NULL,
    phone_e164 VARCHAR(16) NOT NULL UNIQUE,
    driving_license_hash VARCHAR(64) NOT NULL UNIQUE,
    is_safety_pilot BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

-- ============================================================================
-- RENTAL LIFECYCLE MANAGEMENT
-- ============================================================================

CREATE TABLE rentals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reservation_code VARCHAR(32) NOT NULL UNIQUE,
    user_id UUID NOT NULL,
    vehicle_id UUID NOT NULL,
    pickup_depot_id UUID NOT NULL,
    dropoff_depot_id UUID NOT NULL,
    rental_status rental_status NOT NULL DEFAULT 'PENDING_DISPATCH',
    scheduled_start_at TIMESTAMPTZ NOT NULL,
    scheduled_end_at TIMESTAMPTZ NOT NULL,
    actual_start_at TIMESTAMPTZ NULL,
    actual_end_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_rentals_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_rentals_vehicle FOREIGN KEY (vehicle_id) 
        REFERENCES vehicles(id) ON DELETE RESTRICT,
    CONSTRAINT fk_rentals_pickup_depot FOREIGN KEY (pickup_depot_id) 
        REFERENCES depots(id) ON DELETE RESTRICT,
    CONSTRAINT fk_rentals_dropoff_depot FOREIGN KEY (dropoff_depot_id) 
        REFERENCES depots(id) ON DELETE RESTRICT,
    CONSTRAINT chk_rental_schedule CHECK (scheduled_end_at > scheduled_start_at),
    CONSTRAINT chk_rental_actual CHECK (actual_end_at IS NULL OR actual_end_at >= actual_start_at)
);

CREATE TRIGGER trg_rentals_updated_at
BEFORE UPDATE ON rentals
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE INDEX idx_rentals_user ON rentals (user_id);
CREATE INDEX idx_rentals_vehicle ON rentals (vehicle_id);
CREATE INDEX idx_rentals_pickup_depot ON rentals (pickup_depot_id);
CREATE INDEX idx_rentals_dropoff_depot ON rentals (dropoff_depot_id);
CREATE INDEX idx_rentals_status ON rentals (rental_status);

-- ============================================================================
-- AUTONOMOUS TEST BENCH: SCENARIO & EXECUTION MANAGEMENT (SIL/HIL)
-- ============================================================================

CREATE TABLE test_scenarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    description TEXT NOT NULL,
    target_autonomy_level autonomy_level NOT NULL,
    scenario_matrix JSONB NOT NULL,
    max_duration_seconds INT NOT NULL CHECK (max_duration_seconds > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER trg_test_scenarios_updated_at
BEFORE UPDATE ON test_scenarios
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE TABLE test_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_scenario_id UUID NOT NULL,
    vehicle_id UUID NOT NULL,
    rental_id UUID NULL,
    execution_mode test_execution_mode NOT NULL,
    outcome test_outcome NOT NULL DEFAULT 'RUNNING',
    log_artifact_uri VARCHAR(512) NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_executions_scenario FOREIGN KEY (test_scenario_id) 
        REFERENCES test_scenarios(id) ON DELETE RESTRICT,
    CONSTRAINT fk_executions_vehicle FOREIGN KEY (vehicle_id) 
        REFERENCES vehicles(id) ON DELETE RESTRICT,
    CONSTRAINT fk_executions_rental FOREIGN KEY (rental_id) 
        REFERENCES rentals(id) ON DELETE SET NULL,
    CONSTRAINT chk_test_execution_timestamps CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TRIGGER trg_test_executions_updated_at
BEFORE UPDATE ON test_executions
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE INDEX idx_executions_scenario ON test_executions (test_scenario_id);
CREATE INDEX idx_executions_vehicle ON test_executions (vehicle_id);
CREATE INDEX idx_executions_rental ON test_executions (rental_id);
CREATE INDEX idx_executions_outcome ON test_executions (outcome);

-- ============================================================================
-- FAULT INJECTIONS (HIL/SIL TEST RUN ATTRIBUTES)
-- ============================================================================

CREATE TABLE fault_injections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_execution_id UUID NOT NULL,
    target_hardware_mount_id UUID NULL,
    fault_code VARCHAR(64) NOT NULL,
    fault_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    triggered_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ NULL,
    is_system_tolerant BOOLEAN NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_faults_execution FOREIGN KEY (test_execution_id) 
        REFERENCES test_executions(id) ON DELETE CASCADE,
    CONSTRAINT fk_faults_mount FOREIGN KEY (target_hardware_mount_id) 
        REFERENCES vehicle_hardware_mounts(id) ON DELETE SET NULL,
    CONSTRAINT chk_fault_times CHECK (resolved_at IS NULL OR resolved_at >= triggered_at)
);

CREATE TRIGGER trg_fault_injections_updated_at
BEFORE UPDATE ON fault_injections
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE INDEX idx_faults_execution ON fault_injections (test_execution_id);
CREATE INDEX idx_faults_mount ON fault_injections (target_hardware_mount_id);

-- ============================================================================
-- VEHICLE TELEMETRY SNAPSHOTS
-- ============================================================================

CREATE TABLE telemetry_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vehicle_id UUID NOT NULL,
    rental_id UUID NULL,
    test_execution_id UUID NULL,
    autonomy_mode autonomy_mode_state NOT NULL,
    latitude NUMERIC(9, 6) NOT NULL,
    longitude NUMERIC(9, 6) NOT NULL,
    altitude_meters NUMERIC(6, 2) NOT NULL,
    speed_kph NUMERIC(5, 2) NOT NULL CHECK (speed_kph >= 0),
    steering_angle_degrees NUMERIC(5, 2) NOT NULL,
    brake_pressure_psi NUMERIC(6, 2) NOT NULL CHECK (brake_pressure_psi >= 0),
    battery_level_pct NUMERIC(5, 2) NOT NULL CHECK (battery_level_pct BETWEEN 0.00 AND 100.00),
    recorded_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_telemetry_vehicle FOREIGN KEY (vehicle_id) 
        REFERENCES vehicles(id) ON DELETE RESTRICT,
    CONSTRAINT fk_telemetry_rental FOREIGN KEY (rental_id) 
        REFERENCES rentals(id) ON DELETE SET NULL,
    CONSTRAINT fk_telemetry_execution FOREIGN KEY (test_execution_id) 
        REFERENCES test_executions(id) ON DELETE SET NULL,
    CONSTRAINT chk_telemetry_lat CHECK (latitude BETWEEN -90.000000 AND 90.000000),
    CONSTRAINT chk_telemetry_lng CHECK (longitude BETWEEN -180.000000 AND 180.000000)
);

CREATE TRIGGER trg_telemetry_snapshots_updated_at
BEFORE UPDATE ON telemetry_snapshots
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE INDEX idx_telemetry_vehicle_time ON telemetry_snapshots (vehicle_id, recorded_at DESC);
CREATE INDEX idx_telemetry_rental ON telemetry_snapshots (rental_id);
CREATE INDEX idx_telemetry_execution ON telemetry_snapshots (test_execution_id);

-- ============================================================================
-- DISENGAGEMENTS & INTERVENTIONS
-- ============================================================================

CREATE TABLE autonomy_disengagements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vehicle_id UUID NOT NULL,
    rental_id UUID NULL,
    test_execution_id UUID NULL,
    trigger_source VARCHAR(64) NOT NULL,
    root_cause_classification VARCHAR(128) NOT NULL,
    latitude NUMERIC(9, 6) NOT NULL,
    longitude NUMERIC(9, 6) NOT NULL,
    disengaged_at TIMESTAMPTZ NOT NULL,
    system_action_taken VARCHAR(255) NOT NULL,
    operator_notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_disengagements_vehicle FOREIGN KEY (vehicle_id) 
        REFERENCES vehicles(id) ON DELETE RESTRICT,
    CONSTRAINT fk_disengagements_rental FOREIGN KEY (rental_id) 
        REFERENCES rentals(id) ON DELETE SET NULL,
    CONSTRAINT fk_disengagements_execution FOREIGN KEY (test_execution_id) 
        REFERENCES test_executions(id) ON DELETE SET NULL,
    CONSTRAINT chk_disengagement_lat CHECK (latitude BETWEEN -90.000000 AND 90.000000),
    CONSTRAINT chk_disengagement_lng CHECK (longitude BETWEEN -180.000000 AND 180.000000)
);

CREATE TRIGGER trg_autonomy_disengagements_updated_at
BEFORE UPDATE ON autonomy_disengagements
FOR EACH ROW EXECUTE FUNCTION set_updated_at_timestamp();

CREATE INDEX idx_disengagements_vehicle ON autonomy_disengagements (vehicle_id);
CREATE INDEX idx_disengagements_rental ON autonomy_disengagements (rental_id);
CREATE INDEX idx_disengagements_execution ON autonomy_disengagements (test_execution_id);
CREATE INDEX idx_disengagements_time ON autonomy_disengagements (disengaged_at DESC);
