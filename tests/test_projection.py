from olkalou_engine.projections import hard_bounds, monte_carlo


def test_hard_bound():
    result = hard_bounds({"UDA": 1000, "DCP": 400}, 500, [0.6, 0.7])
    assert result["t1_hard_bound"]["mathematically_decided"] is True


def test_monte_carlo_contract():
    result = monte_carlo(
        published=[
            {"stream_key": "a", "ward_name": "KARAU", "registered": 500, "votes": {"UDA": 200, "DCP": 100}, "turnout": 0.62},
            {"stream_key": "b", "ward_name": "KARAU", "registered": 500, "votes": {"UDA": 190, "DCP": 110}, "turnout": 0.61},
        ],
        outstanding=[{"stream_key": "c", "ward_name": "KARAU", "registered": 500}],
        candidate_ids=["UDA", "DCP"],
        simulations=100,
        seed=7,
    )
    assert result is not None
    assert set(result["win_probability"]) == {"UDA", "DCP"}
    assert abs(sum(result["win_probability"].values()) - 1) < 1e-9
