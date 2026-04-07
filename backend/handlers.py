import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import recipe_logic
from database import async_session
from models import Recipe, RecipeIngredient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

router = Router()

# Main menu keyboard
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Add Recipe"), KeyboardButton(text="📚 My Recipes")],
        [KeyboardButton(text="🔍 Suggest Recipe"), KeyboardButton(text="✏️ Edit Recipe")],
        [KeyboardButton(text="🗑 Delete Recipe"), KeyboardButton(text="❓ Help")],
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
    instructions = State()


class SuggestState(StatesGroup):
    ingredients = State()


class EditRecipeState(StatesGroup):
    recipe_id = State()
    new_title = State()
    new_ingredients = State()
    new_instructions = State()


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
    await message.answer("👨‍🍳 Now send **cooking instructions**:\n(step-by-step)")
    await state.set_state(AddRecipeState.instructions)


@router.message(AddRecipeState.instructions)
async def process_instructions(message: Message, state: FSMContext):
    data = await state.get_data()

    async with async_session() as db:
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipe = await recipe_logic.create_recipe(
            db=db,
            user_id=user.id,
            title=data["title"],
            instructions=message.text,
            ingredients_str=data["ingredients"],
            description=None,
        )

        await message.answer(
            f"✅ **Recipe saved!**\n\n"
            f"📖 **{recipe.title}**\n"
            f"🔢 ID: `{recipe.id}`",
            parse_mode="Markdown",
            reply_markup=main_keyboard,
        )
        await state.clear()


# ============ EDIT RECIPE STATE HANDLERS ============

@router.message(EditRecipeState.new_title)
async def edit_new_title(message: Message, state: FSMContext):
    data = await state.get_data()
    rid = data["recipe_id"]

    async with async_session() as db:
        from sqlalchemy import text
        await db.execute(
            text("UPDATE recipes SET title = :title WHERE id = :id"),
            {"title": message.text, "id": rid}
        )
        await db.commit()

    await message.answer(
        f"✅ **Title updated!**\n\n"
        f"📖 **{message.text}**\n"
        f"🔢 ID: `{rid}`",
        parse_mode="Markdown",
        reply_markup=main_keyboard,
    )
    await state.clear()


@router.message(EditRecipeState.new_ingredients)
async def edit_new_ingredients(message: Message, state: FSMContext):
    data = await state.get_data()
    rid = data["recipe_id"]

    async with async_session() as db:
        ok = await recipe_logic.update_recipe_ingredients(db, rid, message.text)

    if ok:
        await message.answer(
            f"✅ **Ingredients updated!**\n\n"
            f"🔢 Recipe ID: `{rid}`",
            parse_mode="Markdown",
            reply_markup=main_keyboard,
        )
    else:
        await message.answer(
            "❌ Recipe not found.",
            reply_markup=main_keyboard,
        )
    await state.clear()


@router.message(EditRecipeState.new_instructions)
async def edit_new_instructions(message: Message, state: FSMContext):
    data = await state.get_data()
    rid = data["recipe_id"]

    async with async_session() as db:
        from sqlalchemy import text
        await db.execute(
            text("UPDATE recipes SET instructions = :inst WHERE id = :id"),
            {"inst": message.text, "id": rid}
        )
        await db.commit()

    await message.answer(
        f"✅ **Instructions updated!**\n\n"
        f"🔢 Recipe ID: `{rid}`",
        parse_mode="Markdown",
        reply_markup=main_keyboard,
    )
    await state.clear()


