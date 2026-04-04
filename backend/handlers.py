import logging
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram import F

import recipe_logic
from database import get_db

router = Router()

# Main menu keyboard
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Add Recipe"), KeyboardButton(text="📚 My Recipes")],
        [KeyboardButton(text="🔍 Suggest Recipe"), KeyboardButton(text="🗑 Delete Recipe")],
        [KeyboardButton(text="❓ Help")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Choose an action...",
)

# States for adding recipe
class AddRecipeState(StatesGroup):
    title = State()
    ingredients = State()
    description = State()
    servings = State()
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
            "Use the buttons below to get started:\n"
            "➕ **Add Recipe** — Save a new recipe\n"
            "📚 **My Recipes** — View your saved recipes\n"
            "🔍 **Suggest Recipe** — Get suggestions based on ingredients\n"
            "🗑 **Delete Recipe** — Remove a recipe\n"
            "❓ **Help** — Show help message\n\n"
            "Tap **➕ Add Recipe** to save your first recipe!"
        )
        await message.answer(welcome_text, parse_mode="Markdown", reply_markup=main_keyboard)


@router.message(F.text == "❓ Help")
async def cmd_help(message: Message):
    """Handle help button"""
    help_text = (
        "🤖 **Recipe Bot Help**\n\n"
        "**Buttons:**\n"
        "➕ **Add Recipe** — Add a new recipe (interactive)\n"
        "📚 **My Recipes** — List all your recipes\n"
        "🔍 **Suggest Recipe** — Get recipe suggestions by ingredients\n"
        "🗑 **Delete Recipe** — Delete a recipe by ID\n"
        "❓ **Help** — Show this message\n\n"
        "**How to add a recipe:**\n"
        "1. Tap **➕ Add Recipe**\n"
        "2. Enter recipe title\n"
        "3. Enter ingredients (comma-separated)\n"
        "4. Enter description (optional, type 'skip' to skip)\n"
        "5. Enter number of servings\n"
        "6. Enter cooking instructions\n\n"
        "**How to get suggestions:**\n"
        "1. Tap **🔍 Suggest Recipe**\n"
        "2. Enter ingredients you have (comma-separated)\n"
        "3. I'll find matching recipes!"
    )
    await message.answer(help_text, parse_mode="Markdown", reply_markup=main_keyboard)


@router.message(Command("help"))
async def cmd_help_slash(message: Message):
    """Handle /help command"""
    await cmd_help(message)


@router.message(F.text == "➕ Add Recipe")
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
        "🍽️ How many **servings** does this recipe make?\n"
        "(e.g., 2, 4, 6)"
    )
    await state.set_state(AddRecipeState.servings)


@router.message(AddRecipeState.servings)
async def process_servings(message: Message, state: FSMContext):
    """Process servings"""
    try:
        servings = int(message.text)
        if servings < 1:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(
            "⚠️ Please enter a valid number (e.g., 2, 4, 6)"
        )
        return

    await state.update_data(servings=servings)
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
            servings=data.get("servings", 2),
        )

        await message.answer(
            f"✅ **Recipe saved!**\n\n"
            f"📖 **Title:** {recipe.title}\n"
            f"🍽️ **Servings:** {recipe.servings}\n"
            f"🔢 **ID:** `{recipe.id}`\n\n"
            f"Tap **📚 My Recipes** to see all your recipes.",
            parse_mode="Markdown",
            reply_markup=main_keyboard,
        )
        await state.clear()
        return


@router.message(Command("my_recipes"))
@router.message(F.text == "📚 My Recipes")
async def cmd_my_recipes(message: Message):
    """Show user's recipes"""
    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipes = await recipe_logic.get_user_recipes(db, user.id)

        if not recipes:
            await message.answer(
                "📭 You don't have any recipes yet!\n\nTap **➕ Add Recipe** to add one.",
                parse_mode="Markdown",
                reply_markup=main_keyboard,
            )
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

        text += "💡 Tap **🔍 Suggest Recipe** to find what to cook!\n"
        text += "🗑 Tap **🗑 Delete Recipe** to remove a recipe."

        await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard)


