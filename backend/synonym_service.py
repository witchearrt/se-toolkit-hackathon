"""
AI Synonym Service - uses sentence-transformers for semantic ingredient matching.
"""
import numpy as np

_model = None
_ingredient_embeddings = {}
_ingredient_names = []


def get_model():
    """Load model once (lazy, singleton)"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def build_ingredient_index(ingredients_list):
    """Build embedding index for all known ingredients"""
    global _ingredient_embeddings, _ingredient_names

    _ingredient_names = [ing.lower() for ing in ingredients_list]
    _ingredient_embeddings = {}

    if not _ingredient_names:
        return 0

    model = get_model()
    embeddings = model.encode(_ingredient_names, convert_to_numpy=True)
    for name, emb in zip(_ingredient_names, embeddings):
        _ingredient_embeddings[name] = emb

    return len(_ingredient_names)


def expand_ingredients_with_synonyms(user_ingredients, threshold=0.4):
    """
    Expand user's ingredient list with semantic matches.
    Returns a set of matched database ingredient names.
    """
    if not _ingredient_embeddings:
        return set(user_ingredients)

    matched = set()
    model = get_model()

    for user_ing in user_ingredients:
        user_embedding = model.encode(user_ing.lower(), convert_to_numpy=True)

        best_match = None
        best_score = 0

        for db_name, db_emb in _ingredient_embeddings.items():
            # Cosine similarity
            similarity = np.dot(user_embedding, db_emb) / (
                np.linalg.norm(user_embedding) * np.linalg.norm(db_emb) + 1e-9
            )
            if similarity > best_score:
                best_score = similarity
                best_match = db_name

        if best_match and best_score >= threshold:
            matched.add(best_match)
        else:
            matched.add(user_ing.lower())

    return matched


def _best_semantic_similarity(recipe_ing, user_ingredients):
    """
    Find best semantic similarity between a recipe ingredient and any user ingredient.
    Returns the highest cosine similarity score.
    """
    if not _ingredient_embeddings:
        return 0

    model = get_model()

    # Get embedding for the recipe ingredient
    recipe_emb = _ingredient_embeddings.get(recipe_ing.lower())
    if recipe_emb is None:
        # Encode on the fly if not in index
        recipe_emb = model.encode(recipe_ing.lower(), convert_to_numpy=True)

    best_score = 0

    for user_ing in user_ingredients:
        user_lower = user_ing.lower()
        user_emb = _ingredient_embeddings.get(user_lower)
        if user_emb is None:
            user_emb = model.encode(user_lower, convert_to_numpy=True)

        similarity = np.dot(recipe_emb, user_emb) / (
            np.linalg.norm(recipe_emb) * np.linalg.norm(user_emb) + 1e-9
        )
        if similarity > best_score:
            best_score = similarity

    return best_score
