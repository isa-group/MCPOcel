"""Adaptive retrieval engine: SQLite FTS5 + BM25 based on OCEL size.

Automatically selects optimal indexing strategy:
- SQLite FTS5: < 5MB (instant, zero deps)
- Hybrid: 5-100MB (SQLite + BM25)
- BM25 only: > 100MB (scalable)
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rank_bm25 import BM25Okapi

from .typing_ocel import SearchResultItemDict

# Size thresholds (bytes)
SMALL_OCEL_THRESHOLD = 5_000_000      # 5MB → SQLite FTS5
LARGE_OCEL_THRESHOLD = 100_000_000    # 100MB → BM25

# Chunking parameters
MAX_CHUNK_SIZE = 1000
EVENTS_PER_CHUNK = 100
OBJECTS_PER_CHUNK = 100


@dataclass
class Chunk:
    """A chunk of OCEL data with metadata."""
    id: str
    content: str
    path: str
    chunk_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class IndexStrategy(Enum):
    """Indexing strategy based on OCEL size."""
    SQLITE_FTS5 = "sqlite_fts5"
    HYBRID = "hybrid"
    BM25_ONLY = "bm25_only"


class SQLiteFTS5Retriever:
    """Fast full-text search using SQLite FTS5 (stdlib, zero dependencies).
    
    Uses SQLite's built-in FTS5 virtual table for full-text search, providing
    BM25-style ranking without external dependencies. Supports optional persistence
    to disk for index reuse across sessions.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize SQLite FTS5 retriever.
        
        Args:
            db_path: Path to SQLite database file. If None, uses in-memory database.
        """
        self.db_path = db_path or ":memory:"
        self.conn: Optional[sqlite3.Connection] = None
        self._indexed = False
    
    def _init_db(self) -> None:
        """Initialize database and FTS5 virtual table."""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        
        self.conn.execute("DROP TABLE IF EXISTS chunks_fts")
        self.conn.execute("""
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                id,
                content,
                path,
                chunk_type,
                metadata_json
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunk_metadata (
                id TEXT PRIMARY KEY,
                path TEXT,
                chunk_type TEXT,
                start INTEGER,
                end INTEGER,
                count INTEGER
            )
        """)
        
        self.conn.commit()
    
    def index_chunks(self, chunks: List[Chunk]) -> None:
        """Index chunks using SQLite FTS5.
        
        Creates FTS5 virtual table and indexes all chunks for full-text search.
        Stores both content and metadata for filtering and retrieval.
        
        Args:
            chunks: List of Chunk objects to index.
        
        Raises:
            sqlite3.DatabaseError: If database operations fail.
        """
        self._init_db()
        
        for chunk in chunks:
            self.conn.execute(
                """INSERT INTO chunks_fts (id, content, path, chunk_type, metadata_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (chunk.id, chunk.content, chunk.path, chunk.chunk_type, json.dumps(chunk.metadata)),
            )
            
            meta = chunk.metadata
            self.conn.execute(
                """INSERT OR IGNORE INTO chunk_metadata (id, path, chunk_type, start, end, count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (chunk.id, chunk.path, chunk.chunk_type, meta.get("start"), meta.get("end"), meta.get("count")),
            )
        
        self.conn.commit()
        self._indexed = True
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        chunk_types: Optional[List[str]] = None,
    ) -> List[Tuple[Chunk, float]]:
        """Search using FTS5 BM25 ranking.
        
        Performs full-text search against indexed chunks using SQLite's native
        BM25 ranking algorithm. Optionally filters by chunk type.
        
        Args:
            query: Search query string. Supports FTS5 syntax: AND, OR, NOT, phrase matching.
                  Example: 'PullRequest AND merged' or '"completed status"'.
            top_k: Maximum number of results to return. Default is 5.
            chunk_types: Optional list of chunk types to filter by.
                        Valid types: 'event_types', 'object_types', 'events', 'objects'.
        
        Returns:
            List of (Chunk, score) tuples sorted by relevance (highest score first).
            Score is normalized to [0, 1] range where 1 is best match.
        """
        if not self._indexed or self.conn is None:
            return []
        
        # Escape FTS5 special characters by wrapping in quotes
        # Double any existing quotes for proper escaping
        escaped_query = query.replace('"', '""')
        fts_query = f'"{escaped_query}"'
        
        type_filter = ""
        params = [fts_query]
        
        if chunk_types:
            placeholders = ",".join("?" * len(chunk_types))
            type_filter = f" AND chunk_type IN ({placeholders})"
            params.extend(chunk_types)
        
        sql = f"""
            SELECT id, content, path, chunk_type, metadata_json, rank as score
            FROM chunks_fts
            WHERE chunks_fts MATCH ? {type_filter}
            ORDER BY rank
            LIMIT ?
        """
        params.append(top_k)
        
        cursor = self.conn.execute(sql, params)
        results = []
        for row in cursor.fetchall():
            chunk = Chunk(
                id=row["id"],
                content=row["content"],
                path=row["path"],
                chunk_type=row["chunk_type"],
                metadata=json.loads(row["metadata_json"]),
            )
            # FTS5 rank is negative (lower = better), convert to [0, 1]
            score = 1.0 / (1.0 - row["score"]) if row["score"] < 1 else 0.5
            results.append((chunk, score))
        
        return results
    
    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None


class BM25Retriever:
    """BM25 retriever for keyword-based ranking.
    
    Implements Okapi BM25 algorithm for ranking documents based on term frequency.
    Suitable for large OCEL files (> 100MB) where in-memory ranking is preferred
    over database queries. No disk persistence - index exists only in memory.
    """
    
    def __init__(self):
        """Initialize BM25 retriever with empty state."""
        self._bm25: Optional[BM25Okapi] = None
        self._chunks: List[Chunk] = []
        self._tokenized_docs: List[List[str]] = []
    
    def index_chunks(self, chunks: List[Chunk]) -> None:
        """Index chunks using BM25 algorithm.
        
        Tokenizes all chunk content and builds BM25 index for ranking.
        Index is stored in memory and lost when object is destroyed.
        
        Args:
            chunks: List of Chunk objects to index.
        """
        self._chunks = chunks
        self._tokenized_docs = [self._tokenize(c.content) for c in chunks]
        self._bm25 = BM25Okapi(self._tokenized_docs)
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization."""
        tokens = re.findall(r'\w+', text.lower())
        return tokens
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        chunk_types: Optional[List[str]] = None,
    ) -> List[Tuple[Chunk, float]]:
        """Search using BM25 ranking algorithm.
        
        Tokenizes query and ranks chunks by term frequency using Okapi BM25.
        Optionally filters results by chunk type before returning.
        
        Args:
            query: Search query string (keywords separated by spaces).
                  Example: 'PullRequest merged'.
            top_k: Maximum number of results to return. Default is 5.
            chunk_types: Optional list of chunk types to filter by.
                        Valid types: 'event_types', 'object_types', 'events', 'objects'.
        
        Returns:
            List of (Chunk, score) tuples sorted by BM25 score (highest first).
            Score represents relevance with higher values indicating better matches.
        """
        if not self._chunks or not self._bm25:
            return []
        
        query_tokens = self._tokenize(query)
        scores = self._bm25.get_scores(query_tokens)
        
        results = []
        for i, (chunk, score) in enumerate(zip(self._chunks, scores)):
            if chunk_types and chunk.chunk_type not in chunk_types:
                continue
            results.append((chunk, score))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]


