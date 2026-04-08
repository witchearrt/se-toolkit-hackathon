from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from models import Recipe, Ingredient, User, RecipeIngredient
from difflib import get_close_matches
import logging

logger = logging.getLogger(__name__)


def _build_synonym_map():
    return {
        'bread': ['baguette', 'bread', 'loaf'],
        'baguette': ['bread', 'baguette'],
        'tomato': ['tomatoes', 'tomato'],
        'tomatoes': ['tomato', 'tomatoes'],
        'potato': ['potatoes', 'potato'],
        'potatoes': ['potato', 'potatoes'],
        'onion': ['onions', 'onion'],
        'onions': ['onion', 'onions'],
        'egg': ['eggs', 'egg'],
        'eggs': ['egg', 'eggs'],
        'mushroom': ['mushrooms', 'mushroom'],
        'mushrooms': ['mushroom', 'mushrooms'],
        'chicken': ['chicken breast', 'chicken thigh', 'chicken'],
        'cheese': ['parmesan', 'mozzarella', 'cheddar', 'cheese'],
        'courgette': ['zucchini', 'courgette'],
        'zucchini': ['courgette', 'zucchini'],
        'eggplant': ['aubergine', 'eggplant'],
        'aubergine': ['eggplant', 'aubergine'],
        'pasta': ['spaghetti', 'penne', 'pasta', 'noodles'],
        'spaghetti': ['pasta', 'spaghetti'],
        'bell pepper': ['capsicum', 'bell pepper'],
        'capsicum': ['bell pepper', 'capsicum'],
        'ground beef': ['minced beef', 'ground beef', 'mince'],
        'mince': ['ground beef', 'minced beef', 'mince'],
        'flour': ['flour', 'all-purpose flour'],
        'salt': ['salt'],
        'sugar': ['sugar'],
        'milk': ['milk'],
        'butter': ['butter'],
        'cream': ['cream', 'heavy cream'],
        'heavy cream': ['cream', 'heavy cream'],
        'garlic': ['garlic', 'garlic cloves'],
        'oil': ['olive oil', 'oil', 'vegetable oil'],
        'olive oil': ['oil', 'olive oil'],
        'rice': ['rice', 'white rice'],
    }


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
    """Suggest recipes with GigaChat AI + fallback to built-in synonyms & fuzzy matching"""
    user_ingredients = [i.strip() for i in user_ingredients if i.strip()]
    if not user_ingredients:
        return []

    # Load all ingredients from DB
    all_ings_result = await db.execute(select(Ingredient))
    all_db_ingredients = [i.name.lower() for i in all_ings_result.scalars().all()]

    # Try AI correction with GigaChat first
    corrected_ingredients = []
    try:
        import ai_service
        if await ai_service.is_available():
            logger.info("[AI] GigaChat available, correcting: %s", user_ingredients)
            for ing in user_ingredients:
                fixed = await ai_service.fix_typo(ing, all_db_ingredients)
                corrected_ingredients.append(fixed)
                if fixed != ing:
                    logger.info("[AI] Corrected: '%s' -> '%s'", ing, fixed)
                else:
                    logger.info("[AI] No correction for: '%s'", ing)
            logger.info("[AI] Final corrected: %s", corrected_ingredients)
        else:
            logger.info("[AI] GigaChat not available, using fallback")
            corrected_ingredients = user_ingredients
    except Exception as e:
        logger.info("[AI] Error: %s, using fallback", e)
        corrected_ingredients = user_ingredients

    # Build synonym map: user_input -> db_ingredient_name
    synonym_map = _build_synonym_map()

    # Match corrected ingredients to DB ingredients (with synonym + fuzzy fallback)
    matched_db_names = set()
    
    for user_ing in corrected_ingredients:
        low = user_ing.lower()
        # 1. Exact match
        if low in all_db_ingredients:
            matched_db_names.add(low)
            logger.info("[AI] Exact match: '%s'", low)
            # Also add synonyms of this ingredient
            if low in synonym_map:
                for syn in synonym_map[low]:
                    if syn in all_db_ingredients:
                        matched_db_names.add(syn)
                        logger.info("[AI] Also matched synonym: '%s' -> '%s'", low, syn)
        # 2. Synonym match
        elif low in synonym_map:
            for synonym in synonym_map[low]:
                if synonym in all_db_ingredients:
                    matched_db_names.add(synonym)
                    logger.info("[AI] Synonym match: '%s' -> '%s'", low, synonym)
        # 3. Fuzzy match (typos like tonato -> tomato)
        else:
            close_matches = get_close_matches(low, all_db_ingredients, n=3, cutoff=0.5)
            if close_matches:
                matched_db_names.add(close_matches[0])
                logger.info("[AI] Fuzzy match: '%s' -> '%s'", low, close_matches[0])
            else:
                # Partial match fallback
                for db_name in all_db_ingredients:
                    if low in db_name or db_name in low:
                        matched_db_names.add(db_name)
                        logger.info("[AI] Partial match: '%s' in '%s'", low, db_name)

    logger.info("[AI] Matched DB ingredients: %s", matched_db_names)
    logger.info("[AI] All DB ingredients: %s", all_db_ingredients)

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
    logger.info("[AI] Found %d recipes for user_id=%s", len(all_recipes), user_id)

    # Score recipes
    scored_recipes = []
    for recipe in all_recipes:
        recipe_ing_names = {link.ingredient.name.lower() for link in recipe.ingredient_links}
        match_count = sum(1 for m in matched_db_names if m in recipe_ing_names)
        logger.info("[AI] Recipe #%d '%s': ingredients=%s, matches=%d", recipe.id, recipe.title, recipe_ing_names, match_count)
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
    logger.info("[AI] Final scored recipes: %d matches", len(scored_recipes))
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
