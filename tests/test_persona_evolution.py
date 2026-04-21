"""
Tests for persona evolution engine.
"""

import pytest
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile
from mcp_server.persona_evolution import (
    PersonaEvolutionEngine,
    PersonaAxes,
    PersonaSignal,
    detect_action_from_context
)


@pytest.fixture
def persona_db():
    """Create temporary persona database."""
    with NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)

    yield db_path

    # Cleanup
    if db_path.exists():
        db_path.unlink()


def test_init_creates_schema(persona_db):
    """Test database schema initialization."""
    engine = PersonaEvolutionEngine(persona_db)

    conn = sqlite3.connect(str(persona_db))
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='persona_nodes'
    """)

    assert cursor.fetchone() is not None
    conn.close()


def test_extract_signals_create_workflow(persona_db):
    """Test signal extraction for workflow creation."""
    engine = PersonaEvolutionEngine(persona_db)

    signals = engine.extract_signals("create_ainl_workflow", {})

    assert len(signals) == 1
    assert signals[0].axis == PersonaAxes.CURIOSITY
    assert signals[0].reward > 0.7
    assert "exploring new tech" in signals[0].reason.lower()


def test_extract_signals_validate_before_run(persona_db):
    """Test signal extraction for validation."""
    engine = PersonaEvolutionEngine(persona_db)

    signals = engine.extract_signals("validate_before_run", {})

    assert len(signals) == 1
    assert signals[0].axis == PersonaAxes.SYSTEMATICITY
    assert signals[0].reward > 0.8


def test_extract_signals_run_immediately(persona_db):
    """Test signal extraction for immediate execution."""
    engine = PersonaEvolutionEngine(persona_db)

    signals = engine.extract_signals("run_immediately", {})

    assert len(signals) == 1
    assert signals[0].axis == PersonaAxes.INSTRUMENTALITY
    assert signals[0].reward > 0.7


def test_extract_signals_retry_after_failure(persona_db):
    """Test signal extraction for retry behavior."""
    engine = PersonaEvolutionEngine(persona_db)

    signals = engine.extract_signals("retry_after_failure", {})

    assert len(signals) == 1
    assert signals[0].axis == PersonaAxes.PERSISTENCE
    assert signals[0].reward > 0.85


def test_extract_signals_verbosity_high(persona_db):
    """Test signal extraction for requesting explanation."""
    engine = PersonaEvolutionEngine(persona_db)

    signals = engine.extract_signals("request_explanation", {})

    assert len(signals) == 1
    assert signals[0].axis == PersonaAxes.VERBOSITY
    assert signals[0].reward > 0.7


def test_extract_signals_verbosity_low(persona_db):
    """Test signal extraction for skipping explanation."""
    engine = PersonaEvolutionEngine(persona_db)

    signals = engine.extract_signals("skip_explanation", {})

    assert len(signals) == 1
    assert signals[0].axis == PersonaAxes.VERBOSITY
    assert signals[0].reward < 0.3


def test_extract_signals_modify_template(persona_db):
    """Test signal extraction for template modification."""
    engine = PersonaEvolutionEngine(persona_db)

    signals = engine.extract_signals("modify_template", {})

    # Should emit both curiosity and instrumentality
    assert len(signals) == 2
    axes = {s.axis for s in signals}
    assert PersonaAxes.CURIOSITY in axes
    assert PersonaAxes.INSTRUMENTALITY in axes


def test_ingest_signals_creates_axis(persona_db):
    """Test signal ingestion creates new axis."""
    engine = PersonaEvolutionEngine(persona_db)

    signal = PersonaSignal(
        axis=PersonaAxes.CURIOSITY,
        reward=0.8,
        weight=0.9,
        reason="Test signal"
    )

    engine.ingest_signals([signal])

    # Check axis was created
    conn = sqlite3.connect(str(persona_db))
    cursor = conn.execute("""
        SELECT strength, evolution_cycle FROM persona_nodes
        WHERE agent_id = ? AND axis_name = ?
    """, ("default", PersonaAxes.CURIOSITY))

    row = cursor.fetchone()
    assert row is not None

    strength, cycle = row
    # Should be between initial 0.5 and target (0.8 * 0.9 = 0.72)
    assert 0.5 <= strength <= 0.72
    assert cycle == 1

    conn.close()


def test_ingest_signals_ema_update(persona_db):
    """Test EMA update formula."""
    engine = PersonaEvolutionEngine(persona_db)

    # First signal: push toward 0.8
    signal1 = PersonaSignal(
        axis=PersonaAxes.CURIOSITY,
        reward=0.8,
        weight=1.0,
        reason="First"
    )
    engine.ingest_signals([signal1])

    # Get current strength
    conn = sqlite3.connect(str(persona_db))
    cursor = conn.execute("""
        SELECT strength FROM persona_nodes
        WHERE agent_id = ? AND axis_name = ?
    """, ("default", PersonaAxes.CURIOSITY))

    strength1 = cursor.fetchone()[0]

    # Expected: 0.5 + 0.3 * (0.8 - 0.5) = 0.59
    assert abs(strength1 - 0.59) < 0.01

    # Second signal: push toward 0.2
    signal2 = PersonaSignal(
        axis=PersonaAxes.CURIOSITY,
        reward=0.2,
        weight=1.0,
        reason="Second"
    )
    engine.ingest_signals([signal2])

    cursor = conn.execute("""
        SELECT strength FROM persona_nodes
        WHERE agent_id = ? AND axis_name = ?
    """, ("default", PersonaAxes.CURIOSITY))

    strength2 = cursor.fetchone()[0]

    # Expected: 0.59 + 0.3 * (0.2 - 0.59) = 0.473
    assert abs(strength2 - 0.473) < 0.01

    conn.close()


def test_correction_tick_drifts_toward_neutral(persona_db):
    """Test correction tick drifts axes toward 0.5."""
    engine = PersonaEvolutionEngine(persona_db)

    # Set axis to extreme value
    signal = PersonaSignal(
        axis=PersonaAxes.CURIOSITY,
        reward=1.0,
        weight=1.0,
        reason="Push high"
    )

    # Apply multiple times to get near 1.0
    for _ in range(10):
        engine.ingest_signals([signal])

    conn = sqlite3.connect(str(persona_db))
    cursor = conn.execute("""
        SELECT strength FROM persona_nodes
        WHERE agent_id = ? AND axis_name = ?
    """, ("default", PersonaAxes.CURIOSITY))

    strength_before = cursor.fetchone()[0]
    assert strength_before > 0.8  # Should be high

    # Apply correction tick
    engine.correction_tick()

    cursor = conn.execute("""
        SELECT strength FROM persona_nodes
        WHERE agent_id = ? AND axis_name = ?
    """, ("default", PersonaAxes.CURIOSITY))

    strength_after = cursor.fetchone()[0]

    # Should drift toward 0.5
    assert strength_after < strength_before
    assert abs(strength_after - 0.5) < abs(strength_before - 0.5)

    conn.close()


def test_get_active_traits_filtering(persona_db):
    """Test active traits filtering by threshold."""
    engine = PersonaEvolutionEngine(persona_db)

    # Create high-strength axis
    high_signal = PersonaSignal(
        axis=PersonaAxes.CURIOSITY,
        reward=0.9,
        weight=1.0,
        reason="High"
    )

    # Create low-strength axis
    low_signal = PersonaSignal(
        axis=PersonaAxes.VERBOSITY,
        reward=0.3,
        weight=1.0,
        reason="Low"
    )

    for _ in range(5):
        engine.ingest_signals([high_signal])
        engine.ingest_signals([low_signal])

    # Get active traits above 0.6
    active = engine.get_active_traits(min_strength=0.6)

    # Only curiosity should be active
    assert len(active) == 1
    assert active[0].axis_name == PersonaAxes.CURIOSITY
    assert active[0].strength >= 0.6


def test_format_traits_for_prompt(persona_db):
    """Test formatting traits for Claude context."""
    engine = PersonaEvolutionEngine(persona_db)

    # Create active trait
    signal = PersonaSignal(
        axis=PersonaAxes.INSTRUMENTALITY,
        reward=0.8,
        weight=1.0,
        reason="Hands-on"
    )

    for _ in range(5):
        engine.ingest_signals([signal])

    formatted = engine.format_traits_for_prompt(min_strength=0.6)

    assert "[User Persona Traits]" in formatted
    assert "instrumentality" in formatted.lower()
    assert "hands-on" in formatted.lower()


def test_detect_action_create_ainl(persona_db):
    """Test action detection for AINL creation."""
    action = detect_action_from_context(
        prompt="Create an AINL workflow to fetch data",
        previous_action=None,
        validation_result=None
    )

    assert action == "create_ainl_workflow"


def test_detect_action_validate(persona_db):
    """Test action detection for validation."""
    action = detect_action_from_context(
        prompt="Run this",
        previous_action=None,
        validation_result={"valid": True}
    )

    assert action == "validate_before_run"


def test_detect_action_retry(persona_db):
    """Test action detection for retry."""
    action = detect_action_from_context(
        prompt="Try again",
        previous_action="failure",
        validation_result=None
    )

    assert action == "retry_after_failure"


def test_get_all_axes(persona_db):
    """Test retrieving all axes including below threshold."""
    engine = PersonaEvolutionEngine(persona_db)

    # Create multiple axes
    signals = [
        PersonaSignal(PersonaAxes.CURIOSITY, 0.8, 1.0, "Test"),
        PersonaSignal(PersonaAxes.VERBOSITY, 0.3, 1.0, "Test"),
        PersonaSignal(PersonaAxes.PERSISTENCE, 0.6, 1.0, "Test")
    ]

    for signal in signals:
        engine.ingest_signals([signal])

    all_axes = engine.get_all_axes()

    assert len(all_axes) == 3
    assert PersonaAxes.CURIOSITY in all_axes
    assert PersonaAxes.VERBOSITY in all_axes
    assert PersonaAxes.PERSISTENCE in all_axes
