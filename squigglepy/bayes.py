import math

import numpy as np

from tqdm import tqdm
from datetime import datetime

from .distributions import norm, beta, mixture


_squigglepy_internal_bayesnet_caches = {}


def simple_bayes(likelihood_h, likelihood_not_h, prior):
    """
    Calculate Bayes rule.

    p(h|e) = (p(e|h)*p(h)) / (p(e|h)*p(h) + p(e|~h)*(1-p(h)))
    p(h|e) is called posterior
    p(e|h) is called likelihood
    p(h) is called prior

    Parameters
    ----------
    likelihood_h : float
        The likelihood (given that the hypothesis is true), aka p(e|h)
    likelihood_not_h : float
        The likelihood given the hypothesis is not true, aka p(e|~h)
    prior : float
        The prior probability, aka p(h)

    Returns
    -------
    float
        The result of Bayes rule, aka p(h|e)

    Examples
    --------
    # Cancer example: prior of having cancer is 1%, the likelihood of a positive
    # mammography given cancer is 80% (true positive rate), and the likelihood of
    # a positive mammography given no cancer is 9.6% (false positive rate).
    # Given this, what is the probability of cancer given a positive mammography?
    >>> simple_bayes(prior=0.01, likelihood_h=0.8, likelihood_not_h=0.096)
    0.07763975155279504
    """
    return ((likelihood_h * prior) /
            (likelihood_h * prior +
             likelihood_not_h * (1 - prior)))


def bayesnet(event_fn, n=1, find=None, conditional_on=None,
             reduce_fn=None, raw=False, cache=True,
             reload_cache=False, verbose=False):
    """
    Calculate a Bayesian network.

    Allows you to find conditional probabilities of custom events based on
    rejection sampling.

    Parameters
    ----------
    event_fn : function
        A function that defines the bayesian network
    n : int
        The number of samples to generate
    find : a function or None
        What do we want to know the probability of?
    conditional_on : a function or None
        When finding the probability, what do we want to condition on?
    reduce_fn : a function or None
        When taking all the results of the simulations, how do we aggregate them
        into a final answer? Defaults to ``np.mean``.
    raw : bool
        If True, just return the results of each simulation without aggregating.
    cache : bool
        If True, cache the results for future calculations. Each cache will be matched
        based on the ``event_fn``.
    reload_cache : bool
        If True, any existing cache will be ignored and recalculated.
    verbose : bool
        If True, will print out statements on computational progress.

    Returns
    -------
    various
        The result of ``reduce_fn`` on ``n`` simulations of ``event_fn``.

    Examples
    --------
    # Cancer example: prior of having cancer is 1%, the likelihood of a positive
    # mammography given cancer is 80% (true positive rate), and the likelihood of
    # a positive mammography given no cancer is 9.6% (false positive rate).
    # Given this, what is the probability of cancer given a positive mammography?
    >> def mammography(has_cancer):
    >>    p = 0.8 if has_cancer else 0.096
    >>    return bool(sq.sample(sq.bernoulli(p)))
    >>
    >> def define_event():
    >>    cancer = sq.sample(sq.bernoulli(0.01))
    >>    return({'mammography': mammography(cancer),
    >>            'cancer': cancer})
    >>
    >> bayes.bayesnet(define_event,
    >>                find=lambda e: e['cancer'],
    >>                conditional_on=lambda e: e['mammography'],
    >>                n=1*M)
    0.07723995880535531
    """
    events = None
    if not reload_cache:
        if verbose:
            print('Checking cache...')
        events = _squigglepy_internal_bayesnet_caches.get(event_fn)
        if events:
            if events['metadata']['n'] < n:
                raise ValueError(('{} results cached but ' +
                                  'requested {}').format(events['metadata']['n'], n))
            else:
                if verbose:
                    print('...Cached data found. Using it.')
                events = events['events']
    elif verbose:
        print('Reloading cache...')

    if events is None:
        if verbose:
            print('Generating Bayes net...')
            events = [event_fn() for _ in tqdm(range(n))]
        else:
            events = [event_fn() for _ in range(n)]
        if verbose:
            print('...Generated')
        if cache:
            if verbose:
                print('Caching...')
            metadata = {'n': n, 'last_generated': datetime.now()}
            _squigglepy_internal_bayesnet_caches[event_fn] = {'events': events,
                                                              'metadata': metadata}
            if verbose:
                print('...Cached')

    if conditional_on is not None:
        if verbose:
            print('Filtering conditional...')
        events = [e for e in events if conditional_on(e)]

    if len(events) < 1:
        raise ValueError('insufficient samples for condition')

    if conditional_on and verbose:
        print('...Done')

    if find is None:
        if verbose:
            print('...Reducing')
        return events if reduce_fn is None else reduce_fn(events)
    else:
        events = [find(e) for e in events]
        if raw:
            return events
        else:
            if verbose:
                print('...Reducing')
            reduce_fn = np.mean if reduce_fn is None else reduce_fn
            return reduce_fn(events)


def update(prior, evidence, evidence_weight=1):
    """
    Update a distribution.

    Starting with a prior distribution, use Bayesian inference to perform an update,
    producing a posterior distribution from the evidence distribution.

    Parameters
    ----------
    prior : Distribution
        The prior distribution. Currently must either be normal or beta type. Other
        types are not yet supported.
    evidence : Distribution
        The distribution used to update the prior. Currently must either be normal
        or beta type. Other types are not yet supported.
    evidence_weight : float
        How much weight to put on the evidence distribution? Currently this only matters
        for normal distributions, where this should be equivalent to the sample weight.

    Returns
    -------
    Distribution
        The posterior distribution

    Examples
    --------
    >> prior = sq.norm(1,5)
    >> evidence = sq.norm(2,3)
    >> bayes.update(prior, evidence)
    <Distribution> norm(mean=2.53, sd=0.29)
    """
    if prior.type == 'norm' and evidence.type == 'norm':
        prior_mean = prior.mean
        prior_var = prior.sd ** 2
        evidence_mean = evidence.mean
        evidence_var = evidence.sd ** 2
        return norm(mean=((evidence_var * prior_mean +
                           evidence_weight * (prior_var * evidence_mean)) /
                          (evidence_weight * prior_var + evidence_var)),
                    sd=math.sqrt((evidence_var * prior_var) /
                                 (evidence_weight * prior_var + evidence_var)))
    elif prior.type == 'beta' and evidence.type == 'beta':
        prior_a = prior.a
        prior_b = prior.b
        evidence_a = evidence.a
        evidence_b = evidence.b
        return beta(prior_a + evidence_a, prior_b + evidence_b)
    elif prior.type != evidence.type:
        raise ValueError('can only update distributions of the same type.')
    else:
        raise ValueError('type `{}` not supported.'.format(prior.type))


def average(prior, evidence, weights=[0.5, 0.5]):
    """
    Average two distributions.

    Parameters
    ----------
    prior : Distribution
        The prior distribution.
    evidence : Distribution
        The distribution used to average with the prior.
    weights : list or np.array or float
        How much weight to put on ``prior`` versus ``evidence`` when averaging? If
        only one weight is passed, the other weight will be inferred to make the
        total weights sum to 1. Defaults to 50-50 weights.

    Returns
    -------
    Distribution
        A mixture distribution that accords weights to ``prior`` and ``evidence``.

    Examples
    --------
    >> prior = sq.norm(1,5)
    >> evidence = sq.norm(2,3)
    >> bayes.average(prior, evidence)
    <Distribution> mixture
    """
    return mixture([prior, evidence], weights)
