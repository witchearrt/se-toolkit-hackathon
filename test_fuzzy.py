from difflib import get_close_matches
import difflib

db_ings = ['tomatoes', 'baguette', 'cheese', 'garlic', 'bread', 'onion', 'milk']

for user_input in ['tonato', 'tmato', 'tomaot', 'chiken', 'bred', 'onions']:
    ratio = difflib.SequenceMatcher(None, user_input, 'tomatoes').ratio()
    matches = get_close_matches(user_input, db_ings, n=1, cutoff=0.5)
    print(f"Input: {user_input:10s} | Ratio to tomatoes: {ratio:.3f} | Matches: {matches}")
