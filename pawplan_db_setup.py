"""
PawPlan Database Setup
======================
Creates the cat_profiles table in Supabase and inserts a test profile.

Run once to set up the database:
    python pawplan_db_setup.py

Requirements:
    pip install psycopg2-binary
    export DATABASE_URL='postgresql://...'
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor


def get_connection():
    return psycopg2.connect(os.environ.get("DATABASE_URL"))


def create_table():
    sql = """
    CREATE TABLE IF NOT EXISTS cat_profiles (
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
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print("✓ Table cat_profiles created (or already exists)")
    finally:
        conn.close()


def insert_test_profile():
    """Insert a test profile for development. Safe to run multiple times."""
    sql = """
    INSERT INTO cat_profiles (user_id, cat_name, date_of_birth, sex, neutered, weight_kg)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (user_id) DO UPDATE SET
        cat_name      = EXCLUDED.cat_name,
        date_of_birth = EXCLUDED.date_of_birth,
        sex           = EXCLUDED.sex,
        neutered      = EXCLUDED.neutered,
        weight_kg     = EXCLUDED.weight_kg,
        updated_at    = NOW();
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (
                "user_001",   # user_id
                "Mochi",      # cat_name
                "2013-03-01", # date_of_birth
                "female",     # sex
                True,         # neutered
                4.2,          # weight_kg
            ))
        conn.commit()
        print("✓ Test profile for Mochi inserted (or updated)")
    finally:
        conn.close()


def verify():
    """Print all profiles in the table to confirm setup worked."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM cat_profiles;")
            rows = cur.fetchall()
            print(f"\n✓ Found {len(rows)} profile(s) in cat_profiles:")
            for row in rows:
                print(f"  {dict(row)}")
    finally:
        conn.close()


if __name__ == "__main__":
    print("Setting up PawPlan database...\n")
    create_table()
    insert_test_profile()
    verify()
    print("\nDatabase setup complete.")
