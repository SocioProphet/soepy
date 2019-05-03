import numpy as np
import numba

from soepy.python.shared.shared_constants import MISSING_INT, NUM_CHOICES
from soepy.python.shared.shared_auxiliary import calculate_continuation_values


def construct_covariates(states):
    """Construct a matrix of covariates
    that depend only on the state space.

    Parameters
    ---------
    states : np.ndarray
        Array with shape (num_states, 6) containing period, experience in OCCUPATION A,
        experience in OCCUPATION B, years of schooling, the lagged choice and the type
        of the agent.

    Returns
    -------
    covariates : np.ndarray
        Array with shape (num_states, number of covariates) containing all additional
        covariates, which depend only on the state space information.

    Examples
    --------
    >>> states = np.array([
    >>> [0, 10, 0, 0, 0],
    >>> [1, 11, 0, 0, 0],
    >>> [2, 12, 0, 0, 0],
    >>> ])

    >>> covariates = construct_covariates(states)
    >>> covariates
    array([[1., 0., 0.],
           [0., 1., 0.],
           [0., 0., 1.]])
    """

    shape = (states.shape[0], 3)

    covariates = np.full(shape, 0.0)

    covariates[:, 0] = np.where(states[:, 1] == 10, 1, 0)
    covariates[:, 1] = np.where(states[:, 1] == 11, 1, 0)
    covariates[:, 2] = np.where(states[:, 1] == 12, 1, 0)

    return covariates


@numba.jit(nopython=True)
def pyth_create_state_space(model_params):
    """Create state space object.

    The state space consists of all admissible combinations of the following components:
    period, years of education, lagged choice, full-time experience (F),
    and part-time experience (P).

    :data:`states` stores the information on states in a tabular format.
    Each row of the table corresponds to one admissible state space point
    and contains the values of the state space components listed above.
    :data:`indexer` is a multidimensional array where each component
    of the state space corresponds to one dimension. The values of the array cells
    index the corresponding state space point in :data:`states`.
    Traversing the state space requires incrementing the indices of :data:`indexer`
    and selecting the corresponding state space point component values in :data:`states`.

    Parameters
    ----------
    model_params.num_periods : int
        Number of periods in the state space.
    model_params.educ_range : int
        Range of initial condition years of education in the (simulated) sample.
    NUM_CHOICES : int
        Number of choices agents have in each period.
    educ_min : int
        Minimum number of years of education in the simulated sample.

    Returns
    -------
    states : np.ndarray
        Array with shape (num_states, 6) containing period, experience in OCCUPATION A,
        experience in OCCUPATION B, years of schooling, the lagged choice and the type
        of the agent.
    indexer : np.ndarray
        A matrix where each dimension represents a characteristic of the state space.
        Switching from one state is possible via incrementing appropriate indices by 1.

    Examples
    --------
    >>> model_params = namedtuple("model_params", "num_periods educ_range educ_min")
    >>> model_params = model_params(10, 3, 10)
    >>> NUM_CHOICES = 3
    >>> states, indexer = pyth_create_state_space(
    ...     model_params
    ... )
    >>> states.shape
    (1110, 5)
    >>> indexer.shape
    (10, 3, 3, 10, 10)
    """
    data = []

    # Array for mapping the state space points (states) to indices
    shape = (
        model_params.num_periods,
        model_params.educ_range,
        NUM_CHOICES,
        model_params.num_periods,
        model_params.num_periods,
    )

    indexer = np.full(shape, MISSING_INT)

    # Initialize counter for admissible state space points
    i = 0

    # Loop over all periods / all ages
    for period in range(model_params.num_periods):

        # Loop over all possible initial conditions for education
        for educ_years in range(model_params.educ_range):

            # Check if individual has already completed education
            # and will make a labor supply choice in the period
            if educ_years > period:
                continue

            # Loop over all admissible years of experience accumulated in part-time
            for exp_f in range(model_params.num_periods):

                # Loop over all admissible years of experience accumulated in full-time
                for exp_p in range(model_params.num_periods):

                    # The accumulation of experience cannot exceed time elapsed
                    # since individual entered the model
                    if exp_f + exp_p > period - educ_years:
                        continue

                    # Add an additional entry state
                    # [educ_years + model_params.educ_min, 0, 0, 0]
                    # for individuals who have just completed education
                    # and still have no experience in any occupation.
                    if period == educ_years:

                        # Assign an additional integer count i
                        # for entry state
                        indexer[period, educ_years, 0, 0, 0] = i

                        # Record the values of the state space components
                        # for the currently reached entry state
                        row = [period, educ_years + model_params.educ_min, 0, 0, 0]

                        # Update count once more
                        i += 1

                        data.append(row)

                    else:

                        # Loop over the three labor market choices, N, P, F
                        for choice_lagged in range(NUM_CHOICES):

                            # If individual has only worked full-time in the past,
                            # she can only have full-time (2) as lagged choice
                            if (choice_lagged != 2) and (exp_f == period - educ_years):
                                continue

                            # If individual has only worked part-time in the past,
                            # she can only have part-time (1) as lagged choice
                            if (choice_lagged != 1) and (exp_p == period - educ_years):
                                continue

                            # If an individual has never worked full-time,
                            # she cannot have that lagged activity
                            if (choice_lagged == 2) and (exp_f == 0):
                                continue

                            # If an individual has never worked part-time,
                            # she cannot have that lagged activity
                            if (choice_lagged == 1) and (exp_p == 0):
                                continue

                            # If an individual has always been employed,
                            # she cannot have nonemployment (0) as lagged choice
                            if (choice_lagged == 0) and (
                                exp_f + exp_p == period - educ_years
                            ):
                                continue

                            # Check for duplicate states
                            if (
                                indexer[period, educ_years, choice_lagged, exp_p, exp_f]
                                != MISSING_INT
                            ):
                                continue

                            # Assign the integer count i as an indicator for the
                            # currently reached admissible state space point
                            indexer[period, educ_years, choice_lagged, exp_p, exp_f] = i

                            # Update count
                            i += 1

                            # Record the values of the state space components
                            # for the currently reached admissible state space point
                            row = [
                                period,
                                educ_years + model_params.educ_min,
                                choice_lagged,
                                exp_p,
                                exp_f,
                            ]

                            data.append(row)

        states = np.array(data)

    # Return function output
    return states, indexer


