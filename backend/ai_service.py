"""
AI Service - GigaChat integration for smart ingredient matching.
Fixes typos and finds synonyms using LLM.
Falls back to built-in methods if GigaChat is unavailable.
"""
import httpx
import os
import base64
import uuid
import re
import logging

logger = logging.getLogger(__name__)

# GigaChat API endpoints
GIGACHAT_AUTH_URL = os.getenv("GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth")
GIGACHAT_API_URL = os.getenv("GIGACHAT_API_URL", "https://gigachat.devices.sberbank.ru:443/api/v1/chat/completions")
GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID", "")
GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET", "")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")

# Cache for auth token
_token = None
_token_expires_at = 0


async def _get_auth_token():
    """Get GigaChat access token using OAuth 2.0"""
    global _token, _token_expires_at

    # Return cached token if still valid
    if _token:
        return _token

    # Decode client_secret to extract actual secret
    # client_secret is base64(client_id:actual_secret)
    try:
        decoded = base64.b64decode(GIGACHAT_CLIENT_SECRET).decode()
        # Format: "client_id:actual_secret"
        parts = decoded.split(":", 1)
        if len(parts) == 2:
            actual_secret = parts[1]
        else:
            actual_secret = GIGACHAT_CLIENT_SECRET
    except Exception:
        actual_secret = GIGACHAT_CLIENT_SECRET

    # Build Basic Auth: base64(client_id:actual_secret)
    credentials = f"{GIGACHAT_CLIENT_ID}:{actual_secret}"
    credentials_b64 = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Authorization": f"Basic {credentials_b64}",
        "RqUID": str(uuid.uuid4()),
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            response = await client.post(
                GIGACHAT_AUTH_URL,
                headers=headers,
                content=f"scope={GIGACHAT_SCOPE}",
            )
            if response.status_code == 200:
                token_data = response.json()
                _token = token_data.get("access_token")
                _token_expires_at = token_data.get("expires_at", 0)
                logger.info("[GigaChat] Auth SUCCESS!")
                return _token
            else:
                logger.error("[GigaChat] Auth error: %s %s", response.status_code, response.text[:300])
                return None
    except Exception as e:
        logger.error("[GigaChat] Auth exception: %s", e)
        return None


async def _call_gigachat(messages: list, temperature: float = 0.1) -> str:
    """Call GigaChat API with messages"""
    token = await _get_auth_token()
    if not token:
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "model": "GigaChat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 500,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            response = await client.post(GIGACHAT_API_URL, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                return None
    except Exception:
        return None


async def fix_typo(user_input: str, known_ingredients: list) -> str:
    """
    Use GigaChat to fix typos and find ingredient synonyms.
    Returns corrected ingredient name or original if no fix needed.
    """
    if not known_ingredients:
        return user_input

    known_list = "\n".join(f"- {ing}" for ing in known_ingredients[:100])

    messages = [
        {
            "role": "system",
            "content": (
                "You are an ingredient name corrector. "
                "The user might type an ingredient with a typo or use a synonym. "
                "Your job is to match it to the correct name from the known list. "
                "Return ONLY the corrected name from the list, nothing else. "
                "If the input already matches something in the list, return it as-is."
            ),
        },
        {
            "role": "user",
            "content": (
                f"The user typed: \"{user_input}\"\n\n"
                f"Known ingredients:\n{known_list}\n\n"
                f"Return ONLY the matching ingredient name from the list above."
            ),
        },
    ]

    result = await _call_gigachat(messages, temperature=0.1)
    logger.info("[GigaChat] fix_typo input='%s' output='%s'", user_input, result)

    if result:
        # Clean up response — remove quotes, extra whitespace
        cleaned = re.sub(r'[\"\']', '', result).strip()
        logger.info("[GigaChat] Cleaned: '%s'", cleaned)
        # Check if result matches a known ingredient
        for ing in known_ingredients:
            if cleaned.lower() == ing.lower():
                logger.info("[GigaChat] Exact match found: '%s'", ing)
                return cleaned
        # Try partial match
        for ing in known_ingredients:
            if cleaned.lower() in ing.lower() or ing.lower() in cleaned.lower():
                logger.info("[GigaChat] Partial match: '%s'", ing)
                return ing
        logger.info("[GigaChat] No match found, returning original")

    # If AI failed or no match, return original (fallback to built-in matching)
    return user_input


async def suggest_from_ingredients(user_ingredients: list, user_recipes: list) -> str:
    """Get recipe suggestions from GigaChat based on available ingredients"""
    if not user_recipes:
        return None

    ingredients_str = ", ".join(user_ingredients)
    recipes_str = json.dumps(user_recipes, ensure_ascii=False)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a recipe recommendation assistant. "
                "Given a list of ingredients the user has, suggest matching recipes "
                "from their recipe collection. "
                "For each match, show the recipe name and what ingredients are missing. "
                "Keep it brief and helpful."
            ),
        },
        {
            "role": "user",
            "content": (
                f"I have these ingredients: {ingredients_str}\n\n"
                f"Here are my saved recipes:\n{recipes_str}\n\n"
                f"Which recipes can I make? List up to 3 matches. "
                f"Show what I'm missing for each. If nothing matches, say so."
            ),
        },
    ]

    result = await _call_gigachat(messages, temperature=0.3)
    return result if result else None


async def is_available():
    """Check if GigaChat API is reachable and authenticated"""
    try:
        result = await _call_gigachat([
            {"role": "user", "content": "Say 'ok' in one word."}
        ], temperature=0.1)
        return result is not None and len(result) > 0
    except Exception:
        return False
