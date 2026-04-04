"""
Auto-migration script: adds missing columns/tables without dropping data.
Run this BEFORE starting the bot.
"""
import asyncio
import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/recipes")


async def migrate():
    print("🔧 Running database migration...")
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    try:
        # Create tables if not exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id VARCHAR(50) UNIQUE NOT NULL,
                username VARCHAR(100)
            );
        """)
        print("✅ Table 'users' exists")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                id SERIAL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                description TEXT,
                instructions TEXT NOT NULL,
                servings INTEGER,
                user_id INTEGER REFERENCES users(id)
            );
        """)
        print("✅ Table 'recipes' exists")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ingredients (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL
            );
        """)
        print("✅ Table 'ingredients' exists")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS recipe_ingredients (
                recipe_id INTEGER REFERENCES recipes(id),
                ingredient_id INTEGER REFERENCES ingredients(id),
                quantity FLOAT,
                unit VARCHAR(50),
                PRIMARY KEY (recipe_id, ingredient_id)
            );
        """)
        print("✅ Table 'recipe_ingredients' exists")

        # Add missing columns
        columns_to_add = {
            "recipes": {
                "servings": "ALTER TABLE recipes ADD COLUMN IF NOT EXISTS servings INTEGER;",
                "description": "ALTER TABLE recipes ADD COLUMN IF NOT EXISTS description TEXT;",
            },
        }

        for table, columns in columns_to_add.items():
            for col, sql in columns.items():
                try:
                    await conn.execute(sql)
                    print(f"✅ Column '{col}' added to '{table}'")
                except Exception:
                    print(f"ℹ️  Column '{col}' already exists in '{table}'")

        print("✅ Migration complete!")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
