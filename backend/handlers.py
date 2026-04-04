import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import recipe_logic
from database import get_db
from models import Recipe, RecipeIngredient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

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


def format_ingredient(link) -> str:
    """Format ingredient with quantity"""
    name = link.ingredient.name
    if link.quantity is not None:
        qty = int(link.quantity) if link.quantity == int(link.quantity) else link.quantity
        unit = link.unit or ''
        return f"{name} — {qty}{unit}" if unit else f"{name} — {qty}"
    return name


# ============ FSM STATES ============

class AddRecipeState(StatesGroup):
    title = State()
    ingredients = State()
    description = State()
    instructions = State()


class SuggestState(StatesGroup):
    ingredients = State()


# ============ STATE HANDLERS (must be registered FIRST) ============

@router.message(AddRecipeState.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer(
        "🥕 Now send **ingredients with quantities** (comma-separated):\n"
        "e.g., 'tomatoes 4 pcs, cottage cheese 200g, flour 500g, salt 1 tsp'\n"
        "Format: `ingredient quantity unit` (unit is optional: g, kg, ml, l, pcs, tsp, tbsp)"
    )
    await state.set_state(AddRecipeState.ingredients)


@router.message(AddRecipeState.ingredients)
async def process_ingredients(message: Message, state: FSMContext):
    await state.update_data(ingredients=message.text)
    await message.answer("📝 Send a **description** (optional, type 'skip'):")
    await state.set_state(AddRecipeState.description)


@router.message(AddRecipeState.description)
async def process_description(message: Message, state: FSMContext):
    desc = message.text if message.text.lower() != "skip" else None
    await state.update_data(description=desc)
    await message.answer("👨‍🍳 Now send **cooking instructions**:\n(step-by-step)")
    await state.set_state(AddRecipeState.instructions)


@router.message(AddRecipeState.instructions)
async def process_instructions(message: Message, state: FSMContext):
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
            f"📖 **{recipe.title}**\n"
            f"🔢 ID: `{recipe.id}`",
            parse_mode="Markdown",
            reply_markup=main_keyboard,
        )
        await state.clear()


@router.message(SuggestState.ingredients)
async def process_suggest(message: Message, state: FSMContext):
    ingredients = [i.strip() for i in message.text.split(",") if i.strip()]

    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        suggestions = await recipe_logic.suggest_recipes(db, ingredients, user.id)

        if not suggestions:
            await message.answer(
                "😔 No recipes found.\nAdd more recipes or try different ingredients!",
                reply_markup=main_keyboard,
            )
            await state.clear()
            return

        for match_count, recipe in suggestions[:5]:
            ing_list = [format_ingredient(link) for link in recipe.ingredient_links]
            missing = [
                link.ingredient.name for link in recipe.ingredient_links
                if link.ingredient.name.lower() not in [x.lower() for x in ingredients]
            ]

            text = (
                f"🍳 **{recipe.title}**\n\n"
                f"✅ Match: {match_count}/{len(recipe.ingredient_links)} ingredients\n"
                f"❌ Missing: {', '.join(missing) if missing else 'nothing!'}\n\n"
                f"🥕 **Ingredients:**\n" + "\n".join(f"• {i}" for i in ing_list) +
                f"\n\n📖 **Instructions:**\n{recipe.instructions}"
            )

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📖 Full Details", callback_data=f"view_{recipe.id}")]
            ])
            await message.answer(text, parse_mode="Markdown", reply_markup=kb)

        await message.answer("💡 Tap a button above to search again!", reply_markup=main_keyboard)
        await state.clear()


# ============ COMMAND / BUTTON HANDLERS ============

@router.message(CommandStart())
async def cmd_start(message: Message):
    username = message.from_user.username or message.from_user.full_name
    async for db in get_db():
        await recipe_logic.get_or_create_user(db, str(message.from_user.id), username)
    await message.answer(
        f"👋 **Welcome, {username}!**\n\n"
        "I'm your **Recipe Assistant** bot! 🍳\n\n"
        "Use buttons below:\n"
        "➕ Add Recipe\n"
        "📚 My Recipes\n"
        "🔍 Suggest Recipe\n"
        "🗑 Delete Recipe\n"
        "❓ Help",
        parse_mode="Markdown",
        reply_markup=main_keyboard,
    )


@router.message(Command("help"))
async def cmd_help_slash(message: Message):
    await message.answer(
        "🤖 **Help**\n\n"
        "➕ **Add Recipe** — save new recipe\n"
        "📚 **My Recipes** — view all your recipes\n"
        "🔍 **Suggest Recipe** — find what to cook by ingredients\n"
        "🗑 **Delete Recipe** — remove a recipe\n\n"
        "Just tap buttons or use /commands!",
        parse_mode="Markdown",
        reply_markup=main_keyboard,
    )


