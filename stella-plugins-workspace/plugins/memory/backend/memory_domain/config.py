"""
Memory configuration module

Explicit configuration for one host-bound plugin namespace
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MemoryConfig:
    """Configuration for memory storage and search"""

    # Host-bound data root
    workspace_root: str

    # Embedding config
    embedding_provider: str = "openai"  # "openai" | "local"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # Chunking config
    chunk_max_tokens: int = 500
    chunk_overlap_tokens: int = 50

    # Search config
    max_results: int = 10
    min_score: float = 0.1

    # Hybrid search weights
    vector_weight: float = 0.7
    keyword_weight: float = 0.3

    sync_on_search: bool = True


    def get_workspace(self) -> Path:
        """Get workspace root directory"""
        return Path(self.workspace_root)

    def get_memory_dir(self) -> Path:
        """Get memory files directory"""
        return Path(self.workspace_root) / "memory"

    def get_db_path(self) -> Path:
        """Get SQLite database path for long-term memory index"""
        return Path(self.workspace_root) / "index.db"

def user_root_for_workspace(workspace, user_id=None):
    # A worker receives exactly one host-bound user namespace.
    return Path(workspace)
