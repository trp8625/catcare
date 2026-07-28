"""
Cat Food Nutrition CSV Parser
==============================
Parses Dr. Lisa A. Pierson's Cat Food Nutritional Composition chart
into a clean, structured CSV for use in CatCare's product matching layer.

Source: catinfo.org — Dr. Lisa A. Pierson, DVM (2017)
Citation: Pierson, L.A. (2017). Cat Food Nutritional Composition.
          Retrieved from https://catinfo.org

Usage:
    python parse_catfood_pdf.py

Output:
    cat_food_products.csv

Requirements:
    pip install pypdf pdfplumber
"""

import re
import csv
import pdfplumber
from pathlib import Path


INPUT_PDF = "CatFoodProteinFatCarbPhosphorusChart.pdf"
OUTPUT_CSV = "cat_food_products.csv"

# Products flagged as not recommended in the source document
NOT_RECOMMENDED = {
    "ADDICTION", "AUTHORITY", "GOOD NATURED", "GRREAT CHOICE",
    "SIMPLY NOURISH", "NUTRISCA", "PARTY ANIMAL", "FELINE NATURAL",
    "BLACKWOOD"
}

# Products that are supplemental only (not complete diets)
SUPPLEMENTAL_ONLY = {"APPLAWS", "WYSONG EPIGEN", "TRADER JOE'S TUNA"}


def clean_number(val):
    """Convert a string to float, return None if not possible."""
    if val is None:
        return None
    val = str(val).strip()
    if val in ("", "-", "—", "N/A"):
        return None
    # Handle ranges like "38-40" — take midpoint
    if "-" in val and not val.startswith("-"):
        parts = val.split("-")
        try:
            return round((float(parts[0]) + float(parts[1])) / 2, 1)
        except ValueError:
            return None
    try:
        return float(val)
    except ValueError:
        return None


