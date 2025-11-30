"""
lib.data.models.ou.py

Simulation and analysis of the Ornstein-Uhlenbeck process.
"""

import numpy
from scipy.stats import norm

def mean(μ: float, λ: float, t: numpy.ndarray[float], x0: float=0.0) -> numpy.ndarray[float]:
    """
    Mean value of Ornstein-Uhlenbeck process.

    Parameters
    ----------
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    t: numpy.ndarray[float]
        Time.
    x0: float
        Initial value.

    Returns
    -------
    numpy.ndarray[float]
        Mean as a function of time for given parameters.
    """

    return x0*numpy.exp(-λ*t) + μ*(1.0 - numpy.exp(-λ*t))

def var(λ: float, t: numpy.ndarray[float], σ: float=1.0) -> numpy.ndarray[float]:
    """
    Variance of Ornstein-Uhlenbeck process.

    Parameters
    ----------
    λ: float
        Mean reversion rate.
    t: numpy.ndarray[float]
        Time
    σ: float
        Standard deviation of random component.

    Returns
    -------
    numpy.ndarray[float]
        variance as a function of time for given parameters.
    """

    return (σ**2/(2.0*λ))*(1.0 - numpy.exp(-2.0*λ*t))

def var_limit(λ: float, σ: float=1.0) -> float:
    """
    Limit as t -> infinity of variance.

    Parameters
    ----------
    λ: float
        Mean reversion rate.
    σ: float
        Standard deviation of random component.

    Returns
    -------
    float
        Limiting variance.
    """

    return  σ**2/(2.0 * λ)

def cov(λ: float, s: float, t: numpy.ndarray[float], σ: float=1.0) -> numpy.ndarray[float]:
    """
    Covariance of Ornstein-Uhlenbeck process.

    Parameters
    ----------
    λ: float
        Mean reversion rate.
    s: float
        Time offset.
    t: numpy.ndarray[float]
        Time
    σ: float
        Standard deviation of random component.

    Returns
    -------
    numpy.ndarray[float]
        Covariance as a function of time for given parameters.
    """

    c = numpy.exp(-λ*(t - s)) - numpy.exp(-λ*(t + s))
    return σ**2*c/(2.0*λ)

def pdf(x: numpy.ndarray[float], μ: float, λ: float, t: float, σ: float=1.0, x0: float=0.0) -> numpy.ndarray[float]:
    """
    Ornstein-Uhlenbeck process PDF for a specified time.

    Parameters
    ----------
    x: numpy.ndarray[float]
        Modeled variable.
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    t: float
        Time
    σ: float
        Standard deviation of random component.
    x0: float
        Initial value.

    Returns
    -------
    numpy.ndarray[float]
        PDF of modeled variable for specified time.
    """

    μt = __mean(μ, λ, t, x0)
    σt = numpy.sqrt(__var(λ, t, σ))
    return norm.pdf(x, loc=μt, scale=σt)

def cdf(x: numpy.ndarray[float], μ: float, λ: float, t: float, σ: float=1.0, x0: float=0.0) -> numpy.ndarray[float]:
    """
    Ornstein-Uhlenbeck process CDF for a specified time.

    Parameters
    ----------
    x: numpy.ndarray[float]
        Modeled variable.
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    t: float
        Time
    σ: float
        Standard deviation of random component.
    x0: float
        Initial value.

    Returns
    -------
    numpy.ndarray[float]
        CDF of modeled variable for specified time.
    """

    μt = __mean(μ, λ, t, x0)
    σt = numpy.sqrt(__var(λ, t, σ))
    return norm.cdf(x, loc=μt, scale=σt)

def pdf_limit(x: numpy.ndarray[float], μ: float, λ: float, σ: float=1.0) -> numpy.ndarray[float]:
    """
    Ornstein-Uhlenbeck process PDF for t -> infinity.

    Parameters
    ----------
    x: numpy.ndarray[float]
        Modeled variable.
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    σ: float
        Standard deviation of random component.

    Returns
    -------
    numpy.ndarray[float]
        Limiting PDF of modeled variable.
    """

    σl = numpy.sqrt(var_limit(λ, σ))
    return norm.pdf(x, loc=μ, scale=σl)

def cdf_limit(x: numpy.ndarray[float], μ: float, λ: float, σ: float=1.0, x0: float=0) -> numpy.ndarray[float]:
    """
    Ornstein-Uhlenbeck process CDF for t -> infinity.

    Parameters
    ----------
    x: numpy.ndarray[float]
        Modeled variable.
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    σ: float
        Standard deviation of random component.

    Returns
    -------
    numpy.ndarray[float]
        Limiting CDF of modeled variable.
    """

    σl = numpy.sqrt(var_limit(λ, σ))
    return norm.cdf(x, loc=μ, scale=σl)

def mean_halflife(λ: float) -> float:
    """
    Ornstein-Uhlenbeck half life to limiting mean.

    Parameters
    ----------
    λ: float
        Mean reversion rate.

    Returns
    -------
    float
        Mean half life
    """

    return numpy.log(2)/λ

def xt(μ: float, λ: float, t: float, σ: float=1.0, x0: float=0, n: int=1) -> numpy.ndarray[float]:
    """
    Simulation of modeled variable at a specified time with the specified parameters.

    Parameters
    ----------
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    t: float
        Time
    σ: float
        Standard deviation of random component.
    x0: float
        Initial value.
    n: int
        Number of values simulated.

    Returns
    -------
    numpy.ndarray[float]
        Simulation of modeled variable at specified time using given parameters.
    """

    μt = __mean(μ, λ, t, x0)
    σt = numpy.sqrt(__var(λ, t, σ))
    ε = numpy.random.normal(0.0, 1.0, n)
    return μt + σt*ε

def ou(μ: float, λ: float, Δt: float, n: int, σ: float=1.0, x0: float=0) -> numpy.ndarray[float]:
    """
    Simulation of Ornstein-Uhlenbeck process using provide parameters.

    Parameters
    ----------
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    Δt: float
        Time increment.
    n: int
        Number of values simulated.
    σ: float
        Standard deviation of random component.
    x0: float
        Initial value.

    Returns
    -------
    numpy.ndarray[float]
        Simulation of Ornstein-Uhlenbeck process using provide parameters.
    """

    x = numpy.zeros(n)
    ε = numpy.random.normal(0.0, 1.0, n)
    x[0] = x0
    for i in range(0, n-1):
        x[i+1] = x[i] + λ*(μ - x[i])*Δt + σ*Δt*ε[i]
    return x

def __var(λ: float, t: float, σ: float=1.0) -> float:
    """
    Variance of Ornstein-Uhlenbeck process.

    Parameters
    ----------
    λ: float
        Mean reversion rate.
    t: float
        Time
    σ: float
        Standard deviation of random component.

    Returns
    -------
    numpy.ndarray[float]
        variance as a function of time for given parameters.
    """

    return (σ**2/(2.0*λ))*(1.0 - numpy.exp(-2.0*λ*t))

def __mean(μ: float, λ: float, t: float, x0: float=0.0) -> float:
    """
    Mean value of Ornstein-Uhlenbeck process.

    Parameters
    ----------
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    t: float
        Time.
    x0: float
        Initial value.

    Returns
    -------
    float
        Mean as for given parameters.
    """

    return x0*numpy.exp(-λ*t) + μ*(1.0 - numpy.exp(-λ*t))

