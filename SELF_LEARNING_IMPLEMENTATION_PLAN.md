# Self-Learning Implementation Plan for AINL Claude Code Plugin

**Date:** 2026-04-21  
**Status:** Ready for Implementation  
**Based on:** Deep analysis of AINL/ArmaraOS architecture + Hermes Agent patterns

---

## Executive Summary

This plan adds **graph-native self-learning** to the AINL Claude Code plugin by integrating the best patterns from:

1. **ArmaraOS** - Graph-as-memory, persona evolution, pattern extraction
2. **Hermes Agent** - Closed learning loop, trajectory capture, validation gates
3. **ainl-* crates** - Zero-LLM learning, semantic ranking, adaptive compression

**Goal:** Make Claude Code learn from every AINL interaction and get smarter over time, without requiring LLM introspection.

**Timeline:** 6 weeks (phased rollout)

---

## Architecture Overview

### Current State (Already Implemented)

✅ MCP tools (validate, compile, run, capabilities, security_report, ir_diff)  
✅ Pattern memory (`ainl_patterns` table with FTS5)  
✅ Detection hook (confidence scoring)  
✅ Auto-validation hook  
✅ Template library  
✅ Basic fitness scoring  

### New Additions (This Plan)

🆕 Trajectory capture & analysis  
🆕 Persona evolution (zero-LLM)  
🆕 Semantic fact recurrence tracking  
🆕 Failure → resolution learning  
🆕 Context-aware compression profiles  
🆕 Episodic tool sequence learning  
🆕 Multi-turn context compilation  
🆕 Closed loop validation gates  
🆕 Background consolidation  

---

## Phase 1: Foundation - Trajectory Capture (Week 1)

### Goal

Capture complete execution history for learning.

### Implementation

#### 1.1 Create `mcp_server/trajectory_capture.py`

