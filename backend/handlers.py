import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import recipe_logic
from database import async_session
from models import Recipe, RecipeIngredient, Ingredient
from sqlalchemy import select, text, func
from sqlalchemy.orm import selectinload

router = Router()

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Add Recipe"), KeyboardButton(text="📚 My Recipes")],
        [KeyboardButton(text="🔍 Suggest Recipe"), KeyboardButton(text="✏️ Edit Recipe")],
        [KeyboardButton(text="🗑 Delete Recipe"), KeyboardButton(text="❓ Help")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Choose an action...",
)


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


# ============ STATE HANDLERS ============

@router.message(AddRecipeState.title)
async def add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("🥕 Send **ingredients** (comma-separated):\ne.g., 'tomatoes 4 pcs, cheese 200g'")
    await state.set_state(AddRecipeState.ingredients)


@router.message(AddRecipeState.ingredients)
async def add_ingredients(message: Message, state: FSMContext):
    await state.update_data(ingredients=message.text)
    await message.answer("👨‍🍳 Send **cooking instructions**:\n(step-by-step)")
    await state.set_state(AddRecipeState.instructions)


@router.message(AddRecipeState.instructions)
async def add_instructions(message: Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as db:
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipe = await recipe_logic.create_recipe(
            db=db, user_id=user.id, title=data["title"],
            instructions=message.text, ingredients_str=data["ingredients"],
        )
        await message.answer(
            f"✅ **Recipe saved!**\n\n📖 **{recipe.title}**\n🔢 ID: `{recipe.id}`",
            parse_mode="Markdown", reply_markup=main_keyboard,
        )
    await state.clear()


@router.message(SuggestState.ingredients)
async def suggest_ingredients(message: Message, state: FSMContext):
    ingredients = [i.strip() for i in message.text.split(",") if i.strip()]
    async with async_session() as db:
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        suggestions = await recipe_logic.suggest_recipes(db, ingredients, user.id)

        # recipe_logic already tries GigaChat AI + fallback internally
        # If still no matches, inform user

        if not suggestions:
            await message.answer("😔 No recipes found.\nAdd more recipes or try different ingredients!", reply_markup=main_keyboard)
            await state.clear()
            return

        for match_count, recipe in suggestions[:5]:
            ings = recipe["ingredients"]
            ing_list = []
            for i in ings:
                if i["quantity"] is not None:
                    qty = int(i["quantity"]) if i["quantity"] == int(i["quantity"]) else i["quantity"]
                    unit = i["unit"] or ""
                    ing_list.append(f"{i['name']} — {qty}{unit}")
                else:
                    ing_list.append(i["name"])
            # Check which matched and which are missing
            synonym_map = recipe_logic._build_synonym_map()
            matched = []
            missing = []
            for i in ings:
                db_name = i["name"].lower()
                found = False
                for user_ing in ingredients:
                    low = user_ing.lower()
                    # Exact
                    if low == db_name:
                        found = True; break
                    # Synonym
                    if low in synonym_map and db_name in synonym_map[low]:
                        found = True; break
                    # Partial
                    if low in db_name or db_name in low:
                        found = True; break
                if found:
                    matched.append(i["name"])
                else:
                    missing.append(i["name"])
            total = len(ings)
            text = (
                f"🍳 **{recipe['title']}**\n\n"
                f"✅ Match: {match_count}/{total} ingredients\n"
                f"❌ Missing: {', '.join(missing) if missing else 'nothing! You have everything!'}\n\n"
                f"🥕 **Ingredients:**\n" + "\n".join(f"• {i}" for i in ing_list) +
                f"\n\n📖 **Instructions:**\n{recipe['instructions']}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📖 Details", callback_data=f"view_{recipe['id']}")]])
            await message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await message.answer("💡 Tap a button above!", reply_markup=main_keyboard)
    await state.clear()


# ============ EDIT ============

