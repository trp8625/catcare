"""
CatCare Product CSV Validator
==============================
Checks cat_food_products.csv for data quality issues and produces
a report of what needs manual cleanup.

Usage:
    python validate_catfood_csv.py

Output:
    - Prints a summary report to terminal
    - Writes cat_food_products_flagged.csv with a new 'issues' column
"""

import csv
from pathlib import Path

INPUT_CSV = "cat_food_products.csv"
OUTPUT_CSV = "cat_food_products_flagged.csv"


def validate_row(row, index):
    """
    Check a single row for data quality issues.
    Returns a list of issue strings (empty list = no issues).
    """
    issues = []

    # 1. Brand is generic placeholder
    if row["brand"].strip().upper() in ("COMPANY", "", "FLAVOR/STYLE"):
        issues.append("brand_missing")

    # 2. Product name looks like a header or is empty
    product = row["product_name"].strip()
    if not product:
        issues.append("product_name_missing")
    if product.upper() in ("FLAVOR/STYLE", "COMPANY", "PRODUCT"):
        issues.append("product_name_is_header")

    # 3. Core nutritional values missing
    for field in ["protein_pct", "fat_pct", "carb_pct"]:
        if not row[field]:
            issues.append(f"{field}_missing")

    # 4. Nutritional values out of reasonable range
    try:
        protein = float(row["protein_pct"]) if row["protein_pct"] else None
        fat = float(row["fat_pct"]) if row["fat_pct"] else None
        carb = float(row["carb_pct"]) if row["carb_pct"] else None

        if protein is not None and (protein < 0 or protein > 100):
            issues.append("protein_out_of_range")
        if fat is not None and (fat < 0 or fat > 100):
            issues.append("fat_out_of_range")
        if carb is not None and (carb < 0 or carb > 100):
            issues.append("carb_out_of_range")

        # 5. Macros should sum to roughly 100% (allow +/-10 for rounding)
        if protein is not None and fat is not None and carb is not None:
            total = protein + fat + carb
            if total < 85 or total > 115:
                issues.append(f"macros_dont_sum_to_100_got_{round(total)}")

    except ValueError:
        issues.append("nutritional_value_not_numeric")

    # 6. Calories missing or unreasonable
    if not row["calories"]:
        issues.append("calories_missing")
    else:
        try:
            cal = float(row["calories"])
            if cal < 20 or cal > 600:
                issues.append(f"calories_suspicious_{round(cal)}")
        except ValueError:
            issues.append("calories_not_numeric")

    # 7. Phosphorus missing (lower priority)
    if not row["phosphorus_mg_per_100kcal"]:
        issues.append("phosphorus_missing")

    return issues


def main():
    path = Path(INPUT_CSV)
    if not path.exists():
        print(f"ERROR: {INPUT_CSV} not found. Run parse_catfood_pdf.py first.")
        return

    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            issues = validate_row(row, i)
            row["issues"] = "|".join(issues)
            rows.append(row)

    total = len(rows)
    clean = sum(1 for r in rows if not r["issues"])
    flagged = total - clean

    issue_counts = {}
    for row in rows:
        for issue in row["issues"].split("|"):
            if issue:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1

    print(f"\n{'='*60}")
    print(f"CatCare Product CSV Validation Report")
    print(f"{'='*60}")
    print(f"Total rows:     {total}")
    print(f"Clean rows:     {clean}  ({round(clean/total*100)}%)")
    print(f"Flagged rows:   {flagged}  ({round(flagged/total*100)}%)")
    print(f"\nIssues found:")
    for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
        print(f"  {issue:<45} {count} rows")

    fieldnames = list(rows[0].keys())
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nFlagged CSV written to: {OUTPUT_CSV}")
    print(f"Open it, filter the 'issues' column for non-empty rows,")
    print(f"and fix or delete those entries.")

    clean_rows = [r for r in rows if not r["issues"]]
    print(f"\nSample clean rows (first 5):")
    for r in clean_rows[:5]:
        print(f"  {r['brand']} | {r['product_name']} | "
              f"P:{r['protein_pct']}% F:{r['fat_pct']}% C:{r['carb_pct']}%"
              f" Cal:{r['calories']}")


if __name__ == "__main__":
    main()
