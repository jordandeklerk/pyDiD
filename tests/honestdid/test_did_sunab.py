# pylint: disable=redefined-outer-name
"""Test Sun and Abraham estimator."""

import warnings

import numpy as np
import pytest

from pydid.honestdid.did_sunab import (
    SunAbrahamResult,
    _create_disaggregated_result,
    _create_interaction_result,
    _empty_result,
    _find_never_always_treated,
    aggregate_sunab,
    aggregate_to_event_study,
    create_period_interactions,
    estimate_sunab_model,
    sunab,
    sunab_att,
)


@pytest.fixture
def basic_panel_data():
    np.random.seed(42)
    n_units = 30
    n_periods = 4

    time = np.tile(np.arange(n_periods), n_units)

    cohort_values = np.array([1, 2, 3, np.inf] * (n_units // 4) + [np.inf] * (n_units % 4))[:n_units]
    cohort = np.repeat(cohort_values, n_periods)

    outcome = np.random.randn(n_units * n_periods)
    covariates = np.column_stack((np.ones(n_units * n_periods), np.random.randn(n_units * n_periods, 2)))

    return {
        "cohort": cohort,
        "period": time,
        "outcome": outcome,
        "covariates": covariates,
    }


@pytest.fixture
def relative_period_data():
    np.random.seed(123)
    n = 100

    cohort = np.repeat([0, 1, 2], [30, 30, 40])
    period = np.concatenate(
        [np.random.choice([-2, -1, 0, 1, 2], 30), np.random.choice([-2, -1, 0, 1, 2], 30), np.repeat(-1, 40)]
    )

    outcome = np.random.randn(n)
    covariates = np.column_stack((np.ones(n), np.random.randn(n, 2)))

    return {
        "cohort": cohort,
        "period": period,
        "outcome": outcome,
        "covariates": covariates,
    }


@pytest.fixture
def simple_data():
    np.random.seed(42)
    n = 100
    y = np.random.randn(n)
    covariates = np.column_stack((np.ones(n), np.random.randn(n, 2)))
    interaction_matrix = np.random.randn(n, 3)
    cohort = np.repeat([0, 1, 2, np.inf], 25)
    period = np.tile([-1, 0, 1, 2], 25)
    period_values = np.array([-1, 0, 1, 2])
    weights = np.ones(n)
    return {
        "y": y,
        "covariates": covariates,
        "interaction_matrix": interaction_matrix,
        "cohort": cohort,
        "period": period,
        "period_values": period_values,
        "weights": weights,
    }


def test_sunab_result_namedtuple():
    result = SunAbrahamResult(
        att_by_event=np.array([0.1, 0.2]),
        se_by_event=np.array([0.01, 0.02]),
        event_times=np.array([-1, 0]),
        vcov=np.eye(2),
        cohort_shares=np.array([0.5, 0.5]),
        influence_func=None,
        att=0.15,
        se_att=0.015,
        n_cohorts=2,
        n_periods=2,
        estimation_params={"test": True},
    )

    assert result.aggregation_type == "dynamic"
    assert len(result.att_by_event) == 2
    assert result.att == 0.15


def test_sunab_basic_calendar_periods(basic_panel_data):
    result = sunab(
        cohort=basic_panel_data["cohort"],
        period=basic_panel_data["period"],
        outcome=basic_panel_data["outcome"],
        covariates=basic_panel_data["covariates"],
    )

    assert isinstance(result, SunAbrahamResult)
    assert result.n_cohorts > 0
    assert result.n_periods > 0
    assert len(result.att_by_event) == len(result.event_times)


def test_sunab_relative_periods(relative_period_data):
    result = sunab(
        cohort=relative_period_data["cohort"],
        period=relative_period_data["period"],
        outcome=relative_period_data["outcome"],
        covariates=relative_period_data["covariates"],
    )

    assert isinstance(result, SunAbrahamResult)
    assert 0 in result.event_times
    assert len(result.event_times) > 0


def test_sunab_return_interactions():
    cohort = np.array([0, 0, 0, 1, 1, 1])
    period = np.array([-2, -1, 0, -1, 0, 1])

    interactions = sunab(cohort=cohort, period=period, return_interactions=True)

    assert isinstance(interactions, np.ndarray)
    assert interactions.shape[0] == len(cohort)


def test_sunab_no_outcome_covariates():
    cohort = np.array([0, 0, 0, 1, 1, 1])
    period = np.array([-2, -1, 0, -1, 0, 1])

    result = sunab(
        cohort=cohort,
        period=period,
    )

    assert isinstance(result, SunAbrahamResult)
    assert result.estimation_params["status"] == "interactions_only"


def test_sunab_with_att(basic_panel_data):
    result = sunab(
        cohort=basic_panel_data["cohort"],
        period=basic_panel_data["period"],
        outcome=basic_panel_data["outcome"],
        covariates=basic_panel_data["covariates"],
        att=True,
    )

    assert result.att is not None
    assert result.se_att is not None


def test_sunab_no_agg(basic_panel_data):
    result = sunab(
        cohort=basic_panel_data["cohort"],
        period=basic_panel_data["period"],
        outcome=basic_panel_data["outcome"],
        covariates=basic_panel_data["covariates"],
        no_agg=True,
    )

    assert result.estimation_params["aggregated"] is False


def test_sunab_with_weights():
    n = 100
    cohort = np.repeat([0, 1, np.inf], [30, 30, 40])
    period = np.tile([0, 1], 50)
    outcome = np.random.randn(n)
    covariates = np.ones((n, 1))
    weights = np.random.uniform(0.5, 2.0, n)

    result = sunab(cohort=cohort, period=period, outcome=outcome, covariates=covariates, weights=weights)

    assert isinstance(result, SunAbrahamResult)


def test_sunab_ref_cohort():
    cohort = np.array([0, 1, 2, 3])
    period = np.array([0, 1, 2, 3])
    ref_cohort = np.array([2])

    result = sunab(cohort=cohort, period=period, ref_cohort=ref_cohort)

    assert isinstance(result, SunAbrahamResult)


@pytest.mark.parametrize("ref_period", [-1, [-1, -2], ".F", ".L"])
def test_sunab_ref_period_options(ref_period):
    cohort = np.repeat([0, 1, np.inf], 10)
    period = np.tile([-2, -1, 0, 1, 2], 6)

    result = sunab(cohort=cohort, period=period, ref_period=ref_period)

    assert isinstance(result, SunAbrahamResult)


def test_sunab_invalid_ref_period():
    cohort = np.array([0, 1])
    period = np.array([0, 1])

    with pytest.raises(ValueError, match="Unknown special reference period"):
        sunab(cohort=cohort, period=period, ref_period=".X")


def test_sunab_mismatched_lengths():
    cohort = np.array([0, 1, 2])
    period = np.array([0, 1])

    with pytest.raises(ValueError, match="same length"):
        sunab(cohort=cohort, period=period)


def test_sunab_bin_conflict():
    cohort = np.array([0, 1])
    period = np.array([0, 1])

    with pytest.raises(ValueError, match="Cannot use 'bin' with"):
        sunab(cohort=cohort, period=period, bin="bin::2", bin_c="bin::2")


def test_sunab_bin_relative_conflict():
    cohort = np.array([0, 1, 2])
    period = np.array([-1, 0, 1])

    with pytest.raises(ValueError, match="Cannot use 'bin' when 'period' contains relative"):
        sunab(cohort=cohort, period=period, bin="bin::2")


def test_sunab_missing_values():
    cohort = np.array([0, 1, np.nan, 2])
    period = np.array([0, 1, 2, np.nan])
    outcome = np.array([1, 2, 3, 4])
    covariates = np.ones((4, 1))

    result = sunab(cohort=cohort, period=period, outcome=outcome, covariates=covariates)

    assert isinstance(result, SunAbrahamResult)


def test_sunab_all_never_treated():
    cohort = np.array([10, 11, 12])
    period = np.array([0, 1, 2])

    with pytest.raises(ValueError, match="No cohort values found in period values"):
        sunab(cohort=cohort, period=period)


def test_sunab_no_valid_observations():
    cohort = np.array([0, 1])
    period = np.array([0, 1])
    ref_cohort = np.array([0, 1])

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = sunab(cohort=cohort, period=period, ref_cohort=ref_cohort)
        assert len(w) == 1
        assert "No observations remain" in str(w[0].message)
        assert result.estimation_params["status"] == "no_valid_observations"


def test_sunab_att_wrapper(basic_panel_data):
    result = sunab_att(
        cohort=basic_panel_data["cohort"],
        period=basic_panel_data["period"],
        outcome=basic_panel_data["outcome"],
        covariates=basic_panel_data["covariates"],
    )

    assert isinstance(result, SunAbrahamResult)
    assert result.att is not None
    assert result.se_att is not None


def test_aggregate_sunab():
    event_times = np.array([-1, 0, 1])
    initial_result = SunAbrahamResult(
        att_by_event=np.zeros(3),
        se_by_event=np.zeros(3),
        event_times=event_times,
        vcov=np.eye(3),
        cohort_shares=np.array([0.5, 0.5]),
        influence_func=None,
        att=None,
        se_att=None,
        n_cohorts=2,
        n_periods=3,
        estimation_params={},
    )

    cohort_coefs = {
        (-1, 0): 0.1,
        (-1, 1): 0.2,
        (0, 0): 0.3,
        (0, 1): 0.4,
        (1, 0): 0.5,
        (1, 1): 0.6,
    }

    cohort_vcov = np.diag([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])

    result = aggregate_sunab(initial_result, cohort_coefs, cohort_vcov)

    assert isinstance(result, SunAbrahamResult)
    assert len(result.att_by_event) == 3
    assert not np.allclose(result.att_by_event, 0)


def test_create_interaction_result():
    period_values = np.array([-1, 0, 1])
    cohort_values = np.array([0, 1, 2])
    interaction_matrix = np.zeros((10, 3))
    cohort = np.array([0, 0, 1, 1, 2, 2, 0, 1, 2, 0])
    is_ref_cohort = np.array([False] * 10)

    result = _create_interaction_result(
        period_values, cohort_values, interaction_matrix, cohort, is_ref_cohort, att=True
    )

    assert isinstance(result, SunAbrahamResult)
    assert result.att == 0.0
    assert result.se_att == 0.0
    assert result.estimation_params["status"] == "interactions_only"


def test_create_disaggregated_result():
    coefs = np.array([0.1, 0.2, 0.3])
    vcov = np.diag([0.01, 0.02, 0.03])
    cohort = np.array([0, 1, 2])
    period_values = np.array([-1, 0, 1])

    result = _create_disaggregated_result(coefs, vcov, cohort, period_values)

    assert isinstance(result, SunAbrahamResult)
    assert np.allclose(result.att_by_event, coefs)
    assert np.allclose(result.se_by_event, np.sqrt(np.diag(vcov)))
    assert result.estimation_params["aggregated"] is False


def test_empty_result():
    result = _empty_result()

    assert isinstance(result, SunAbrahamResult)
    assert len(result.att_by_event) == 0
    assert len(result.se_by_event) == 0
    assert np.isnan(result.att)
    assert np.isnan(result.se_att)
    assert result.n_cohorts == 0
    assert result.n_periods == 0
    assert result.estimation_params["status"] == "no_valid_observations"


@pytest.mark.parametrize("n_units,n_periods", [(50, 5), (100, 3), (200, 10)])
def test_sunab_various_sizes(n_units, n_periods):
    time = np.tile(np.arange(n_periods), n_units)

    cohort_values = np.random.choice([1, 2, np.inf], n_units)
    cohort = np.repeat(cohort_values, n_periods)

    outcome = np.random.randn(n_units * n_periods)
    covariates = np.ones((n_units * n_periods, 1))

    result = sunab(cohort=cohort, period=time, outcome=outcome, covariates=covariates)

    assert isinstance(result, SunAbrahamResult)
    assert result.n_periods > 0
    assert result.n_cohorts > 0


def test_estimate_sunab_model_basic(simple_data):
    result = estimate_sunab_model(
        simple_data["y"],
        simple_data["covariates"],
        simple_data["interaction_matrix"],
        simple_data["cohort"],
        simple_data["period"],
        simple_data["period_values"],
        simple_data["weights"],
        att=False,
        no_agg=False,
    )

    assert isinstance(result, dict)
    assert "att_by_event" in result
    assert "se_by_event" in result
    assert "vcov_event" in result
    assert "aggregated" in result
    assert result["aggregated"] is True
    assert len(result["att_by_event"]) == len(simple_data["period_values"])


def test_estimate_sunab_model_no_agg(simple_data):
    result = estimate_sunab_model(
        simple_data["y"],
        simple_data["covariates"],
        simple_data["interaction_matrix"],
        simple_data["cohort"],
        simple_data["period"],
        simple_data["period_values"],
        simple_data["weights"],
        att=False,
        no_agg=True,
    )

    assert result["aggregated"] is False
    assert "coefs" in result
    assert "vcov" in result
    assert "se" in result
    assert len(result["coefs"]) == simple_data["interaction_matrix"].shape[1]


def test_estimate_sunab_model_with_att(simple_data):
    result = estimate_sunab_model(
        simple_data["y"],
        simple_data["covariates"],
        simple_data["interaction_matrix"],
        simple_data["cohort"],
        simple_data["period"],
        simple_data["period_values"],
        simple_data["weights"],
        att=True,
        no_agg=False,
    )

    assert "att" in result
    assert "se_att" in result
    assert result["att"] is not None
    assert result["se_att"] is not None


def test_estimate_sunab_model_nan_handling(simple_data):
    interaction_with_nan = simple_data["interaction_matrix"].copy()
    interaction_with_nan[10:15, :] = np.nan

    result = estimate_sunab_model(
        simple_data["y"],
        simple_data["covariates"],
        interaction_with_nan,
        simple_data["cohort"],
        simple_data["period"],
        simple_data["period_values"],
        simple_data["weights"],
        att=False,
        no_agg=False,
    )

    assert result is not None
    assert "n_obs" in result


def test_estimate_sunab_model_insufficient_obs():
    n = 5
    y = np.random.randn(n)
    covariates = np.random.randn(n, 10)
    interaction_matrix = np.random.randn(n, 10)
    cohort = np.arange(n)
    period = np.arange(n)
    period_values = np.unique(period)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = estimate_sunab_model(
            y, covariates, interaction_matrix, cohort, period, period_values, None, False, False
        )
        assert result is None
        assert len(w) == 1
        assert "Insufficient observations" in str(w[0].message)


def test_estimate_sunab_model_singular_matrix(simple_data):
    covariates = np.column_stack((np.ones(100), np.arange(100), np.arange(100) * 2))

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = estimate_sunab_model(
            simple_data["y"],
            covariates,
            simple_data["interaction_matrix"],
            simple_data["cohort"],
            simple_data["period"],
            simple_data["period_values"],
            simple_data["weights"],
            att=False,
            no_agg=False,
        )
        assert result is not None or len(w) > 0


def test__find_never_always_treated_basic():
    cohort_int = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2])
    period = np.array([-1, 0, 1, -1, -2, -3, 0, 1, 2])
    n_cohorts = 3

    never_treated, always_treated_idx = _find_never_always_treated(cohort_int, period, n_cohorts)

    assert len(never_treated) == 1
    assert 1 in never_treated
    assert len(always_treated_idx) == 3
    assert set(always_treated_idx) == {6, 7, 8}


