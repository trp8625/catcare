"""
CatCare API
============
FastAPI backend that exposes the CatCare pipeline as HTTP endpoints.

Endpoints:
    POST /profile            - Create or update a cat profile
    GET  /profile/{cat_id}   - Get a cat profile with life stage and DER
    POST /ask                - Ask a nutrition question for a specific cat
    GET  /recommend/{cat_id} - Get product recommendations for a cat

Usage:
    pip install fastapi uvicorn
    uvicorn catcare_api:app --reload

Then open http://localhost:8000/docs to see the interactive API documentation.

Environment variables required:
    DATABASE_URL    - PostgreSQL connection string (Supabase)
    GOOGLE_API_KEY  - Google Gemini API key
"""

import os
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Import existing pipeline functions
from pawplan_query import ask, get_cat_profile, derive_life_stage
from catcare_matcher import match, calculate_der, load_products, score_product, calculate_feeding_amount
import psycopg2
from psycopg2.extras import RealDictCursor


# ── APP SETUP ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CatCare API",
    description="AI-powered personalized cat nutrition assistant",
    version="1.0.0",
)

# CORS: update allow_origins to your Railway domain once deployed
# e.g. ["https://catcare-production.up.railway.app"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── STATIC FILES (serves catcare.html at /) ───────────────────────────────────

# Serve catcare.html when someone visits the root URL
@app.get("/", include_in_schema=False)
def serve_frontend():
    html_path = os.path.join(os.path.dirname(__file__), "catcare.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="Frontend not found. Make sure catcare.html is in the project folder.")
    return FileResponse(html_path, media_type="text/html")


# ── REQUEST / RESPONSE MODELS ─────────────────────────────────────────────────

class CatProfileCreate(BaseModel):
    cat_id: str               # unique identifier for the cat (e.g. "shelter-cat-001")
    cat_name: str
    date_of_birth: str        # ISO format: "2020-03-15"
    sex: str                  # "male" or "female"
    neutered: bool
    weight_kg: float

    class Config:
        json_schema_extra = {
            "example": {
                "cat_id": "shelter-cat-001",
                "cat_name": "Biscuit",
                "date_of_birth": "2020-03-15",
                "sex": "male",
                "neutered": True,
                "weight_kg": 4.5
            }
        }


class AskRequest(BaseModel):
    cat_id: str
    question: str

    class Config:
        json_schema_extra = {
            "example": {
                "cat_id": "shelter-cat-001",
                "question": "How much protein does my cat need?"
            }
        }


# ── DATABASE HELPERS ──────────────────────────────────────────────────────────

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")
    return psycopg2.connect(db_url)


def fetch_profile_from_db(cat_id: str) -> dict:
    """Fetch a cat profile from PostgreSQL by cat_id."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM cat_profiles WHERE user_id = %s;",
                (cat_id,)
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No cat profile found for id: {cat_id}"
                )
            profile = dict(row)
            profile["date_of_birth"] = profile["date_of_birth"].isoformat()
            profile["name"] = profile.pop("cat_name")
            return profile
    finally:
        conn.close()


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@app.post("/profile")
def create_or_update_profile(profile: CatProfileCreate):
    """
    Create or update a cat profile.
    If a profile with the same cat_id already exists, it will be updated.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cat_profiles (user_id, cat_name, date_of_birth, sex, neutered, weight_kg)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    cat_name      = EXCLUDED.cat_name,
                    date_of_birth = EXCLUDED.date_of_birth,
                    sex           = EXCLUDED.sex,
                    neutered      = EXCLUDED.neutered,
                    weight_kg     = EXCLUDED.weight_kg,
                    updated_at    = NOW();
            """, (
                profile.cat_id,
                profile.cat_name,
                profile.date_of_birth,
                profile.sex,
                profile.neutered,
                profile.weight_kg,
            ))
        conn.commit()

        life_stage, age = derive_life_stage(profile.date_of_birth)
        energy = calculate_der(profile.weight_kg, life_stage)

        return {
            "cat_id": profile.cat_id,
            "cat_name": profile.cat_name,
            "date_of_birth": profile.date_of_birth,
            "sex": profile.sex,
            "neutered": profile.neutered,
            "weight_kg": profile.weight_kg,
            "age_years": age,
            "life_stage": life_stage,
            "energy": energy,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/profile/{cat_id}")
def get_profile(cat_id: str):
    """
    Get a cat profile by cat_id, including derived life stage and energy requirements.
    """
    profile = fetch_profile_from_db(cat_id)
    life_stage, age = derive_life_stage(profile["date_of_birth"])
    energy = calculate_der(float(profile["weight_kg"]), life_stage)

    return {
        "cat_id": cat_id,
        "cat_name": profile["name"],
        "date_of_birth": profile["date_of_birth"],
        "sex": profile["sex"],
        "neutered": profile["neutered"],
        "weight_kg": float(profile["weight_kg"]),
        "age_years": age,
        "life_stage": life_stage,
        "energy": energy,
    }


@app.post("/ask")
def ask_question(request: AskRequest):
    """
    Ask a nutrition question for a specific cat.
    Returns a grounded answer based on the veterinary knowledge base.
    """
    profile = fetch_profile_from_db(request.cat_id)

    try:
        answer = ask(
            question=request.question,
            user_id=request.cat_id,
            verbose=False
        )
        life_stage, age = derive_life_stage(profile["date_of_birth"])

        return {
            "cat_id": request.cat_id,
            "cat_name": profile["name"],
            "question": request.question,
            "answer": answer,
            "life_stage": life_stage,
            "age_years": age,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recommend/{cat_id}")
def get_recommendations(cat_id: str, top_n: int = 5):
    """
    Get product recommendations for a specific cat.
    Returns top-N ranked wet cat food products with feeding amounts.

    Query params:
        top_n: number of recommendations to return (default: 5, max: 20)
    """
    if top_n > 20:
        top_n = 20

    profile = fetch_profile_from_db(cat_id)

    try:
        result = match(profile, top_n=top_n)
        return result
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=str(e) + " Make sure cat_food_products_clean.csv is in the project folder."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health_check():
    """Simple health check endpoint for deployment monitoring."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
