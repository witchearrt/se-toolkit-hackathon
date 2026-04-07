"""
AI Service - calls the local Qwen Code API for smart ingredient matching.
"""
import httpx
import os
import json

QWEN_API_URL = os.getenv("QWEN_API_URL", "http://qwen-code-api:8080/v1/chat/completions")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "xxjfnbdhb9mTIWlOL9EQVkBWEGRGOEIR7zTkRR8o8UzX7JV00FhUE3A0tYbmsT9IKleq5WCUAYOrAxKEa6RwDA")
QWEN_MODEL = os.getenv("QWEN_MODEL", "coder-model")


async def _call_qwen_api(prompt: str) -> str:
    """Call Qwen Code API with a prompt"""
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": QWEN_API_KEY,
    }
    payload = {
        "model": QWEN_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 500,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(QWEN_API_URL, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                return f"[AI Error: {response.status_code} {response.text[:100]}]"
    except Exception as e:
        return f"[AI Unavailable: {str(e)[:80]}]"


async def fix_typo(user_input: str, known_ingredients: list) -> str:
    """Use AI to fix typos in ingredient names"""
    known_list = ", ".join(known_ingredients)
    prompt = (
        f"You are an ingredient name corrector. The user typed \"{user_input}\" but it might be a typo.\n"
        f"Known ingredients: {known_list}\n"
        f"Return ONLY the corrected ingredient name from the known list, or the original if it's correct.\n"
        f"Respond with just the word, nothing else."
    )
    result = await _call_qwen_api(prompt)
    return result.strip() if result else user_input


async def suggest_from_ingredients(user_ingredients: list, user_recipes: list) -> str:
    """Get recipe suggestions from AI based on available ingredients"""
    ingredients_str = ", ".join(user_ingredients)
    recipes_str = json.dumps(user_recipes, ensure_ascii=False)

    prompt = (
        f"I have these ingredients: {ingredients_str}\n\n"
        f"Here are my saved recipes:\n{recipes_str}\n\n"
        f"Which recipes can I make with what I have? List up to 3 matching recipes.\n"
        f"For each match, say the recipe name and what I'm missing (if anything).\n"
        f"Keep it brief. If nothing matches, say so."
    )
    result = await _call_qwen_api(prompt)
    return result if result else "No matching recipes found."


async def is_available():
    """Check if Qwen API is reachable"""
    try:
        result = await _call_qwen_api("Say 'ok' in one word.")
        return len(result) > 0
    except Exception:
        return False
