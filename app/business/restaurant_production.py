"""G1 restaurant's single-recipe lifecycle using explicit base-yield policy.

Original table: 900 seconds, food cost via building_level.costRatio, gold and
player XP reward, building XP. Menu interpolation is a compatibility settlement
policy, not a recovered original-server formula. Shared harvest applies the
authorized road/skill modifiers; this fixed recipe does not renew automatically.
"""
from __future__ import annotations

from app.business.tutorial_production import TutorialFieldProduction


class RestaurantProduction(TutorialFieldProduction):
    FIELD = "building200_036_01_01_1_1"
    PRODUCE_TYPE = "single"
    PRODUCT = FIELD
    PRODUCTS = frozenset({PRODUCT})
    PLAN_KEY = "restaurantBaseProductionV1"  # Server-internal, never on the wire.
    RESOURCE_ITEM = "item11_0000101"
    RESOURCE = "gold"
    RECIPE_ERROR = "no stub response: only the G1 restaurant's original fixed recipe is enabled"
