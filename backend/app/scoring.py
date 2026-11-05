"""Liidin pisteytys 0-100: paras liidi on toimiva, suosittu yritys jolla on huono tai puuttuva nettisivu.

score = website + reviews + rating - no_reviews_penalty - closed_penalty, rajattuna 0-100.
Kaava ja painot dokumentoitu myös docs/save_state.md:ssä — pidä ne synkassa.
"""
import math
from typing import Optional

# Nettisivun tila painaa eniten (max 55)
WEBSITE_POINTS: dict[str, int] = {
    "NO WEBSITE": 55,
    "BROKEN WEBSITE": 50,
    "NOT MOBILE": 35,
    "WEBSITE OK": 5,
}
UNKNOWN_WEBSITE_POINTS = 0

# Arvostelujen määrä = aktiivisuus / asiakasvirta (max 30, logaritminen, täysi pistemäärä 200 arvostelusta)
REVIEW_MAX_POINTS = 30
REVIEW_SATURATION = 200

# Hyvä rating (max 15): <= 3.0 -> 0, 5.0 -> täysi. Kerrotaan luottamuksella, ettei 5.0 / 1 arvostelu riitä.
RATING_MAX_POINTS = 15
RATING_FLOOR = 3.0
RATING_CEIL = 5.0
RATING_CONFIDENCE_REVIEWS = 10

# Ei yhtään arvostelua: voi olla kuollut tai uusi yritys
NO_REVIEWS_PENALTY = 5

# Tilapäisesti suljettu laskee paljon; pysyvästi suljettu on aina 0
CLOSED_TEMPORARILY_PENALTY = 40


def _review_points(review_count: int) -> float:
    ratio = math.log1p(review_count) / math.log1p(REVIEW_SATURATION)
    return REVIEW_MAX_POINTS * min(1.0, ratio)


def _rating_points(rating: float, review_count: int) -> float:
    quality = (rating - RATING_FLOOR) / (RATING_CEIL - RATING_FLOOR)
    quality = max(0.0, min(1.0, quality))
    confidence = min(1.0, review_count / RATING_CONFIDENCE_REVIEWS)
    return RATING_MAX_POINTS * quality * confidence


def lead_score(
    website_status: Optional[str],
    rating: Optional[float],
    review_count: Optional[int],
    business_status: Optional[str],
) -> int:
    if business_status == "CLOSED_PERMANENTLY":
        return 0

    # Google jättää userRatingCountin pois kun arvosteluja ei ole -> None tulkitaan nollaksi
    reviews = max(0, review_count or 0)

    score: float = WEBSITE_POINTS.get(website_status or "", UNKNOWN_WEBSITE_POINTS)
    if reviews == 0:
        score -= NO_REVIEWS_PENALTY
    else:
        score += _review_points(reviews)
        if rating is not None:
            score += _rating_points(rating, reviews)

    if business_status == "CLOSED_TEMPORARILY":
        score -= CLOSED_TEMPORARILY_PENALTY

    return max(0, min(100, round(score)))
