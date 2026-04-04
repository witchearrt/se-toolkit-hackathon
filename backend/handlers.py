import logging
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import recipe_logic
from database import get_db

router = Router()

# States for adding recipe
class AddRecipeState(StatesGroup):
    title = State()
    ingredients = State()
    description = State()
    instructions = State()


# States for suggesting recipes
class SuggestState(StatesGroup):
    ingredients = State()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Handle /start command"""
    username = message.from_user.username or message.from_user.full_name
    
    async for db in get_db():
        await recipe_logic.get_or_create_user(db, str(message.from_user.id), username)

        welcome_text = (
            f"👋 **Welcome, {username}!**\n\n"
            "I'm your **Recipe Assistant** bot! 🍳\n\n"
            "Here's what I can do:\n"
            "📝 `/add_recipe` — Save a new recipe\n"
            "📚 `/my_recipes` — View your saved recipes\n"
            "🔍 `/suggest` — Get recipe suggestions based on ingredients you have\n"
            "🗑 `/delete_recipe` — Delete a recipe\n"
            "❓ `/help` — Show this help message\n\n"
            "Try `/add_recipe` to save your first recipe!"
        )
        await message.answer(welcome_text, parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command"""
    help_text = (
        "🤖 **Recipe Bot Help**\n\n"
        "**Commands:**\n"
        "/start — Start the bot\n"
        "/add_recipe — Add a new recipe (interactive)\n"
        "/my_recipes — List all your recipes\n"
        "/suggest — Get recipe suggestions by ingredients\n"
        "/delete_recipe — Delete a recipe by ID\n"
        "/help — Show this message\n\n"
        "**How to add a recipe:**\n"
        "1. Send `/add_recipe`\n"
        "2. Enter recipe title\n"
        "3. Enter ingredients (comma-separated)\n"
        "4. Enter description (optional, type 'skip' to skip)\n"
        "5. Enter cooking instructions\n\n"
        "**How to get suggestions:**\n"
        "1. Send `/suggest`\n"
        "2. Enter ingredients you have (comma-separated)\n"
        "3. I'll find matching recipes!"
    )
    await message.answer(help_text, parse_mode="Markdown")


@router.message(Command("add_recipe"))
async def cmd_add_recipe(message: Message, state: FSMContext):
    """Start adding a recipe"""
    await message.answer(
        "📝 **Adding a new recipe**\n\n"
        "Send the **recipe title** (e.g., 'Pasta Carbonara'):",
        parse_mode="Markdown",
    )
    await state.set_state(AddRecipeState.title)


@router.message(AddRecipeState.title)
async def process_title(message: Message, state: FSMContext):
    """Process recipe title"""
    await state.update_data(title=message.text)
    await message.answer(
        "🥕 Great! Now send the **ingredients** (comma-separated):\n"
        "e.g., 'pasta, eggs, bacon, parmesan, black pepper'"
    )
    await state.set_state(AddRecipeState.ingredients)


@router.message(AddRecipeState.ingredients)
async def process_ingredients(message: Message, state: FSMContext):
    """Process ingredients"""
    await state.update_data(ingredients=message.text)
    await message.answer(
        "📝 Send a **description** (optional, type 'skip' to skip):"
    )
    await state.set_state(AddRecipeState.description)


@router.message(AddRecipeState.description)
async def process_description(message: Message, state: FSMContext):
    """Process description"""
    description = message.text if message.text.lower() != "skip" else None
    await state.update_data(description=description)
    await message.answer(
        "👨‍🍳 Now send the **cooking instructions**:\n"
        "(step-by-step guide)"
    )
    await state.set_state(AddRecipeState.instructions)


@router.message(AddRecipeState.instructions)
async def process_instructions(message: Message, state: FSMContext):
    """Process instructions and save recipe"""
    data = await state.get_data()

    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))

        recipe = await recipe_logic.create_recipe(
            db=db,
            user_id=user.id,
            title=data["title"],
            instructions=message.text,
            ingredients_str=data["ingredients"],
            description=data.get("description"),
        )

        await message.answer(
            f"✅ **Recipe saved!**\n\n"
            f"📖 **Title:** {recipe.title}\n"
            f"🔢 **ID:** `{recipe.id}`\n\n"
            f"Use `/my_recipes` to see all your recipes.",
            parse_mode="Markdown",
        )
        await state.clear()
        return


@router.message(Command("my_recipes"))
async def cmd_my_recipes(message: Message):
    """Show user's recipes"""
    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipes = await recipe_logic.get_user_recipes(db, user.id)

        if not recipes:
            await message.answer("📭 You don't have any recipes yet!\nUse `/add_recipe` to add one.", parse_mode="Markdown")
            return

        text = f"📚 **Your Recipes** ({len(recipes)} total):\n\n"
        for recipe in recipes:
            ingredients_list = ", ".join([i.name for i in recipe.ingredients[:5]])
            if len(recipe.ingredients) > 5:
                ingredients_list += "..."

            text += (
                f"🔢 **#{recipe.id}** — **{recipe.title}**\n"
                f"🥕 {ingredients_list}\n\n"
            )

        text += "💡 Use `/suggest` to find what to cook!\n"
        text += "🗑 Use `/delete_recipe <ID>` to remove a recipe."

        await message.answer(text, parse_mode="Markdown")


@router.message(Command("suggest"))
async def cmd_suggest(message: Message, state: FSMContext):
    """Start recipe suggestion"""
    await message.answer(
        "🔍 **Recipe Suggestion**\n\n"
        "Send the **ingredients you have** (comma-separated):\n"
        "e.g., 'chicken, rice, onion, garlic'",
        parse_mode="Markdown",
    )
    await state.set_state(SuggestState.ingredients)


@router.message(SuggestState.ingredients)
async def process_suggest(message: Message, state: FSMContext):
    """Process suggestion request"""
    ingredients = [i.strip() for i in message.text.split(",") if i.strip()]

    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        suggestions = await recipe_logic.suggest_recipes(db, ingredients, user.id)

        if not suggestions:
            await message.answer(
                "😔 No matching recipes found.\n"
                "Try different ingredients or add more recipes!"
            )
            await state.clear()
            return

        text = f"🍳 **Found {len(suggestions)} recipe(s):**\n\n"

        for match_count, recipe in suggestions[:5]:  # Top 5
            missing = [
                i.name for i in recipe.ingredients
                if i.name.lower() not in [x.lower() for x in ingredients]
            ]

            text += (
                f"📖 **{recipe.title}** (ID: `{recipe.id}`)\n"
                f"✅ Matches: {match_count}/{len(recipe.ingredients)} ingredients\n"
                f"❌ Missing: {', '.join(missing) if missing else 'nothing!'}\n\n"
            )

        text += "💡 Use `/delete_recipe <ID>` to remove a recipe."

        await message.answer(text, parse_mode="Markdown")
        await state.clear()


@router.message(Command("delete_recipe"))
async def cmd_delete_recipe(message: Message):
    """Delete a recipe by ID"""
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "🗑 **Delete Recipe**\n\n"
            "Usage: `/delete_recipe <ID>`\n"
            "e.g., `/delete_recipe 5`\n\n"
            "Use `/my_recipes` to see recipe IDs.",
            parse_mode="Markdown",
        )
        return

    recipe_id = int(parts[1])

    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        success = await recipe_logic.delete_recipe(db, recipe_id, user.id)

        if success:
            await message.answer(f"✅ Recipe #{recipe_id} deleted!")
        else:
            await message.answer(f"❌ Recipe #{recipe_id} not found or doesn't belong to you.")
