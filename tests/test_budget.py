from conftest import make_piece

from davidtimes import budget


def test_count_words_handles_spanish_and_hyphens():
    assert budget.count_words("El piloto anglo-belga ganó, ¡otra vez! It's 3-0.") == 8


def test_reading_minutes():
    assert budget.reading_minutes(6600, 220) == 30
    assert budget.reading_minutes(100, 220) == 1
    assert budget.reading_minutes(0, 220) == 0


def test_default_budget_split():
    total = budget.total_budget(30, 220)
    assert total == 6600
    weights = {"f1": 1.0, "pl": 1.0, "co": 1.2, "world": 1.2, "culture": 1.2}
    split = budget.section_budgets(total, weights)
    assert split["f1"] == 1179 and split["co"] == 1414
    assert abs(sum(split.values()) - total) <= len(weights)
    assert budget.pieces_for(split["f1"], 350) == 3
    assert budget.pieces_for(split["co"], 350) == 4
    assert budget.pieces_for(0, 350) == 0


def test_piece_target_clamps_and_sets_hard_max():
    assert budget.piece_target(1179, 3) == (393, 492)
    assert budget.piece_target(5000, 1) == (600, 750)
    assert budget.piece_target(100, 1) == (200, 250)


def test_off_target():
    assert not budget.off_target(450, 400)
    assert budget.off_target(520, 400)
    assert budget.off_target(280, 400)


def test_trim_drops_lowest_ranked_but_keeps_one_per_section():
    pieces = [make_piece("a", 0, 500), make_piece("a", 1, 500), make_piece("b", 0, 500)]
    kept = budget.trim_to_budget(pieces, 1000)  # limit 1100
    assert [(p.section, p.rank) for p in kept] == [("a", 0), ("b", 0)]
    # Cannot drop below one piece per section even when over budget.
    assert len(budget.trim_to_budget(kept, 100)) == 2


def test_needs_more():
    assert budget.needs_more(5000, 6600)
    assert not budget.needs_more(6000, 6600)