def pyth_backward_induction(model_params, states, indexer, covariates, flow_utilities):
    """Obtain the value function maximum values
    for all admissible states and periods in a backward induction procedure.
    """

    # Initialize container for the final result,
    # maximal value function per state:
    periods_emax = np.full(states.shape[0], np.nan)

    # Loop over all periods
    for k in reversed(range(states.shape[0])):

        # Construct additional education information
        educ_level = covariates[k, :]
        educ_years_idx = np.where(educ_level == np.max(educ_level))[0]

        # Integrate out the error term
        emax = construct_emax(
            model_params,
            k,
            flow_utilities,
            educ_years_idx,
            states,
            indexer,
            periods_emax,
        )

        # Record function output
        periods_emax[k] = emax

    # Return function output
    return periods_emax


def construct_emax(
    model_params, k, flow_utilities, educ_years_idx, states, indexer, periods_emax
):
    """Integrate out the error terms in a Monte Carlo simulation procedure
    to obtain value function maximum values for each period and state.
    """

    # Initialize container for sum of value function maximum values
    # over all error term draws for the period and state
    emax = 0.0

    # Loop over all error term draws
    # for the period and state currently reached by the parent loop
    for i in range(model_params.num_draws_emax):

        # Extract relevant state space components
        period, _, _, exp_p, exp_f = states[k, :]

        # Calculate flow utility at current period, state, and draw
        current_flow_utilities = flow_utilities[k, i, :]

        # Obtain continuation values for all choices
        continuation_values = calculate_continuation_values(
            model_params, indexer, period, periods_emax, educ_years_idx, exp_p, exp_f
        )

        # Calculate choice specific value functions
        value_functions = (
            current_flow_utilities + model_params.delta * continuation_values
        )

        # Obtain highest value function value among the available choices. If above
        # draws were the true shocks, maximum is the the current period value function
        # value. It is the sum the flow utility and next periods value function given an
        # optimal decision in the future and an optimal choice in the current period.
        maximum = max(value_functions)

        # Add to sum over all draws
        emax += maximum

        # End loop

    # Average over the number of draws
    emax = emax / model_params.num_draws_emax

    # Thus, we have integrated out the error term

    # Return function output
    return emax
