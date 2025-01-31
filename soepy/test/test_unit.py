import collections
import random
from random import randint
from random import randrange

import numpy as np
import pandas as pd

from soepy.exogenous_processes.children import gen_prob_child_init_age_vector
from soepy.exogenous_processes.children import gen_prob_child_vector
from soepy.exogenous_processes.education import gen_prob_educ_level_vector
from soepy.exogenous_processes.experience import gen_prob_init_exp_vector
from soepy.exogenous_processes.partner import gen_prob_partner
from soepy.exogenous_processes.partner import gen_prob_partner_present_vector
from soepy.pre_processing.model_processing import read_model_params_init
from soepy.pre_processing.model_processing import read_model_spec_init
from soepy.simulate.simulate_auxiliary import pyth_simulate
from soepy.simulate.simulate_python import simulate
from soepy.solve.create_state_space import create_state_space_objects
from soepy.solve.create_state_space import pyth_create_state_space
from soepy.solve.solve_python import pyth_solve
from soepy.test.random_init import init_dict_flat_to_init_dict
from soepy.test.random_init import namedtuple_to_dict
from soepy.test.random_init import random_init
from soepy.test.random_init import read_init_file2


def test_unit_nan():
    """This test ensures that the data frame only includes individuals that have
    completed education.
    """
    constr = {
        "AGENTS": 200,
        "PERIODS": 7,
        "EDUC_YEARS": [0, np.random.randint(1, 3), np.random.randint(4, 6)],
    }
    random_init(constr)
    df = simulate("test.soepy.pkl", "test.soepy.yml")

    np.testing.assert_equal(
        df[df["Education_Level"] == 1]["Period"].min(), constr["EDUC_YEARS"][1],
    )
    np.testing.assert_equal(
        df[df["Education_Level"] == 2]["Period"].min(), constr["EDUC_YEARS"][2],
    )


def test_unit_init_print():
    """This test ensures that the init file printing process work as intended. For this
    purpose we generate random init file specifications import the resulting files,
    write the specifications to another init file, import it again and comparing both
     initialization dicts
    """
    order = [
        "GENERAL",
        "CONSTANTS",
        "EDUC",
        "SIMULATION",
        "SOLUTION",
        "EXOG_PROC",
    ]

    for _ in range(5):
        random_init()
        model_params_df, _ = read_model_params_init("test.soepy.pkl")
        model_spec = read_model_spec_init("test.soepy.yml", model_params_df)
        init_dict_flat = namedtuple_to_dict(model_spec)
        init_dict = init_dict_flat_to_init_dict(init_dict_flat)
        init_dict2 = read_init_file2("test.soepy.yml")

        for key in order:
            for subkey in init_dict[key].keys():
                if not init_dict[key][subkey] == init_dict2[key][subkey]:
                    raise AssertionError()