@router.message(SuggestState.ingredients)
async def process_suggest(message: Message, state: FSMContext):
    ingredients = [i.strip() for i in message.text.split(",") if i.strip()]

    async with async_session() as db:
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
            # recipe is now a dict, not an ORM object
            ings = recipe["ingredients"]
            ing_list = [
                f"{i['name']} — {int(i['quantity'])}{i['unit'] or ''}" if i['quantity'] is not None
                else f"{int(i['quantity'])} {i['unit'] or ''}" if i['unit']
                else i['name']
                for i in ings
            ]

            # Используем AI семантическое matching
            import synonym_service
            matched_names = []
            missing_names = []
            for i in ings:
                db_name = i["name"].lower()
                found = False
                for user_ing in ingredients:
                    user_lower = user_ing.lower()
                    # Точное/частичное совпадение
                    if user_lower == db_name or user_lower in db_name or db_name in user_lower:
                        found = True
                        break
                if not found:
                    # AI семантическое совпадение (lower threshold)
                    best_sim = synonym_service._best_semantic_similarity(db_name, ingredients)
                    if best_sim >= 0.25:
                        found = True
                
                if found:
                    matched_names.append(i["name"])
                else:
                    missing_names.append(i["name"])

            total = len(ings)

            text = (
                f"🍳 **{recipe['title']}**\n\n"
                f"✅ Match: {match_count}/{total} ingredients\n"
                f"❌ Missing: {', '.join(missing_names) if missing_names else 'nothing! You have everything!'}\n\n"
                f"🥕 **Ingredients:**\n" + "\n".join(f"• {i}" for i in ing_list) +
                f"\n\n📖 **Instructions:**\n{recipe['instructions']}"
            )

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📖 Full Details", callback_data=f"view_{recipe['id']}")]
            ])
            await message.answer(text, parse_mode="Markdown", reply_markup=kb)

        await message.answer("💡 Tap a button above to search again!", reply_markup=main_keyboard)
        await state.clear()


# ============ COMMAND / BUTTON HANDLERS ============

@router.message(CommandStart())
async def cmd_start(message: Message):
    username = message.from_user.username or message.from_user.full_name
    async with async_session() as db:
        await recipe_logic.get_or_create_user(db, str(message.from_user.id), username)
    await message.answer(
        f"👋 **Welcome, {username}!**\n\n"
        "I'm your **Recipe Assistant** bot! 🍳\n\n"
        "Use buttons below:\n"
        "➕ Add Recipe\n"
        "📚 My Recipes\n"
        "🔍 Suggest Recipe\n"
        "✏️ Edit Recipe\n"
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
        "✏️ **Edit Recipe** — edit an existing recipe\n"
        "🗑 **Delete Recipe** — remove a recipe\n\n"
        "Flow: title → ingredients → instructions\n"
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
    async with async_session() as db:
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

        text += "🔍 **Suggest Recipe** — find what to cook\n✏️ **Edit Recipe** — modify\n🗑 **Delete Recipe** — remove"
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


@router.message(Command("edit_recipe"))
async def cmd_edit_slash(message: Message):
    await _show_edit(message)


@router.message(F.text == "✏️ Edit Recipe", StateFilter(None))
async def cmd_edit_btn(message: Message):
    await _show_edit(message)


async def _show_edit(message: Message):
    async with async_session() as db:
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipes = await recipe_logic.get_user_recipes(db, user.id)

        if not recipes:
            await message.answer(
                "📭 No recipes!\nTap **➕ Add Recipe** first.",
                reply_markup=main_keyboard,
            )
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✏️ #{r.id} {r.title}", callback_data=f"edit_{r.id}")]
            for r in recipes[:10]
        ])
        await message.answer("✏️ **Select recipe to edit:**", reply_markup=kb, parse_mode="Markdown")


@router.message(F.text == "🗑 Delete Recipe", StateFilter(None))
async def cmd_delete_btn(message: Message):
    await _show_delete(message)


async def _show_delete(message: Message):
    async with async_session() as db:
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
        await message.answer("🗑 **Select recipe to delete:**", reply_markup=kb, parse_mode="Markdown")


# ============ CALLBACKS ============

@router.callback_query(F.data.startswith("view_"))
async def handle_view(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    async with async_session() as db:
        # Загружаем рецепт напрямую через raw SQL
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT id, title, instructions, description, servings FROM recipes WHERE id = :id"),
            {"id": rid}
        )
        row = result.fetchone()
        if row:
            rid, title, instructions, description, servings = row
            
            ing_result = await db.execute(
                text("SELECT i.name, ri.quantity, ri.unit FROM recipe_ingredients ri JOIN ingredients i ON ri.ingredient_id = i.id WHERE ri.recipe_id = :id"),
                {"id": rid}
            )
            ings = ing_result.fetchall()
            
            ing_list = [
                f"{name} — {int(qty)}{unit or ''}" if qty is not None
                else name
                for name, qty, unit in ings
            ]
            
            text = f"📖 **{title}**\n\n🥕 **Ingredients:**\n" + "\n".join(f"• {i}" for i in ing_list)
            if description:
                text += f"\n\n📝 {description}"
            text += f"\n\n👨‍🍳 **Instructions:**\n{instructions}"
            await callback.message.edit_text(text, parse_mode="Markdown")
        else:
            await callback.answer("Not found!", show_alert=True)


