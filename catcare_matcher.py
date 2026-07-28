"""
CatCare Product Matching Layer
================================
Recommends specific wet cat food products based on a cat's profile
and calculated daily energy requirements.

This is a structured lookup layer — it does NOT use RAG or vector search.
It uses deterministic scoring against the cat food CSV dataset.

Usage:
    python catcare_matcher.py

    Or import and call match() directly:
        from catcare_matcher import match
        recommendations = match(profile, der_kcal)

Data source:
    Pierson, L.A. (2017). Cat Food Nutritional Composition.
    Retrieved from https://catinfo.org
    Used with attribution for non-commercial research purposes.
"""

import csv
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import date
from pathlib import Path

PRODUCTS_CSV = "cat_food_products_clean.csv"
TOP_N = 5  # number of recommendations to return


# ── SCORING WEIGHTS ───────────────────────────────────────────────────────────
# These reflect veterinary guidelines for feline nutrition.
# Cats are obligate carnivores: high protein, moderate fat, very low carb.

# Target ranges by life stage (protein %, fat %, carb % of calories)
LIFE_STAGE_TARGETS = {
    "kitten": {
        "protein_min": 35, "protein_ideal": 50,
        "fat_min": 20, "fat_max": 50,
        "carb_max": 15,
    },
    "young_adult": {
        "protein_min": 35, "protein_ideal": 45,
        "fat_min": 20, "fat_max": 50,
        "carb_max": 10,
    },
    "mature_adult": {
        "protein_min": 35, "protein_ideal": 45,
        "fat_min": 20, "fat_max": 50,
        "carb_max": 10,
    },
    "senior": {
        # Senior cats need higher protein to prevent muscle loss (sarcopenia)
        # Source: 2021 AAHA/AAFP Feline Life Stage Guidelines
        "protein_min": 40, "protein_ideal": 50,
        "fat_min": 20, "fat_max": 55,
        "carb_max": 10,
    },
}


# ── LOAD PRODUCTS ─────────────────────────────────────────────────────────────