def test_unit_data_frame_shape():
    """This test ensures that the shape of the simulated data frame corresponds
    to the random specifications of our initialization file.
    """
    for _ in range(5):
        constr = dict()
        constr["AGENTS"] = np.random.randint(10, 100)
        constr["PERIODS"] = np.random.randint(7, 10)
        constr["EDUC_YEARS"] = [0, np.random.randint(1, 2), np.random.randint(3, 5)]

        random_init(constr)

        model_params_df, model_params = read_model_params_init("test.soepy.pkl")
        model_spec = read_model_spec_init("test.soepy.yml", model_params_df)

        prob_educ_level = gen_prob_educ_level_vector(model_spec)
        prob_child_age = gen_prob_child_init_age_vector(model_spec)
        prob_partner_present = gen_prob_partner_present_vector(model_spec)
        prob_exp_ft = gen_prob_init_exp_vector(
            model_spec, model_spec.ft_exp_shares_file_name
        )
        prob_exp_pt = gen_prob_init_exp_vector(
            model_spec, model_spec.pt_exp_shares_file_name
        )
        prob_child = gen_prob_child_vector(model_spec)
        prob_partner = gen_prob_partner(model_spec)

        (
            states,
            indexer,
            covariates,
            child_age_update_rule,
            child_state_indexes,
        ) = create_state_space_objects(model_spec)

        # Obtain model solution
        non_employment_consumption_resources, emaxs = pyth_solve(
            states,
            covariates,
            child_state_indexes,
            model_params,
            model_spec,
            prob_child,
            prob_partner,
            False,
        )

        # Simulate
        df = pyth_simulate(
            model_params,
            model_spec,
            states,
            indexer,
            emaxs,
            covariates,
            non_employment_consumption_resources,
            child_age_update_rule,
            prob_educ_level,
            prob_child_age,
            prob_partner_present,
            prob_exp_ft,
            prob_exp_pt,
            prob_child,
            prob_partner,
            is_expected=False,
        )

        # Count individuals with each educ level
        counts = []
        for i in [0, 1, 2]:
            counts.append(df[df["Education_Level"] == i]["Identifier"].nunique())

        shape = (
            constr["AGENTS"] * constr["PERIODS"]
            - counts[1] * constr["EDUC_YEARS"][1]
            - counts[2] * constr["EDUC_YEARS"][2]
        )

        np.testing.assert_array_equal(df.shape[0], shape)


def test_unit_childbearing_age():
    """This test verifies that the state space does not contain newly born children
    after the last childbearing period"""
    expected = 0

    model_spec = collections.namedtuple(
        "model_spec",
        "num_periods num_educ_levels num_types \
        last_child_bearing_period child_age_max \
        educ_years child_age_init_max init_exp_max",
    )

    num_periods = randint(1, 11)
    last_child_bearing_period = randrange(num_periods)
    model_spec = model_spec(
        num_periods, 3, 2, last_child_bearing_period, 10, [0, 1, 2], 4, 4
    )

    states, _ = pyth_create_state_space(model_spec)

    np.testing.assert_equal(
        sum(
            states[np.where(states[:, 0] == model_spec.last_child_bearing_period + 1)][
                :, 6
            ]
            == 0
        ),
        expected,
    )


def test_no_children_no_exp():
    """This test ensures that
    i) child age equals -1 in the entire simulates sample,
    equivalent to no kid is ever born, if the probability to get a child is zero
    for all periods
    ii) initial experience is zero if so specified in constraint"""

    expected = 0

    is_expected = False

    constr = {"AGENTS": 200, "PERIODS": 10, "CHILD_AGE_INIT_MAX": -1, "INIT_EXP_MAX": 0}
    random_init(constr)

    model_params_df, model_params = read_model_params_init("test.soepy.pkl")
    model_spec = read_model_spec_init("test.soepy.yml", model_params_df)

    # Set probability of having children to zero for all periods
    prob_child = np.full((model_spec.num_periods, 3), 0.00)

    prob_educ_level = gen_prob_educ_level_vector(model_spec)
    prob_child_age = gen_prob_child_init_age_vector(model_spec)
    prob_partner_present = gen_prob_partner_present_vector(model_spec)
    prob_exp_ft = gen_prob_init_exp_vector(
        model_spec, model_spec.ft_exp_shares_file_name
    )
    prob_exp_pt = gen_prob_init_exp_vector(
        model_spec, model_spec.pt_exp_shares_file_name
    )
    prob_partner = gen_prob_partner(model_spec)

    (
        states,
        indexer,
        covariates,
        child_age_update_rule,
        child_state_indexes,
    ) = create_state_space_objects(model_spec)

    # Obtain model solution
    non_employment_consumption_resources, emaxs = pyth_solve(
        states,
        covariates,
        child_state_indexes,
        model_params,
        model_spec,
        prob_child,
        prob_partner,
        False,
    )

    # Simulate
    df = pyth_simulate(
        model_params,
        model_spec,
        states,
        indexer,
        emaxs,
        covariates,
        non_employment_consumption_resources,
        child_age_update_rule,
        prob_educ_level,
        prob_child_age,
        prob_partner_present,
        prob_exp_ft,
        prob_exp_pt,
        prob_child,
        prob_partner,
        is_expected=False,
    )

    np.testing.assert_equal(sum(df.dropna()["Age_Youngest_Child"] != -1), expected)
    np.testing.assert_equal(
        sum(df[df["Period"] == 0].dropna()["Experience_Part_Time"] != 0), expected
    )
    np.testing.assert_equal(
        sum(df[df["Period"] == 0].dropna()["Experience_Full_Time"] != 0), expected
    )