```python
"""
Trajectory capture for AINL executions.
Logs every run for pattern analysis and learning.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import sqlite3

@dataclass
class TrajectoryStep:
    """Single step in AINL execution."""
    step_id: str
    timestamp: str
    adapter: str
    operation: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    duration_ms: float
    success: bool
    error: Optional[str] = None

@dataclass
class ExecutionTrajectory:
    """Complete AINL execution trace."""
    trajectory_id: str
    session_id: str
    project_id: str
    ainl_source_hash: str
    ainl_source: str
    frame_vars: Dict[str, Any]
    adapters_enabled: List[str]
    executed_at: str
    duration_ms: float
    outcome: str  # success/failure/partial
    steps: List[TrajectoryStep]
    tags: List[str]
    fitness_delta: float  # change in pattern fitness

class TrajectoryStore:
    """Store and retrieve AINL execution trajectories."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()
    
    def _init_schema(self):
        """Initialize trajectory storage schema."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trajectories (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                ainl_source_hash TEXT NOT NULL,
                ainl_source TEXT NOT NULL,
                frame_vars TEXT NOT NULL,  -- JSON
                adapters_enabled TEXT NOT NULL,  -- JSON array
                executed_at TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                outcome TEXT NOT NULL,
                steps TEXT NOT NULL,  -- JSONL
                tags TEXT NOT NULL,  -- JSON array
                fitness_delta REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_session ON trajectories(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_outcome ON trajectories(outcome)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_hash ON trajectories(ainl_source_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_project ON trajectories(project_id)")
        
        conn.commit()
        conn.close()
    
    def record_trajectory(self, trajectory: ExecutionTrajectory):
        """Record a complete execution trajectory."""
        conn = sqlite3.connect(str(self.db_path))
        
        conn.execute("""
            INSERT INTO trajectories 
            (id, session_id, project_id, ainl_source_hash, ainl_source, 
             frame_vars, adapters_enabled, executed_at, duration_ms, outcome, 
             steps, tags, fitness_delta, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trajectory.trajectory_id,
            trajectory.session_id,
            trajectory.project_id,
            trajectory.ainl_source_hash,
            trajectory.ainl_source,
            json.dumps(trajectory.frame_vars),
            json.dumps(trajectory.adapters_enabled),
            trajectory.executed_at,
            trajectory.duration_ms,
            trajectory.outcome,
            '\n'.join(json.dumps(asdict(s)) for s in trajectory.steps),
            json.dumps(trajectory.tags),
            trajectory.fitness_delta,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
    
    def get_recent_trajectories(self, session_id: str, limit: int = 10) -> List[ExecutionTrajectory]:
        """Get recent trajectories for a session."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("""
            SELECT * FROM trajectories
            WHERE session_id = ?
            ORDER BY executed_at DESC
            LIMIT ?
        """, (session_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_trajectory(row) for row in rows]
    
    def get_trajectories_by_hash(self, source_hash: str) -> List[ExecutionTrajectory]:
        """Get all trajectories for a specific AINL source."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("""
            SELECT * FROM trajectories
            WHERE ainl_source_hash = ?
            ORDER BY executed_at DESC
        """, (source_hash,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_trajectory(row) for row in rows]
    
    def _row_to_trajectory(self, row) -> ExecutionTrajectory:
        """Convert DB row to ExecutionTrajectory."""
        steps = [TrajectoryStep(**json.loads(line)) for line in row[10].split('\n')]
        
        return ExecutionTrajectory(
            trajectory_id=row[0],
            session_id=row[1],
            project_id=row[2],
            ainl_source_hash=row[3],
            ainl_source=row[4],
            frame_vars=json.loads(row[5]),
            adapters_enabled=json.loads(row[6]),
            executed_at=row[7],
            duration_ms=row[8],
            outcome=row[9],
            steps=steps,
            tags=json.loads(row[11]),
            fitness_delta=row[12]
        )

def capture_trajectory_from_run(
    ainl_source: str,
    frame: Dict[str, Any],
    adapters: Dict[str, Any],
    result: Dict[str, Any],
    session_id: str,
    project_id: str
) -> ExecutionTrajectory:
    """
    Capture trajectory from ainl_run execution.
    Hook this into mcp_server/ainl_tools.py run() method.
    """
    import hashlib
    
    source_hash = hashlib.sha256(ainl_source.encode()).hexdigest()[:16]
    
    # Extract steps from result (runtime provides this)
    steps = []
    if 'steps' in result:
        for step in result['steps']:
            steps.append(TrajectoryStep(
                step_id=str(uuid.uuid4()),
                timestamp=step.get('timestamp', datetime.now().isoformat()),
                adapter=step.get('adapter', 'unknown'),
                operation=step.get('operation', ''),
                inputs=step.get('inputs', {}),
                outputs=step.get('outputs', {}),
                duration_ms=step.get('duration_ms', 0),
                success=step.get('success', False),
                error=step.get('error')
            ))
    
    # Determine outcome
    outcome = 'success' if result.get('success') else 'failure'
    if result.get('partial_success'):
        outcome = 'partial'
    
    # Extract tags (adapters used)
    tags = list(adapters.get('enable', []))
    
    trajectory = ExecutionTrajectory(
        trajectory_id=str(uuid.uuid4()),
        session_id=session_id,
        project_id=project_id,
        ainl_source_hash=source_hash,
        ainl_source=ainl_source,
        frame_vars=frame,
        adapters_enabled=tags,
        executed_at=datetime.now().isoformat(),
        duration_ms=result.get('duration_ms', 0),
        outcome=outcome,
        steps=steps,
        tags=tags,
        fitness_delta=0.0  # calculated by pattern analyzer
    )
    
    return trajectory
```

#### 1.2 Integrate into `ainl_tools.py`

```python
# In mcp_server/ainl_tools.py

from .trajectory_capture import TrajectoryStore, capture_trajectory_from_run

class AINLTools:
    def __init__(self):
        # ... existing init ...
        self.trajectory_store = TrajectoryStore(
            self.db_path.parent / "ainl_trajectories.db"
        )
    
    def run(self, source: str, frame: dict, adapters: dict, 
            session_id: str = None, project_id: str = None):
        """Execute AINL workflow with trajectory capture."""
        
        # Existing run logic
        result = self._execute_ainl(source, frame, adapters)
        
        # Capture trajectory
        if session_id and project_id:
            trajectory = capture_trajectory_from_run(
                ainl_source=source,
                frame=frame,
                adapters=adapters,
                result=result,
                session_id=session_id,
                project_id=project_id
            )
            
            self.trajectory_store.record_trajectory(trajectory)
            
            # Update pattern fitness based on outcome
            if trajectory.outcome == 'success':
                self._update_pattern_fitness(trajectory, delta=+0.05)
            elif trajectory.outcome == 'failure':
                self._update_pattern_fitness(trajectory, delta=-0.03)
        
        return result
```

