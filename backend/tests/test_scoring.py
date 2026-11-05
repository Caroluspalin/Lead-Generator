import pytest

from app.scoring import (
    CLOSED_TEMPORARILY_PENALTY,
    NO_REVIEWS_PENALTY,
    WEBSITE_POINTS,
    lead_score,
)


def test_best_possible_lead_is_100() -> None:
    assert lead_score("NO WEBSITE", 5.0, 500, "OPERATIONAL") == 100


def test_worst_lead_is_0() -> None:
    assert lead_score("WEBSITE OK", None, 0, "OPERATIONAL") == 0


def test_permanently_closed_is_always_0() -> None:
    assert lead_score("NO WEBSITE", 5.0, 500, "CLOSED_PERMANENTLY") == 0


def test_website_status_order_with_equal_popularity() -> None:
    scores = [lead_score(s, 4.5, 50, "OPERATIONAL") for s in ("NO WEBSITE", "BROKEN WEBSITE", "NOT MOBILE", "WEBSITE OK")]
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) == 4


def test_website_dominates_popularity() -> None:
    # Hyvin suosittu yritys toimivalla sivulla ei ohita keskinkertaista ilman sivua
    assert lead_score("NO WEBSITE", 4.0, 10, "OPERATIONAL") > lead_score("WEBSITE OK", 5.0, 1000, "OPERATIONAL")


def test_more_reviews_score_higher() -> None:
    assert lead_score("NO WEBSITE", 4.5, 150, None) > lead_score("NO WEBSITE", 4.5, 15, None)


def test_review_points_saturate() -> None:
    assert lead_score("NOT MOBILE", 4.5, 200, None) == lead_score("NOT MOBILE", 4.5, 20000, None)


def test_better_rating_scores_higher() -> None:
    assert lead_score("NO WEBSITE", 4.8, 40, None) > lead_score("NO WEBSITE", 3.8, 40, None)


def test_rating_at_or_below_floor_gives_no_rating_points() -> None:
    assert lead_score("NO WEBSITE", 3.0, 40, None) == lead_score("NO WEBSITE", 1.0, 40, None)


def test_perfect_rating_with_one_review_counts_little() -> None:
    one = lead_score("NOT MOBILE", 5.0, 1, None)
    many = lead_score("NOT MOBILE", 5.0, 10, None)
    assert many - one >= 10


@pytest.mark.parametrize("count", [0, None])
def test_no_reviews_lowers_slightly(count: int | None) -> None:
    base = WEBSITE_POINTS["NO WEBSITE"]
    assert lead_score("NO WEBSITE", None, count, "OPERATIONAL") == base - NO_REVIEWS_PENALTY


def test_rating_without_reviews_is_ignored() -> None:
    assert lead_score("NO WEBSITE", 5.0, 0, None) == lead_score("NO WEBSITE", None, 0, None)


def test_closed_temporarily_lowers_a_lot() -> None:
    open_score = lead_score("NO WEBSITE", 4.5, 80, "OPERATIONAL")
    closed = lead_score("NO WEBSITE", 4.5, 80, "CLOSED_TEMPORARILY")
    assert open_score - closed == CLOSED_TEMPORARILY_PENALTY


def test_unknown_website_status_and_clamping() -> None:
    assert lead_score(None, None, None, None) == 0
    assert lead_score("SOMETHING ELSE", None, None, "CLOSED_TEMPORARILY") == 0


def test_negative_review_count_treated_as_zero() -> None:
    assert lead_score("NO WEBSITE", 4.0, -5, None) == lead_score("NO WEBSITE", 4.0, 0, None)


def test_result_is_int_in_range() -> None:
    for status in (*WEBSITE_POINTS, None):
        for rating in (None, 1.0, 3.5, 5.0):
            for count in (None, 0, 3, 99, 10_000):
                for bs in (None, "OPERATIONAL", "CLOSED_TEMPORARILY"):
                    s = lead_score(status, rating, count, bs)
                    assert isinstance(s, int)
                    assert 0 <= s <= 100
