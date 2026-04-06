from sqlalchemy import select, func, or_
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
    """Предложить рецепты на основе имеющихся ингредиентов — с частичным совпадением"""
    user_ingredients = [i.strip().lower() for i in user_ingredients if i.strip()]

    if not user_ingredients:
        return []

    # Ищем ингредиенты в БД по частичному совпадению (LIKE)
    conditions = [func.lower(Ingredient.name).like(f"%{ing}%") for ing in user_ingredients]
    result = await db.execute(
        select(Ingredient).where(or_(*conditions))
    )
    found_ingredients = result.scalars().all()

    if not found_ingredients:
        return []

    # Строим маппинг: какое пользовательское ингредиент совпало с каким в БД
    user_to_db = {}  # user_ing -> [db_ing_id, ...]
    for db_ing in found_ingredients:
        for user_ing in user_ingredients:
            if user_ing in db_ing.name.lower() or db_ing.name.lower() in user_ing:
                if user_ing not in user_to_db:
                    user_to_db[user_ing] = []
                user_to_db[user_ing].append(db_ing.id)

    if not user_to_db:
        return []

    # Собираем все ID найденных ингредиентов
    matched_db_ids = set()
    for ids in user_to_db.values():
        matched_db_ids.update(ids)

    query = (
        select(Recipe)
        .options(selectinload(Recipe.ingredient_links).selectinload(RecipeIngredient.ingredient))
        .join(Recipe.ingredient_links)
        .join(RecipeIngredient.ingredient)
        .where(RecipeIngredient.ingredient_id.in_(list(matched_db_ids)))
    )

    if user_id:
        query = query.where(Recipe.user_id == user_id)

    result = await db.execute(query)
    recipes = result.scalars().all()

    # Считаем совпадения по пользовательским ингредиентам
    scored_recipes = []
    for recipe in recipes:
        recipe_ing_names = {link.ingredient.name.lower() for link in recipe.ingredient_links}
        match_count = 0
        for user_ing in user_ingredients:
            for recipe_ing in recipe_ing_names:
                if user_ing in recipe_ing or recipe_ing in user_ing:
                    match_count += 1
                    break
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
    """Обновить рецепт — полностью через raw SQL для async безопасности"""
    from sqlalchemy import text

    # Проверяем что рецепт принадлежит пользователю
    result = await db.execute(
        text("SELECT id FROM recipes WHERE id = :id AND user_id = :uid"),
        {"id": recipe_id, "uid": user_id}
    )
    row = result.fetchone()
    if not row:
        return False

    # Обновляем основные поля
    await db.execute(
        text("UPDATE recipes SET title = :title, instructions = :instructions WHERE id = :id"),
        {"title": title, "instructions": instructions, "id": recipe_id}
    )

    # Удаляем старые ингредиенты
    await db.execute(
        text("DELETE FROM recipe_ingredients WHERE recipe_id = :id"),
        {"id": recipe_id}
    )

    # Добавляем новые ингредиенты
    ingredient_parts = [i.strip() for i in ingredients_str.split(",") if i.strip()]
    for part in ingredient_parts:
        name, quantity, unit = parse_ingredient(part)

        # Получаем или создаём ингредиент
        result = await db.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        ing_row = result.fetchone()

        if ing_row:
            ingredient_id = ing_row[0]
        else:
            result = await db.execute(
                text("INSERT INTO ingredients (name) VALUES (:name) RETURNING id"),
                {"name": name}
            )
            ingredient_id = result.scalar()

        # Вставляем связь
        await db.execute(
            text("INSERT INTO recipe_ingredients (recipe_id, ingredient_id, quantity, unit) VALUES (:rid, :iid, :qty, :unit)"),
            {"rid": recipe_id, "iid": ingredient_id, "qty": quantity, "unit": unit}
        )

    await db.commit()
    return True


async def update_recipe_ingredients(db: AsyncSession, recipe_id: int, ingredients_str: str):
    """Обновить только ингредиенты рецепта (raw SQL)"""
    from sqlalchemy import text

    # Проверяем что рецепт существует
    result = await db.execute(
        text("SELECT id FROM recipes WHERE id = :id"),
        {"id": recipe_id}
    )
    if not result.fetchone():
        return False

    # Удаляем старые ингредиенты
    await db.execute(
        text("DELETE FROM recipe_ingredients WHERE recipe_id = :id"),
        {"id": recipe_id}
    )

    # Добавляем новые ингредиенты
    ingredient_parts = [i.strip() for i in ingredients_str.split(",") if i.strip()]
    for part in ingredient_parts:
        name, quantity, unit = parse_ingredient(part)

        result = await db.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        ing_row = result.fetchone()

        if ing_row:
            ingredient_id = ing_row[0]
        else:
            result = await db.execute(
                text("INSERT INTO ingredients (name) VALUES (:name) RETURNING id"),
                {"name": name}
            )
            ingredient_id = result.scalar()

        await db.execute(
            text("INSERT INTO recipe_ingredients (recipe_id, ingredient_id, quantity, unit) VALUES (:rid, :iid, :qty, :unit)"),
            {"rid": recipe_id, "iid": ingredient_id, "qty": quantity, "unit": unit}
        )

    await db.commit()
    return True
