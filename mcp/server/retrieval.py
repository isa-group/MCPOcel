"""Hybrid retrieval engine using BM25 + Semantic Embeddings for OCEL data.

This module implements Reciprocal Rank Fusion (RRF) to combine:
- BM25: Fast keyword-based ranking
- Semantic Embeddings: Understands synonyms and concepts

Optimized for large OCEL JSON files with hierarchical chunking.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from chromadb.config import Settings
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

# Default embedding model (small, fast, good quality)
DEFAULT_MODEL = "all-MiniLM-L6-v2"

# Chunking parameters
MAX_CHUNK_SIZE = 1000  # Max characters per chunk
EVENTS_PER_CHUNK = 100  # Events per chunk for large logs
OBJECTS_PER_CHUNK = 100  # Objects per chunk for large logs

# RRF parameter (standard value)
RRF_K = 60


@dataclass
class Chunk:
    """A chunk of OCEL data with metadata."""
    id: str
    content: str
    path: str  # JSON path (e.g., "ocel:events[0:100]")
    chunk_type: str  # "metadata", "event_type", "object_type", "events", "objects"
    metadata: Dict[str, Any] = field(default_factory=dict)


class OCELChunker:
    """Hierarchical chunker for OCEL 2.0 JSON files."""

    def __init__(self, max_chunk_size: int = MAX_CHUNK_SIZE):
        self.max_chunk_size = max_chunk_size

    def chunk_ocel(self, data: Dict[str, Any]) -> List[Chunk]:
        """Chunk an OCEL JSON into retrievable pieces."""
        chunks: List[Chunk] = []
        chunk_id = 0

        # 1. Metadata chunk (version, global-log, etc.)
        metadata_keys = ["ocel:version", "ocel:ordering", "ocel:global-log"]
        metadata = {k: data.get(k) for k in metadata_keys if k in data}
        if metadata:
            chunks.append(Chunk(
                id=f"chunk_{chunk_id}",
                content=json.dumps(metadata, indent=2),
                path="metadata",
                chunk_type="metadata",
            ))
            chunk_id += 1

        # 2. Event types (one chunk per type or grouped)
        event_types = data.get("ocel:event-types") or data.get("eventTypes") or []
        if event_types:
            if isinstance(event_types, list):
                chunks.append(Chunk(
                    id=f"chunk_{chunk_id}",
                    content=f"Event Types: {json.dumps(event_types)}",
                    path="ocel:event-types",
                    chunk_type="event_types",
                    metadata={"count": len(event_types)},
                ))
            elif isinstance(event_types, dict):
                for et_name, et_def in event_types.items():
                    chunks.append(Chunk(
                        id=f"chunk_{chunk_id}",
                        content=f"Event Type '{et_name}': {json.dumps(et_def, indent=2)}",
                        path=f"ocel:event-types.{et_name}",
                        chunk_type="event_type",
                        metadata={"name": et_name},
                    ))
                    chunk_id += 1

        # 3. Object types (one chunk per type or grouped)
        object_types = data.get("ocel:object-types") or data.get("objectTypes") or []
        if object_types:
            if isinstance(object_types, list):
                chunks.append(Chunk(
                    id=f"chunk_{chunk_id}",
                    content=f"Object Types: {json.dumps(object_types)}",
                    path="ocel:object-types",
                    chunk_type="object_types",
                    metadata={"count": len(object_types)},
                ))
            elif isinstance(object_types, dict):
                for ot_name, ot_def in object_types.items():
                    chunks.append(Chunk(
                        id=f"chunk_{chunk_id}",
                        content=f"Object Type '{ot_name}': {json.dumps(ot_def, indent=2)}",
                        path=f"ocel:object-types.{ot_name}",
                        chunk_type="object_type",
                        metadata={"name": ot_name},
                    ))
                    chunk_id += 1

        # 4. Attribute names
        attr_names = data.get("ocel:attribute-names") or {}
        if attr_names:
            chunks.append(Chunk(
                id=f"chunk_{chunk_id}",
                content=f"Attribute Names: {json.dumps(attr_names, indent=2)}",
                path="ocel:attribute-names",
                chunk_type="attributes",
            ))
            chunk_id += 1

        # 5. Events (chunked in batches)
        events = data.get("ocel:events") or []
        if isinstance(events, list) and events:
            for i in range(0, len(events), EVENTS_PER_CHUNK):
                batch = events[i:i + EVENTS_PER_CHUNK]
                # Create summary instead of full dump for large batches
                if len(json.dumps(batch)) > self.max_chunk_size:
                    summary = self._summarize_events(batch, i, i + len(batch))
                    content = summary
                else:
                    content = json.dumps(batch, indent=2)

                chunks.append(Chunk(
                    id=f"chunk_{chunk_id}",
                    content=content,
                    path=f"ocel:events[{i}:{i + len(batch)}]",
                    chunk_type="events",
                    metadata={"start": i, "end": i + len(batch), "count": len(batch)},
                ))
                chunk_id += 1

        # 6. Objects (chunked in batches)
        objects = data.get("ocel:objects") or {}
        if isinstance(objects, dict) and objects:
            obj_items = list(objects.items())
            for i in range(0, len(obj_items), OBJECTS_PER_CHUNK):
                batch = dict(obj_items[i:i + OBJECTS_PER_CHUNK])
                if len(json.dumps(batch)) > self.max_chunk_size:
                    summary = self._summarize_objects(batch, i, i + len(batch))
                    content = summary
                else:
                    content = json.dumps(batch, indent=2)

                chunks.append(Chunk(
                    id=f"chunk_{chunk_id}",
                    content=content,
                    path=f"ocel:objects[{i}:{i + len(batch)}]",
                    chunk_type="objects",
                    metadata={"start": i, "end": i + len(batch), "count": len(batch)},
                ))
                chunk_id += 1

        return chunks

    def _summarize_events(self, events: List[Dict], start: int, end: int) -> str:
        """Create a searchable summary of events batch."""
        activities = {}
        timestamps = []
        object_refs = set()

        for e in events:
            act = e.get("ocel:activity") or e.get("ocel:type-name", "unknown")
            activities[act] = activities.get(act, 0) + 1
            if ts := e.get("ocel:timestamp"):
                timestamps.append(str(ts))
            for oid in e.get("ocel:omap", []):
                object_refs.add(oid)

        return (
            f"Events batch [{start}:{end}]\n"
            f"Activities: {json.dumps(activities)}\n"
            f"Time range: {min(timestamps) if timestamps else 'N/A'} to {max(timestamps) if timestamps else 'N/A'}\n"
            f"Referenced objects: {len(object_refs)} unique\n"
            f"Sample object IDs: {list(object_refs)[:10]}"
        )

    def _summarize_objects(self, objects: Dict, start: int, end: int) -> str:
        """Create a searchable summary of objects batch."""
        types = {}
        for oid, obj in objects.items():
            otype = obj.get("ocel:type", "unknown")
            types[otype] = types.get(otype, 0) + 1

        return (
            f"Objects batch [{start}:{end}]\n"
            f"Types: {json.dumps(types)}\n"
            f"Object IDs: {list(objects.keys())[:20]}{'...' if len(objects) > 20 else ''}"
        )


class HybridRetriever:
    """Hybrid BM25 + Semantic Embeddings retriever with RRF fusion."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        persist_directory: Optional[str] = None,
    ):
        """
        Initialize the hybrid retriever.

        Args:
            model_name: Sentence transformer model for embeddings.
            persist_directory: Optional path to persist ChromaDB.
        """
        self.model_name = model_name
        self._model: Optional[SentenceTransformer] = None
        self._bm25: Optional[BM25Okapi] = None
        self._chunks: List[Chunk] = []
        self._tokenized_docs: List[List[str]] = []

        # ChromaDB for vector storage
        if persist_directory:
            self._chroma_client = chromadb.PersistentClient(path=persist_directory)
        else:
            self._chroma_client = chromadb.Client(Settings(anonymized_telemetry=False))

        self._collection: Optional[chromadb.Collection] = None
        self._indexed_hash: Optional[str] = None

    @property
    def model(self) -> SentenceTransformer:
        """Lazy load the embedding model."""
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def index_chunks(self, chunks: List[Chunk], force: bool = False) -> None:
        """
        Index chunks for hybrid retrieval.

        Args:
            chunks: List of chunks to index.
            force: Re-index even if content hasn't changed.
        """
        # Check if reindexing is needed
        content_hash = hashlib.sha256(
            json.dumps([c.content for c in chunks]).encode()
        ).hexdigest()

        if not force and content_hash == self._indexed_hash:
            return

        self._chunks = chunks

        # 1. Build BM25 index
        self._tokenized_docs = [self._tokenize(c.content) for c in chunks]
        self._bm25 = BM25Okapi(self._tokenized_docs)

        # 2. Build ChromaDB vector index
        collection_name = f"ocel_{content_hash[:16]}"

        # Delete existing collection if exists
        try:
            self._chroma_client.delete_collection(collection_name)
        except Exception:
            pass

        self._collection = self._chroma_client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # Generate embeddings and add to collection
        contents = [c.content for c in chunks]
        embeddings = self.model.encode(contents, show_progress_bar=False).tolist()

        self._collection.add(
            ids=[c.id for c in chunks],
            embeddings=embeddings,
            documents=contents,
            metadatas=[{"path": c.path, "type": c.chunk_type} for c in chunks],
        )

        self._indexed_hash = content_hash

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25."""
        # Lowercase and split on non-alphanumeric
        tokens = re.findall(r'\w+', text.lower())
        return tokens

    def search(
        self,
        query: str,
        top_k: int = 5,
        bm25_weight: float = 0.5,
        semantic_weight: float = 0.5,
    ) -> List[Tuple[Chunk, float]]:
        """
        Hybrid search using RRF fusion of BM25 and semantic scores.

        Args:
            query: Search query.
            top_k: Number of results to return.
            bm25_weight: Weight for BM25 scores (0-1).
            semantic_weight: Weight for semantic scores (0-1).

        Returns:
            List of (Chunk, score) tuples sorted by relevance.
        """
        if not self._chunks or not self._bm25 or not self._collection:
            return []

        # 1. BM25 scores
        query_tokens = self._tokenize(query)
        bm25_scores = self._bm25.get_scores(query_tokens)

        # 2. Semantic scores from ChromaDB
        query_embedding = self.model.encode([query], show_progress_bar=False).tolist()
        semantic_results = self._collection.query(
            query_embeddings=query_embedding,
            n_results=len(self._chunks),
            include=["distances"],
        )

        # Convert distances to similarities (ChromaDB returns distances)
        semantic_scores = {}
        if semantic_results["ids"] and semantic_results["distances"]:
            for idx, (chunk_id, distance) in enumerate(
                zip(semantic_results["ids"][0], semantic_results["distances"][0])
            ):
                # Cosine distance to similarity
                similarity = 1 - distance
                semantic_scores[chunk_id] = similarity

        # 3. RRF Fusion
        # Get rankings
        bm25_ranking = sorted(
            range(len(bm25_scores)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )
        bm25_ranks = {idx: rank for rank, idx in enumerate(bm25_ranking)}

        semantic_ranking = sorted(
            semantic_scores.keys(),
            key=lambda cid: semantic_scores.get(cid, 0),
            reverse=True,
        )
        semantic_ranks = {cid: rank for rank, cid in enumerate(semantic_ranking)}

        # Compute RRF scores
        rrf_scores = []
        for i, chunk in enumerate(self._chunks):
            bm25_rank = bm25_ranks.get(i, len(self._chunks))
            sem_rank = semantic_ranks.get(chunk.id, len(self._chunks))

            # RRF formula: 1/(k + rank)
            bm25_rrf = bm25_weight / (RRF_K + bm25_rank)
            sem_rrf = semantic_weight / (RRF_K + sem_rank)
            combined = bm25_rrf + sem_rrf

            rrf_scores.append((chunk, combined))

        # Sort by combined score
        rrf_scores.sort(key=lambda x: x[1], reverse=True)

        return rrf_scores[:top_k]

    def search_by_type(
        self,
        query: str,
        chunk_types: List[str],
        top_k: int = 5,
    ) -> List[Tuple[Chunk, float]]:
        """Search within specific chunk types only."""
        all_results = self.search(query, top_k=len(self._chunks))
        filtered = [(c, s) for c, s in all_results if c.chunk_type in chunk_types]
        return filtered[:top_k]


class OCELRetrievalEngine:
    """High-level retrieval engine for OCEL data."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        persist_directory: Optional[str] = None,
    ):
        self.chunker = OCELChunker()
        self.retriever = HybridRetriever(
            model_name=model_name,
            persist_directory=persist_directory,
        )
        self._indexed = False

    def index_ocel(self, ocel_data: Dict[str, Any], force: bool = False) -> int:
        """
        Index OCEL data for retrieval.

        Args:
            ocel_data: Parsed OCEL JSON.
            force: Force reindex.

        Returns:
            Number of chunks created.
        """
        chunks = self.chunker.chunk_ocel(ocel_data)
        self.retriever.index_chunks(chunks, force=force)
        self._indexed = True
        return len(chunks)

    def index_from_file(self, ocel_path: Path, force: bool = False) -> int:
        """Index OCEL from file path."""
        with open(ocel_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self.index_ocel(data, force=force)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search indexed OCEL data.

        Args:
            query: Natural language query.
            top_k: Number of results.

        Returns:
            List of results with chunk content and metadata.
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

    def search_schema(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Search only schema-related chunks (types, attributes)."""
        if not self._indexed:
            return []

        schema_types = ["metadata", "event_types", "event_type", "object_types", "object_type", "attributes"]
        results = self.retriever.search_by_type(query, schema_types, top_k=top_k)
        return [
            {
                "content": chunk.content,
                "path": chunk.path,
                "type": chunk.chunk_type,
                "score": score,
            }
            for chunk, score in results
        ]

    def search_data(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search only data chunks (events, objects)."""
        if not self._indexed:
            return []

        data_types = ["events", "objects"]
        results = self.retriever.search_by_type(query, data_types, top_k=top_k)
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