def test_shares_according_to_initial_conditions():
    """This test ensures that the shares of individuals with particular characteristics
    in the simulated data frame as determined by initial conditions correspond to the probabilities
    specified in the init file.
    """

    constr = dict()
    constr["AGENTS"] = 500000
    constr["EDUC_YEARS"] = [0, 0, 0]
    constr["PERIODS"] = 2
    constr["CHILD_AGE_INIT_MAX"] = 1
    constr["INIT_EXP_MAX"] = 2

    random_init(constr)

    model_params_df, model_params = read_model_params_init("test.soepy.pkl")
    model_spec = read_model_spec_init("test.soepy.yml", model_params_df)

    prob_educ_level = gen_prob_educ_level_vector(model_spec)
    prob_child_age = gen_prob_child_init_age_vector(model_spec)
    prob_partner_present = gen_prob_partner_present_vector(model_spec)
    prob_exp_ft = gen_prob_init_exp_vector(
        model_spec, model_spec.ft_exp_shares_file_name
    )
    prob_exp_pt = gen_prob_init_exp_vector(
        model_spec, model_spec.pt_exp_shares_file_name
    )
    prob_child = gen_prob_child_vector(model_spec)
    prob_partner = gen_prob_partner(model_spec)

    (
        states,
        indexer,
        covariates,
        child_age_update_rule,
        child_state_indexes,
    ) = create_state_space_objects(model_spec)

    # Obtain model solution
    non_employment_consumption_resources, emaxs = pyth_solve(
        states,
        covariates,
        child_state_indexes,
        model_params,
        model_spec,
        prob_child,
        prob_partner,
        False,
    )

    # Simulate
    df = pyth_simulate(
        model_params,
        model_spec,
        states,
        indexer,
        emaxs,
        covariates,
        non_employment_consumption_resources,
        child_age_update_rule,
        prob_educ_level,
        prob_child_age,
        prob_partner_present,
        prob_exp_ft,
        prob_exp_pt,
        prob_child,
        prob_partner,
        is_expected=False,
    )

    # Education level shares
    simulated = (
        df.groupby(["Education_Level"])["Identifier"].nunique().to_numpy()
        / constr["AGENTS"]
    )
    np.testing.assert_almost_equal(
        simulated, prob_educ_level, decimal=2, err_msg="Education level shares mismatch"
    )

    # Partner status in initial period
    simulated = (
        df[df["Period"] == 0]
        .groupby(["Education_Level"])["Partner_Indicator"]
        .mean()
        .to_numpy()
    )
    np.testing.assert_almost_equal(
        simulated, prob_partner_present, decimal=2, err_msg="Partner shares mismatch"
    )

    # Child ages in initial period
    simulated = (
        df[df["Period"] == 0]
        .groupby(["Education_Level"])["Age_Youngest_Child"]
        .value_counts(normalize=True)
        .sort_index(ascending=True)
        .to_numpy()
    )
    prob_child_age_flat = [item for sublist in prob_child_age for item in sublist]
    np.testing.assert_almost_equal(
        simulated, prob_child_age_flat, decimal=2, err_msg="Child age shares mismatch"
    )

    # Experience in initial period
    # Part-time
    simulated = (
        df[df["Period"] == 0]
        .groupby(["Education_Level"])["Experience_Part_Time"]
        .value_counts(normalize=True)
        .sort_index(ascending=True)
        .to_numpy()
    )
    prob_exp_pt_flat = [item for sublist in prob_exp_pt for item in sublist]
    np.testing.assert_almost_equal(
        simulated,
        prob_exp_pt_flat,
        decimal=2,
        err_msg="Part-time experience shares mismatch",
    )

    # Full-time
    simulated = (
        df[df["Period"] == 0]
        .groupby(["Education_Level"])["Experience_Full_Time"]
        .value_counts(normalize=True)
        .sort_index(ascending=True)
        .to_numpy()
    )
    prob_exp_ft_flat = [item for sublist in prob_exp_ft for item in sublist]
    np.testing.assert_almost_equal(
        simulated,
        prob_exp_ft_flat,
        decimal=2,
        err_msg="Full-time experience shares mismatch",
    )


