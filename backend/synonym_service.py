"""
AI Synonym Service - uses sentence-transformers for semantic ingredient matching.
Maps ingredient names to vectors and finds similar ingredients by cosine similarity.
"""
import numpy as np
from sentence_transformers import SentenceTransformer, util
import os
import json

MODEL_NAME = "all-MiniLM-L6-v2"
CACHE_DIR = "/app/models"
_cache_file = os.path.join(CACHE_DIR, "embeddings_cache.json")

_model = None
_ingredient_embeddings = {}  # name -> vector
_ingredient_names = []


def get_model():
    """Load model once (lazy, singleton)"""
    global _model
    if _model is None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        _model = SentenceTransformer(MODEL_NAME, cache_folder=CACHE_DIR)
    return _model


def embed_text(text):
    """Embed a single text string"""
    model = get_model()
    return model.encode(text, convert_to_tensor=True)


def build_ingredient_index(ingredients_list):
    """Build/update the embedding index for all known ingredients"""
    global _ingredient_embeddings, _ingredient_names
    
    _ingredient_names = [ing.lower() for ing in ingredients_list]
    _ingredient_embeddings = {}
    
    model = get_model()
    if _ingredient_names:
        embeddings = model.encode(_ingredient_names, convert_to_tensor=True)
        for name, emb in zip(_ingredient_names, embeddings):
            _ingredient_embeddings[name] = emb
    
    # Save cache
    try:
        with open(_cache_file, "w") as f:
            json.dump({
                "names": _ingredient_names,
            }, f)
    except Exception:
        pass
    
    return len(_ingredient_names)


def find_similar_ingredients(user_input, threshold=0.5, top_k=5):
    """
    Find ingredients semantically similar to user input.
    Returns list of (ingredient_name, similarity_score) tuples.
    """
    if not _ingredient_embeddings:
        return []
    
    model = get_model()
    user_embedding = model.encode(user_input.lower(), convert_to_tensor=True)
    
    results = []
    for name, emb in _ingredient_embeddings.items():
        similarity = util.cos_sim(user_embedding, emb).item()
        if similarity >= threshold:
            results.append((name, similarity))
    
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


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
        user_embedding = model.encode(user_ing.lower(), convert_to_tensor=True)
        
        best_match = None
        best_score = 0
        
        for db_name, db_emb in _ingredient_embeddings.items():
            similarity = util.cos_sim(user_embedding, db_emb).item()
            if similarity > best_score:
                best_score = similarity
                best_match = db_name
        
        # If good match found, add it
        if best_match and best_score >= threshold:
            matched.add(best_match)
        else:
            # No semantic match, add original as fallback
            matched.add(user_ing.lower())
    
    return matched
