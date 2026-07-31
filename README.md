# CatCare

**AI-powered personalized cat nutrition assistant**

View here: https://catcare.up.railway.app/

CatCare answers feline nutrition questions using a profile-aware RAG (Retrieval-Augmented Generation) pipeline. Given a cat's profile, it retrieves relevant veterinary content from a curated knowledge base and generates grounded, personalized answers via an LLM.

---

## Architecture

PawPlan uses a three-layer architecture designed around a core principle: **if the answer is a lookup, use structured storage; if it requires reasoning, use RAG.**

```
User question
     │
     ▼
┌─────────────────────────────────┐
│  Layer 1: Cat Profile           │
│  PostgreSQL (Supabase)          │
│  Structured, deterministic      │
│  Fields: name, DOB, sex,        │
│  neutered, weight_kg            │
└──────────────┬──────────────────┘
               │ derive life stage from DOB
               ▼
┌─────────────────────────────────┐
│  Layer 2: RAG Knowledge Base    │
│  ChromaDB (local vector DB)     │
│  574 chunks across 11 documents │
│  Filtered by life stage         │
│  Embedded: all-MiniLM-L6-v2     │
└──────────────┬──────────────────┘
               │ top-k chunks
               ▼
┌─────────────────────────────────┐
│  Layer 3: Answer Generation     │
│  Google Gemini API              │
│  Grounded in retrieved chunks   │
│  Personalized to cat profile    │
└─────────────────────────────────┘
               │
               ▼
        Personalized answer
```

### Key design decisions

**Life stage derived at query time, not stored.** The cat's date of birth is stored in PostgreSQL. Life stage (kitten / young adult / mature adult / senior) is calculated at query time using the current date. This ensures the life stage is always accurate without requiring any update logic.

**Life stage mapping:**
- Under 1 year → kitten
- 1–6 years → young adult
- 7–10 years → mature adult
- Over 10 years → senior

**Profile-aware retrieval.** The cat's life stage is used as a metadata filter on ChromaDB. Chunks tagged for the cat's life stage are retrieved preferentially. Untagged chunks (null life stage) apply universally and are always included.

**Manual metadata tagging.** All 11 documents were manually tagged with `topic_tags` and `life_stage`. At this corpus size, manual tagging gives higher precision than automated LLM tagging.

**Structured data stays out of RAG.** Commercial food data (Phase 3) belongs in a structured lookup layer, not the vector database. The RAG layer is for content that requires reasoning, not lookups.

---

## Knowledge Base

11 documents across 3 subfolders, ingested as 574 chunks.

### general_feline_nutrition
| Document | Type | Year | Key content |
|----------|------|------|-------------|
| Calorie-Needs-for-Healthy-Adult-Cats | Chart | 2020 | Calorie tables by bodyweight |
| cat_nutrition_final | Research paper | 2002 | Obligate carnivore nutritional requirements |
| estimation-of-the-dietary-nutrient-profile-of-free-roaming-feral-cats | Research paper | 2011 | Feral cat macronutrient baseline |
| Muscle-Condition-Score-Chart-for-Cats | Chart | 2014 | MCS scoring (manual chunk — image PDF) |
| nutrient requirements of cats | Guideline | 2006 | NRC nutrient requirements |
| WSAVA_BCSCat_BCSCat_Nutrition | Chart | 2025 | Body condition scoring |
| WSAVA_GuidetoTreats_Cats | Guideline | 2025 | Treat guidelines and toxic foods |

### life_stage
| Document | Type | Year | Key content |
|----------|------|------|-------------|
| 10.1177_1098612X211021538 | Guideline | 2021 | AAFP Senior Care Guidelines |
| 2021-aaha-aafp-feline-life-stage-guidelines | Guideline | 2021 | AAHA/AAFP Life Stage Guidelines |

### practical_feeding
| Document | Type | Year | Key content |
|----------|------|------|-------------|
| FelineVMAHowtoFeedCat_Web | Client brochure | 2024 | Behavioral feeding, meal frequency, multi-cat households |
| Selecting-a-pet-food-for-your-pet-updated-2021_WSAVA | Guideline | 2021 | Pet food brand and label evaluation |

---

## Metadata Schema

Each chunk in ChromaDB carries the following metadata:

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | string | Filename of source document |
| `source_type` | string | `guideline`, `research_paper`, `chart`, `client_brochure` |
| `topic_tags` | JSON string | List of content tags (see vocabulary below) |
| `life_stage` | JSON string | List of applicable life stages, or absent if universal |
| `chunk_index` | integer | Position within source document |
| `year` | integer | Publication year |

### Topic tag vocabulary

**Nutrition fundamentals:** `protein`, `fat`, `carbohydrates`, `vitamins`, `minerals`, `hydration`, `taurine`, `amino_acids`, `energy_requirements`, `macronutrient_ratios`, `calorie_calculation`

**Feeding practice:** `meal_frequency`, `portion_control`, `puzzle_feeders`, `multi_cat_feeding`, `food_texture`, `food_transitions`