@router.callback_query(F.data.startswith("delete_"))
async def handle_delete(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    async with async_session() as db:
        user = await recipe_logic.get_or_create_user(db, str(callback.from_user.id))
        ok = await recipe_logic.delete_recipe(db, rid, user.id)
        if ok:
            await callback.answer("✅ Recipe successfully deleted!")
            await callback.message.delete()
            await callback.message.answer("✅ Recipe successfully deleted!", reply_markup=main_keyboard)
        else:
            await callback.answer("❌ Recipe not found!", show_alert=True)


@router.callback_query(F.data.startswith("edit_"))
async def handle_edit(callback: CallbackQuery, state: FSMContext):
    rid = int(callback.data.split("_")[1])
    await state.update_data(recipe_id=rid)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Title", callback_data=f"editf_title_{rid}")],
        [InlineKeyboardButton(text="🥕 Ingredients", callback_data=f"editf_ingredients_{rid}")],
        [InlineKeyboardButton(text="👨‍🍳 Instructions", callback_data=f"editf_instructions_{rid}")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="edit_cancel")],
    ])
    
    await callback.message.delete()
    await callback.message.answer(
        "✏️ **What would you like to edit?**\n\n"
        f"🔢 Recipe ID: `{rid}`",
        parse_mode="Markdown",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("editf_"))
async def handle_edit_field(callback: CallbackQuery, state: FSMContext):
    # Parse: editf_title_5, editf_ingredients_5, editf_instructions_5
    data = callback.data
    last_underscore = data.rfind("_")
    field = data[6:last_underscore]  # between "editf_" and last "_"
    rid = int(data[last_underscore + 1:])

    await state.update_data(recipe_id=rid)

    if field == "title":
        await callback.message.edit_text("📝 Enter **new title**:", parse_mode="Markdown")
        await state.set_state(EditRecipeState.new_title)
    elif field == "ingredients":
        await callback.message.edit_text(
            "🥕 Enter **new ingredients** (comma-separated):\n"
            "e.g., 'tomatoes 4 pcs, cheese 200g'",
            parse_mode="Markdown",
        )
        await state.set_state(EditRecipeState.new_ingredients)
    elif field == "instructions":
        await callback.message.edit_text("👨‍🍳 Enter **new instructions**:", parse_mode="Markdown")
        await state.set_state(EditRecipeState.new_instructions)


@router.callback_query(F.data == "edit_cancel")
async def handle_edit_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("✏️ Edit cancelled.", reply_markup=main_keyboard)


@router.message(Command("add_synonym"))
async def cmd_add_synonym(message: Message):
    """Add a synonym: /add_synonym bread baguette"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "Usage: `/add_synonym <word> <synonym>`\n"
            "e.g., `/add_synonym bread baguette`",
            parse_mode="Markdown",
        )
        return

    word = parts[1].lower()
    synonym = parts[2].lower()

    async with async_session() as db:
        from sqlalchemy import text
        # Find or create ingredient for the synonym target
        result = await db.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": synonym}
        )
        row = result.fetchone()

        if not row:
            # Create the ingredient first
            result = await db.execute(
                text("INSERT INTO ingredients (name) VALUES (:name) RETURNING id"),
                {"name": synonym}
            )
            ing_id = result.scalar()
        else:
            ing_id = row[0]

        # Add synonym
        try:
            await db.execute(
                text("INSERT INTO ingredient_synonyms (ingredient_id, synonym) VALUES (:iid, :syn)"),
                {"iid": ing_id, "syn": word}
            )
            await db.commit()
            await message.answer(f"✅ Synonym added: **{word}** → **{synonym}**", parse_mode="Markdown")
        except Exception:
            await message.answer(f"⚠️ Synonym **{word}** already exists!", parse_mode="Markdown")
