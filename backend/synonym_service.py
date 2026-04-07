"""
AI Synonym Service - graceful fallback if AI unavailable
"""
import numpy as np

_model = None
_ingredient_embeddings = {}
_ai_available = False


def _try_load_model():
    """Try to load AI model, set flag on failure"""
    global _model, _ai_available
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        _ai_available = True
    except Exception as e:
        print(f"⚠️ AI model unavailable, using basic matching: {e}")
        _ai_available = False


def get_model():
    """Load model once (lazy, singleton)"""
    global _model
    if _model is None:
        _try_load_model()
    return _model


def build_ingredient_index(ingredients_list):
    """Build embedding index for all known ingredients"""
    global _ingredient_embeddings
    _ingredient_embeddings = {}
    
    if not _ai_available:
        _try_load_model()
    
    if not _ai_available:
        return 0

    ing_names = [ing.lower() for ing in ingredients_list]
    embeddings = _model.encode(ing_names, convert_to_numpy=True)
    for name, emb in zip(ing_names, embeddings):
        _ingredient_embeddings[name] = emb

    return len(ing_names)


def expand_ingredients_with_synonyms(user_ingredients, threshold=0.4):
    """Expand user's ingredient list with semantic matches"""
    if not _ai_available:
        return set(user_ingredients)

    matched = set()
    for user_ing in user_ingredients:
        user_emb = _model.encode(user_ing.lower(), convert_to_numpy=True)
        best_score = 0
        for db_name, db_emb in _ingredient_embeddings.items():
            sim = np.dot(user_emb, db_emb) / (np.linalg.norm(user_emb) * np.linalg.norm(db_emb) + 1e-9)
            if sim > best_score:
                best_score = sim
                if best_score >= threshold:
                    matched.add(db_name)
        if not any(best_score >= threshold for _ in [1]):
            matched.add(user_ing.lower())
    return matched


def _best_semantic_similarity(recipe_ing, user_ingredients):
    """Find best semantic similarity"""
    if not _ai_available:
        return 0

    recipe_emb = _ingredient_embeddings.get(recipe_ing.lower())
    if recipe_emb is None:
        recipe_emb = _model.encode(recipe_ing.lower(), convert_to_numpy=True)

    best_score = 0
    for user_ing in user_ingredients:
        user_emb = _ingredient_embeddings.get(user_ing.lower())
        if user_emb is None:
            user_emb = _model.encode(user_ing.lower(), convert_to_numpy=True)
        sim = np.dot(recipe_emb, user_emb) / (np.linalg.norm(recipe_emb) * np.linalg.norm(user_emb) + 1e-9)
        if sim > best_score:
            best_score = sim
    return best_score