def parse_calories(cal_str):
    """
    Parse calorie field which often includes serving size info.
    e.g. "91" or "84/3 oz" or "3 oz: 86-95  5.5 oz: 157-178"
    Returns (calories, serving_size_oz) as best estimate.
    """
    if not cal_str:
        return None, None

    cal_str = cal_str.strip()

    # Pattern: "84/3 oz" → calories=84, serving=3
    match = re.match(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\s*oz", cal_str)
    if match:
        return float(match.group(1)), float(match.group(2))

    # Pattern: "3 oz: 86-95  5.5 oz: 157-178" → take 5.5 oz value
    match = re.search(r"5\.5\s*oz:\s*(\d+)(?:-(\d+))?", cal_str)
    if match:
        lo = float(match.group(1))
        hi = float(match.group(2)) if match.group(2) else lo
        return round((lo + hi) / 2, 0), 5.5

    # Pattern: simple number
    match = re.match(r"^(\d+(?:\.\d+)?)$", cal_str.split()[0])
    if match:
        return float(match.group(1)), 5.5  # default serving

    return None, None


def extract_text_by_page(pdf_path):
    """Extract text from each page using pdfplumber."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return pages


def parse_products(all_text):
    """
    Parse product entries from the raw text.
    Returns list of dicts with product data.
    """
    products = []
    current_brand = None
    current_brand_notes = ""

    lines = all_text.split("\n")

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        # Skip header lines that repeat on every page
        if any(skip in line for skip in [
            "CAT FOOD - NUTRITIONAL COMPOSITION",
            "Data compiled by Lisa",
            "Typical nutrient analysis",
            "Wet only - no dry food",
            "Caloric Distribution",
            "PROTEIN % FAT % CARB %",
            "mg PHOSPHORUS",
            "CALORIES per",
            "2 Sortable Charts",
            "Google Drive",
            "Extensive filters",
            "Print",
            "The print version",
            "many blank areas",
            "I am waiting for data",
            "will be adding to",
        ]):
            continue

        # Detect brand headers (ALL CAPS lines, possibly with sub-category)
        # Brand lines look like: "FANCY FEAST" or "FANCY FEAST " or "BLUE "
        brand_match = re.match(r'^([A-Z][A-Z0-9\s\'\&\.\-]+?)(?:\s*\n|$)', line)

        # Check if line is a brand header (all caps, no numbers at start)
        if re.match(r'^[A-Z][A-Z0-9\s\'\&\.\-/]+$', line) and len(line) > 2:
            # Likely a brand or sub-category header
            if not any(char.isdigit() for char in line[:5]):
                current_brand = line.strip()
                continue

        # Try to parse a data row
        # Format: product_name protein fat carb phosphorus calories
        # Numbers are space-separated at end of line
        # e.g. "Chicken Feast 40 57 3 430 91"
        data_match = re.search(
            r'^(.+?)\s+(\d{1,3}(?:\.\d+)?(?:-\d{1,3}(?:\.\d+)?)?)\s+'
            r'(\d{1,3}(?:\.\d+)?(?:-\d{1,3}(?:\.\d+)?)?)\s+'
            r'(\d{1,3}(?:\.\d+)?(?:-\d{1,3}(?:\.\d+)?)?)\s+'
            r'(\d{1,4}(?:\.\d+)?(?:-\d{1,4}(?:\.\d+)?)?)\s+'
            r'(.+)$',
            line
        )

        if data_match and current_brand:
            product_name = data_match.group(1).strip()
            protein = clean_number(data_match.group(2))
            fat = clean_number(data_match.group(3))
            carb = clean_number(data_match.group(4))
            phosphorus = clean_number(data_match.group(5))
            cal_raw = data_match.group(6).strip()
            calories, serving_oz = parse_calories(cal_raw)

            # Skip if core nutritional data is missing
            if protein is None or fat is None:
                continue

            # Determine if product is recommended
            brand_upper = current_brand.upper()
            not_recommended = any(nr in brand_upper for nr in NOT_RECOMMENDED)
            supplemental = any(s in brand_upper for s in SUPPLEMENTAL_ONLY)

            products.append({
                "brand": current_brand,
                "product_name": product_name,
                "protein_pct": protein,
                "fat_pct": fat,
                "carb_pct": carb,
                "phosphorus_mg_per_100kcal": phosphorus,
                "calories": calories,
                "serving_size_oz": serving_oz,
                "not_recommended": not_recommended,
                "supplemental_only": supplemental,
                "source": "Pierson, L.A. (2017). catinfo.org",
            })

    return products


def write_csv(products, output_path):
    """Write parsed products to CSV."""
    if not products:
        print("No products parsed — check the PDF path and format.")
        return

    fieldnames = [
        "brand", "product_name", "protein_pct", "fat_pct", "carb_pct",
        "phosphorus_mg_per_100kcal", "calories", "serving_size_oz",
        "not_recommended", "supplemental_only", "source"
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)

    print(f"Wrote {len(products)} products to {output_path}")


def main():
    pdf_path = Path(INPUT_PDF)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path.absolute()}")
        print(f"Make sure {INPUT_PDF} is in the same folder as this script.")
        return

    print(f"Reading {INPUT_PDF}...")
    pages = extract_text_by_page(str(pdf_path))
    all_text = "\n".join(pages)

    print(f"Parsing products...")
    products = parse_products(all_text)

    print(f"Found {len(products)} product entries")
    write_csv(products, OUTPUT_CSV)

    # Print a sample so you can verify it looks right
    print("\nSample rows (first 5):")
    for p in products[:5]:
        print(f"  {p['brand']} | {p['product_name']} | "
              f"P:{p['protein_pct']}% F:{p['fat_pct']}% C:{p['carb_pct']}% "
              f"Phos:{p['phosphorus_mg_per_100kcal']} Cal:{p['calories']}")

    print("\nNote: Review cat_food_products.csv carefully.")
    print("The parser gets ~60-70% of rows cleanly. Manual cleanup will be needed")
    print("for rows with complex formatting, ranges, or multi-product entries.")


if __name__ == "__main__":
    main()
