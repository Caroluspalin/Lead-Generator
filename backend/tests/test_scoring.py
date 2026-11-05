import pytest

from app.scoring import (
    CLOSED_TEMPORARILY_PENALTY,
    NO_REVIEWS_PENALTY,
    OPPORTUNITY,
    POPULARITY_FLOOR,
    lead_score,
    popularity,
)

ALL_STATUSES = ("NO WEBSITE", "BROKEN WEBSITE", "INSECURE", "NOT MOBILE", "UNKNOWN", "WEBSITE OK")


def test_best_possible_lead_is_100() -> None:
    assert lead_score("NO WEBSITE", 5.0, 500, "OPERATIONAL") == 100


def test_worst_lead_is_0() -> None:
    assert lead_score("WEBSITE OK", None, 0, "OPERATIONAL") == 0


def test_permanently_closed_is_always_0() -> None:
    assert lead_score("NO WEBSITE", 5.0, 500, "CLOSED_PERMANENTLY") == 0


# --- Sivun tila ---

def test_website_status_order_with_equal_popularity() -> None:
    order = ("NO WEBSITE", "BROKEN WEBSITE", "NOT MOBILE", "WEBSITE OK")
    scores = [lead_score(s, 4.5, 50, "OPERATIONAL") for s in order]
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) == 4


def test_insecure_is_at_not_mobile_level() -> None:
    assert lead_score("INSECURE", 4.5, 50, None) == lead_score("NOT MOBILE", 4.5, 50, None)


@pytest.mark.parametrize("reviews", [0, 5, 50, 500])
def test_website_ok_never_above_20(reviews: int) -> None:
    assert lead_score("WEBSITE OK", 5.0, reviews, "OPERATIONAL") <= 20


def test_popular_good_site_is_not_hot() -> None:
    # Live-havainto: 4.9/340 toimivalla sivulla oli vanhalla kaavalla 49 ~ sama kuin NO WEBSITE ilman arvosteluja
    assert lead_score("WEBSITE OK", 4.9, 340, None) == 20
    assert lead_score("NO WEBSITE", 4.0, 10, None) > 3 * lead_score("WEBSITE OK", 4.9, 340, None)


def test_unknown_is_neutral_between_issues_and_ok() -> None:
    unknown = lead_score("UNKNOWN", 4.5, 50, None)
    assert lead_score("NOT MOBILE", 4.5, 50, None) > unknown > lead_score("WEBSITE OK", 4.5, 50, None)


def test_unknown_never_scored_as_broken() -> None:
    assert lead_score("UNKNOWN", 5.0, 500, None) < lead_score("BROKEN WEBSITE", 5.0, 500, None)
    assert lead_score("UNKNOWN", 5.0, 500, None) <= OPPORTUNITY["UNKNOWN"]


@pytest.mark.parametrize("status", [None, "SOMETHING ELSE"])
def test_missing_or_unrecognized_status_treated_as_unknown(status: str | None) -> None:
    assert lead_score(status, 4.5, 50, None) == lead_score("UNKNOWN", 4.5, 50, None)


# --- Suosio kerrotaan, ei lasketa yhteen ---

def test_popularity_is_multiplied_by_opportunity() -> None:
    gain_no_site = lead_score("NO WEBSITE", 5.0, 200, None) - lead_score("NO WEBSITE", 3.0, 1, None)
    gain_ok_site = lead_score("WEBSITE OK", 5.0, 200, None) - lead_score("WEBSITE OK", 3.0, 1, None)
    assert gain_no_site > 4 * gain_ok_site


def test_popularity_range() -> None:
    assert popularity(None, 0) == 0.0
    assert popularity(5.0, 0) == 0.0
    assert popularity(5.0, 200) == pytest.approx(1.0)
    assert 0.0 < popularity(4.0, 10) < 1.0


def test_more_reviews_score_higher() -> None:
    assert lead_score("NO WEBSITE", 4.5, 150, None) > lead_score("NO WEBSITE", 4.5, 15, None)


def test_review_points_saturate() -> None:
    assert lead_score("NOT MOBILE", 4.5, 200, None) == lead_score("NOT MOBILE", 4.5, 20000, None)


def test_better_rating_scores_higher() -> None:
    assert lead_score("NO WEBSITE", 4.8, 40, None) > lead_score("NO WEBSITE", 3.8, 40, None)


def test_rating_at_or_below_floor_gives_no_rating_points() -> None:
    assert lead_score("NO WEBSITE", 3.0, 40, None) == lead_score("NO WEBSITE", 1.0, 40, None)


def test_perfect_rating_with_one_review_counts_little() -> None:
    assert popularity(5.0, 10) - popularity(5.0, 1) > 0.3


# --- Ei arvosteluja ---

@pytest.mark.parametrize("count", [0, None])
def test_no_reviews_penalty(count: int | None) -> None:
    expected = round(OPPORTUNITY["NO WEBSITE"] * POPULARITY_FLOOR - NO_REVIEWS_PENALTY)
    assert lead_score("NO WEBSITE", None, count, "OPERATIONAL") == expected


def test_no_reviews_penalty_in_expected_range() -> None:
    assert 15 <= NO_REVIEWS_PENALTY <= 20


def test_no_reviews_clearly_below_established_no_website() -> None:
    # Live-havainto: kolme 0-arvostelun yritystä oli top 5:ssä
    assert lead_score("NO WEBSITE", 4.6, 11, None) - lead_score("NO WEBSITE", None, 0, None) >= 25


def test_rating_without_reviews_is_ignored() -> None:
    assert lead_score("NO WEBSITE", 5.0, 0, None) == lead_score("NO WEBSITE", None, 0, None)


def test_negative_review_count_treated_as_zero() -> None:
    assert lead_score("NO WEBSITE", 4.0, -5, None) == lead_score("NO WEBSITE", 4.0, 0, None)


# --- Suljettu ---

def test_closed_temporarily_lowers_a_lot() -> None:
    open_score = lead_score("NO WEBSITE", 4.5, 80, "OPERATIONAL")
    closed = lead_score("NO WEBSITE", 4.5, 80, "CLOSED_TEMPORARILY")
    assert open_score - closed == CLOSED_TEMPORARILY_PENALTY


def test_clamped_to_zero() -> None:
    assert lead_score("WEBSITE OK", None, None, "CLOSED_TEMPORARILY") == 0


def test_result_is_int_in_range() -> None:
    for status in (*ALL_STATUSES, None):
        for rating in (None, 1.0, 3.5, 5.0):
            for count in (None, 0, 3, 99, 10_000):
                for bs in (None, "OPERATIONAL", "CLOSED_TEMPORARILY"):
                    s = lead_score(status, rating, count, bs)
                    assert isinstance(s, int)
                    assert 0 <= s <= 100