#### 1.3 Add Pattern Recurrence Tracking

```python
# In mcp_server/ainl_patterns.py

def track_recurrence(self, pattern_id: str, outcome: str):
    """Track pattern recurrence and update fitness."""
    conn = sqlite3.connect(str(self.db_path))
    
    # Get current pattern
    cursor = conn.execute(
        "SELECT uses, successes, failures, fitness_score FROM ainl_patterns WHERE id = ?",
        (pattern_id,)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return
    
    uses, successes, failures, fitness = row
    
    # Update counts
    uses += 1
    if outcome == 'success':
        successes += 1
    elif outcome == 'failure':
        failures += 1
    
    # Calculate new fitness (EMA-style)
    success_rate = successes / uses if uses > 0 else 0.0
    alpha = 0.3  # EMA smoothing factor
    new_fitness = alpha * success_rate + (1 - alpha) * fitness
    
    # Update DB
    conn.execute("""
        UPDATE ainl_patterns
        SET uses = ?, successes = ?, failures = ?, fitness_score = ?, last_seen = ?
        WHERE id = ?
    """, (uses, successes, failures, new_fitness, datetime.now().isoformat(), pattern_id))
    
    conn.commit()
    conn.close()
```

### Testing

```python
# tests/test_trajectory_capture.py

def test_trajectory_recording():
    """Test trajectory capture and storage."""
    store = TrajectoryStore(Path("/tmp/test_trajectories.db"))
    
    trajectory = ExecutionTrajectory(
        trajectory_id="test-123",
        session_id="session-1",
        project_id="project-1",
        ainl_source_hash="abc123",
        ainl_source="L1:\\n  R core.ADD 2 3 ->sum",
        frame_vars={},
        adapters_enabled=["core"],
        executed_at=datetime.now().isoformat(),
        duration_ms=50.0,
        outcome="success",
        steps=[],
        tags=["core", "math"],
        fitness_delta=0.05
    )
    
    store.record_trajectory(trajectory)
    
    # Verify retrieval
    trajectories = store.get_recent_trajectories("session-1")
    assert len(trajectories) == 1
    assert trajectories[0].outcome == "success"
```

---

## Phase 2: Persona Evolution (Week 2)

### Goal

Implement zero-LLM persona learning via soft axes.

### Implementation

#### 2.1 Create `mcp_server/persona_evolution.py`