@router.message(EditRecipeState.new_title)
async def edit_title(message: Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as db:
        recipe = await db.get(Recipe, data["recipe_id"])
        if recipe:
            await db.execute(text("UPDATE recipes SET title = :t WHERE id = :id"), {"t": message.text, "id": data["recipe_id"]})
            await db.commit()
            await message.answer(f"✅ Title updated to **{message.text}**!", reply_markup=main_keyboard, parse_mode="Markdown")
        else:
            await message.answer(f"❌ Recipe not found!", reply_markup=main_keyboard)
    await state.clear()


@router.message(EditRecipeState.new_ingredients)
async def edit_ingredients(message: Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as db:
        recipe = await db.get(Recipe, data["recipe_id"])
        if recipe:
            # Parse new ingredients
            new_ingredients = [i.strip() for i in message.text.split(",") if i.strip()]
            
            # Clear existing ingredient links
            for link in recipe.ingredient_links:
                await db.delete(link)
            await db.flush()
            
            # Create new ingredient links
            for ing_name in new_ingredients:
                # Get or create ingredient
                result = await db.execute(
                    select(Ingredient).where(func.lower(Ingredient.name) == ing_name.lower())
                )
                ingredient = result.scalar_one_or_none()
                
                if not ingredient:
                    ingredient = Ingredient(name=ing_name)
                    db.add(ingredient)
                    await db.flush()
                
                link = RecipeIngredient(recipe_id=recipe.id, ingredient_id=ingredient.id)
                db.add(link)
            
            await db.commit()
            await message.answer(f"✅ Ingredients updated for **{recipe.title}**!", reply_markup=main_keyboard, parse_mode="Markdown")
        else:
            await message.answer(f"❌ Recipe not found!", reply_markup=main_keyboard)
    await state.clear()


@router.message(EditRecipeState.new_instructions)
async def edit_instructions(message: Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as db:
        recipe = await db.get(Recipe, data["recipe_id"])
        if recipe:
            await db.execute(text("UPDATE recipes SET instructions = :i WHERE id = :id"), {"i": message.text, "id": data["recipe_id"]})
            await db.commit()
            await message.answer(f"✅ Instructions updated for **{recipe.title}**!", reply_markup=main_keyboard, parse_mode="Markdown")
        else:
            await message.answer(f"❌ Recipe not found!", reply_markup=main_keyboard)
    await state.clear()


# ============ COMMANDS / BUTTONS ============

@router.message(CommandStart())
async def cmd_start(message: Message):
    username = message.from_user.username or message.from_user.full_name
    async with async_session() as db:
        await recipe_logic.get_or_create_user(db, str(message.from_user.id), username)
    await message.answer(f"👋 **Welcome, {username}!**\n\nUse buttons below:", parse_mode="Markdown", reply_markup=main_keyboard)


@router.message(Command("help"))
async def cmd_help_slash(message: Message):
    await message.answer("🤖 **Help**\n\n➕ Add Recipe\n📚 My Recipes\n🔍 Suggest Recipe\n✏️ Edit Recipe\n🗑 Delete Recipe", parse_mode="Markdown", reply_markup=main_keyboard)


@router.message(F.text == "❓ Help", StateFilter(None))
async def cmd_help_btn(message: Message):
    await cmd_help_slash(message)


@router.message(Command("add_recipe"))
async def cmd_add_slash(message: Message, state: FSMContext):
    await state.set_state(AddRecipeState.title)
    await message.answer("📝 Send **recipe title**:")


@router.message(F.text == "➕ Add Recipe", StateFilter(None))
async def cmd_add_btn(message: Message, state: FSMContext):
    await state.set_state(AddRecipeState.title)
    await message.answer("📝 Send **recipe title**:")


@router.message(Command("my_recipes"))
async def cmd_my_slash(message: Message):
    await _show_recipes(message)


@router.message(F.text == "📚 My Recipes", StateFilter(None))
async def cmd_my_btn(message: Message):
    await _show_recipes(message)


async def _show_recipes(message: Message):
    async with async_session() as db:
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipes = await recipe_logic.get_user_recipes(db, user.id)
        if not recipes:
            await message.answer("📭 No recipes yet!\nTap **➕ Add Recipe**", reply_markup=main_keyboard)
            return
        text = f"📚 **Your Recipes** ({len(recipes)}):\n\n"
        for r in recipes:
            ings = [link.ingredient.name for link in r.ingredient_links[:3]]
            text += f"🔢 **#{r.id}** — **{r.title}**\n🥕 {', '.join(ings)}\n\n"
        text += "🔍 Suggest | ✏️ Edit | 🗑 Delete"
        await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard)


@router.message(Command("suggest"))
async def cmd_suggest_slash(message: Message, state: FSMContext):
    await _start_suggest(message, state)


@router.message(F.text == "🔍 Suggest Recipe", StateFilter(None))
async def cmd_suggest_btn(message: Message, state: FSMContext):
    await _start_suggest(message, state)


async def _start_suggest(message: Message, state: FSMContext):
    await message.answer("🔍 Send **ingredients you have** (comma-separated):\ne.g., 'chicken, rice, onion'")
    await state.set_state(SuggestState.ingredients)


@router.message(Command("delete_recipe"))
async def cmd_delete_slash(message: Message):
    await _show_delete(message)


@router.message(F.text == "🗑 Delete Recipe", StateFilter(None))
async def cmd_delete_btn(message: Message):
    await _show_delete(message)


async def _show_delete(message: Message):
    async with async_session() as db:
        user = await recipe_logic.get_or_create_user(db, str(message.from_user.id))
        recipes = await recipe_logic.get_user_recipes(db, user.id)
        if not recipes:
            await message.answer("📭 No recipes!", reply_markup=main_keyboard)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"🗑 #{r.id} {r.title}", callback_data=f"delete_{r.id}")] for r in recipes[:10]])
        await message.answer("🗑 Select recipe:", reply_markup=kb)


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
            await message.answer("📭 No recipes!", reply_markup=main_keyboard)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"✏️ #{r.id} {r.title}", callback_data=f"edit_{r.id}")] for r in recipes[:10]])
        await message.answer("✏️ Select recipe to edit:", reply_markup=kb)


