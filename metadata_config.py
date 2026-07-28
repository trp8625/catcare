"""
PawPlan Document Metadata Configuration
========================================
This is where you manually assign metadata to each document before ingestion.
One entry per PDF. Fill in topic_tags and life_stage based on the vocabulary
we established.

TOPIC TAG VOCABULARY (pick from these only, for consistency):
    Nutrition fundamentals:
        protein, fat, carbohydrates, vitamins, minerals, hydration,
        taurine, amino_acids, energy_requirements, macronutrient_ratios,
        calorie_calculation

    Feeding practice:
        meal_frequency, portion_control, puzzle_feeders,
        multi_cat_feeding, food_texture, food_transitions

    Body condition:
        body_condition_score, muscle_condition_score,
        obesity_prevention, weight_management

    Food evaluation:
        aafco_standards, label_reading, brand_evaluation,
        treat_guidelines, toxic_foods

    Life stage specific:
        kitten_growth, senior_caloric_needs, sarcopenia

LIFE STAGE VALUES (use a list — a chunk can span multiple stages):
    "kitten", "young_adult", "mature_adult", "senior"
    Leave as None if the content applies to all life stages.

SOURCE TYPE VALUES:
    "guideline", "research_paper", "chart", "client_brochure"
"""

DOCUMENT_METADATA = {

    # ── GENERAL FELINE NUTRITION ──────────────────────────────────────────────

    "Calorie-Needs-for-Healthy-Adult-Cats-updated-July-2020.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/general_feline_nutrition/Calorie-Needs-for-Healthy-Adult-Cats-updated-July-2020.pdf",
        "source_type": "chart",
        "year": 2020,
        "life_stage": ["young_adult", "mature_adult"],
        "topic_tags": ["calorie_calculation", "energy_requirements", "portion_control"],
    },

    "cat_nutrition_final.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/general_feline_nutrition/cat_nutrition_final.pdf",
        "source_type": "research_paper",
        "year": 2002,
        "life_stage": None,  # foundational — applies to all life stages
        "topic_tags": [
            "protein", "taurine", "amino_acids", "vitamins",
            "macronutrient_ratios", "energy_requirements"
        ],
    },

    "estimation-of-the-dietary-nutrient-profile-of-free-roaming-feral-cats-possible-implications-for-nutrition-of-domestic-cats.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/general_feline_nutrition/estimation-of-the-dietary-nutrient-profile-of-free-roaming-feral-cats-possible-implications-for-nutrition-of-domestic-cats.pdf",
        "source_type": "research_paper",
        "year": 2011,
        "life_stage": None,  # evolutionary baseline — applies to all life stages
        "topic_tags": ["protein", "fat", "carbohydrates", "macronutrient_ratios"],
    },

    "Muscle-Condition-Score-Chart-for-Cats.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/general_feline_nutrition/Muscle-Condition-Score-Chart-for-Cats.pdf",
        "source_type": "chart",
        "year": 2014,
        "life_stage": None,  # used across all life stages but especially senior
        "topic_tags": ["muscle_condition_score", "sarcopenia", "weight_management"],
    },

    "nutrient requirements of cats .pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/general_feline_nutrition/nutrient requirements of cats .pdf",
        "source_type": "guideline",
        "year": 2006,
        "life_stage": None,
        "topic_tags": [
            "protein", "fat", "vitamins", "minerals", "amino_acids",
            "taurine", "energy_requirements", "calorie_calculation"
        ],
    },

    "WSAVA_BCSCat_BCSCat_Nutrition_250612.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/general_feline_nutrition/WSAVA_BCSCat_BCSCat_Nutrition_250612.pdf",
        "source_type": "chart",
        "year": 2025,
        "life_stage": None,
        "topic_tags": ["body_condition_score", "obesity_prevention", "weight_management"],
    },

    "WSAVA_GuidetoTreats_Cats_251107.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/general_feline_nutrition/WSAVA_GuidetoTreats_Cats_251107.pdf",
        "source_type": "guideline",
        "year": 2025,
        "life_stage": None,
        "topic_tags": ["treat_guidelines", "toxic_foods", "portion_control", "calorie_calculation"],
    },

    # ── LIFE STAGE ────────────────────────────────────────────────────────────

    "10.1177_1098612X211021538.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/life_stage/10.1177_1098612X211021538.pdf",
        "source_type": "guideline",
        "year": 2021,
        "life_stage": ["senior"],
        "topic_tags": [
            "senior_caloric_needs", "sarcopenia", "protein",
            "energy_requirements", "calorie_calculation",
            "weight_management", "muscle_condition_score"
        ],
    },

    "2021-aaha-aafp-feline-life-stage-guidelines.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/life_stage/2021-aaha-aafp-feline-life-stage-guidelines.pdf",
        "source_type": "guideline",
        "year": 2021,
        "life_stage": ["kitten", "young_adult", "mature_adult", "senior"],
        "topic_tags": [
            "energy_requirements", "calorie_calculation", "protein",
            "obesity_prevention", "weight_management", "kitten_growth",
            "senior_caloric_needs", "food_transitions", "aafco_standards",
            "hydration", "body_condition_score", "muscle_condition_score"
        ],
    },

    # ── PRACTICAL FEEDING ─────────────────────────────────────────────────────

    "FelineVMAHowtoFeedCat_Web.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/practical_feeding/FelineVMAHowtoFeedCat_Web.pdf",
        "source_type": "client_brochure",
        "year": 2024,
        "life_stage": None,
        "topic_tags": [
            "meal_frequency", "puzzle_feeders", "multi_cat_feeding",
            "portion_control", "obesity_prevention"
        ],
    },

    "Selecting-a-pet-food-for-your-pet-updated-2021_WSAVA-Global-Nutrition-Toolkit.pdf": {
        "path": "/Users/tanvipatel/Desktop/catcare/practical_feeding/Selecting-a-pet-food-for-your-pet-updated-2021_WSAVA-Global-Nutrition-Toolkit.pdf",
        "source_type": "guideline",
        "year": 2021,
        "life_stage": None,
        "topic_tags": [
            "brand_evaluation", "label_reading", "aafco_standards",
            "calorie_calculation", "food_texture"
        ],
    },

}
