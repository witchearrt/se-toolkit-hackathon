from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from models import Recipe, Ingredient, User, RecipeIngredient


async def get_or_create_user(db: AsyncSession, telegram_id: str, username: str = None):
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
    """Create recipe - FIXED: no ingredients= in constructor"""
    ingredient_names = [i.strip().lower() for i in ingredients_str.split(",") if i.strip()]

    # Get or create ingredients
    ingredient_ids = []
    for name in ingredient_names:
        result = await db.execute(select(Ingredient).where(func.lower(Ingredient.name) == name))
        ingredient = result.scalar_one_or_none()
        if not ingredient:
            ingredient = Ingredient(name=name)
            db.add(ingredient)
            await db.flush()
        ingredient_ids.append(ingredient.id)

    # Create recipe WITHOUT ingredients= (property has no setter!)
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
    for ing_id in ingredient_ids:
        link = RecipeIngredient(recipe_id=recipe.id, ingredient_id=ing_id)
        db.add(link)

    await db.commit()
    await db.refresh(recipe)
    return recipe


async def get_user_recipes(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(Recipe)
        .options(selectinload(Recipe.ingredient_links).selectinload(RecipeIngredient.ingredient))
        .where(Recipe.user_id == user_id)
        .order_by(Recipe.id.desc())
    )
    return result.scalars().all()


async def suggest_recipes(db: AsyncSession, user_ingredients: list, user_id: int = None):
    """Suggest recipes with synonym support"""
    user_ingredients = [i.strip() for i in user_ingredients if i.strip()]
    if not user_ingredients:
        return []

    # Load all ingredients from DB
    all_ings_result = await db.execute(select(Ingredient))
    all_db_ingredients = [i.name.lower() for i in all_ings_result.scalars().all()]

    # Build synonym map: user_input -> db_ingredient_name
    synonym_map = _build_synonym_map()
    
    # Match user ingredients to DB ingredients (with synonym support)
    matched_db_names = set()
    for user_ing in user_ingredients:
        low = user_ing.lower()
        # 1. Exact match
        if low in all_db_ingredients:
            matched_db_names.add(low)
        # 2. Synonym match
        elif low in synonym_map:
            for synonym in synonym_map[low]:
                if synonym in all_db_ingredients:
                    matched_db_names.add(synonym)
        # 3. Partial match (user_ing in db_name or db_name in user_ing)
        else:
            for db_name in all_db_ingredients:
                if low in db_name or db_name in low:
                    matched_db_names.add(db_name)

    if not matched_db_names:
        return []

    # Load all user recipes
    if user_id:
        result = await db.execute(
            select(Recipe).options(
                selectinload(Recipe.ingredient_links).selectinload(RecipeIngredient.ingredient)
            ).where(Recipe.user_id == user_id)
        )
    else:
        result = await db.execute(
            select(Recipe).options(
                selectinload(Recipe.ingredient_links).selectinload(RecipeIngredient.ingredient)
            )
        )
    all_recipes = result.scalars().all()

    # Score recipes
    scored_recipes = []
    for recipe in all_recipes:
        recipe_ing_names = {link.ingredient.name.lower() for link in recipe.ingredient_links}
        match_count = sum(1 for m in matched_db_names if m in recipe_ing_names)
        if match_count > 0:
            scored_recipes.append((match_count, {
                "id": recipe.id,
                "title": recipe.title,
                "instructions": recipe.instructions,
                "description": recipe.description,
                "servings": recipe.servings,
                "ingredients": [{"name": link.ingredient.name, "quantity": link.quantity, "unit": link.unit} for link in recipe.ingredient_links],
            }))

    scored_recipes.sort(key=lambda x: x[0], reverse=True)
    return scored_recipes


async def delete_recipe(db: AsyncSession, recipe_id: int, user_id: int):
    result = await db.execute(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.user_id == user_id)
    )
    recipe = result.scalar_one_or_none()
    if recipe:
        await db.delete(recipe)
        await db.commit()
        return True
    return False


def _build_synonym_map():
    """Built-in synonym dictionary - works without AI!"""
    return {
        "bread": ["baguette", "loaf", "bread"],
        "baguette": ["bread", "baguette"],
        "tomato": ["tomatoes", "tomato"],
        "tomatoes": ["tomato", "tomatoes"],
        "potato": ["potatoes", "potato"],
        "potatoes": ["potato", "potatoes"],
        "onion": ["onions", "onion"],
        "onions": ["onion", "onions"],
        "egg": ["eggs", "egg"],
        "eggs": ["egg", "eggs"],
        "mushroom": ["mushrooms", "mushroom"],
        "mushrooms": ["mushroom", "mushrooms"],
        "pepper": ["peppers", "pepper"],
        "peppers": ["pepper", "peppers"],
        "chicken": ["chicken breast", "chicken thigh", "chicken"],
        "chicken breast": ["chicken", "chicken breast"],
        "chicken thigh": ["chicken", "chicken thigh"],
        "beef": ["beef", "steak"],
        "steak": ["beef", "steak"],
        "pork": ["pork", "bacon"],
        "bacon": ["pork", "bacon"],
        "fish": ["salmon", "tuna", "fish"],
        "salmon": ["fish", "salmon"],
        "tuna": ["fish", "tuna"],
        "cheese": ["parmesan", "mozzarella", "cheddar", "cheese"],
        "parmesan": ["cheese", "parmesan"],
        "mozzarella": ["cheese", "mozzarella"],
        "cheddar": ["cheese", "cheddar"],
        "milk": ["milk"],
        "butter": ["butter"],
        "cream": ["heavy cream", "cream"],
        "heavy cream": ["cream", "heavy cream"],
        "garlic": ["garlic", "garlic cloves"],
        "garlic cloves": ["garlic", "garlic cloves"],
        "courgette": ["zucchini", "courgette"],
        "zucchini": ["courgette", "zucchini"],
        "eggplant": ["aubergine", "eggplant"],
        "aubergine": ["eggplant", "aubergine"],
        "cilantro": ["coriander", "cilantro"],
        "coriander": ["cilantro", "coriander"],
        "bell pepper": ["capsicum", "bell pepper"],
        "capsicum": ["bell pepper", "capsicum"],
        "ground beef": ["minced beef", "ground beef", "mince"],
        "minced beef": ["ground beef", "minced beef", "mince"],
        "mince": ["ground beef", "minced beef", "mince"],
        "flour": ["flour", "all-purpose flour"],
        "all-purpose flour": ["flour", "all-purpose flour"],
        "sugar": ["sugar", "white sugar"],
        "salt": ["salt", "table salt"],
        "olive oil": ["oil", "olive oil"],
        "oil": ["olive oil", "oil", "vegetable oil"],
        "vegetable oil": ["oil", "vegetable oil"],
        "rice": ["rice", "white rice", "brown rice"],
        "white rice": ["rice", "white rice"],
        "brown rice": ["rice", "brown rice"],
        "pasta": ["spaghetti", "penne", "pasta", "noodles"],
        "spaghetti": ["pasta", "spaghetti"],
        "penne": ["pasta", "penne"],
        "noodles": ["pasta", "noodles"],
        "cottage cheese": ["cottage cheese", "curd"],
        "curd": ["cottage cheese", "curd"],
        "yogurt": ["yogurt", "yoghurt"],
        "yoghurt": ["yogurt", "yoghurt"],
        "green onion": ["scallion", "green onion"],
        "scallion": ["green onion", "scallion"],
    }
