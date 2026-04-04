from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from models import Recipe, Ingredient, User, recipe_ingredients


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
    # Парсим ингредиенты (через запятую)
    ingredient_names = [i.strip().lower() for i in ingredients_str.split(",") if i.strip()]

    # Получаем или создаём ингредиенты
    ingredients = []
    for name in ingredient_names:
        result = await db.execute(select(Ingredient).where(func.lower(Ingredient.name) == name))
        ingredient = result.scalar_one_or_none()

        if not ingredient:
            ingredient = Ingredient(name=name)
            db.add(ingredient)
            await db.commit()
            await db.refresh(ingredient)

        ingredients.append(ingredient)

    # Создаём рецепт
    recipe = Recipe(
        title=title,
        description=description,
        instructions=instructions,
        servings=servings,
        user_id=user_id,
        ingredients=ingredients,
    )
    db.add(recipe)
    await db.commit()
    await db.refresh(recipe)

    return recipe


async def get_user_recipes(db: AsyncSession, user_id: int):
    """Получить все рецепты пользователя"""
    result = await db.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .where(Recipe.user_id == user_id)
        .order_by(Recipe.id.desc())
    )
    return result.scalars().all()


async def suggest_recipes(db: AsyncSession, user_ingredients: list, user_id: int = None):
    """Предложить рецепты на основе имеющихся ингредиентов"""
    # Нормализуем входные ингредиенты
    user_ingredients = [i.strip().lower() for i in user_ingredients if i.strip()]

    if not user_ingredients:
        return []

    # Ищем ингредиенты в БД
    result = await db.execute(
        select(Ingredient).where(func.lower(Ingredient.name).in_(user_ingredients))
    )
    found_ingredients = result.scalars().all()

    if not found_ingredients:
        return []

    # Ищем рецепты, которые содержат эти ингредиенты
    query = (
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .join(recipe_ingredients)
        .join(Ingredient)
        .where(Ingredient.id.in_([i.id for i in found_ingredients]))
    )

    # Если указан user_id, показываем только его рецепты
    if user_id:
        query = query.where(Recipe.user_id == user_id)

    result = await db.execute(query)
    recipes = result.scalars().all()

    # Сортируем по количеству совпадений (больше совпадений = выше)
    scored_recipes = []
    for recipe in recipes:
        recipe_ingredient_names = {i.name.lower() for i in recipe.ingredients}
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