```python
"""
Zero-LLM persona evolution via soft axes.
Learn user preferences from behavior, not LLM introspection.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime
import sqlite3
from pathlib import Path

@dataclass
class PersonaAxis:
    """Single persona axis with EMA evolution."""
    axis_name: str
    strength: float  # 0.0-1.0
    evolution_cycle: int
    last_updated: str

class PersonaAxes:
    """5 core persona axes."""
    
    INSTRUMENTALITY = "instrumentality"  # Prefers hands-on action vs guidance
    CURIOSITY = "curiosity"              # Explores new features actively
    PERSISTENCE = "persistence"          # Retries on failure vs gives up
    SYSTEMATICITY = "systematicity"      # Validates before acting
    VERBOSITY = "verbosity"              # Detailed explanations vs terse

    @staticmethod
    def all_axes() -> List[str]:
        return [
            PersonaAxes.INSTRUMENTALITY,
            PersonaAxes.CURIOSITY,
            PersonaAxes.PERSISTENCE,
            PersonaAxes.SYSTEMATICITY,
            PersonaAxes.VERBOSITY
        ]

@dataclass
class PersonaSignal:
    """Signal to update persona axes."""
    axis: str
    reward: float  # Target value (0.0-1.0)
    weight: float  # Signal strength (0.0-1.0)
    reason: str

class PersonaEvolutionEngine:
    """Evolve persona axes via weighted EMA."""
    
    EMA_ALPHA = 0.3  # Smoothing factor
    CORRECTION_RATE = 0.05  # Drift toward 0.5 when idle
    
    def __init__(self, db_path: Path, agent_id: str = "default"):
        self.db_path = db_path
        self.agent_id = agent_id
        self._init_schema()
    
    def _init_schema(self):
        """Initialize persona storage."""
        conn = sqlite3.connect(str(self.db_path))
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS persona_nodes (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                axis_name TEXT NOT NULL,
                strength REAL NOT NULL,
                evolution_cycle INTEGER NOT NULL,
                last_updated TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_persona_agent_axis ON persona_nodes(agent_id, axis_name)")
        
        conn.commit()
        conn.close()
    
    def extract_signals(self, action: str, context: Dict) -> List[PersonaSignal]:
        """Extract persona signals from user action."""
        signals = []
        
        # AINL workflow creation → curiosity (exploring new tech)
        if action == "create_ainl_workflow":
            signals.append(PersonaSignal(
                axis=PersonaAxes.CURIOSITY,
                reward=0.75,
                weight=0.8,
                reason="User creating AINL workflow (exploring new tech)"
            ))
        
        # Validation before running → systematicity
        if action == "validate_before_run":
            signals.append(PersonaSignal(
                axis=PersonaAxes.SYSTEMATICITY,
                reward=0.85,
                weight=0.9,
                reason="User validates before running (methodical approach)"
            ))
        
        # Run immediately without validation → instrumentality
        if action == "run_immediately":
            signals.append(PersonaSignal(
                axis=PersonaAxes.INSTRUMENTALITY,
                reward=0.8,
                weight=0.7,
                reason="User runs immediately (hands-on, action-oriented)"
            ))
        
        # Retry after failure → persistence
        if action == "retry_after_failure":
            signals.append(PersonaSignal(
                axis=PersonaAxes.PERSISTENCE,
                reward=0.9,
                weight=0.85,
                reason="User retries after failure (persistent)"
            ))
        
        # Ask for detailed explanation → verbosity
        if action == "request_explanation":
            signals.append(PersonaSignal(
                axis=PersonaAxes.VERBOSITY,
                reward=0.8,
                weight=0.75,
                reason="User requests detailed explanation (prefers verbosity)"
            ))
        
        # Skip explanation, just do it → verbosity (low)
        if action == "skip_explanation":
            signals.append(PersonaSignal(
                axis=PersonaAxes.VERBOSITY,
                reward=0.2,
                weight=0.7,
                reason="User wants action without explanation (prefers terseness)"
            ))
        
        return signals
    
    def ingest_signals(self, signals: List[PersonaSignal]):
        """Apply signals to persona axes via weighted EMA."""
        conn = sqlite3.connect(str(self.db_path))
        
        for signal in signals:
            # Get current axis state
            cursor = conn.execute("""
                SELECT strength, evolution_cycle FROM persona_nodes
                WHERE agent_id = ? AND axis_name = ?
            """, (self.agent_id, signal.axis))
            
            row = cursor.fetchone()
            
            if row:
                current_strength, cycle = row
            else:
                # Initialize at 0.5 (neutral)
                current_strength = 0.5
                cycle = 0
            
            # Weighted EMA update
            # new_strength = alpha * (reward * weight) + (1 - alpha) * current_strength
            delta = signal.reward * signal.weight - current_strength
            new_strength = current_strength + self.EMA_ALPHA * delta
            
            # Clamp to [0, 1]
            new_strength = max(0.0, min(1.0, new_strength))
            
            # Increment cycle
            new_cycle = cycle + 1
            
            # Upsert
            conn.execute("""
                INSERT INTO persona_nodes 
                (id, agent_id, axis_name, strength, evolution_cycle, last_updated, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id, axis_name) DO UPDATE SET
                    strength = ?,
                    evolution_cycle = ?,
                    last_updated = ?
            """, (
                f"{self.agent_id}_{signal.axis}",
                self.agent_id,
                signal.axis,
                new_strength,
                new_cycle,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                new_strength,
                new_cycle,
                datetime.now().isoformat()
            ))
        
        conn.commit()
        conn.close()
    
    def correction_tick(self):
        """Drift axes toward 0.5 when no signals (prevents overfitting)."""
        conn = sqlite3.connect(str(self.db_path))
        
        cursor = conn.execute("""
            SELECT axis_name, strength, evolution_cycle FROM persona_nodes
            WHERE agent_id = ?
        """, (self.agent_id,))
        
        rows = cursor.fetchall()
        
        for axis_name, strength, cycle in rows:
            # Drift toward 0.5
            delta = 0.5 - strength
            new_strength = strength + self.CORRECTION_RATE * delta
            
            conn.execute("""
                UPDATE persona_nodes
                SET strength = ?, last_updated = ?
                WHERE agent_id = ? AND axis_name = ?
            """, (new_strength, datetime.now().isoformat(), self.agent_id, axis_name))
        
        conn.commit()
        conn.close()
    
    def get_active_traits(self, min_strength: float = 0.6) -> List[PersonaAxis]:
        """Get persona traits above strength threshold."""
        conn = sqlite3.connect(str(self.db_path))
        
        cursor = conn.execute("""
            SELECT axis_name, strength, evolution_cycle, last_updated
            FROM persona_nodes
            WHERE agent_id = ? AND strength >= ?
            ORDER BY strength DESC
        """, (self.agent_id, min_strength))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [PersonaAxis(*row) for row in rows]
    
    def format_traits_for_prompt(self, min_strength: float = 0.6) -> str:
        """Format active traits for Claude context injection."""
        traits = self.get_active_traits(min_strength)
        
        if not traits:
            return ""
        
        lines = ["[User Persona Traits]"]
        for trait in traits:
            description = self._trait_description(trait.axis_name, trait.strength)
            lines.append(f"- {trait.axis_name}: {trait.strength:.2f} ({description})")
        
        return "\n".join(lines)
    
    def _trait_description(self, axis: str, strength: float) -> str:
        """Human-readable trait description."""
        if axis == PersonaAxes.INSTRUMENTALITY:
            if strength > 0.7:
                return "prefers hands-on action"
            elif strength < 0.3:
                return "prefers guidance and explanation"
            else:
                return "balanced action/guidance"
        
        elif axis == PersonaAxes.CURIOSITY:
            if strength > 0.7:
                return "actively explores new features"
            elif strength < 0.3:
                return "sticks to familiar patterns"
            else:
                return "moderate exploration"
        
        elif axis == PersonaAxes.PERSISTENCE:
            if strength > 0.7:
                return "retries multiple times on failure"
            elif strength < 0.3:
                return "gives up quickly on errors"
            else:
                return "moderate persistence"
        
        elif axis == PersonaAxes.SYSTEMATICITY:
            if strength > 0.7:
                return "validates before acting (methodical)"
            elif strength < 0.3:
                return "acts quickly without validation"
            else:
                return "balanced validation"
        
        elif axis == PersonaAxes.VERBOSITY:
            if strength > 0.7:
                return "prefers detailed explanations"
            elif strength < 0.3:
                return "prefers terse responses"
            else:
                return "balanced verbosity"
        
        return "neutral"
```