class AdaptiveRetriever:
    """Automatically selects between SQLite FTS5 and BM25 based on OCEL size.
    
    Implements strategy selection logic:
    - SQLite FTS5: For small OCEL files (< 5MB) - instant searches, persistent DB
    - Hybrid: For medium files (5-100MB) - combines SQLite + BM25 for best recall
    - BM25 only: For large files (> 100MB) - scalable in-memory indexing
    """
    
    def __init__(
        self,
        persist_directory: Optional[str] = None,
        force_strategy: Optional[str] = None,
    ):
        """Initialize adaptive retriever.
        
        Args:
            persist_directory: Directory for SQLite persistence.
                             Enables index reuse across server restarts.
            force_strategy: Force a specific strategy regardless of OCEL size.
                          Valid values: 'sqlite_fts5', 'hybrid', 'bm25_only'.
                          Useful for testing or when size estimation is inaccurate.
        """
        self.persist_directory = persist_directory
        self.force_strategy = force_strategy
        self.strategy: Optional[IndexStrategy] = None
        
        self.sqlite_retriever: Optional[SQLiteFTS5Retriever] = None
        self.bm25_retriever: Optional[BM25Retriever] = None
        
        self._ocel_size_bytes = 0
        self._indexed = False
    
    def _select_strategy(self, ocel_json: Dict[str, Any]) -> IndexStrategy:
        """Select indexing strategy based on OCEL size.
        
        Estimates OCEL JSON size and returns appropriate strategy:
        - < 5MB: SQLITE_FTS5 (instant, persistent)
        - 5-100MB: HYBRID (balance speed and recall)
        - > 100MB: BM25_ONLY (scalable for large logs)
        
        Args:
            ocel_json: Full OCEL JSON dictionary (used to estimate size).
        
        Returns:
            IndexStrategy enum value indicating selected strategy.
        """
        if self.force_strategy:
            return IndexStrategy(self.force_strategy)
        
        json_str = json.dumps(ocel_json)
        size_bytes = len(json_str.encode('utf-8'))
        self._ocel_size_bytes = size_bytes
        
        if size_bytes < SMALL_OCEL_THRESHOLD:
            return IndexStrategy.SQLITE_FTS5
        elif size_bytes > LARGE_OCEL_THRESHOLD:
            return IndexStrategy.BM25_ONLY
        else:
            return IndexStrategy.HYBRID
    
    def index_chunks(self, chunks: List[Chunk], ocel_json: Dict[str, Any]) -> None:
        """Index chunks using adaptive strategy.
        
        Selects appropriate indexing strategy and initializes corresponding retriever.
        Only one retriever (SQLite FTS5 or BM25) is active, depending on strategy.
        In hybrid mode, both are initialized for combined search results.
        
        Args:
            chunks: List of Chunk objects to index.
            ocel_json: Full OCEL JSON dictionary (for size estimation).
        """
        self.strategy = self._select_strategy(ocel_json)
        
        if self.strategy == IndexStrategy.SQLITE_FTS5:
            db_path = None
            if self.persist_directory:
                db_path = f"{self.persist_directory}/ocel_fts5.db"
            self.sqlite_retriever = SQLiteFTS5Retriever(db_path=db_path)
            self.sqlite_retriever.index_chunks(chunks)
        
        elif self.strategy == IndexStrategy.HYBRID:
            db_path = None
            if self.persist_directory:
                db_path = f"{self.persist_directory}/ocel_fts5.db"
            self.sqlite_retriever = SQLiteFTS5Retriever(db_path=db_path)
            self.sqlite_retriever.index_chunks(chunks)
            
            self.bm25_retriever = BM25Retriever()
            self.bm25_retriever.index_chunks(chunks)
        
        elif self.strategy == IndexStrategy.BM25_ONLY:
            self.bm25_retriever = BM25Retriever()
            self.bm25_retriever.index_chunks(chunks)
        
        self._indexed = True
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        chunk_types: Optional[List[str]] = None,
    ) -> List[Tuple[Chunk, float]]:
        """Search using appropriate strategy.
        
        Delegates to active retriever (SQLite FTS5, BM25, or both in hybrid mode).
        In hybrid mode, merges and deduplicates results with weighted averaging.
        
        Args:
            query: Search query string.
            top_k: Maximum number of results to return. Default is 5.
            chunk_types: Optional list of chunk types to filter by.
        
        Returns:
            List of (Chunk, score) tuples sorted by relevance, deduplicated.
        """
        if not self._indexed:
            return []
        
        if self.strategy == IndexStrategy.SQLITE_FTS5:
            return self.sqlite_retriever.search(query, top_k, chunk_types)
        
        elif self.strategy == IndexStrategy.HYBRID:
            sqlite_results = self.sqlite_retriever.search(query, top_k * 2, chunk_types)
            bm25_results = self.bm25_retriever.search(query, top_k * 2, chunk_types)
            
            merged = {}
            for chunk, score in sqlite_results:
                merged[chunk.id] = (chunk, score * 0.5)
            
            for chunk, score in bm25_results:
                if chunk.id in merged:
                    _, existing_score = merged[chunk.id]
                    merged[chunk.id] = (chunk, (existing_score + score * 0.5) / 2)
                else:
                    merged[chunk.id] = (chunk, score * 0.5)
            
            results = sorted(merged.values(), key=lambda x: x[1], reverse=True)
            return results[:top_k]
        
        else:  # BM25_ONLY
            return self.bm25_retriever.search(query, top_k, chunk_types)
    
    def get_info(self) -> Dict[str, Any]:
        """Get retrieval engine information."""
        return {
            "strategy": self.strategy.value if self.strategy else None,
            "ocel_size_mb": round(self._ocel_size_bytes / 1_000_000, 2),
            "indexed": self._indexed,
        }


