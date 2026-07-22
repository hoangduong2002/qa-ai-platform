from __future__ import annotations

import re
import sqlite3
import time
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile

from knowledge.domain.errors import KnowledgeValidationError
from knowledge.domain.models import ChunkRecord, SearchRequest, SearchResponse, SearchResult


IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Z0-9-]{1,}\b")


class SQLiteFTSKnowledgeRetriever:
    def __init__(self, index_path_getter):
        self._index_path_getter = index_path_getter

    def _connect(self, path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    def verify_fts5(self) -> bool:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE VIRTUAL TABLE test_fts USING fts5(content)")
            return True
        except sqlite3.OperationalError:
            return False
        finally:
            connection.close()

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chunk_meta (
                id INTEGER PRIMARY KEY,
                kb_id TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                confidence REAL NOT NULL,
                effective_from TEXT,
                effective_to TEXT,
                checksum TEXT NOT NULL,
                source_citation TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                content TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks
            USING fts5(content, document_id, collection_id, tokenize='unicode61 remove_diacritics 2')
            """
        )
        connection.commit()

    def rebuild_index(self, kb_id: str, chunks: list[ChunkRecord]) -> dict:
        active_path = self._index_path_getter(kb_id)
        active_path.parent.mkdir(parents=True, exist_ok=True)

        staging_path = active_path.parent / "search.db.next"

        with NamedTemporaryFile(delete=False, suffix=".db", dir=str(active_path.parent)) as temp_file:
            temp_path = Path(temp_file.name)

        connection = self._connect(temp_path)
        try:
            self._create_schema(connection)

            for chunk in chunks:
                cursor = connection.execute(
                    """
                    INSERT INTO chunk_meta (
                        kb_id, collection_id, document_id, version, chunk_index,
                        confidence, effective_from, effective_to, checksum, source_citation,
                        is_active, content
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.kb_id,
                        chunk.collection_id,
                        chunk.document_id,
                        chunk.version,
                        chunk.chunk_index,
                        chunk.confidence,
                        chunk.effective_from,
                        chunk.effective_to,
                        chunk.checksum,
                        chunk.source_citation,
                        1 if chunk.is_active else 0,
                        chunk.content,
                    ),
                )
                row_id = cursor.lastrowid
                connection.execute(
                    "INSERT INTO fts_chunks(rowid, content, document_id, collection_id) VALUES (?, ?, ?, ?)",
                    (row_id, chunk.content, chunk.document_id, chunk.collection_id),
                )

            connection.commit()
            self._validate_index(connection)
        finally:
            connection.close()

        if staging_path.exists():
            staging_path.unlink()

        temp_path.replace(staging_path)

        if active_path.exists():
            backup_path = active_path.parent / "search.db.bak"
            if backup_path.exists():
                backup_path.unlink()
            active_path.replace(backup_path)
            staging_path.replace(active_path)
            backup_path.unlink(missing_ok=True)
        else:
            staging_path.replace(active_path)

        return {
            "kb_id": kb_id,
            "index_path": str(active_path),
            "chunk_count": len(chunks),
        }

    def _validate_index(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT COUNT(*) AS count FROM chunk_meta").fetchone()
        if row is None:
            raise KnowledgeValidationError("Failed to validate index.")

    def _build_match_query(self, request: SearchRequest) -> str:
        query = request.query.strip()

        if not query:
            raise KnowledgeValidationError("Search query is empty.")

        if request.prefix:
            terms = [term for term in re.split(r"\s+", query) if term]
            return " ".join(f"{term}*" for term in terms)

        return query

    def search(self, kb_id: str, request: SearchRequest) -> SearchResponse:
        start = time.time()
        db_path = self._index_path_getter(kb_id)

        if not db_path.exists():
            return SearchResponse(query=request.query, took_ms=0, total=0, results=[])

        snapshot_path = db_path.parent / "search.db.read"

        try:
            shutil.copy2(db_path, snapshot_path)
            read_path = snapshot_path
        except Exception:
            read_path = db_path

        connection = self._connect(read_path)
        try:
            match_query = self._build_match_query(request)
            filters = ["m.kb_id = ?"]
            params: list = [kb_id]

            if request.collection_id:
                filters.append("m.collection_id = ?")
                params.append(request.collection_id)

            if request.document_id:
                filters.append("m.document_id = ?")
                params.append(request.document_id)

            if request.min_confidence is not None:
                filters.append("m.confidence >= ?")
                params.append(request.min_confidence)

            if request.active_only:
                filters.append("m.is_active = 1")

            if request.effective_at:
                filters.append("(m.effective_from IS NULL OR m.effective_from <= ?)")
                filters.append("(m.effective_to IS NULL OR m.effective_to >= ?)")
                params.extend([request.effective_at, request.effective_at])

            where_clause = " AND ".join(filters)

            identifier_tokens = IDENTIFIER_RE.findall(request.query.upper())
            boost_expr = "0.0"
            for token in identifier_tokens:
                safe_token = token.replace("'", "''")
                boost_expr += (
                    " + CASE WHEN INSTR(UPPER(m.content), '"
                    + safe_token
                    + "') > 0 THEN 1.0 ELSE 0.0 END"
                )

            sql = f"""
                SELECT
                    m.kb_id,
                    m.collection_id,
                    m.document_id,
                    m.version,
                    m.chunk_index,
                    m.content,
                    m.confidence,
                    m.source_citation,
                    bm25(fts_chunks) AS bm,
                    ({boost_expr}) AS boost
                FROM fts_chunks
                JOIN chunk_meta m ON m.id = fts_chunks.rowid
                WHERE fts_chunks MATCH ?
                  AND {where_clause}
                ORDER BY (-bm25(fts_chunks) + ({boost_expr})) DESC
                LIMIT ?
            """

            query_params = [match_query, *params, request.top_k * 3]
            rows = connection.execute(sql, query_params).fetchall()

            results: list[SearchResult] = []
            seen: set[tuple[str, int, int]] = set()

            for row in rows:
                key = (row["document_id"], row["version"], row["chunk_index"])
                if key in seen:
                    continue
                seen.add(key)

                score = float(-(row["bm"] or 0.0) + (row["boost"] or 0.0))
                bm25_value = float(row["bm"] or 0.0)
                boost_value = float(row["boost"] or 0.0)
                explanation = (
                    f"bm25={bm25_value:.4f}, identifier_boost={boost_value:.2f}"
                    if request.explain
                    else ""
                )

                results.append(
                    SearchResult(
                        kb_id=row["kb_id"],
                        collection_id=row["collection_id"],
                        document_id=row["document_id"],
                        version=row["version"],
                        chunk_index=row["chunk_index"],
                        content=row["content"],
                        confidence=row["confidence"],
                        score=score,
                        explanation=explanation,
                        source_citation=row["source_citation"],
                    )
                )

                if len(results) >= request.top_k:
                    break

            took_ms = int((time.time() - start) * 1000)
            return SearchResponse(
                query=request.query,
                took_ms=took_ms,
                total=len(results),
                results=results,
            )
        finally:
            connection.close()
            if read_path == snapshot_path and snapshot_path.exists():
                snapshot_path.unlink(missing_ok=True)