#### 2.2 Hook into AINL Detection

```python
# In hooks/ainl_detection.py

from mcp_server.persona_evolution import PersonaEvolutionEngine, PersonaSignal, PersonaAxes

class AINLDetector:
    def __init__(self):
        # ... existing init ...
        self.persona_engine = PersonaEvolutionEngine(
            db_path=self.db_path.parent / "persona.db"
        )
    
    def record_user_action(self, action: str, context: Dict):
        """Record user action and extract persona signals."""
        signals = self.persona_engine.extract_signals(action, context)
        if signals:
            self.persona_engine.ingest_signals(signals)
```

#### 2.3 Inject Traits into Claude Context

```python
# When detection hook fires (UserPromptSubmit)

def on_user_prompt_submit(self, prompt: str):
    # ... existing detection logic ...
    
    # Get persona traits
    traits_block = self.persona_engine.format_traits_for_prompt(min_strength=0.6)
    
    # Inject into context
    if traits_block and self.should_suggest_ainl(prompt):
        context = f"""
{traits_block}

[AINL Suggestion]
Based on your persona traits and this request, AINL is recommended...
"""
        return context
```

### Testing

```python
# tests/test_persona_evolution.py

def test_persona_signal_extraction():
    """Test signal extraction from user actions."""
    engine = PersonaEvolutionEngine(Path("/tmp/test_persona.db"))
    
    signals = engine.extract_signals("create_ainl_workflow", {})
    assert len(signals) == 1
    assert signals[0].axis == PersonaAxes.CURIOSITY

def test_persona_ema_update():
    """Test EMA-based persona updates."""
    engine = PersonaEvolutionEngine(Path("/tmp/test_persona.db"))
    
    # Start at neutral (0.5)
    signal = PersonaSignal(
        axis=PersonaAxes.CURIOSITY,
        reward=0.8,
        weight=0.9,
        reason="Test"
    )
    
    engine.ingest_signals([signal])
    
    traits = engine.get_active_traits(min_strength=0.0)
    curiosity = next(t for t in traits if t.axis_name == PersonaAxes.CURIOSITY)
    
    # Should move toward 0.8
    assert curiosity.strength > 0.5
    assert curiosity.strength < 0.8
    assert curiosity.evolution_cycle == 1
```

