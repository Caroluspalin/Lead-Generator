"""Liidin pisteytys 0-100: paras liidi on toimiva, suosittu yritys jolla on huono tai puuttuva nettisivu.

Suosio KERROTAAN sivun tilan painolla (ei lasketa yhteen), joten suosittu yritys hyvällä
sivulla ei voi nousta kuumaksi liidiksi:

    score = OPPORTUNITY[status] * (POPULARITY_FLOOR + (1 - POPULARITY_FLOOR) * popularity)
            - NO_REVIEWS_PENALTY (jos ei arvosteluja) - CLOSED_TEMPORARILY_PENALTY (jos suljettu)

Kaava ja painot dokumentoitu myös docs/save_state.md:ssä — pidä ne synkassa.
"""
import math
from typing import Optional

# Sivun tilan maksimipisteet = myyntimahdollisuuden koko. Huom: UNKNOWN on neutraali
# keskiarvo (ei bonusta eikä rangaistusta), koska tilaa ei saatu varmistettua.
OPPORTUNITY: dict[str, int] = {
    "NO WEBSITE": 100,
    "BROKEN WEBSITE": 90,
    "INSECURE": 65,
    "NOT MOBILE": 65,
    "UNKNOWN": 50,
    "WEBSITE OK": 20,
}
UNKNOWN_STATUS_OPPORTUNITY = OPPORTUNITY["UNKNOWN"]

# Osuus OPPORTUNITY-pisteistä, jonka yritys saa ilman yhtään suosiota
POPULARITY_FLOOR = 0.6

# Suosio 0-1 = REVIEW_WEIGHT * arvostelumäärä + RATING_WEIGHT * arvosana
REVIEW_WEIGHT = 0.7
RATING_WEIGHT = 0.3

# Arvostelumäärä log-asteikolla, täysi arvo REVIEW_SATURATION arvostelusta
REVIEW_SATURATION = 200

# Arvosana: <= RATING_FLOOR -> 0, RATING_CEIL -> 1, kerrottuna luottamuksella
RATING_FLOOR = 3.0
RATING_CEIL = 5.0
RATING_CONFIDENCE_REVIEWS = 10

# Ei yhtään arvostelua: voi olla kuollut tai uusi yritys
NO_REVIEWS_PENALTY = 15

# Tilapäisesti suljettu laskee paljon; pysyvästi suljettu on aina 0
CLOSED_TEMPORARILY_PENALTY = 40


def popularity(rating: Optional[float], review_count: int) -> float:
    """0-1. Nolla arvostelua -> 0."""
    if review_count <= 0:
        return 0.0
    reviews = min(1.0, math.log1p(review_count) / math.log1p(REVIEW_SATURATION))
    quality = 0.0
    if rating is not None:
        quality = max(0.0, min(1.0, (rating - RATING_FLOOR) / (RATING_CEIL - RATING_FLOOR)))
        quality *= min(1.0, review_count / RATING_CONFIDENCE_REVIEWS)
    return REVIEW_WEIGHT * reviews + RATING_WEIGHT * quality


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

    opportunity = OPPORTUNITY.get(website_status or "", UNKNOWN_STATUS_OPPORTUNITY)
    score = opportunity * (POPULARITY_FLOOR + (1 - POPULARITY_FLOOR) * popularity(rating, reviews))

    if reviews == 0:
        score -= NO_REVIEWS_PENALTY
    if business_status == "CLOSED_TEMPORARILY":
        score -= CLOSED_TEMPORARILY_PENALTY

    return max(0, min(100, round(score)))
