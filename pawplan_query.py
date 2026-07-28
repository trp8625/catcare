"""
PawPlan Query Layer
====================
Takes a cat profile and a user question, retrieves relevant chunks from
the Chroma knowledge base, and generates a grounded answer via the Claude API.

Usage:
    python pawplan_query.py

Requirements:
    pip install anthropic chromadb sentence-transformers
    Set ANTHROPIC_API_KEY environment variable.

Flow:
    cat profile → derive life stage → retrieve chunks → generate answer
"""

import os
import json
from datetime import date
import chromadb
import google.genai as genai
import psycopg2
from psycopg2.extras import RealDictCursor
from sentence_transformers import SentenceTransformer


# ── CONFIG ────────────────────────────────────────────────────────────────────

CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "pawplan_knowledge"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
N_RESULTS = 5  # number of chunks to retrieve per query


# ── CAT PROFILE FROM POSTGRESQL ───────────────────────────────────────────────

def get_cat_profile(user_id: str) -> dict:
    """
    Fetches a cat profile from PostgreSQL by user_id.
    Returns a dict matching the shape the rest of the query layer expects.
    """
    conn = psycopg2.connect(os.environ.get("DATABASE_URL"))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM cat_profiles WHERE user_id = %s;",
                (user_id,)
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No profile found for user_id: {user_id}")
            profile = dict(row)
            # Normalize date_of_birth to ISO string for derive_life_stage()
            profile["date_of_birth"] = profile["date_of_birth"].isoformat()
            # Rename cat_name to name for consistency with rest of query layer
            profile["name"] = profile.pop("cat_name")
            return profile
    finally:
        conn.close()


# Default user for development — swap this for real auth later
DEFAULT_USER_ID = "user_001"


# ── LIFE STAGE DERIVATION ─────────────────────────────────────────────────────

def derive_life_stage(date_of_birth: str) -> tuple[str, float]:
    """
    Derives life stage and age from a date of birth string (YYYY-MM-DD).
    Returns (life_stage, age_in_years).
    """
    dob = date.fromisoformat(date_of_birth)
    today = date.today()
    age_years = (today - dob).days / 365.25

    if age_years < 1:
        life_stage = "kitten"
    elif age_years <= 6:
        life_stage = "young_adult"
    elif age_years <= 10:
        life_stage = "mature_adult"
    else:
        life_stage = "senior"

    return life_stage, round(age_years, 1)


# ── QUERY REWRITING ──────────────────────────────────────────────────────────

# Maps plain English query patterns to expanded technical terms.
# This bridges the gap between how users ask questions and how
# veterinary documents are written.
QUERY_EXPANSIONS = {
    "calorie": "calories kcal resting energy requirement RER daily energy requirement DER calorie calculation",
    "calories": "calories kcal resting energy requirement RER daily energy requirement DER calorie calculation",
    "how much to feed": "daily energy requirement RER calorie calculation portion feeding amount",
    "how much food": "daily energy requirement RER calorie calculation portion feeding amount",
    "weight": "body weight body condition score BCS weight management obesity",
    "overweight": "obesity body condition score BCS weight management overweight",
    "protein": "protein amino acids dietary protein lean muscle mass",
    "muscle": "muscle condition score MCS sarcopenia lean muscle mass protein",
}

def rewrite_query(question: str) -> str:
    """
    Expands a plain English question with technical veterinary terms
    to improve retrieval of relevant chunks.
    """
    question_lower = question.lower()
    expansions = []
    for keyword, expansion in QUERY_EXPANSIONS.items():
        if keyword in question_lower:
            expansions.append(expansion)
    if expansions:
        return f"{question} {' '.join(expansions)}"
    return question


# ── RETRIEVAL ─────────────────────────────────────────────────────────────────

def retrieve_chunks(question: str, life_stage: str, n_results: int = N_RESULTS) -> list[dict]:
    """
    Retrieves the most relevant chunks from Chroma for a given question,
    filtered to the cat's life stage (plus untagged chunks that apply to all).

    Returns a list of dicts with 'text', 'source_id', and 'topic_tags'.
    """
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION_NAME)
    embedder = SentenceTransformer(EMBEDDING_MODEL)

    expanded_question = rewrite_query(question)
    query_embedding = embedder.encode(expanded_question).tolist()

    # Filter: return chunks tagged for this life stage OR untagged chunks
    # Untagged chunks (no life_stage key) apply to all life stages
    where_filter = {
        "$or": [
            {"life_stage": {"$eq": json.dumps([life_stage])}},
            # Multi-stage docs (e.g. AAHA guidelines cover all 4 stages)
            {"life_stage": {"$contains": life_stage}},
        ]
    }

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        chunks = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        ):
            chunks.append({
                "text": doc,
                "source_id": meta.get("source_id", "unknown"),
                "source_type": meta.get("source_type", "unknown"),
                "topic_tags": meta.get("topic_tags", "[]"),
                "similarity": round(1 - dist, 3),
            })
        return chunks

    except Exception as e:
        # If life stage filter returns no results, fall back to unfiltered
        print(f"  Note: Life stage filter returned no results, falling back to unfiltered search")
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        chunks = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        ):
            chunks.append({
                "text": doc,
                "source_id": meta.get("source_id", "unknown"),
                "source_type": meta.get("source_type", "unknown"),
                "topic_tags": meta.get("topic_tags", "[]"),
                "similarity": round(1 - dist, 3),
            })
        return chunks


