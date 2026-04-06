from sqlalchemy import Column, Integer, String, Text, ForeignKey, Float
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(String(50), unique=True, nullable=False)
    username = Column(String(100), nullable=True)
    recipes = relationship("Recipe", back_populates="user", cascade="all, delete-orphan")


class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    recipe_links = relationship("RecipeIngredient", back_populates="ingredient")
    synonyms = relationship("IngredientSynonym", back_populates="ingredient", cascade="all, delete-orphan")


class IngredientSynonym(Base):
    """Synonyms for ingredients (e.g., 'baguette' -> 'bread')"""
    __tablename__ = "ingredient_synonyms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)
    synonym = Column(String(100), unique=True, nullable=False)

    ingredient = relationship("Ingredient", back_populates="synonyms")


class RecipeIngredient(Base):
    """Association model linking recipes to ingredients with quantity"""
    __tablename__ = "recipe_ingredients"

    recipe_id = Column(Integer, ForeignKey("recipes.id"), primary_key=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), primary_key=True)
    quantity = Column(Float, nullable=True)
    unit = Column(String(50), nullable=True)
    
    ingredient = relationship("Ingredient", back_populates="recipe_links")
    recipe = relationship("Recipe", back_populates="ingredient_links")


class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    instructions = Column(Text, nullable=False)
    servings = Column(Integer, nullable=True, default=2)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    ingredient_links = relationship("RecipeIngredient", back_populates="recipe", cascade="all, delete-orphan")
    user = relationship("User", back_populates="recipes")

    @property
    def ingredients(self):
        """Return list of Ingredient objects (for backward compatibility)"""
        return [link.ingredient for link in self.ingredient_links]
