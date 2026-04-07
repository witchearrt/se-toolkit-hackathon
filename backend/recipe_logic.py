from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from models import Recipe, Ingredient, User, RecipeIngredient
import re


async def get_or_create_user(db: AsyncSession, telegram_id: str, username: str = None):
    """Получить или создать пользователя"""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(telegram_id=telegram_id, username=username)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user


async def create_recipe(db: AsyncSession, user_id: int, title: str, instructions: str,
                        ingredients_str: str, description: str = None, servings: int = 2):
    """Создать новый рецепт"""
    ingredient_names = [i.strip().lower() for i in ingredients_str.split(",") if i.strip()]

    # Get or create ingredients
    ingredient_links = []
    for name in ingredient_names:
        result = await db.execute(select(Ingredient).where(func.lower(Ingredient.name) == name))
        ingredient = result.scalar_one_or_none()

        if not ingredient:
            ingredient = Ingredient(name=name)
            db.add(ingredient)
            await db.flush()

        link = RecipeIngredient(ingredient_id=ingredient.id)
        ingredient_links.append(link)

    # Create recipe WITHOUT passing ingredients (property has no setter!)
    recipe = Recipe(
        title=title,
        description=description,
        instructions=instructions,
        servings=servings,
        user_id=user_id,
    )
    db.add(recipe)
    await db.flush()  # Get recipe.id

    # Add ingredient links
    for link in ingredient_links:
        link.recipe_id = recipe.id
        db.add(link)

    await db.commit()
    await db.refresh(recipe)

    return recipe


async def get_user_recipes(db: AsyncSession, user_id: int):
    """Получить все рецепты пользователя"""
    result = await db.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredient_links).selectinload(RecipeIngredient.ingredient))
        .where(Recipe.user_id == user_id)
        .order_by(Recipe.id.desc())
    )
    return result.scalars().all()


async def delete_recipe(db: AsyncSession, recipe_id: int, user_id: int):
    """Удалить рецепт"""
    result = await db.execute(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user_id)
    )
    recipe = result.scalar_one_or_none()

    if recipe:
        await db.delete(recipe)
        await db.commit()
        return True
    return False


def parse_ingredient(ingredient_str):
    """Parse ingredient string like 'tomatoes 4 pcs' or 'cottage cheese 200g'"""
    ingredient_str = ingredient_str.strip()

    import re
    match = re.match(r'^(.+?)\s+(\d+\.?\d*)\s*(g|kg|ml|l|pcs|pieces|tsp|tbsp|pinch|to taste|cloves|slices)?$', ingredient_str, re.IGNORECASE)

    if match:
        name = match.group(1).strip()
        quantity = float(match.group(2))
        unit = match.group(3) if match.group(3) else ""
        unit_map = {
            'g': 'g', 'kg': 'kg', 'ml': 'ml', 'l': 'l',
            'pcs': 'pcs', 'pieces': 'pcs',
            'tsp': 'tsp', 'tbsp': 'tbsp',
            'pinch': 'pinch', 'to taste': 'to taste',
            'cloves': 'cloves', 'slices': 'slices'
        }
        unit = unit_map.get(unit.lower(), unit.lower()) if unit else ""
        return name.lower(), quantity, unit
    else:
        return ingredient_str.lower(), None, ""


async def suggest_recipes(db: AsyncSession, user_ingredients: list, user_id: int = None):
    """Предложить рецепты — с AI семантическим поиском синонимов"""
    from sqlalchemy import text
    import synonym_service

    user_ingredients = [i.strip() for i in user_ingredients if i.strip()]

    if not user_ingredients:
        return []

    # 1. Загружаем все ингредиенты из БД и строим индекс
    ing_result = await db.execute(text("SELECT name FROM ingredients"))
    all_ing_names = [row[0] for row in ing_result.fetchall()]

    synonym_service.build_ingredient_index(all_ing_names)

    # 2. Загружаем ВСЕ рецепты
    if user_id:
        sql = "SELECT r.id, r.title, r.instructions, r.description, r.servings FROM recipes r WHERE r.user_id = :uid"
        result = await db.execute(text(sql), {"uid": user_id})
    else:
        sql = "SELECT r.id, r.title, r.instructions, r.description, r.servings FROM recipes r"
        result = await db.execute(text(sql))
    all_recipes = result.fetchall()

    if not all_recipes:
        return []

    # 3. Загружаем ингредиенты для рецептов
    recipe_ids = [r[0] for r in all_recipes]
    placeholders = ",".join([f":rid{i}" for i in range(len(recipe_ids))])
    params = {f"rid{i}": rid for i, rid in enumerate(recipe_ids)}

    ing_sql = f"""
        SELECT ri.recipe_id, i.name, ri.quantity, ri.unit
        FROM recipe_ingredients ri
        JOIN ingredients i ON ri.ingredient_id = i.id
        WHERE ri.recipe_id IN ({placeholders})
    """
    ing_result = await db.execute(text(ing_sql), params)
    all_ingredients_rows = ing_result.fetchall()

    # 4. Строим карту: recipe_id -> [{name, quantity, unit}]
    recipe_ingredients_map = {}
    for row in all_ingredients_rows:
        rid = row[0]
        if rid not in recipe_ingredients_map:
            recipe_ingredients_map[rid] = []
        recipe_ingredients_map[rid].append({
            "name": row[1],
            "quantity": row[2],
            "unit": row[3],
        })

    # 5. Фильтруем и сортируем с AI семантическим matching
    scored_recipes = []
    for recipe in all_recipes:
        rid, title, instructions, description, servings = recipe
        ings = recipe_ingredients_map.get(rid, [])
        recipe_ing_names = [i["name"].lower() for i in ings]

        match_count = 0
        matched_recipe_ings = set()
        
        for recipe_ing in recipe_ing_names:
            # Проверяем точное/частичное совпадение
            for user_ing in user_ingredients:
                user_lower = user_ing.lower()
                if user_lower == recipe_ing or user_lower in recipe_ing or recipe_ing in user_lower:
                    match_count += 1
                    matched_recipe_ings.add(recipe_ing)
                    break
            
            # Если не совпало, проверяем AI семантику
            if recipe_ing not in matched_recipe_ings:
                best_sim = synonym_service._best_semantic_similarity(recipe_ing, user_ingredients)
                # Lower threshold for better matches (bread ≈ baguette ~0.35)
                if best_sim >= 0.25:
                    match_count += 1
                    matched_recipe_ings.add(recipe_ing)

        if match_count > 0:
            scored_recipes.append((match_count, {
                "id": rid,
                "title": title,
                "instructions": instructions,
                "description": description,
                "servings": servings,
                "ingredients": ings,
            }))

    scored_recipes.sort(key=lambda x: x[0], reverse=True)
    return scored_recipes
