"""
AINL Graph Memory Node Types

Typed node definitions inspired by ainl-memory/src/node.rs
Each node type has a well-defined JSON schema in the data field.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Literal
from enum import Enum
import uuid
import time


class NodeType(str, Enum):
    """Node type enum (matches ainl-memory AinlNodeKind)"""
    EPISODE = "episode"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PERSONA = "persona"
    FAILURE = "failure"
    RUNTIME_STATE = "runtime_state"
    GOAL = "goal"


class EdgeType(str, Enum):
    """Edge type enum (matches ainl-memory edge types)"""
    FOLLOWS = "FOLLOWS"              # Episode timeline
    MENTIONS = "MENTIONS"            # References entity
    TOUCHES = "TOUCHES"              # Modified file/entity
    DEPENDS_ON = "DEPENDS_ON"        # Dependency relationship
    FIXED_BY = "FIXED_BY"            # Failure → Fix episode
    DERIVES_FROM = "DERIVES_FROM"    # Semantic → Source episode
    RELATED_TO = "RELATED_TO"        # General association
    PATTERN_FOR = "PATTERN_FOR"      # Procedural → Context
    OCCURRED_IN = "OCCURRED_IN"      # Event → Episode
    RESOLVES = "RESOLVES"            # Fix → Failure
    EMIT_TO = "EMIT_TO"              # Episode → Output target
    LEARNED_FROM = "LEARNED_FROM"    # Persona → Evidence episodes
    REFERENCES = "REFERENCES"        # Semantic → Referenced entity
    A2A_THREAD = "A2A_THREAD"        # A2A message → thread (links messages in same thread)
    GOAL_TRACKS = "GOAL_TRACKS"      # Goal → Episode (episode contributed to this goal)


@dataclass
class GraphNode:
    """
    Core graph node structure (matches ainl-memory AinlMemoryNode).

    The data field contains type-specific payload matching node_type.
    """
    id: str
    node_type: NodeType
    project_id: str
    created_at: int
    updated_at: int
    confidence: float
    data: Dict[str, Any]
    agent_id: str = "claude-code"
    metadata: Optional[Dict[str, Any]] = None
    embedding_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        result = asdict(self)
        result['node_type'] = self.node_type.value
        return result

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'GraphNode':
        """Create from dict"""
        d = d.copy()
        d['node_type'] = NodeType(d['node_type'])
        return cls(**d)


@dataclass
class GraphEdge:
    """Typed graph edge (matches ainl-memory AinlEdge)"""
    id: str
    edge_type: EdgeType
    from_node: str
    to_node: str
    created_at: int
    confidence: float
    project_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization"""
        result = asdict(self)
        result['edge_type'] = self.edge_type.value
        return result

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'GraphEdge':
        """Create from dict"""
        d = d.copy()
        d['edge_type'] = EdgeType(d['edge_type'])
        return cls(**d)


# ============================================================================
# Node Data Schemas (type-specific payloads)
# ============================================================================

@dataclass
class EpisodeData:
    """
    Episode node data (matches ainl-memory EpisodicNode).
    Records what happened during a coding turn.
    """
    turn_id: str
    task_description: str
    tool_calls: List[str]           # Canonicalized tool names
    files_touched: List[str]
    outcome: Literal["success", "failure", "partial"]
    duration_ms: Optional[int] = None
    git_commit: Optional[str] = None
    test_results: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class SemanticData:
    """
    Semantic node data (matches ainl-memory SemanticNode).
    Records facts learned with confidence scores.
    """
    fact: str
    topic_cluster: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    recurrence_count: int = 1
    reference_count: int = 0
    source_turn_id: Optional[str] = None


@dataclass
class ProceduralData:
    """
    Procedural node data (matches ainl-memory ProceduralNode).
    Records reusable workflow patterns.
    """
    pattern_name: str
    trigger: str
    tool_sequence: List[str]        # Canonicalized
    success_count: int = 0
    failure_count: int = 0
    fitness: float = 1.0            # EMA fitness score
    last_used_at: Optional[int] = None
    scope: Literal["project", "global"] = "project"
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class PersonaData:
    """
    Persona node data (matches ainl-memory PersonaNode).
    Records evolving developer/project traits.
    """
    trait_name: str
    strength: float                 # 0.0-1.0
    layer: Literal["base", "adaptive", "dynamic"] = "adaptive"
    learned_from: List[str] = field(default_factory=list)  # Episode IDs
    axis: Optional[str] = None
    decay_rate: float = 0.95


@dataclass
class FailureData:
    """
    Failure node data.
    Records errors and their resolutions.
    """
    error_type: str
    tool: str
    command: Optional[str] = None
    error_message: str = ""
    file: Optional[str] = None
    line: Optional[int] = None
    stack_trace: Optional[str] = None
    resolution: Optional[str] = None
    resolution_turn_id: Optional[str] = None
    resolved_at: Optional[int] = None


@dataclass
class GoalData:
    """
    Goal node data.
    Persists multi-session intent and tracks progress toward a named objective.
    """
    title: str
    description: str
    status: Literal["active", "completed", "abandoned", "blocked"] = "active"
    completion_criteria: Optional[str] = None
    progress_notes: List[Dict[str, Any]] = field(default_factory=list)  # [{ts, note}]
    contributing_episodes: List[str] = field(default_factory=list)      # episode node IDs
    tags: List[str] = field(default_factory=list)
    created_session: Optional[str] = None
    last_active_session: Optional[str] = None
    inferred: bool = False   # True if auto-inferred, False if explicitly set


