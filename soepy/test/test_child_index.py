import pickle

import numpy as np
import pytest

from soepy.exogenous_processes.children import define_child_age_update_rule
from soepy.exogenous_processes.children import gen_prob_child_vector
from soepy.exogenous_processes.partner import gen_prob_partner
from soepy.pre_processing.model_processing import read_model_params_init
from soepy.pre_processing.model_processing import read_model_spec_init
from soepy.shared.non_employment_benefits import calculate_non_employment_benefits
from soepy.shared.shared_auxiliary import calculate_non_employment_consumption_resources
from soepy.shared.shared_auxiliary import calculate_utility_components
from soepy.shared.shared_auxiliary import draw_disturbances
from soepy.soepy_config import TEST_RESOURCES_DIR
from soepy.solve.covariates import construct_covariates
from soepy.solve.create_state_space import create_child_indexes
from soepy.solve.create_state_space import pyth_create_state_space
from soepy.solve.emaxs import do_weighting_emax
from soepy.solve.solve_python import pyth_backward_induction


@pytest.fixture(scope="module")
def input_data():

    vault = TEST_RESOURCES_DIR / "regression_vault.soepy.pkl"

    with open(vault, "rb") as file:
        tests = pickle.load(file)

    (
        model_spec_init_dict,
        random_model_params_df,
        exog_educ_shares,
        exog_child_age_shares,
        exog_partner_shares,
        exog_exper_shares_pt,
        exog_exper_shares_ft,
        exog_child_info,
        exog_partner_arrival_info,
        exog_partner_separation_info,
        expected_df_sim_func,
        expected_df_sim_sol,
    ) = tests[0]

    exog_educ_shares.to_pickle("test.soepy.educ.shares.pkl")
    exog_child_age_shares.to_pickle("test.soepy.child.age.shares.pkl")
    exog_child_info.to_pickle("test.soepy.child.pkl")
    exog_partner_shares.to_pickle("test.soepy.partner.shares.pkl")
    exog_exper_shares_pt.to_pickle("test.soepy.pt.exp.shares.pkl")
    exog_exper_shares_ft.to_pickle("test.soepy.ft.exp.shares.pkl")
    exog_partner_arrival_info.to_pickle("test.soepy.partner.arrival.pkl")
    exog_partner_separation_info.to_pickle("test.soepy.partner.separation.pkl")

    model_params_df, model_params = read_model_params_init(random_model_params_df)
    model_spec = read_model_spec_init(model_spec_init_dict, model_params_df)

    prob_child = gen_prob_child_vector(model_spec)
    prob_partner = gen_prob_partner(model_spec)

    states, indexer = pyth_create_state_space(model_spec)

    # Create objects that depend only on the state space
    covariates = construct_covariates(states, model_spec)

    child_age_update_rule = define_child_age_update_rule(model_spec, states)

    child_state_indexes = create_child_indexes(
        states, indexer, model_spec, child_age_update_rule
    )

    attrs_spec = ["seed_emax", "num_periods", "num_draws_emax"]
    draws_emax = draw_disturbances(
        *[getattr(model_spec, attr) for attr in attrs_spec], model_params
    )

    log_wage_systematic, non_consumption_utilities = calculate_utility_components(
        model_params, model_spec, states, covariates, True
    )

    non_employment_benefits = calculate_non_employment_benefits(
        model_spec, states, log_wage_systematic
    )

    deductions_spec = np.array(model_spec.ssc_deductions)
    tax_splitting = model_spec.tax_splitting

    non_employment_consumption_resources = calculate_non_employment_consumption_resources(
        deductions_spec,
        model_spec.tax_params,
        covariates[:, 1],
        non_employment_benefits,
        tax_splitting,
    )

    # Solve the model in a backward induction procedure
    # Error term for continuation values is integrated out
    # numerically in a Monte Carlo procedure
    emaxs = pyth_backward_induction(
        model_spec,
        states,
        child_state_indexes,
        log_wage_systematic,
        non_consumption_utilities,
        draws_emax,
        covariates,
        prob_child,
        prob_partner,
        non_employment_consumption_resources,
        deductions_spec,
    )

    return states, emaxs, child_state_indexes, prob_child, prob_partner


def test_child_state_index(input_data):
    states, emaxs, child_state_indexes, prob_child, prob_partner = input_data

    (
        period,
        educ_level,
        choice_lagged,
        exp_p,
        exp_f,
        disutil_type,
        age_kid,
        partner_indicator,
    ) = states[10]

    child_index = child_state_indexes[10, 1, :, :]
    child_emax = emaxs[:, 3][child_index]

    weighted_emax = do_weighting_emax(
        child_emax,
        prob_child[period, educ_level],
        prob_partner[period, educ_level, partner_indicator, :],
    )

    np.testing.assert_allclose(weighted_emax, emaxs[10, 1])