def load_products(csv_path: str) -> list[dict]:
    """Load and parse the clean cat food CSV."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Product CSV not found at {csv_path}. "
            "Run parse_catfood_pdf.py and validate_catfood_csv.py first."
        )

    products = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip not-recommended products
            if row.get("not_recommended", "").lower() == "true":
                continue

            # Parse numeric fields
            try:
                product = {
                    "brand": row["brand"].strip(),
                    "product_name": row["product_name"].strip(),
                    "protein_pct": float(row["protein_pct"]) if row["protein_pct"] else None,
                    "fat_pct": float(row["fat_pct"]) if row["fat_pct"] else None,
                    "carb_pct": float(row["carb_pct"]) if row["carb_pct"] else None,
                    "phosphorus": float(row["phosphorus_mg_per_100kcal"]) if row["phosphorus_mg_per_100kcal"] else None,
                    "calories": float(row["calories"]) if row["calories"] else None,
                    "serving_size_oz": float(row["serving_size_oz"]) if row["serving_size_oz"] else 5.5,
                    "supplemental_only": row.get("supplemental_only", "").lower() == "true",
                }
                # Only include products with complete macro data
                if all(v is not None for v in [product["protein_pct"], product["fat_pct"], product["carb_pct"]]):
                    products.append(product)
            except (ValueError, KeyError):
                continue

    return products


# ── SCORING ───────────────────────────────────────────────────────────────────

def score_product(product: dict, life_stage: str, der_kcal: float) -> float:
    """
    Score a product on a 0–100 scale based on how well it fits
    the cat's life stage nutritional targets.

    Higher score = better fit.
    """
    targets = LIFE_STAGE_TARGETS.get(life_stage, LIFE_STAGE_TARGETS["young_adult"])
    score = 100.0

    protein = product["protein_pct"]
    fat = product["fat_pct"]
    carb = product["carb_pct"]

    # ── Protein scoring (most important — worth 40 points) ──
    if protein < targets["protein_min"]:
        # Penalize linearly for being below minimum
        deficit = targets["protein_min"] - protein
        score -= min(40, deficit * 2)
    elif protein >= targets["protein_ideal"]:
        # Bonus for hitting ideal
        score += 5

    # ── Carb scoring (second most important — worth 30 points) ──
    if carb > targets["carb_max"]:
        excess = carb - targets["carb_max"]
        score -= min(30, excess * 2)

    # ── Fat scoring (worth 15 points) ──
    if fat < targets["fat_min"]:
        score -= min(15, (targets["fat_min"] - fat) * 1.5)
    elif fat > targets["fat_max"]:
        score -= min(15, (fat - targets["fat_max"]) * 1.5)

    # ── Calorie density bonus for senior cats ──
    # Senior cats benefit from calorie-dense foods (more calories per oz)
    if life_stage == "senior" and product["calories"] is not None:
        kcal_per_oz = product["calories"] / product["serving_size_oz"]
        if kcal_per_oz >= 25:  # reasonably calorie-dense
            score += 5

    # ── Supplemental-only penalty ──
    if product["supplemental_only"]:
        score -= 25

    return max(0, round(score, 1))


def calculate_feeding_amount(product: dict, der_kcal: float) -> dict:
    """
    Calculate how much of a product to feed per day to meet DER.
    Returns feeding instructions.
    """
    if product["calories"] is None or product["serving_size_oz"] is None:
        return {"amount_oz": None, "amount_cans": None, "note": "Calorie data unavailable — check label"}

    calories_per_oz = product["calories"] / product["serving_size_oz"]
    if calories_per_oz <= 0:
        return {"amount_oz": None, "amount_cans": None, "note": "Invalid calorie data"}

    oz_per_day = round(der_kcal / calories_per_oz, 1)
    cans_per_day = round(oz_per_day / product["serving_size_oz"], 2)

    return {
        "amount_oz": oz_per_day,
        "cans_per_day": cans_per_day,
        "serving_size_oz": product["serving_size_oz"],
        "note": f"{oz_per_day} oz/day ({cans_per_day} × {product['serving_size_oz']} oz servings)"
    }


# ── LIFE STAGE DERIVATION ─────────────────────────────────────────────────────

def derive_life_stage(date_of_birth: str) -> tuple[str, float]:
    """Derive life stage and age from date of birth string."""
    dob = date.fromisoformat(str(date_of_birth))
    today = date.today()
    age_years = (today - dob).days / 365.25

    if age_years < 1:
        return "kitten", round(age_years, 1)
    elif age_years <= 6:
        return "young_adult", round(age_years, 1)
    elif age_years <= 10:
        return "mature_adult", round(age_years, 1)
    else:
        return "senior", round(age_years, 1)


def calculate_der(weight_kg: float, life_stage: str) -> dict:
    """
    Calculate Resting Energy Requirement and Daily Energy Requirement.
    Formula: RER = 30 × weight_kg + 70
    Source: 2021 AAHA/AAFP Feline Life Stage Guidelines
    """
    rer = round(30 * weight_kg + 70, 1)

    # Needs factors by life stage
    if life_stage == "kitten":
        factor_lo, factor_hi = 2.0, 3.0
    elif life_stage == "young_adult":
        factor_lo, factor_hi = 1.0, 1.2
    elif life_stage == "mature_adult":
        factor_lo, factor_hi = 1.0, 1.1
    else:  # senior
        factor_lo, factor_hi = 1.1, 1.2

    der_lo = round(rer * factor_lo, 0)
    der_hi = round(rer * factor_hi, 0)
    der_mid = round((der_lo + der_hi) / 2, 0)

    return {
        "rer": rer,
        "der_lo": der_lo,
        "der_hi": der_hi,
        "der_mid": der_mid,
    }


# ── MAIN MATCH FUNCTION ───────────────────────────────────────────────────────

def match(profile: dict, top_n: int = TOP_N) -> dict:
    """
    Main entry point for the product matching layer.

    Args:
        profile: Cat profile dict with date_of_birth, weight_kg, name, etc.
        top_n: Number of recommendations to return

    Returns:
        Dict with energy calculations and ranked product recommendations
    """
    # Derive life stage and calculate energy needs
    life_stage, age = derive_life_stage(profile["date_of_birth"])
    energy = calculate_der(float(profile["weight_kg"]), life_stage)

    # Load and score products
    products = load_products(PRODUCTS_CSV)
    scored = []
    for product in products:
        score = score_product(product, life_stage, energy["der_mid"])
        feeding = calculate_feeding_amount(product, energy["der_mid"])
        scored.append({
            "score": score,
            "brand": product["brand"],
            "product_name": product["product_name"],
            "protein_pct": product["protein_pct"],
            "fat_pct": product["fat_pct"],
            "carb_pct": product["carb_pct"],
            "phosphorus": product["phosphorus"],
            "calories_per_serving": product["calories"],
            "serving_size_oz": product["serving_size_oz"],
            "feeding": feeding,
        })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_n]

    return {
        "cat_name": profile.get("name") or profile.get("cat_name", "Your cat"),
        "age_years": age,
        "life_stage": life_stage,
        "weight_kg": float(profile["weight_kg"]),
        "energy": energy,
        "recommendations": top,
    }


def format_recommendations(result: dict) -> str:
    """Format match results for human-readable output."""
    cat = result["cat_name"]
    age = result["age_years"]
    stage = result["life_stage"].replace("_", " ")
    weight = result["weight_kg"]
    energy = result["energy"]

    lines = [
        f"\n{'='*60}",
        f"CatCare Product Recommendations for {cat}",
        f"{'='*60}",
        f"Age: {age} years ({stage}) | Weight: {weight} kg",
        f"",
        f"Daily Energy Requirements:",
        f"  RER (resting):  {energy['rer']} kcal/day",
        f"  DER (daily):    {energy['der_lo']}–{energy['der_hi']} kcal/day",
        f"  Target used:    {energy['der_mid']} kcal/day",
        f"",
        f"Top {len(result['recommendations'])} Recommended Products:",
        f"{'─'*60}",
    ]

    for i, rec in enumerate(result["recommendations"], 1):
        feeding = rec["feeding"]
        lines += [
            f"",
            f"#{i} {rec['brand']} — {rec['product_name']}",
            f"   Score: {rec['score']}/100",
            f"   Protein: {rec['protein_pct']}%  Fat: {rec['fat_pct']}%  Carb: {rec['carb_pct']}%",
        ]
        if rec["phosphorus"]:
            lines.append(f"   Phosphorus: {rec['phosphorus']} mg/100kcal")
        if feeding["amount_oz"]:
            lines.append(f"   Feed: {feeding['note']}")
        else:
            lines.append(f"   Feed: {feeding['note']}")

    lines.append(f"\n{'='*60}")
    lines.append("Data source: Pierson, L.A. (2017). catinfo.org")
    lines.append("Consult your veterinarian before changing your cat's diet.")

    return "\n".join(lines)


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Fetch profile from PostgreSQL
    conn = psycopg2.connect(os.environ.get("DATABASE_URL"))
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM cat_profiles WHERE user_id = %s;", ("user_001",))
            row = cur.fetchone()
            profile = dict(row)
            profile["name"] = profile.pop("cat_name")
            profile["date_of_birth"] = profile["date_of_birth"].isoformat()
    finally:
        conn.close()

    result = match(profile)
    print(format_recommendations(result))