---

## Phase 3: Smart Suggestions (Week 3)

### Goal

Proactive pattern suggestions and failure prevention.

### Implementation

#### 3.1 Semantic Fact Ranking

```python
# In mcp_server/ainl_patterns.py

import math

def get_ranked_facts(
    self, 
    project_id: str, 
    min_confidence: float = 0.5, 
    limit: int = 5
) -> List[Dict]:
    """Get semantic facts ranked by confidence × recurrence × recency."""
    conn = sqlite3.connect(str(self.db_path))
    
    cursor = conn.execute("""
        SELECT id, pattern_type, description, fitness_score, uses, 
               successes, adapters_used, tags, last_seen
        FROM ainl_patterns
        WHERE project_id = ? AND fitness_score >= ?
        ORDER BY fitness_score DESC, uses DESC
        LIMIT ?
    """, (project_id, min_confidence, limit * 2))  # Get extra for ranking
    
    rows = cursor.fetchall()
    conn.close()
    
    facts = []
    now = datetime.now()
    
    for row in rows:
        last_seen = datetime.fromisoformat(row[8])
        days_old = (now - last_seen).days
        
        # Recency weight (exponential decay)
        recency_weight = math.exp(-days_old / 30.0)  # Half-life of 30 days
        
        # Recurrence weight (logarithmic)
        recurrence_weight = 1 + math.log(1 + row[4])  # uses
        
        # Combined rank
        rank_score = row[3] * recurrence_weight * recency_weight  # fitness × recurrence × recency
        
        facts.append({
            'id': row[0],
            'type': row[1],
            'description': row[2],
            'fitness_score': row[3],
            'uses': row[4],
            'rank_score': rank_score,
            'adapters': json.loads(row[6]),
            'tags': json.loads(row[7])
        })
    
    # Sort by rank and return top N
    facts.sort(key=lambda f: f['rank_score'], reverse=True)
    return facts[:limit]
```

#### 3.2 Failure Resolution Learning

