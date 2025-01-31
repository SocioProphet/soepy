import numpy as np

from soepy.shared.non_employment_benefits import calculate_non_employment_benefits
from soepy.shared.shared_auxiliary import calculate_non_employment_consumption_resources
from soepy.shared.shared_auxiliary import calculate_utility_components
from soepy.shared.shared_auxiliary import draw_disturbances
from soepy.shared.shared_constants import HOURS
from soepy.shared.shared_constants import NUM_CHOICES
from soepy.solve.emaxs import construct_emax


def pyth_solve(
    states,
    covariates,
    child_state_indexes,
    model_params,
    model_spec,
    prob_child,
    prob_partner,
    is_expected,
):
    """Solve the model by backward induction.

    The solution routine performs four key operations:
    - create all nodes (state space points) of the decision tree (state space)
    that the agents might possibly reach.
    - create covariates that depend on the state space components at every
    state space point.
    - calculate the instantaneous/flow utilities for each possible choice at every
    state space point
    - calculate the continuation values for each choice at every
    state space point.

    Parameters
    __________
    model_params : namedtuple
        Namedtuple containing all structural, potentially free and estimable,
        parameters relevant for running a simulation.
    model_spec : namedtuple
        Namedtuple containing all fixed parameters relevant for running a simulation
    is_expected: bool
        A boolean indicator that differentiates between the human capital accumulation
        process that agents expect (is_expected = True) and that the market generates
        (is_expected = False)

    Returns
    _______
    states : np.ndarray
        Array with shape (num_states, 5) containing period, years of schooling,
        the lagged choice, the years of experience in part-time, and the
        years of experience in full-time employment.
    indexer : np.ndarray
        A matrix where each dimension represents a characteristic of the state space.
        Switching from one state is possible via incrementing appropriate indices by 1.
    covariates : np.ndarray
        Array with shape (num_states, number of covariates) containing all additional
        covariates, which depend only on the state space information.
    emaxs : np.ndarray
        Array with shape (num states, num_choices +1). First block of dimension
        num_choices contains continuation values of the state space point.
        Lat element contains the expected maximum value function of the state space point.
    """

    attrs_spec = ["seed_emax", "num_periods", "num_draws_emax"]
    draws_emax = draw_disturbances(
        *[getattr(model_spec, attr) for attr in attrs_spec], model_params
    )

    log_wage_systematic, non_consumption_utilities = calculate_utility_components(
        model_params, model_spec, states, covariates, is_expected
    )

    non_employment_benefits = calculate_non_employment_benefits(
        model_spec, states, log_wage_systematic
    )

    tax_splitting = model_spec.tax_splitting

    non_employment_consumption_resources = calculate_non_employment_consumption_resources(
        model_spec.ssc_deductions,
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
        model_spec.ssc_deductions,
    )

    # Return function output
    return (
        non_employment_consumption_resources,
        emaxs,
    )


def pyth_backward_induction(
    model_spec,
    states,
    child_state_indexes,
    log_wage_systematic,
    non_consumption_utilities,
    draws,
    covariates,
    prob_child,
    prob_partner,
    non_employment_consumption_resources,
    deductions_spec,
):
    """Get expected maximum value function at every state space point.
    Backward induction is performed all at once for all states in a given period.
    The function loops through each period. The included construct_emax function
    implicitly loops through all states in the period currently reached by the
    parent loop.

    Parameters
    ----------
    model_spec : namedtuple
        Contains all fixed parameters of the model including information on dimensions
        such as number of periods, agents, random draws, etc.
    states : np.ndarray
        Array with shape (num_states, 5) containing period, years of schooling,
        the lagged choice, the years of experience in part-time, and the
        years of experience in full-time employment.
    indexer : np.ndarray
        Array where each dimension represents a componenet of the state space.
        :data:`states[k]` returns the values of the state space components
        at state :data:`k`. Indexing :data:`indexer` by the same state space
        component values returns :data:`k`.
    log_wage_systematic : np.array
        One dimensional array with length num_states containing the part of the wages
        at the respective state space point that do not depend on the agent's choice,
        nor on the random shock.
    non_consumption_utilities : np.ndarray
        Array of dimension (num_states, num_choices) containing the utility
        contribution of non-pecuniary factors.

    Returns
    -------
    emaxs : np.ndarray
        An array of dimension (num_states, num choices + 1). The object's rows contain
        the continuation values of each choice at the specific state space points
        as its first elements. The last row element corresponds to the maximum
        expected value function of the state.
    """
    dummy_array = np.zeros(4)  # Need this array to define output for construct_emaxs

    emaxs = np.zeros((states.shape[0], NUM_CHOICES + 1))

    # Set taxing type
    tax_splitting = model_spec.tax_splitting

    # Loop backwards over all periods
    for period in reversed(range(model_spec.num_periods)):
        state_period_cond = states[:, 0] == period

        # Extract period information
        # States
        states_period = states[state_period_cond]

        # Probability that a child arrives
        prob_child_period = prob_child[period][states_period[:, 1]]

        # Probability of partner states.
        prob_partner_period = prob_partner[period][
            states_period[:, 1], states_period[:, 7]
        ]

        # Period rewards
        log_wage_systematic_period = log_wage_systematic[state_period_cond]
        non_consumption_utilities_period = non_consumption_utilities[state_period_cond]
        non_employment_consumption_resources_period = non_employment_consumption_resources[
            state_period_cond
        ]

        # Corresponding equivalence scale for period states
        male_wage_period = covariates[np.where(state_period_cond)][:, 1]
        equivalence_scale_period = covariates[state_period_cond][:, 2]
        child_benefits_period = covariates[state_period_cond][:, 3]
        child_bins_period = covariates[state_period_cond][:, 0].astype(int)
        index_child_care_costs = np.where(child_bins_period > 2, 0, child_bins_period)

        # Continuation value calculation not performed for last period
        # since continuation values are known to be zero
        if period == model_spec.num_periods - 1:
            emaxs_child_states = np.zeros(
                shape=(states_period.shape[0], 3, 2, 2), dtype=float
            )
        else:
            child_states_ind_period = child_state_indexes[state_period_cond]
            emaxs_child_states = emaxs[:, 3][child_states_ind_period]

        # Calculate emax for current period reached by the loop
        emaxs_period = construct_emax(
            model_spec.delta,
            log_wage_systematic_period,
            non_consumption_utilities_period,
            draws[period],
            emaxs_child_states,
            prob_child_period,
            prob_partner_period,
            HOURS,
            model_spec.mu,
            non_employment_consumption_resources_period,
            deductions_spec,
            model_spec.tax_params,
            model_spec.child_care_costs,
            index_child_care_costs,
            male_wage_period,
            child_benefits_period,
            equivalence_scale_period,
            tax_splitting,
            dummy_array,
        )

        emaxs[state_period_cond] = emaxs_period

    return emaxs