def test__find_never_always_treated_all_treated():
    cohort_int = np.array([0, 0, 1, 1])
    period = np.array([0, 1, 2, 3])
    n_cohorts = 2

    never_treated, always_treated_idx = _find_never_always_treated(cohort_int, period, n_cohorts)

    assert len(never_treated) == 0
    assert len(always_treated_idx) == 4


def test__find_never_always_treated_mixed():
    cohort_int = np.array([0, 0, 0, 1, 1, 1])
    period = np.array([-1, 0, 1, -2, -1, 0])
    n_cohorts = 2

    never_treated, always_treated_idx = _find_never_always_treated(cohort_int, period, n_cohorts)

    assert len(never_treated) == 0
    assert len(always_treated_idx) == 0


def test_create_period_interactions_basic():
    period = np.array([-1, 0, 1, -1, 0, 1])
    period_values = np.array([-1, 0, 1])
    is_ref_cohort = np.array([False, False, False, True, True, True])
    is_always_treated = np.array([False, False, False, False, False, False])
    n_total = 6

    interactions = create_period_interactions(period, period_values, is_ref_cohort, is_always_treated, n_total, None)

    assert interactions.shape == (n_total, len(period_values))
    assert np.all(interactions[is_ref_cohort] == 0)
    assert interactions[0, 0] == 1
    assert interactions[1, 1] == 1
    assert interactions[2, 2] == 1


