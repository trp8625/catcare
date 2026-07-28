"""
PawPlan RAG Ingestion Pipeline
================================
Reads PDFs from a source folder, chunks them, attaches manual metadata,
and loads them into a local Chroma vector database.

Usage:
    python pawplan_ingest.py

Requirements:
    pip install chromadb pypdf sentence-transformers

Folder structure expected:
    documents/
        general_feline_nutrition/
        life_stage/
        practical_feeding/
    metadata_config.py   ← you fill this in per document
"""

import os
import json
import chromadb
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from metadata_config import DOCUMENT_METADATA


# ── CONFIG ────────────────────────────────────────────────────────────────────

DOCUMENTS_DIR = "documents"
CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "pawplan_knowledge"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # fast, good quality, runs locally

# Chunk size in characters. 1000 chars ≈ 150-200 words, which is a good
# size for retrieval — specific enough to be useful, broad enough for context.
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150  # overlap prevents cutting a sentence mid-thought


# ── CHUNKING ──────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract raw text from a PDF file."""
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text.strip())
    return "\n\n".join(pages)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping chunks by character count.
    Tries to break at sentence boundaries ('. ') to avoid mid-sentence cuts.
    """
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            # Try to find a sentence boundary near the end of the window
            boundary = text.rfind(". ", start, end)
            if boundary != -1 and boundary > start + (chunk_size // 2):
                end = boundary + 1  # include the period
            # Otherwise fall back to the hard character limit

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap  # step back by overlap amount

    return chunks


# ── LIFE STAGE DERIVATION (for query time — shown here for reference) ─────────

def derive_life_stage(age_in_years: float) -> str:
    """
    Derives life stage from a cat's age.
    Called at query time using the cat's profile from PostgreSQL,
    not stored as a fixed field.
    """
    if age_in_years < 1:
        return "kitten"
    elif age_in_years <= 6:
        return "young_adult"
    elif age_in_years <= 10:
        return "mature_adult"
    else:
        return "senior"


# ── INGESTION ─────────────────────────────────────────────────────────────────

def ingest_documents():
    # Set up Chroma (local, no external dependency)
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # Delete and recreate collection on each run so re-ingestion is clean
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Cleared existing collection: {COLLECTION_NAME}")
    except Exception:
        pass  # collection didn't exist yet, that's fine

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}  # cosine similarity for semantic search
    )

    # Load embedding model (runs locally, no API key needed)
    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    embedder = SentenceTransformer(EMBEDDING_MODEL)

    total_chunks = 0

    # Manual chunks for image-based PDFs that pypdf cannot extract text from
    MANUAL_CHUNKS = {
        "Muscle-Condition-Score-Chart-for-Cats.pdf": [
            """The WSAVA Muscle Condition Score (MCS) chart assesses muscle mass in cats on a scale from 
normal to severely wasted. Muscle is evaluated by visual examination and palpation over the 
spine, scapulae, skull, and wings of the ilia. Grades are: Normal muscle mass; Mild muscle 
wasting (slight loss over spine/scapulae); Moderate muscle wasting (moderate loss, bones 
easily palpable); Severe muscle wasting (dramatic loss, bones prominent). MCS should be 
assessed alongside Body Condition Score (BCS) at every veterinary visit. Muscle wasting 
(sarcopenia) is common in senior cats and can occur even when BCS appears normal or high, 
making MCS an essential separate assessment. Cats with low MCS despite adequate BCS may 
require higher dietary protein to preserve lean muscle mass."""
        ]
    }

    # Supplementary chunks injected alongside regular chunks for specific documents.
    # Used when a key formula or fact gets split across chunk boundaries during extraction.
    SUPPLEMENTARY_CHUNKS = {
        "2021-aaha-aafp-feline-life-stage-guidelines.pdf": [
            """Calorie calculation for cats using Resting Energy Requirements (RER):