@router.message(F.text == "❓ Help", StateFilter(None))
async def cmd_help_btn(message: Message):
    await cmd_help_slash(message)


@router.message(Command("add_recipe"))
async def cmd_add_recipe_slash(message: Message, state: FSMContext):
    await state.set_state(AddRecipeState.title)
    await message.answer("📝 Send **recipe title**:", parse_mode="Markdown")


@router.message(F.text == "➕ Add Recipe", StateFilter(None))
async def cmd_add_recipe_btn(message: Message, state: FSMContext):
    await state.set_state(AddRecipeState.title)
    await message.answer("📝 Send **recipe title**:", parse_mode="Markdown")


@router.message(Command("my_recipes"))
async def cmd_my_recipes_slash(message: Message):
    await _show_recipes(message)


@router.message(F.text == "📚 My Recipes", StateFilter(None))
async def cmd_my_recipes_btn(message: Message):
    await _show_recipes(message)


async def _show_recipes(message: Message):
    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipes = await recipe_logic.get_user_recipes(db, user.id)

        if not recipes:
            await message.answer(
                "📭 No recipes yet!\nTap **➕ Add Recipe** to add one.",
                reply_markup=main_keyboard,
            )
            return

        text = f"📚 **Your Recipes** ({len(recipes)}):\n\n"
        for r in recipes:
            ings = [format_ingredient(link) for link in r.ingredient_links[:5]]
            text += f"🔢 **#{r.id}** — **{r.title}**\n🥕 {', '.join(ings)}\n\n"

        text += "🔍 **Suggest Recipe** — find what to cook\n🗑 **Delete Recipe** — remove"
        await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard)


@router.message(Command("suggest"))
async def cmd_suggest_slash(message: Message, state: FSMContext):
    await _start_suggest(message, state)


@router.message(F.text == "🔍 Suggest Recipe", StateFilter(None))
async def cmd_suggest_btn(message: Message, state: FSMContext):
    await _start_suggest(message, state)


async def _start_suggest(message: Message, state: FSMContext):
    await message.answer(
        "🔍 Send **ingredients you have** (comma-separated):\ne.g., 'chicken, rice, onion'",
        parse_mode="Markdown",
    )
    await state.set_state(SuggestState.ingredients)


@router.message(Command("delete_recipe"))
async def cmd_delete_slash(message: Message):
    await _show_delete(message)


@router.message(F.text == "🗑 Delete Recipe", StateFilter(None))
async def cmd_delete_btn(message: Message):
    await _show_delete(message)


async def _show_delete(message: Message):
    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipes = await recipe_logic.get_user_recipes(db, user.id)

        if not recipes:
            await message.answer(
                "📭 No recipes!\nTap **➕ Add Recipe** first.",
                reply_markup=main_keyboard,
            )
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗑 #{r.id} {r.title}", callback_data=f"delete_{r.id}")]
            for r in recipes[:10]
        ])
        await message.answer("🗑 Tap to delete:", reply_markup=kb)


# ============ CALLBACKS ============

@router.callback_query(F.data.startswith("view_"))
async def handle_view(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    async for db in get_db():
        result = await db.execute(
            select(Recipe).options(selectinload(Recipe.ingredient_links).selectinload(RecipeIngredient.ingredient)).where(Recipe.id == rid)
        )
        recipe = result.scalar_one_or_none()
        if recipe:
            ings = [format_ingredient(link) for link in recipe.ingredient_links]
            text = f"📖 **{recipe.title}**\n\n🥕 **Ingredients:**\n" + "\n".join(f"• {i}" for i in ings)
            if recipe.description:
                text += f"\n\n📝 {recipe.description}"
            text += f"\n\n👨‍🍳 **Instructions:**\n{recipe.instructions}"
            await callback.message.edit_text(text, parse_mode="Markdown")
        else:
            await callback.answer("Not found!", show_alert=True)


@router.callback_query(F.data.startswith("delete_"))
async def handle_delete(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    async for db in get_db():
        user = await recipe_logic.get_or_create_user(db, str(callback.from_user.id))
        ok = await recipe_logic.delete_recipe(db, rid, user.id)
        if ok:
            await callback.answer("✅ Recipe successfully deleted!")
            await callback.message.delete()
            await callback.message.answer("✅ Recipe successfully deleted!", reply_markup=main_keyboard)
        else:
            await callback.answer("❌ Recipe not found!", show_alert=True)
