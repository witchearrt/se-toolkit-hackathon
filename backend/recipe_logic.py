from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from models import Recipe, Ingredient, User, RecipeIngredient
import re


def parse_ingredient(ingredient_str):
    """Parse ingredient string like 'tomatoes 4 pcs' or 'cottage cheese 200g'"""
    ingredient_str = ingredient_str.strip()
    
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
    """Создать новый рецепт с количеством ингредиентов"""
    ingredient_parts = [i.strip() for i in ingredients_str.split(",") if i.strip()]

    recipe = Recipe(
        title=title,
        description=description,
        instructions=instructions,
        servings=servings,
        user_id=user_id,
    )
    db.add(recipe)
    await db.flush()

    for part in ingredient_parts:
        name, quantity, unit = parse_ingredient(part)
        
        result = await db.execute(select(Ingredient).where(func.lower(Ingredient.name) == name))
        ingredient = result.scalar_one_or_none()

        if not ingredient:
            ingredient = Ingredient(name=name)
            db.add(ingredient)
            await db.flush()

        link = RecipeIngredient(
            recipe_id=recipe.id,
            ingredient_id=ingredient.id,
            quantity=quantity,
            unit=unit,
        )
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


async def suggest_recipes(db: AsyncSession, user_ingredients: list, user_id: int = None):
    """Предложить рецепты на основе имеющихся ингредиентов"""
    user_ingredients = [i.strip().lower() for i in user_ingredients if i.strip()]

    if not user_ingredients:
        return []

    result = await db.execute(
        select(Ingredient).where(func.lower(Ingredient.name).in_(user_ingredients))
    )
    found_ingredients = result.scalars().all()

    if not found_ingredients:
        return []

    query = (
        select(Recipe)
        .options(selectinload(Recipe.ingredient_links).selectinload(RecipeIngredient.ingredient))
        .join(Recipe.ingredient_links)
        .join(RecipeIngredient.ingredient)
        .where(RecipeIngredient.ingredient_id.in_([i.id for i in found_ingredients]))
    )

    if user_id:
        query = query.where(Recipe.user_id == user_id)

    result = await db.execute(query)
    recipes = result.scalars().all()

    scored_recipes = []
    for recipe in recipes:
        recipe_ingredient_names = {link.ingredient.name.lower() for link in recipe.ingredient_links}
        match_count = sum(1 for i in user_ingredients if i in recipe_ingredient_names)
        scored_recipes.append((match_count, recipe))

    scored_recipes.sort(key=lambda x: x[0], reverse=True)

    return scored_recipes


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


async def update_recipe(db: AsyncSession, recipe_id: int, user_id: int,
                        title: str, instructions: str, ingredients_str: str):
    """Обновить рецепт (title, instructions, ingredients)"""
    from sqlalchemy import text

    result = await db.execute(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user_id)
    )
    recipe = result.scalar_one_or_none()

    if not recipe:
        return False

    # Обновляем основные поля напрямую
    await db.execute(
        text("UPDATE recipes SET title = :title, instructions = :instructions WHERE id = :id"),
        {"title": title, "instructions": instructions, "id": recipe_id}
    )

    # Удаляем старые ингредиенты через raw SQL
    await db.execute(
        text("DELETE FROM recipe_ingredients WHERE recipe_id = :id"),
        {"id": recipe_id}
    )

    # Добавляем новые ингредиенты
    ingredient_parts = [i.strip() for i in ingredients_str.split(",") if i.strip()]
    for part in ingredient_parts:
        name, quantity, unit = parse_ingredient(part)

        ing_result = await db.execute(select(Ingredient).where(func.lower(Ingredient.name) == name))
        ingredient = ing_result.scalar_one_or_none()

        if not ingredient:
            ingredient = Ingredient(name=name)
            db.add(ingredient)
            await db.flush()

        await db.execute(
            text("INSERT INTO recipe_ingredients (recipe_id, ingredient_id, quantity, unit) VALUES (:rid, :iid, :qty, :unit)"),
            {"rid": recipe_id, "iid": ingredient.id, "qty": quantity, "unit": unit}
        )

    await db.commit()
    return True
