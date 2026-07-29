"""
PawPlan Query Layer
====================
Takes a cat profile and a user question, retrieves relevant chunks from
the Chroma knowledge base, and generates a grounded answer via the Gemini API.
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
N_RESULTS = 5


# ── CAT PROFILE FROM POSTGRESQL ───────────────────────────────────────────────

def get_cat_profile(user_id: str) -> dict:
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
            profile["date_of_birth"] = profile["date_of_birth"].isoformat()
            profile["name"] = profile.pop("cat_name")
            return profile
    finally:
        conn.close()


DEFAULT_USER_ID = "user_001"


# ── LIFE STAGE DERIVATION ─────────────────────────────────────────────────────

def derive_life_stage(date_of_birth: str) -> tuple[str, float]:
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


# ── QUERY REWRITING ───────────────────────────────────────────────────────────

QUERY_EXPANSIONS = {
    "calorie": "calories kcal resting energy requirement RER daily energy requirement DER calorie calculation",
    "calories": "calories kcal resting energy requirement RER daily energy requirement DER calorie calculation",
    "how much to feed": "daily energy requirement RER calorie calculation portion feeding amount",
    "how much food": "daily energy requirement RER calorie calculation portion feeding amount",
    "weight": "body weight body condition score BCS weight management obesity",
    "overweight": "obesity body condition score BCS weight management overweight",
    "protein": "protein amino acids dietary protein lean muscle mass obligate carnivore",
    "muscle": "muscle condition score MCS sarcopenia lean muscle mass protein",
}

def rewrite_query(question: str) -> str:
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
    Retrieves relevant chunks from Chroma.
    Strategy: run two queries (life-stage filtered + unfiltered) and merge,
    deduplicating by text. This avoids filter failures causing empty results.
    """
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION_NAME)
    embedder = SentenceTransformer(EMBEDDING_MODEL)

    expanded_question = rewrite_query(question)
    query_embedding = embedder.encode(expanded_question).tolist()

    all_chunks = []
    seen_texts = set()

    def _parse_results(results):
        chunks = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        ):
            if doc not in seen_texts:
                seen_texts.add(doc)
                chunks.append({
                    "text": doc,
                    "source_id": meta.get("source_id", "unknown"),
                    "source_type": meta.get("source_type", "unknown"),
                    "topic_tags": meta.get("topic_tags", "[]"),
                    "similarity": round(1 - dist, 3),
                })
        return chunks

    # Query 1: life-stage filtered
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"life_stage": {"$eq": life_stage}},
            include=["documents", "metadatas", "distances"]
        )
        all_chunks.extend(_parse_results(results))
    except Exception:
        pass

    # Query 2: unfiltered fallback to catch general + multi-stage chunks
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        all_chunks.extend(_parse_results(results))
    except Exception as e:
        print(f"Unfiltered query failed: {e}")

    # Sort by similarity and cap at n_results
    all_chunks.sort(key=lambda x: x["similarity"], reverse=True)
    return all_chunks[:n_results]


# ── ANSWER GENERATION ─────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    return """You are CatCare, an AI-powered cat nutrition assistant.
Your answers are grounded in veterinary nutrition guidelines and research.
You give clear, practical, personalized advice based on the cat's profile.

Rules:
- Use information from the provided context chunks to answer.
- Always tailor your answer to the specific cat's life stage, weight, and sex.
- Keep answers concise and owner-friendly.
- Never make up specific numbers unless they appear in the context.
- If a question requires veterinary diagnosis or treatment, recommend consulting a vet."""


def build_user_prompt(question: str, profile: dict, life_stage: str, age: float, chunks: list[dict]) -> str:
    sex_str = f"{'spayed' if profile['neutered'] else 'intact'} {profile['sex']}"
    profile_summary = (
        f"Cat name: {profile['name']}\n"
        f"Age: {age} years ({life_stage.replace('_', ' ')})\n"
        f"Weight: {profile['weight_kg']} kg\n"
        f"Sex: {sex_str}"
    )

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
    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=build_user_prompt(question, profile, life_stage, age, chunks),
        config=genai.types.GenerateContentConfig(
            system_instruction=build_system_prompt()
        )
    )

    return response.text


# ── MAIN QUERY FUNCTION ───────────────────────────────────────────────────────

def ask(question: str, user_id: str = DEFAULT_USER_ID, verbose: bool = False) -> str:
    # Step 1: Load cat profile
    profile = get_cat_profile(user_id)

    # Step 2: Derive life stage
    life_stage, age = derive_life_stage(profile["date_of_birth"])

    # Step 3: Retrieve chunks
    chunks = retrieve_chunks(question, life_stage)

    # Step 4: Inject pinned chunks for calorie/energy questions
    question_lower = question.lower()
    if any(word in question_lower for word in ["calorie", "calories", "how much to feed", "how much food", "kcal", "energy"]):
        rer_chunk = {
            "text": """Calorie calculation for cats using Resting Energy Requirements (RER):
RER (kcal per day) = 30 x (body weight in kg) + 70.
Daily Energy Requirements (DER) are calculated by multiplying RER by a needs factor.
For young healthy adult cats the needs factor is 1.0-1.2 (DER = RER x 1.0-1.2).
For mature adult cats aged 7-10 years, DER may be equivalent to RER x 1.0-1.1.
For senior cats over 10 years, RER should be multiplied by a factor of 1.1 to 1.2.
Example: A 4.2 kg senior cat has RER = 30 x 4.2 + 70 = 196 kcal/day.
At a 1.2 needs factor, DER = 196 x 1.2 = 235 kcal/day.
Source: 2021 AAHA/AAFP Feline Life Stage Guidelines.""",
            "source_id": "2021-aaha-aafp-feline-life-stage-guidelines.pdf",
            "source_type": "guideline",
            "topic_tags": '["calorie_calculation", "energy_requirements"]',
            "similarity": 1.0,
        }
        chunks.insert(0, rer_chunk)
        chunks = chunks[:N_RESULTS]

    # Step 5: Generate answer
    answer = generate_answer(question, profile, life_stage, age, chunks)
    return answer


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ask("how much protein does my cat need?")
    print("\n")
    ask("how many calories should my cat eat per day?")