**Body condition:** `body_condition_score`, `muscle_condition_score`, `obesity_prevention`, `weight_management`

**Food evaluation:** `aafco_standards`, `label_reading`, `brand_evaluation`, `treat_guidelines`, `toxic_foods`

**Life stage specific:** `kitten_growth`, `senior_caloric_needs`, `sarcopenia`

---

## Database Schema

```sql
CREATE TABLE cat_profiles (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(50) UNIQUE NOT NULL,
    cat_name        VARCHAR(100) NOT NULL,
    date_of_birth   DATE NOT NULL,
    sex             VARCHAR(10) NOT NULL,
    neutered        BOOLEAN NOT NULL,
    weight_kg       DECIMAL(4,1) NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
```

One cat per user enforced via `UNIQUE` constraint on `user_id`.

---

## File Structure

```
catcare/
├── pawplan_ingest.py       # Ingestion pipeline: PDFs → ChromaDB
├── pawplan_query.py        # Query layer: profile + question → answer
├── pawplan_db_setup.py     # Database setup: creates table, inserts test profile
├── metadata_config.py      # Manual metadata assignments for all 11 documents
├── chroma_db/              # Local ChromaDB storage (574 chunks)
├── general_feline_nutrition/
├── life_stage/
└── practical_feeding/
```

---

## Setup

### Prerequisites
- Python 3.11 (via conda)
- Supabase account (free tier)
- Google AI Studio account (free tier)

### Environment

```bash
conda activate pawplan
export DATABASE_URL='postgresql://...'
export GOOGLE_API_KEY='...'
```

### Install dependencies

```bash
pip install chromadb pypdf sentence-transformers psycopg2-binary google-genai
pip install "torch==2.2.2" "numpy<2" "sentence-transformers==2.7.0" "transformers==4.38.0"
```

### Run ingestion

```bash
python pawplan_ingest.py
```

Reads all 11 PDFs, chunks them, embeds with `all-MiniLM-L6-v2`, loads into ChromaDB. Produces 574 chunks.

### Set up database

```bash
python pawplan_db_setup.py
```

Creates `cat_profiles` table in Supabase and inserts a test profile.

### Run a query

```bash
python pawplan_query.py
```

Fetches profile from PostgreSQL, retrieves relevant chunks from ChromaDB filtered by life stage, generates answer via Gemini.

---

## Scope

**Phase 1 (complete):** Healthy cats across four life stages. RAG knowledge base (574 chunks, 11 documents), PostgreSQL cat profiles, life stage-filtered retrieval, answer generation via Gemini.

**Phase 2 (complete):** Retrieval tuning. Fixed calorie calculation gap via query rewriting and pinned RER formula chunk injection.

**Phase 3 (complete):** Commercial food product matching. 829 wet cat food products scored and ranked by life stage nutritional targets, with per-day feeding calculations based on the cat's calculated DER.

**Phase 4 (deferred):** Disease-specific nutrition. Requires comorbidity handling and conflict resolution logic. See architectural note below.

---

## Architectural Notes

### Why product matching is a separate layer from RAG

Commercial cat food data is structured and deterministic — a product either has 45% protein or it doesn't. Putting it in the vector database would mean retrieving it by semantic similarity, which is the wrong tool for a lookup problem. The product matcher uses direct CSV filtering and numerical scoring, which is faster, more predictable, and easier to explain.

### Why Phase 4 is deferred

The Phase 3 product scorer ranks products based on life stage nutritional targets for healthy cats. Introducing health conditions (Phase 4) requires a fundamentally different scoring model for two reasons:

**Hard constraints vs soft scoring.** A cat with chronic kidney disease (CKD) requires phosphorus restriction — typically under 100–120 mg/100kcal. This is not a scoring preference; it is a hard ceiling that overrides all other criteria. The current scorer has no concept of hard constraints.

**Comorbidity conflict resolution.** Many senior cats have multiple conditions simultaneously. A cat with both CKD and obesity needs low phosphorus AND calorie restriction. A cat with CKD and sarcopenia needs low phosphorus but HIGH protein — goals that conflict directly, since high-protein foods tend to be high in phosphorus. Resolving these conflicts requires a constraint satisfaction approach, not a simple scoring function.

For example, the top-ranked products for a healthy senior cat have phosphorus values of 226–341 mg/100kcal. For a cat with CKD, those same products would be contraindicated and the ranking would look completely different. Phase 4 addresses this by introducing condition-specific hard constraints and conflict resolution logic.

### Why life stage is derived at query time, not stored

Storing life stage as a fixed field in the cat profile would cause it to go stale — a cat crosses from young adult to mature adult at age 7, and nothing would update the stored value automatically. Deriving it at query time from date_of_birth ensures it is always accurate with no maintenance burden.

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Vector database | ChromaDB (local) |
| Embeddings | all-MiniLM-L6-v2 (sentence-transformers) |
| Structured database | PostgreSQL via Supabase |
| LLM | Google Gemini (gemini-3.5-flash) |
| PDF extraction | pypdf |
| Language | Python 3.11 |