@dataclass
class RuntimeStateData:
    """
    Runtime state node data (matches ainl-memory RuntimeStateNode).
    One stable node per project for session persistence.
    """
    turn_count: int = 0
    last_extraction_at_turn: int = 0
    persona_snapshot_json: Optional[str] = None
    extraction_interval: int = 10
    updated_at: int = field(default_factory=lambda: int(time.time()))


# ============================================================================
# Node Factory Functions
# ============================================================================

def create_episode_node(
    project_id: str,
    task_description: str,
    tool_calls: List[str],
    files_touched: List[str],
    outcome: Literal["success", "failure", "partial"],
    **kwargs
) -> GraphNode:
    """Create an episode node with proper structure"""
    turn_id = str(uuid.uuid4())
    now = int(time.time())

    episode_data = EpisodeData(
        turn_id=turn_id,
        task_description=task_description,
        tool_calls=tool_calls,
        files_touched=files_touched,
        outcome=outcome,
        **{k: v for k, v in kwargs.items() if k in EpisodeData.__annotations__}
    )

    # Build embedding text for FTS
    embedding_text = f"{task_description} {' '.join(tool_calls)} {' '.join(files_touched)}"

    return GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.EPISODE,
        project_id=project_id,
        created_at=now,
        updated_at=now,
        confidence=1.0,
        data=asdict(episode_data),
        embedding_text=embedding_text
    )


def create_semantic_node(
    project_id: str,
    fact: str,
    confidence: float,
    source_turn_id: Optional[str] = None,
    **kwargs
) -> GraphNode:
    """Create a semantic fact node"""
    now = int(time.time())

    semantic_data = SemanticData(
        fact=fact,
        source_turn_id=source_turn_id,
        **{k: v for k, v in kwargs.items() if k in SemanticData.__annotations__}
    )

    return GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.SEMANTIC,
        project_id=project_id,
        created_at=now,
        updated_at=now,
        confidence=confidence,
        data=asdict(semantic_data),
        embedding_text=fact
    )


def create_procedural_node(
    project_id: str,
    pattern_name: str,
    trigger: str,
    tool_sequence: List[str],
    **kwargs
) -> GraphNode:
    """Create a procedural pattern node"""
    now = int(time.time())

    procedural_data = ProceduralData(
        pattern_name=pattern_name,
        trigger=trigger,
        tool_sequence=tool_sequence,
        **{k: v for k, v in kwargs.items() if k in ProceduralData.__annotations__}
    )

    embedding_text = f"{pattern_name} {trigger} {' '.join(tool_sequence)}"

    return GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.PROCEDURAL,
        project_id=project_id,
        created_at=now,
        updated_at=now,
        confidence=procedural_data.fitness,
        data=asdict(procedural_data),
        embedding_text=embedding_text
    )


def create_persona_node(
    project_id: str,
    trait_name: str,
    strength: float,
    learned_from: List[str],
    **kwargs
) -> GraphNode:
    """Create a persona trait node"""
    now = int(time.time())

    persona_data = PersonaData(
        trait_name=trait_name,
        strength=strength,
        learned_from=learned_from,
        **{k: v for k, v in kwargs.items() if k in PersonaData.__annotations__}
    )

    return GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.PERSONA,
        project_id=project_id,
        created_at=now,
        updated_at=now,
        confidence=strength,
        data=asdict(persona_data),
        embedding_text=trait_name
    )


def create_failure_node(
    project_id: str,
    error_type: str,
    tool: str,
    error_message: str,
    **kwargs
) -> GraphNode:
    """Create a failure node"""
    now = int(time.time())

    failure_data = FailureData(
        error_type=error_type,
        tool=tool,
        error_message=error_message,
        **{k: v for k, v in kwargs.items() if k in FailureData.__annotations__}
    )

    embedding_text = f"{error_type} {tool} {error_message}"

    return GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.FAILURE,
        project_id=project_id,
        created_at=now,
        updated_at=now,
        confidence=1.0,
        data=asdict(failure_data),
        embedding_text=embedding_text
    )


def create_goal_node(
    project_id: str,
    title: str,
    description: str,
    status: str = "active",
    inferred: bool = False,
    **kwargs
) -> GraphNode:
    """Create a goal / intent node"""
    now = int(time.time())

    goal_data = GoalData(
        title=title,
        description=description,
        status=status,
        inferred=inferred,
        **{k: v for k, v in kwargs.items() if k in GoalData.__annotations__}
    )

    embedding_text = f"{title} {description}"

    return GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.GOAL,
        project_id=project_id,
        created_at=now,
        updated_at=now,
        confidence=0.7 if inferred else 1.0,
        data=asdict(goal_data),
        embedding_text=embedding_text
    )


def create_edge(
    from_node: str,
    to_node: str,
    edge_type: EdgeType,
    project_id: Optional[str] = None,
    confidence: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None
) -> GraphEdge:
    """Create a typed edge"""
    return GraphEdge(
        id=str(uuid.uuid4()),
        edge_type=edge_type,
        from_node=from_node,
        to_node=to_node,
        created_at=int(time.time()),
        confidence=confidence,
        project_id=project_id,
        metadata=metadata
    )
