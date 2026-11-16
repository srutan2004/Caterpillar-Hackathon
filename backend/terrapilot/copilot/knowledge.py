"""Knowledge indexing and hybrid retrieval (§12.2 rag_tool).

* Structure-aware chunking: every `### PROCEDURE <id>` is one chunk with its steps kept together; other
  sections split at headings, then by size. Metadata: machine_class, section, procedure_id, heading, fault codes.
* Dense vectors (fastembed, bge-small) in Qdrant — and a local copy so retrieval works offline.
* BM25 (rank-bm25) over the same chunks; the two rankings are fused with reciprocal rank fusion.
* `knowledge_scope` from the machine manifest filters by machine class.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from terrapilot.core.config import ConfigBundle
from terrapilot.core.logging import get_logger
from terrapilot.core.refs import load_ref_cached
from terrapilot.core.settings import REPO_ROOT, get_settings

log = get_logger("copilot.knowledge")
_FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)
_HEAD = re.compile(r"^(#{1,3})\s+(.*)$", re.M)
_PROC = re.compile(r"^###\s+PROCEDURE\s+([\w-]+)\s*:?\s*(.*)$")
_TOKEN = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")


@dataclass
class Chunk:
    id: str
    text: str
    machine_class: str
    section: str
    heading: str
    procedure_id: str | None
    fault_codes: list[str]
    source: str

    def payload(self) -> dict[str, Any]:
        return asdict(self)


class Embedder(Protocol):
    def __call__(self, texts: list[str]) -> np.ndarray: ...


# ------------------------------------------------------------------ chunking
def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    import yaml

    m = _FRONT.match(text)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, text[m.end() :]


def chunk_markdown(
    text: str, meta: dict[str, Any], source: str, max_words: int, code_re: re.Pattern[str]
) -> list[Chunk]:
    cls, section = str(meta.get("machine_class", "common")), str(meta.get("section", Path(source).stem))
    lines = text.splitlines()
    blocks: list[tuple[str, str | None, list[str]]] = []  # heading, procedure id, lines
    heading, proc = section, None
    buf: list[str] = []
    for ln in lines:
        h = _HEAD.match(ln)
        if h:
            if buf and "".join(buf).strip():
                blocks.append((heading, proc, buf))
            p = _PROC.match(ln)
            heading, proc, buf = (h.group(2).strip(), p.group(1) if p else None, [ln])
            continue
        buf.append(ln)
    if buf and "".join(buf).strip():
        blocks.append((heading, proc, buf))
    out: list[Chunk] = []
    for i, (head, pid, blines) in enumerate(blocks):
        body = "\n".join(blines).strip()
        pieces = [body]
        if pid is None and len(body.split()) > max_words:  # procedures are never split
            words, pieces = body.split(), []
            for j in range(0, len(words), max_words):
                pieces.append(" ".join(words[j : j + max_words]))
        for k, piece in enumerate(pieces):
            cid = pid or f"{cls}/{section}/{i:02d}{'' if len(pieces) == 1 else f'-{k}'}"
            out.append(Chunk(cid, piece, cls, section, head, pid, sorted(set(code_re.findall(piece))), source))
    return out


def load_chunks(cfg: ConfigBundle, manuals_dir: Path | None = None) -> list[Chunk]:
    kc = cfg.ask["knowledge"]
    base = manuals_dir or REPO_ROOT / kc["manuals_dir"]
    code_re = re.compile(kc["fault_code_pattern"])
    chunks: list[Chunk] = []
    for path in sorted(base.rglob("*.md")):
        meta, body = _frontmatter(path.read_text(encoding="utf-8"))
        chunks += chunk_markdown(body, meta, path.relative_to(base).as_posix(), int(kc["chunk_max_words"]), code_re)
    seen: dict[str, int] = {}
    for c in chunks:  # procedure ids can repeat across classes: make ids unique and stable
        n = seen.get(c.id, 0)
        seen[c.id] = n + 1
        if n:
            c.id = f"{c.machine_class}/{c.id}-{n}"
    return chunks


# ------------------------------------------------------------------ embeddings
def model_name(cfg: ConfigBundle) -> str:
    ref = cfg.ask["knowledge"]["embedding_model_ref"]
    return str(load_ref_cached(cfg.root, ref))


@lru_cache(maxsize=1)
def _fastembed(name: str) -> Any:
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=name, cache_dir=str(get_settings().data_dir / "models" / "fastembed"))


def default_embedder(cfg: ConfigBundle) -> Embedder:
    name = model_name(cfg)

    def embed(texts: list[str]) -> np.ndarray:
        vecs = np.array(list(_fastembed(name).embed(texts)), dtype=np.float32)
        return vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)

    return embed


def hashing_embedder(dim: int = 256) -> Embedder:
    """Deterministic bag-of-words embedder for tests/offline smoke checks (not used in production)."""

    def embed(texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in _TOKEN.findall(t.lower()):
                out[i, int(hashlib.md5(tok.encode()).hexdigest(), 16) % dim] += 1.0
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)

    return embed


# ------------------------------------------------------------------ index
def index_dir(cfg: ConfigBundle, data_dir: Path | None = None) -> Path:
    return (data_dir or get_settings().data_dir) / str(cfg.ask["knowledge"]["index_dir"])


def build_index(
    cfg: ConfigBundle,
    embedder: Embedder | None = None,
    *,
    manuals_dir: Path | None = None,
    data_dir: Path | None = None,
    qdrant: bool = True,
) -> dict[str, Any]:
    chunks = load_chunks(cfg, manuals_dir)
    if not chunks:
        raise RuntimeError("no approved manuals in knowledge/manuals — run `tp review approve` first")
    emb = embedder or default_embedder(cfg)
    vecs = emb([f"{c.heading}\n{c.text}" for c in chunks])
    out = index_dir(cfg, data_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "chunks.json").write_text(json.dumps([c.payload() for c in chunks], ensure_ascii=False), encoding="utf-8")
    np.save(out / "vectors.npy", vecs)
    stored = False
    if qdrant:
        stored = _upsert_qdrant(cfg, chunks, vecs)
    KnowledgeBase.cache_clear()
    return {"chunks": len(chunks), "dim": int(vecs.shape[1]), "qdrant": stored, "dir": str(out)}


def _upsert_qdrant(cfg: ConfigBundle, chunks: list[Chunk], vecs: np.ndarray) -> bool:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        client = QdrantClient(url=get_settings().qdrant_url, timeout=10)
        name = str(cfg.ask["knowledge"]["collection"])
        if client.collection_exists(name):
            client.delete_collection(name)
        client.create_collection(name, vectors_config=VectorParams(size=int(vecs.shape[1]), distance=Distance.COSINE))
        client.upsert(
            name,
            points=[PointStruct(id=i, vector=vecs[i].tolist(), payload=c.payload()) for i, c in enumerate(chunks)],
        )
        return True
    except Exception as exc:  # Qdrant is optional at runtime: the local vectors serve offline
        log.warning("qdrant upsert failed; local index only", error=str(exc)[:200])
        return False


_KB_CACHE: dict[str, KnowledgeBase] = {}


@dataclass
class Hit:
    chunk: Chunk
    score: float  # fused RRF score
    dense: float  # cosine similarity (bounded-knowledge threshold)
    bm25: float

    def cite(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk.id,
            "section": self.chunk.section,
            "heading": self.chunk.heading,
            "machine_class": self.chunk.machine_class,
            "score": round(self.dense, 3),
        }


class KnowledgeBase:
    def __init__(
        self, cfg: ConfigBundle, chunks: list[Chunk], vecs: np.ndarray, embedder: Embedder, use_qdrant: bool = True
    ):
        from rank_bm25 import BM25Okapi

        self.cfg = cfg
        self.chunks = chunks
        self.vecs = vecs
        self.embed = embedder
        self.bm25 = BM25Okapi([_TOKEN.findall(f"{c.heading} {c.text}".lower()) for c in chunks])
        self.use_qdrant = use_qdrant
        self.dense_source = "local"

    @classmethod
    def load(
        cls, cfg: ConfigBundle, data_dir: Path | None = None, embedder: Callable[..., Any] | None = None
    ) -> KnowledgeBase:
        d = index_dir(cfg, data_dir)
        key = str(d)
        if key not in _KB_CACHE:
            if not (d / "chunks.json").is_file():
                raise FileNotFoundError("knowledge index missing — run `uv run tp index`")
            chunks = [Chunk(**c) for c in json.loads((d / "chunks.json").read_text(encoding="utf-8"))]
            _KB_CACHE[key] = cls(cfg, chunks, np.load(d / "vectors.npy"), embedder or default_embedder(cfg))
        return _KB_CACHE[key]

    @staticmethod
    def cache_clear() -> None:
        _KB_CACHE.clear()

    def search(self, query: str, scope: list[str] | None = None, top_k: int | None = None) -> list[Hit]:
        rc = self.cfg.ask["retrieval"]
        k = int(top_k or rc["top_k"])
        n = int(rc["candidates_per_retriever"])
        allowed = np.array([scope is None or c.machine_class in scope for c in self.chunks])
        if not allowed.any():
            return []
        q = self.embed([query])[0]
        dense = self._qdrant_dense(q, scope, n)
        self.dense_source = "qdrant" if dense is not None else "local"
        if dense is None:
            dense = np.where(allowed, self.vecs @ q, -np.inf)
        bm = np.asarray(self.bm25.get_scores(_TOKEN.findall(query.lower())), dtype=float)
        bm = np.where(allowed, bm, -np.inf)
        d_rank = [i for i in np.argsort(-dense)[:n] if math.isfinite(dense[i])]
        b_rank = [i for i in np.argsort(-bm)[:n] if math.isfinite(bm[i]) and bm[i] > 0]
        rrf: dict[int, float] = {}
        kk = float(rc["rrf_k"])
        for rank_list in (d_rank, b_rank):
            for r, i in enumerate(rank_list):
                rrf[int(i)] = rrf.get(int(i), 0.0) + 1.0 / (kk + r + 1)
        best = sorted(rrf, key=lambda i: -rrf[i])[:k]
        return [
            Hit(self.chunks[i], rrf[i], float(dense[i]), float(bm[i]) if math.isfinite(bm[i]) else 0.0) for i in best
        ]

    def _qdrant_dense(self, q: np.ndarray, scope: list[str] | None, n: int) -> np.ndarray | None:
        """Dense scores from Qdrant (payload filter on machine_class); None when Qdrant is unavailable."""
        if not self.use_qdrant:
            return None
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import FieldCondition, Filter, MatchAny

            client = QdrantClient(url=get_settings().qdrant_url, timeout=2)
            flt = Filter(must=[FieldCondition(key="machine_class", match=MatchAny(any=scope))]) if scope else None
            res = client.query_points(
                str(self.cfg.ask["knowledge"]["collection"]), query=q.tolist(), limit=n, query_filter=flt
            )
        except Exception:
            self.use_qdrant = False  # fall back to local vectors for the rest of the process
            return None
        dense = np.full(len(self.chunks), -np.inf)
        ids = {c.id: i for i, c in enumerate(self.chunks)}
        for pt in res.points:
            i = ids.get(str((pt.payload or {}).get("id")))
            if i is not None:
                dense[i] = float(pt.score)
        return dense

    def by_procedure(self, procedure_id: str) -> list[Chunk]:
        return [c for c in self.chunks if c.procedure_id == procedure_id]