# ============ CALLBACKS ============

@router.callback_query(F.data.startswith("view_"))
async def handle_view(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    async with async_session() as db:
        result = await db.execute(select(Recipe).options(selectinload(Recipe.ingredient_links).selectinload(RecipeIngredient.ingredient)).where(Recipe.id == rid))
        recipe = result.scalar_one_or_none()
        if recipe:
            ings = [link.ingredient.name for link in recipe.ingredient_links]
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
    async with async_session() as db:
        user = await recipe_logic.get_or_create_user(db, str(callback.from_user.id))
        ok = await recipe_logic.delete_recipe(db, rid, user.id)
        if ok:
            try:
                await callback.message.edit_text(f"✅ Recipe #{rid} deleted!")
            except Exception:
                await callback.message.answer(f"✅ Recipe #{rid} deleted!", reply_markup=main_keyboard)
        else:
            try:
                await callback.message.edit_text(f"❌ Recipe #{rid} not found or doesn't belong to you.")
            except Exception:
                await callback.message.answer(f"❌ Recipe #{rid} not found or doesn't belong to you.", reply_markup=main_keyboard)
        await callback.answer()


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
    await callback.message.edit_text(f"✏️ Edit recipe #{rid}\nWhat to change?", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("editf_"))
async def handle_edit_field(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    field = parts[1]
    rid = int(parts[2])
    await state.update_data(recipe_id=rid)
    
    try:
        if field == "title":
            await state.set_state(EditRecipeState.new_title)
            await callback.message.edit_text("📝 Enter **new title**:")
        elif field == "ingredients":
            await state.set_state(EditRecipeState.new_ingredients)
            await callback.message.edit_text("🥕 Enter **new ingredients** (comma-separated):\ne.g., 'tomatoes 4 pcs, cheese 200g'")
        elif field == "instructions":
            await state.set_state(EditRecipeState.new_instructions)
            await callback.message.edit_text("👨‍🍳 Enter **new instructions**:")
        await callback.answer()
    except Exception as e:
        print(f"Edit field error: {e}")
        await callback.answer("Error occurred", show_alert=True)


@router.callback_query(F.data == "edit_cancel")
async def handle_edit_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("✏️ Edit cancelled.", reply_markup=main_keyboard)