def test_create_period_interactions_with_always_treated():
    period = np.array([-1, 0, 1, 2])
    period_values = np.array([-1, 0, 1, 2])
    is_ref_cohort = np.array([False, False, False, False])
    is_always_treated = np.array([False, False, True, True])
    n_total = 4

    interactions = create_period_interactions(period, period_values, is_ref_cohort, is_always_treated, n_total, None)

    assert interactions.shape == (n_total, len(period_values))
    assert np.all(np.isnan(interactions[is_always_treated]))
    assert interactions[0, 0] == 1
    assert interactions[1, 1] == 1


def test_create_period_interactions_with_valid_mask():
    period = np.array([-1, 0, 1])
    period_values = np.array([-1, 0, 1])
    is_ref_cohort = np.array([False, False, False])
    is_always_treated = np.array([False, False, False])
    n_total = 5
    valid_obs_mask = np.array([True, True, True, False, False])

    interactions = create_period_interactions(
        period, period_values, is_ref_cohort, is_always_treated, n_total, valid_obs_mask
    )

    assert interactions.shape == (n_total, len(period_values))
    assert np.all(interactions[3:] == 0)


def test_aggregate_to_event_study_basic():
    coefs = np.array([0.1, 0.2, 0.3])
    vcov = np.diag([0.01, 0.02, 0.03])
    interactions = np.eye(3)
    cohort = np.array([0, 1, 2])
    period_values = np.array([-1, 0, 1])
    weights = np.ones(3)

    result = aggregate_to_event_study(coefs, vcov, interactions, cohort, period_values, weights, compute_att=False)

    assert "att_by_event" in result
    assert "se_by_event" in result
    assert "vcov_event" in result
    assert "cohort_shares" in result
    assert np.allclose(result["att_by_event"], coefs)
    assert result["att"] is None