class OCELChunker:
    """Hierarchical chunker for OCEL 2.0 JSON files.
    
    Breaks down large OCEL JSON into retrievable chunks organized by:
    - Event types schema
    - Object types schema  
    - Event batches (100 events per chunk)
    - Object batches (100 objects per chunk)
    
    Large batches are automatically summarized instead of being dumped as JSON.
    """
    
    def __init__(self, max_chunk_size: int = MAX_CHUNK_SIZE):
        """Initialize OCEL chunker.
        
        Args:
            max_chunk_size: Maximum characters per chunk before summarization.
                          Default is 1000 chars. Larger values = fewer, denser chunks.
        """
        self.max_chunk_size = max_chunk_size

    def chunk_ocel(self, data: Dict[str, Any]) -> List[Chunk]:
        """Chunk an OCEL JSON into retrievable pieces.
        
        Hierarchically chunks OCEL data:
        1. Event types (one chunk, max info density)
        2. Object types (one chunk, max info density)
        3. Events in batches of 100 (or summarized if > max_chunk_size)
        4. Objects in batches of 100 (or summarized if > max_chunk_size)
        
        Args:
            data: Parsed OCEL 2.0 JSON dictionary with keys:
                 'eventTypes', 'objectTypes', 'events', 'objects'.
        
        Returns:
            List of Chunk objects ready for indexing.
        """
        chunks: List[Chunk] = []
        chunk_id = 0

        # Event types
        event_types = data.get("eventTypes", [])
        if event_types and isinstance(event_types, list):
            type_names = [et.get("name", et) if isinstance(et, dict) else et for et in event_types]
            chunks.append(Chunk(
                id=f"chunk_{chunk_id}",
                content=f"Event Types: {json.dumps(type_names)}",
                path="eventTypes",
                chunk_type="event_types",
                metadata={"count": len(event_types)},
            ))
            chunk_id += 1
        
        # Object types
        object_types = data.get("objectTypes", [])
        if object_types and isinstance(object_types, list):
            type_names = [ot.get("name", ot) if isinstance(ot, dict) else ot for ot in object_types]
            chunks.append(Chunk(
                id=f"chunk_{chunk_id}",
                content=f"Object Types: {json.dumps(type_names)}",
                path="objectTypes",
                chunk_type="object_types",
                metadata={"count": len(object_types)},
            ))
            chunk_id += 1
        
        # Events
        events = data.get("events", [])
        if isinstance(events, list) and events:
            for i in range(0, len(events), EVENTS_PER_CHUNK):
                batch = events[i:i + EVENTS_PER_CHUNK]
                if len(json.dumps(batch)) > self.max_chunk_size:
                    summary = self._summarize_events(batch, i, i + len(batch))
                    content = summary
                else:
                    content = json.dumps(batch, indent=2)
                
                chunks.append(Chunk(
                    id=f"chunk_{chunk_id}",
                    content=content,
                    path=f"events[{i}:{i + len(batch)}]",
                    chunk_type="events",
                    metadata={"start": i, "end": i + len(batch), "count": len(batch)},
                ))
                chunk_id += 1
        
        # Objects
        objects = data.get("objects", [])
        if isinstance(objects, list) and objects:
            for i in range(0, len(objects), OBJECTS_PER_CHUNK):
                batch = objects[i:i + OBJECTS_PER_CHUNK]
                if len(json.dumps(batch)) > self.max_chunk_size:
                    summary = self._summarize_objects(batch, i, i + len(batch))
                    content = summary
                else:
                    content = json.dumps(batch, indent=2)
                
                chunks.append(Chunk(
                    id=f"chunk_{chunk_id}",
                    content=content,
                    path=f"objects[{i}:{i + len(batch)}]",
                    chunk_type="objects",
                    metadata={"start": i, "end": i + len(batch), "count": len(batch)},
                ))
                chunk_id += 1
        
        return chunks
    
    def _summarize_events(self, events: List[Dict], start: int, end: int) -> str:
        """Create a searchable summary of events batch.
        
        Aggregates large event batches into compact summaries containing:
        - Activity frequency distribution
        - Time range (earliest to latest timestamp)
        - Count of unique referenced objects
        - Sample object IDs
        
        Args:
            events: List of event dictionaries to summarize.
            start: Starting index of batch in full events list.
            end: Ending index of batch in full events list.
        
        Returns:
            Formatted text summary optimized for full-text search.
        """
        activities = {}
        timestamps = []
        object_refs = set()
        
        for e in events:
            act = e.get("type", "unknown")
            activities[act] = activities.get(act, 0) + 1
            if ts := e.get("time"):
                timestamps.append(str(ts))
            for rel in e.get("relationships", []):
                if obj_id := rel.get("objectId"):
                    object_refs.add(obj_id)
        
        return (
            f"Events batch [{start}:{end}]\n"
            f"Activities: {json.dumps(activities)}\n"
            f"Time range: {min(timestamps) if timestamps else 'N/A'} to {max(timestamps) if timestamps else 'N/A'}\n"
            f"Referenced objects: {len(object_refs)} unique\n"
            f"Sample object IDs: {list(object_refs)[:10]}"
        )
    
    def _summarize_objects(self, objects: List[Dict], start: int, end: int) -> str:
        """Create a searchable summary of objects batch.
        
        Aggregates large object batches into compact summaries containing:
        - Object type frequency distribution
        - Up to 20 sample object IDs
        
        Args:
            objects: List of object dictionaries to summarize.
            start: Starting index of batch in full objects list.
            end: Ending index of batch in full objects list.
        
        Returns:
            Formatted text summary optimized for full-text search.
        """
        types = {}
        for obj in objects:
            otype = obj.get("type", "unknown")
            types[otype] = types.get(otype, 0) + 1
        
        obj_ids = [obj.get("id", "") for obj in objects]
        return (
            f"Objects batch [{start}:{end}]\n"
            f"Types: {json.dumps(types)}\n"
            f"Object IDs: {obj_ids[:20]}{'...' if len(obj_ids) > 20 else ''}"
        )


