"""
AI Service - calls the local Qwen Code API for smart ingredient matching.
"""
import httpx
import os
import json

QWEN_API_URL = os.getenv("QWEN_API_URL", "http://host.docker.internal:42005/v1/chat/completions")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "my-secret-qwen-key")
QWEN_MODEL = os.getenv("QWEN_MODEL", "coder-model")

# Fallback: if host.docker.internal doesn't work, try common Docker gateway IPs
FALLBACK_URLS = [
    "http://172.17.0.1:42005/v1/chat/completions",
    "http://172.18.0.1:42005/v1/chat/completions",
    "http://172.19.0.1:42005/v1/chat/completions",
]


async def _call_qwen_api(prompt: str) -> str:
    """Call Qwen Code API with a prompt"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {QWEN_API_KEY}",
    }
    payload = {
        "model": QWEN_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 500,
    }

    # Try primary URL first
    urls_to_try = [QWEN_API_URL] + FALLBACK_URLS

    for url in urls_to_try:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception:
            continue

    return ""


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