@router.message(Command("suggest"))
@router.message(F.text == "🔍 Suggest Recipe")
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
                "Try different ingredients or add more recipes!",
                reply_markup=main_keyboard,
            )
            await state.clear()
            return

        # Send each recipe with cooking instructions as a separate message
        for match_count, recipe in suggestions[:5]:  # Top 5
            missing = [
                i.name for i in recipe.ingredients
                if i.name.lower() not in [x.lower() for x in ingredients]
            ]

            text = (
                f"🍳 **{recipe.title}**\n\n"
                f"🍽️ **Servings:** {recipe.servings}\n"
                f"✅ **Match:** {match_count}/{len(recipe.ingredients)} ingredients\n"
                f"❌ **Missing:** {', '.join(missing) if missing else 'nothing! You have everything!'}\n\n"
                f"🥕 **All ingredients:** {', '.join([i.name for i in recipe.ingredients])}\n\n"
                f"📖 **Cooking Instructions:**\n"
                f"{recipe.instructions}"
            )

            # Create inline keyboard with recipe details
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"📖 Full Recipe Details", callback_data=f"view_{recipe.id}")],
                ]
            )

            await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

        await message.answer(
            "💡 Tap **🔍 Suggest Recipe** to search again or use other buttons!",
            reply_markup=main_keyboard,
        )
        await state.clear()


@router.callback_query(F.data.startswith("view_"))
async def handle_view_recipe_callback(callback: CallbackQuery):
    """Show full recipe details"""
    recipe_id = int(callback.data.split("_")[1])

    async for db in get_db():
        from models import Recipe
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        result = await db.execute(
            select(Recipe)
            .options(selectinload(Recipe.ingredients))
            .where(Recipe.id == recipe_id)
        )
        recipe = result.scalar_one_or_none()

        if recipe:
            ingredients_list = ", ".join([i.name for i in recipe.ingredients])

            text = (
                f"📖 **{recipe.title}**\n\n"
                f"🍽️ **Servings:** {recipe.servings}\n\n"
                f"🥕 **Ingredients:**\n{ingredients_list}\n\n"
            )

            if recipe.description:
                text += f"📝 **Description:**\n{recipe.description}\n\n"

            text += f"👨‍🍳 **Instructions:**\n{recipe.instructions}"

            await callback.message.edit_text(text, parse_mode="Markdown")
        else:
            await callback.answer("Recipe not found!", show_alert=True)


# Keyboard for delete recipe selection
def get_delete_keyboard(recipes):
    """Create inline keyboard for recipe deletion"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🗑 #{recipe.id} {recipe.title}", callback_data=f"delete_{recipe.id}")]
            for recipe in recipes[:10]  # Show max 10 recipes
        ]
    )
    return keyboard


@router.message(Command("delete_recipe"))
@router.message(F.text == "🗑 Delete Recipe")
async def cmd_delete_recipe(message: Message):
    """Show recipes with buttons for deletion"""
    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipes = await recipe_logic.get_user_recipes(db, user.id)

        if not recipes:
            await message.answer(
                "📭 You don't have any recipes yet!\n\nTap **➕ Add Recipe** to add one.",
                parse_mode="Markdown",
                reply_markup=main_keyboard,
            )
            return

        await message.answer(
            "🗑 **Select a recipe to delete:**\n\n"
            "Tap a button below to remove that recipe.",
            parse_mode="Markdown",
            reply_markup=get_delete_keyboard(recipes),
        )


@router.callback_query(F.data.startswith("delete_"))
async def handle_delete_callback(callback: CallbackQuery):
    """Handle recipe deletion from inline keyboard"""
    recipe_id = int(callback.data.split("_")[1])

    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(callback.from_user.id))
        success = await recipe_logic.delete_recipe(db, recipe_id, user.id)

        if success:
            await callback.message.edit_text(
                f"✅ Recipe #{recipe_id} deleted!",
                reply_markup=main_keyboard,
            )
        else:
            await callback.message.edit_text(
                f"❌ Recipe #{recipe_id} not found or doesn't belong to you.",
                reply_markup=main_keyboard,
            )