def test_aggregate_to_event_study_with_att():
    coefs = np.array([0.0, 0.5, 0.6])
    vcov = np.diag([0.01, 0.02, 0.03])
    interactions = np.eye(3)
    cohort = np.array([0, 1, 2])
    period_values = np.array([-1, 0, 1])
    weights = np.ones(3)

    result = aggregate_to_event_study(coefs, vcov, interactions, cohort, period_values, weights, compute_att=True)

    assert result["att"] is not None
    assert result["se_att"] is not None
    expected_att = (0.5 + 0.6) / 2
    assert np.isclose(result["att"], expected_att)


def test_aggregate_to_event_study_cohort_shares():
    coefs = np.array([0.1, 0.2])
    vcov = np.diag([0.01, 0.02])
    interactions = np.array(
        [
            [1, 0],
            [1, 0],
            [0, 1],
        ]
    )
    cohort = np.array([0, 0, 1])
    period_values = np.array([0, 1])
    weights = np.ones(3)

    result = aggregate_to_event_study(coefs, vcov, interactions, cohort, period_values, weights, compute_att=False)

    assert len(result["cohort_shares"]) == 2
    assert np.isclose(result["cohort_shares"][0], 2 / 3)
    assert np.isclose(result["cohort_shares"][1], 1 / 3)