RER (kcal per day) = 30 x (body weight in kg) + 70.
Daily Energy Requirements (DER) are calculated by multiplying RER by a needs factor.
For young healthy adult cats the needs factor is 1 (DER = RER).
For mature adult cats aged 7-10 years, DER may be equivalent to RER.
For senior cats over 10 years, RER should be multiplied by a factor of 1.1 to 1.2
(i.e. 10-20% above RER), and in some cases up to 1.25 (25% above RER).
Example: A 4.2 kg senior cat has RER = 30 x 4.2 + 70 = 196 kcal/day.
At a 1.2 needs factor, DER = 196 x 1.2 = 235 kcal/day.
Food intake is determined by comparing DER with the caloric density of the cat's food.
Source: 2021 AAHA/AAFP Feline Life Stage Guidelines."""
        ]
    }

    for filename, doc_meta in DOCUMENT_METADATA.items():
        pdf_path = doc_meta["path"]

        if not os.path.exists(pdf_path):
            print(f"  WARNING: File not found, skipping — {pdf_path}")
            continue

        print(f"\nProcessing: {filename}")

        # Extract and chunk text
        raw_text = extract_text_from_pdf(pdf_path)
        chunks = chunk_text(raw_text)
        print(f"  → {len(chunks)} chunks")

        if len(chunks) == 0:
            if filename in MANUAL_CHUNKS:
                chunks = MANUAL_CHUNKS[filename]
                print(f"  → Using manual chunk (image-based PDF)")
            else:
                print(f"  → Skipping (no extractable text — likely a scanned/image PDF)")
                continue

        # Build chunk IDs, embeddings, and metadata
        ids = []
        embeddings = []
        metadatas = []
        documents = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{filename}__chunk_{i}"

            # Metadata attached to every chunk
            metadata = {
                "source_id": filename,
                "source_type": doc_meta["source_type"],
                "topic_tags": json.dumps(doc_meta["topic_tags"]),  # Chroma stores strings
                "chunk_index": i,
                "year": doc_meta["year"],
            }

            # life_stage is optional — null means "applies to all life stages"
            if doc_meta.get("life_stage"):
                metadata["life_stage"] = json.dumps(doc_meta["life_stage"])

            ids.append(chunk_id)
            embeddings.append(embedder.encode(chunk).tolist())
            metadatas.append(metadata)
            documents.append(chunk)

        # Inject supplementary chunks if defined for this document
        if filename in SUPPLEMENTARY_CHUNKS:
            for i, supp_chunk in enumerate(SUPPLEMENTARY_CHUNKS[filename]):
                supp_id = f"{filename}__supplementary_{i}"
                supp_meta = {
                    "source_id": filename,
                    "source_type": doc_meta["source_type"],
                    "topic_tags": json.dumps(doc_meta["topic_tags"]),
                    "chunk_index": len(chunks) + i,
                    "year": doc_meta["year"],
                }
                if doc_meta.get("life_stage"):
                    supp_meta["life_stage"] = json.dumps(doc_meta["life_stage"])
                ids.append(supp_id)
                embeddings.append(embedder.encode(supp_chunk).tolist())
                metadatas.append(supp_meta)
                documents.append(supp_chunk)
            print(f"  → +{len(SUPPLEMENTARY_CHUNKS[filename])} supplementary chunk(s)")

        # Load batch into Chroma
        collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

        total_chunks += len(chunks)
        print(f"  → Loaded into Chroma")

    print(f"\nIngestion complete. Total chunks loaded: {total_chunks}")
    print(f"Chroma DB saved to: {CHROMA_PATH}/")


# ── QUERY HELPER (for testing retrieval) ─────────────────────────────────────

def query(question: str, cat_age: float = None, n_results: int = 5):
    """
    Run a test query against the knowledge base.
    Optionally filter by life stage derived from cat_age.

    Example:
        query("how much protein does a senior cat need?", cat_age=12)
    """
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION_NAME)
    embedder = SentenceTransformer(EMBEDDING_MODEL)

    query_embedding = embedder.encode(question).tolist()

    # Build life stage filter if age provided
    where_filter = None
    if cat_age is not None:
        life_stage = derive_life_stage(cat_age)
        # Return chunks tagged for this life stage OR untagged chunks (null = all life stages)
        where_filter = {
            "$or": [
                {"life_stage": {"$eq": json.dumps([life_stage])}},
                {"life_stage": {"$eq": json.dumps(["all"])}},
            ]
        }
        print(f"Life stage filter: {life_stage}")

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    print(f"\nQuery: {question}")
    print("-" * 60)
    for i, (doc, meta, dist) in enumerate(zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    )):
        print(f"\nResult {i+1} (similarity: {1 - dist:.3f})")
        print(f"Source: {meta['source_id']} | Type: {meta['source_type']}")
        print(f"Tags: {meta.get('topic_tags', '[]')}")
        print(f"Text: {doc[:200]}...")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ingest_documents()
