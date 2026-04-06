async def suggest_recipes(db: AsyncSession, user_ingredients: list, user_id: int = None):
    """Предложить рецепты — с поддержкой синонимов из БД"""
    from sqlalchemy import text

    user_ingredients = [i.strip() for i in user_ingredients if i.strip()]

    if not user_ingredients:
        return []

    # Загружаем все синонимы: synonym -> ingredient_name
    syn_result = await db.execute(text("SELECT synonym, i.name FROM ingredient_synonyms s JOIN ingredients i ON s.ingredient_id = i.id"))
    synonym_map = {}
    for syn_row in syn_result.fetchall():
        synonym_map[syn_row[0].lower()] = syn_row[1].lower()

    # Раскрываем синонимы
    expanded = set()
    for user_ing in user_ingredients:
        low = user_ing.lower()
        # Проверяем прямой синоним
        if low in synonym_map:
            expanded.add(synonym_map[low])
        # Добавляем оригинал для partial match
        expanded.add(low)

    # Загружаем ВСЕ рецепты
    sql = """
        SELECT r.id, r.title, r.instructions, r.description, r.servings
        FROM recipes r
        WHERE (:uid IS NULL OR r.user_id = :uid)
    """
    result = await db.execute(text(sql), {"uid": user_id})
    all_recipes = result.fetchall()

    if not all_recipes:
        return []

    # Загружаем ингредиенты
    recipe_ids = [r[0] for r in all_recipes]
    placeholders = ",".join([f":rid{i}" for i in range(len(recipe_ids))])
    params = {f"rid{i}": rid for i, rid in enumerate(recipe_ids)}

    ing_sql = f"""
        SELECT ri.recipe_id, i.name, ri.quantity, ri.unit
        FROM recipe_ingredients ri
        JOIN ingredients i ON ri.ingredient_id = i.id
        WHERE ri.recipe_id IN ({placeholders})
    """
    ing_result = await db.execute(text(ing_sql), params)
    all_ingredients_rows = ing_result.fetchall()

    recipe_ingredients_map = {}
    for row in all_ingredients_rows:
        rid = row[0]
        if rid not in recipe_ingredients_map:
            recipe_ingredients_map[rid] = []
        recipe_ingredients_map[rid].append({
            "name": row[1],
            "quantity": row[2],
            "unit": row[3],
        })

    # Фильтруем и сортируем
    scored_recipes = []
    for recipe in all_recipes:
        rid, title, instructions, description, servings = recipe
        ings = recipe_ingredients_map.get(rid, [])
        recipe_ing_names = [i["name"].lower() for i in ings]

        match_count = 0
        for user_ing in user_ingredients:
            low = user_ing.lower()
            for recipe_ing in recipe_ing_names:
                # Точное совпадение
                if low == recipe_ing:
                    match_count += 1
                    break
                # Синоним
                if low in synonym_map and synonym_map[low] == recipe_ing:
                    match_count += 1
                    break
                # Частичное совпадение
                if low in recipe_ing or recipe_ing in low:
                    match_count += 1
                    break

        if match_count > 0:
            scored_recipes.append((match_count, {
                "id": rid,
                "title": title,
                "instructions": instructions,
                "description": description,
                "servings": servings,
                "ingredients": ings,
            }))

    scored_recipes.sort(key=lambda x: x[0], reverse=True)
    return scored_recipes