def test_coef_educ_level_specificity():
    """This test ensures that when parameters for a specific
    education group are changed, the simulated data for the remaining education
    groups does not change."""

    constr = dict()
    constr["AGENTS"] = 100000
    constr["PERIODS"] = 10

    random_init(constr)

    model_params_base = pd.read_pickle("test.soepy.pkl")

    # Draw random education level to change
    educ_levels = ["low", "middle", "high"]
    random_educ_level = random.choice([0, 1, 2])
    param_to_change = f"gamma_f_{educ_levels[random_educ_level]}"

    model_params_changed = model_params_base
    model_params_changed.loc[("exp_returns_f", param_to_change), "value"] = (
        model_params_changed.loc[("exp_returns_f", param_to_change), "value"] * 2
    )

    data = []

    for num_sim, i in enumerate([model_params_base, model_params_changed]):

        model_params_df, model_params = read_model_params_init(i)
        model_spec = read_model_spec_init("test.soepy.yml", model_params_df)

        prob_educ_level = gen_prob_educ_level_vector(model_spec)
        prob_child_age = gen_prob_child_init_age_vector(model_spec)
        prob_partner_present = gen_prob_partner_present_vector(model_spec)
        prob_exp_ft = gen_prob_init_exp_vector(
            model_spec, model_spec.ft_exp_shares_file_name
        )
        prob_exp_pt = gen_prob_init_exp_vector(
            model_spec, model_spec.pt_exp_shares_file_name
        )
        prob_child = gen_prob_child_vector(model_spec)
        prob_partner = gen_prob_partner(model_spec)

        (
            states,
            indexer,
            covariates,
            child_age_update_rule,
            child_state_indexes,
        ) = create_state_space_objects(model_spec)

        # Obtain model solution
        non_employment_consumption_resources, emaxs = pyth_solve(
            states,
            covariates,
            child_state_indexes,
            model_params,
            model_spec,
            prob_child,
            prob_partner,
            False,
        )
        # Simulate
        df = pyth_simulate(
            model_params,
            model_spec,
            states,
            indexer,
            emaxs,
            covariates,
            non_employment_consumption_resources,
            child_age_update_rule,
            prob_educ_level,
            prob_child_age,
            prob_partner_present,
            prob_exp_ft,
            prob_exp_pt,
            prob_child,
            prob_partner,
            is_expected=False,
        )

        data.append(df)

    data_base = data[0]
    data_changed = data[1]

    for level in (0, 1, 2):
        if level == random_educ_level:
            continue
        data_base_educ_level = data_base[data_base["Education_Level"] == level]
        data_changed_educ_level = data_changed[data_changed["Education_Level"] == level]
        true_list = [
            col
            for col in data_changed_educ_level.columns.values
            if not pd.Series.equals(
                data_base_educ_level[col], data_changed_educ_level[col]
            )
        ]

        pd.testing.assert_frame_equal(data_base_educ_level, data_changed_educ_level)