# ── ANSWER GENERATION ─────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    return """You are PawPlan, an AI-powered cat nutrition assistant.
Your answers are grounded in veterinary nutrition guidelines and research.
You give clear, practical, personalized advice based on the cat's profile.

Rules:
- Only use information from the provided context chunks to answer.
- If the context doesn't contain enough information to answer, say so clearly.
- Always tailor your answer to the specific cat's life stage, weight, and sex.
- Keep answers concise and owner-friendly — avoid unnecessary jargon.
- Never make up specific numbers (calories, protein percentages) unless they appear in the context.
- If a question requires veterinary diagnosis or treatment, recommend consulting a vet."""


def build_user_prompt(question: str, profile: dict, life_stage: str, age: float, chunks: list[dict]) -> str:
    # Format cat profile summary
    sex_str = f"{'spayed' if profile['neutered'] else 'intact'} {profile['sex']}"
    profile_summary = (
        f"Cat name: {profile['name']}\n"
        f"Age: {age} years ({life_stage.replace('_', ' ')})\n"
        f"Weight: {profile['weight_kg']} kg\n"
        f"Sex: {sex_str}"
    )

    # Format retrieved chunks as numbered context
    context_str = "\n\n".join([
        f"[Source {i+1}: {c['source_id']} | similarity: {c['similarity']}]\n{c['text']}"
        for i, c in enumerate(chunks)
    ])

    return f"""CAT PROFILE:
{profile_summary}

RETRIEVED CONTEXT:
{context_str}

USER QUESTION:
{question}

Please answer the question based on the retrieved context and the cat's profile above."""


def generate_answer(question: str, profile: dict, life_stage: str, age: float, chunks: list[dict]) -> str:
    """
    Sends the retrieved chunks and cat profile to Gemini and returns the answer.
    """
    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=build_user_prompt(question, profile, life_stage, age, chunks),
        config=genai.types.GenerateContentConfig(
            system_instruction=build_system_prompt()
        )
    )

    return response.text


# ── MAIN QUERY FUNCTION ───────────────────────────────────────────────────────

def ask(question: str, user_id: str = DEFAULT_USER_ID, verbose: bool = False) -> str:
    """
    Main entry point for the PawPlan query layer.

    Takes a user question and a cat profile dict, returns a grounded answer.

    Args:
        question: The user's nutrition question
        profile: Cat profile dict (defaults to MOCK_PROFILE for development)
        verbose: If True, prints retrieved chunks before the answer

    Returns:
        A string answer grounded in the knowledge base
    """
    # Step 1: Load cat profile from PostgreSQL
    profile = get_cat_profile(user_id)

    # Step 2: Derive life stage
    life_stage, age = derive_life_stage(profile["date_of_birth"])
    print(f"\n{'='*60}")
    print(f"Cat: {profile['name']} | Age: {age}y | Life stage: {life_stage}")
    print(f"Question: {question}")
    print(f"{'='*60}")

    # Step 3: Retrieve relevant chunks
    chunks = retrieve_chunks(question, life_stage)

    # Inject pinned chunks for specific query types
    # This ensures key formulas always surface regardless of similarity ranking
    question_lower = question.lower()
    if any(word in question_lower for word in ["calorie", "calories", "how much to feed", "how much food", "kcal", "energy"]):
        rer_chunk = {
            "text": """Calorie calculation for cats using Resting Energy Requirements (RER):
RER (kcal per day) = 30 x (body weight in kg) + 70.
Daily Energy Requirements (DER) are calculated by multiplying RER by a needs factor.
For young healthy adult cats the needs factor is 1 (DER = RER).
For mature adult cats aged 7-10 years, DER may be equivalent to RER.
For senior cats over 10 years, RER should be multiplied by a factor of 1.1 to 1.2
(i.e. 10-20% above RER), and in some cases up to 1.25 (25% above RER).
Example: A 4.2 kg senior cat has RER = 30 x 4.2 + 70 = 196 kcal/day.
At a 1.2 needs factor, DER = 196 x 1.2 = 235 kcal/day.
Source: 2021 AAHA/AAFP Feline Life Stage Guidelines.""",
            "source_id": "2021-aaha-aafp-feline-life-stage-guidelines.pdf",
            "source_type": "guideline",
            "topic_tags": '["calorie_calculation", "energy_requirements"]',
            "similarity": 1.0,  # pinned — always included
        }
        # Insert at position 0 so it leads the context
        chunks.insert(0, rer_chunk)
        chunks = chunks[:N_RESULTS]  # keep total at N_RESULTS
        print(f"  → Pinned RER formula chunk injected")

    print(f"Retrieved {len(chunks)} chunks")

    if verbose:
        print("\n── Retrieved chunks ──")
        for i, chunk in enumerate(chunks):
            print(f"\n[{i+1}] {chunk['source_id']} (similarity: {chunk['similarity']})")
            print(chunk['text'][:300] + "...")

    # Step 4: Generate answer
    print("\nGenerating answer...\n")
    answer = generate_answer(question, profile, life_stage, age, chunks)

    print(f"── Answer ──\n{answer}")
    return answer


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test with two different questions against the mock profile
    ask("how much protein does my cat need?")

    print("\n")

    ask("how many calories should my cat eat per day?")
