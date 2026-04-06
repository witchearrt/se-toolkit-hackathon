async def suggest_recipes(db: AsyncSession, user_ingredients: list, user_id: int = None):
    """Предложить рецепты — с AI семантическим поиском синонимов"""
    from sqlalchemy import text
    import synonym_service

    user_ingredients = [i.strip() for i in user_ingredients if i.strip()]

    if not user_ingredients:
        return []

    # 1. Загружаем все ингредиенты из БД и строим индекс
    ing_result = await db.execute(text("SELECT name FROM ingredients"))
    all_ing_names = [row[0] for row in ing_result.fetchall()]

    synonym_service.build_ingredient_index(all_ing_names)

    # 2. Раскрываем синонимы и семантические совпадения
    matched_db_ingredients = synonym_service.expand_ingredients_with_synonyms(
        user_ingredients, threshold=0.4
    )

    if not matched_db_ingredients:
        return []

    # 3. Загружаем ВСЕ рецепты
    sql = """
        SELECT r.id, r.title, r.instructions, r.description, r.servings
        FROM recipes r
        WHERE (:uid IS NULL OR r.user_id = :uid)
    """
    result = await db.execute(text(sql), {"uid": user_id})
    all_recipes = result.fetchall()

    if not all_recipes:
        return []

    # 4. Загружаем ингредиенты для рецептов
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

    # 5. Строим карту: recipe_id -> [{name, quantity, unit}]
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

    # 6. Фильтруем и сортируем (с семантическим matching)
    scored_recipes = []
    for recipe in all_recipes:
        rid, title, instructions, description, servings = recipe
        ings = recipe_ingredients_map.get(rid, [])
        recipe_ing_names = [i["name"].lower() for i in ings]

        match_count = 0
        for user_ing in user_ingredients:
            for recipe_ing in recipe_ing_names:
                # Точное или частичное совпадение
                if user_ing.lower() == recipe_ing or \
                   user_ing.lower() in recipe_ing or recipe_ing in user_ing.lower():
                    match_count += 1
                    break
                # Семантическое совпадение через AI
                elif recipe_ing in matched_db_ingredients:
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