class OCELRetrievalEngine:
    """High-level retrieval engine with adaptive strategy.
    
    Main entry point for OCEL indexing and searching. Orchestrates chunking
    and retrieval using adaptive strategy (SQLite FTS5 or BM25) based on OCEL size.
    """

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        force_strategy: Optional[str] = None,
    ):
        """Initialize OCEL retrieval engine.
        
        Args:
            persist_directory: Directory for SQLite FTS5 persistence. If provided,
                             index is saved to disk and reused across sessions.
                             Example: './storage' creates './storage/ocel_fts5.db'.
                             If None, only in-memory retrieval is available.
            force_strategy: Force a specific indexing strategy regardless of OCEL size.
                          Valid values: 'sqlite_fts5', 'hybrid', 'bm25_only'.
                          Useful for testing or overriding automatic selection.
                          Default (None) = automatic selection based on OCEL size.
        """
        self.chunker = OCELChunker()
        self.retriever = AdaptiveRetriever(
            persist_directory=persist_directory,
            force_strategy=force_strategy,
        )
        self._indexed = False
    
    def index_ocel(self, ocel_data: Dict[str, Any]) -> int:
        """Index OCEL data for retrieval.
        
        Chunks OCEL data hierarchically and initializes search indices using
        the adaptive strategy. Must be called before searching.
        
        Args:
            ocel_data: Parsed OCEL 2.0 JSON dictionary.
        
        Returns:
            Number of chunks created and indexed.
        """
        chunks = self.chunker.chunk_ocel(ocel_data)
        self.retriever.index_chunks(chunks, ocel_data)
        self._indexed = True
        return len(chunks)
    
    def index_from_file(self, ocel_path: Path) -> int:
        """Index OCEL from file path."""
        with open(ocel_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self.index_ocel(data)
    
    def search(self, query: str, top_k: int = 5) -> List[SearchResultItemDict]:
        """Search indexed OCEL data across all chunk types.
        
        Performs full-text search against all indexed chunks (events, objects, types).
        Results include content, path, type, score, and metadata.
        
        Args:
            query: Natural language search query.
                  Examples: 'PullRequest merged', 'object lifecycle', 'failed events'.
            top_k: Maximum number of results to return. Default is 5.
        
        Returns:
            List of SearchResultItemDict with keys:
            - 'content': Chunk text content
            - 'path': JSON path (e.g., 'events[100:200]', 'objectTypes')
            - 'type': Chunk type ('events', 'objects', 'event_types', 'object_types')
            - 'score': Relevance score [0, 1] - higher is better
            - 'metadata': Dict with 'count', 'start', 'end' (if available)
        
        Returns empty list if engine is not yet indexed.
        """
        if not self._indexed:
            return []
        
        results = self.retriever.search(query, top_k=top_k)
        return [
            {
                "content": chunk.content,
                "path": chunk.path,
                "type": chunk.chunk_type,
                "score": score,
                "metadata": chunk.metadata,
            }
            for chunk, score in results
        ]
    
    def search_schema(self, query: str, top_k: int = 3) -> List[SearchResultItemDict]:
        """Search only schema-related chunks (types and attributes).
        
        Filters search results to only include event/object type definitions,
        useful when exploring OCEL structure without data records.
        
        Args:
            query: Schema-related search query.
                  Examples: 'object types', 'event attributes', 'activity names'.
            top_k: Maximum number of results. Default is 3.
        
        Returns:
            List of SearchResultItemDict for schema chunks only.
        
        See search() for return value details.
        """
        if not self._indexed:
            return []
        
        schema_types = ["metadata", "event_types", "event_type", "object_types", "object_type", "attributes"]
        results = self.retriever.search(query, top_k=top_k, chunk_types=schema_types)
        return [
            {
                "content": chunk.content,
                "path": chunk.path,
                "type": chunk.chunk_type,
                "score": score,
            }
            for chunk, score in results
        ]
    
    def search_data(self, query: str, top_k: int = 5) -> List[SearchResultItemDict]:
        """Search only data chunks (events and objects).
        
        Filters search results to only include event and object records,
        excluding schema definitions. Useful for querying actual process data.
        
        Args:
            query: Data-related search query.
                  Examples: 'failed process', 'object XYZ', 'merged pull requests'.
            top_k: Maximum number of results. Default is 5.
        
        Returns:
            List of SearchResultItemDict for data chunks only (events and objects).
        
        See search() for return value details.
        """
        if not self._indexed:
            return []
        
        data_types = ["events", "objects"]
        results = self.retriever.search(query, top_k=top_k, chunk_types=data_types)
        return [
            {
                "content": chunk.content,
                "path": chunk.path,
                "type": chunk.chunk_type,
                "score": score,
                "metadata": chunk.metadata,
            }
            for chunk, score in results
        ]
    
    def get_info(self) -> Dict[str, Any]:
        """Get retrieval engine information and current status.
        
        Returns:
            Dictionary with keys:
            - 'strategy': Selected strategy ('sqlite_fts5', 'hybrid', or 'bm25_only')
            - 'ocel_size_mb': OCEL JSON size in megabytes (rounded to 2 decimals)
            - 'indexed': Boolean indicating if indexing is complete
        
        Returns None values if engine is not yet indexed.
        """
        return self.retriever.get_info()