def test_aggregate_to_event_study_weighted():
    coefs = np.array([0.1, 0.2])
    vcov = np.diag([0.01, 0.02])
    interactions = np.array(
        [
            [1, 0],
            [0, 1],
        ]
    )
    cohort = np.array([0, 1])
    period_values = np.array([0, 1])
    weights = np.array([2.0, 1.0])

    result = aggregate_to_event_study(coefs, vcov, interactions, cohort, period_values, weights, compute_att=False)

    assert np.allclose(result["att_by_event"], coefs)


def test_aggregate_to_event_study_multi_cohort_period():
    n_periods = 2
    coefs = np.array([0.1, 0.2, 0.3, 0.4])
    vcov = np.diag([0.01, 0.02, 0.03, 0.04])

    interactions = np.zeros((4, 4))
    interactions[0, 0] = 1
    interactions[1, 1] = 1
    interactions[2, 2] = 1
    interactions[3, 3] = 1

    cohort = np.array([0, 0, 1, 1])
    period_values = np.array([0, 1])
    weights = np.ones(4)

    result = aggregate_to_event_study(coefs, vcov, interactions, cohort, period_values, weights, compute_att=False)

    assert len(result["att_by_event"]) == n_periods
    expected_period0 = (0.1 + 0.3) / 2
    assert np.isclose(result["att_by_event"][0], expected_period0)


@pytest.mark.parametrize("compute_att", [True, False])
def test_aggregate_to_event_study_empty_period(compute_att):
    coefs = np.array([0.1, 0.0, 0.3])
    vcov = np.diag([0.01, 0.0, 0.03])
    interactions = np.array(
        [
            [1, 0, 0],
            [0, 0, 1],
        ]
    )
    cohort = np.array([0, 1])
    period_values = np.array([0, 1, 2])
    weights = np.ones(2)

    result = aggregate_to_event_study(coefs, vcov, interactions, cohort, period_values, weights, compute_att)

    assert len(result["att_by_event"]) == len(period_values)
    assert result["att_by_event"][1] == 0