```python
# Create mcp_server/failure_learning.py

"""
Learn from failures and suggest resolutions.
"""

import sqlite3
from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime
from pathlib import Path

@dataclass
class FailureResolution:
    """Failure with optional resolution."""
    id: str
    error_type: str
    error_message: str
    ainl_source: str
    context: Dict
    resolution: Optional[str]
    resolution_diff: Optional[str]
    prevented_count: int
    created_at: str
    resolved_at: Optional[str]

class FailureLearningStore:
    """Store and retrieve failure resolutions."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()
    
    def _init_schema(self):
        conn = sqlite3.connect(str(self.db_path))
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS failure_resolutions (
                id TEXT PRIMARY KEY,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                ainl_source TEXT NOT NULL,
                context TEXT NOT NULL,  -- JSON
                resolution TEXT,
                resolution_diff TEXT,
                prevented_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
        """)
        
        # FTS5 index for error message search
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS failure_search USING fts5(
                failure_id,
                error_message,
                error_type
            )
        """)
        
        conn.commit()
        conn.close()
    
    def record_failure(
        self, 
        error_type: str, 
        error_message: str, 
        ainl_source: str, 
        context: Dict
    ) -> str:
        """Record a validation failure."""
        import uuid, json
        
        failure_id = str(uuid.uuid4())
        
        conn = sqlite3.connect(str(self.db_path))
        
        conn.execute("""
            INSERT INTO failure_resolutions
            (id, error_type, error_message, ainl_source, context, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            failure_id,
            error_type,
            error_message,
            ainl_source,
            json.dumps(context),
            datetime.now().isoformat()
        ))
        
        conn.execute("""
            INSERT INTO failure_search (failure_id, error_message, error_type)
            VALUES (?, ?, ?)
        """, (failure_id, error_message, error_type))
        
        conn.commit()
        conn.close()
        
        return failure_id
    
    def record_resolution(self, failure_id: str, fixed_source: str):
        """Record resolution when failure is fixed."""
        import difflib
        
        conn = sqlite3.connect(str(self.db_path))
        
        # Get original source
        cursor = conn.execute(
            "SELECT ainl_source FROM failure_resolutions WHERE id = ?",
            (failure_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return
        
        original = row[0]
        
        # Generate diff
        diff = '\n'.join(difflib.unified_diff(
            original.splitlines(),
            fixed_source.splitlines(),
            lineterm='',
            n=3
        ))
        
        # Update with resolution
        conn.execute("""
            UPDATE failure_resolutions
            SET resolution = ?, resolution_diff = ?, resolved_at = ?
            WHERE id = ?
        """, (fixed_source, diff, datetime.now().isoformat(), failure_id))
        
        conn.commit()
        conn.close()
    
    def find_similar_failures(self, error_message: str, limit: int = 5) -> List[FailureResolution]:
        """Find similar failures via FTS5 search."""
        conn = sqlite3.connect(str(self.db_path))
        
        # FTS5 search
        cursor = conn.execute("""
            SELECT f.id, f.error_type, f.error_message, f.ainl_source, 
                   f.context, f.resolution, f.resolution_diff, f.prevented_count,
                   f.created_at, f.resolved_at
            FROM failure_search fs
            JOIN failure_resolutions f ON fs.failure_id = f.id
            WHERE failure_search MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (error_message, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_failure(row) for row in rows]
    
    def increment_prevented(self, failure_id: str):
        """Increment prevented count (user accepted suggestion)."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            UPDATE failure_resolutions
            SET prevented_count = prevented_count + 1
            WHERE id = ?
        """, (failure_id,))
        conn.commit()
        conn.close()
    
    def _row_to_failure(self, row) -> FailureResolution:
        import json
        return FailureResolution(
            id=row[0],
            error_type=row[1],
            error_message=row[2],
            ainl_source=row[3],
            context=json.loads(row[4]),
            resolution=row[5],
            resolution_diff=row[6],
            prevented_count=row[7],
            created_at=row[8],
            resolved_at=row[9]
        )
```

#### 3.3 Hook into Validation

```python
# In hooks/ainl_validator.py

from mcp_server.failure_learning import FailureLearningStore

class AINLValidator:
    def __init__(self):
        # ... existing init ...
        self.failure_store = FailureLearningStore(
            self.db_path.parent / "failures.db"
        )
    
    def on_validation_failure(self, source: str, diagnostics: Dict):
        """Record failure and suggest resolution if known."""
        
        # Record failure
        failure_id = self.failure_store.record_failure(
            error_type=diagnostics.get('error_type', 'unknown'),
            error_message=diagnostics.get('error', ''),
            ainl_source=source,
            context={'file': diagnostics.get('file')}
        )
        
        # Search for similar failures with resolutions
        similar = self.failure_store.find_similar_failures(
            error_message=diagnostics.get('error', ''),
            limit=3
        )
        
        resolved = [f for f in similar if f.resolution]
        
        if resolved:
            # Suggest resolution
            best_match = resolved[0]
            suggestion = f"""
❌ AINL Validation: {diagnostics.get('file')}

Error: {diagnostics.get('error')}

💡 I've seen this error before. The fix was:
{best_match.resolution_diff}

Would you like me to apply this fix?
"""
            return suggestion, failure_id
        
        return None, failure_id
    
    def on_validation_success_after_failure(self, failure_id: str, fixed_source: str):
        """User fixed the failure - record resolution."""
        self.failure_store.record_resolution(failure_id, fixed_source)
```

---

## Phase 4-6: Continued in Next Message

The plan continues with:

- **Phase 4:** Context-aware compression profiles
- **Phase 5:** Closed loop validation gates
- **Phase 6:** Multi-turn context compilation

Would you like me to:
1. Continue with phases 4-6 in detail?
2. Start implementing Phase 1 code?
3. Create integration tests for the self-learning features?
