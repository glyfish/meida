"""
data.models.bm.oy

Simulation and analysis of Brownian motion.
"""

import numpy

def noise(n: int) -> numpy.ndarray[float]:
    """
    Generate brownian noise with zero mean and unit variance.

    Parameters
    ----------
    n: int
        Number of simulated values.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """
    return numpy.random.normal(0.0, 1.0, n)

def bm(n: int, Δt: float=1.0) -> numpy.ndarray[float]:
    """
    Generate brownian motion with zero mean and unit variance.

    Parameters
    ----------
    n: int
        Number of simulated values.
    Δt: float
        Width of time step. (default 1)
    
    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    σ = numpy.sqrt(Δt)
    samples = numpy.zeros(n)
    for i in range(1, n):
        Δ = numpy.random.normal()
        samples[i] = samples[i-1] + σ * Δ
    return samples

def bm_with_drift(μ: float, σ: float, n: int, Δt: float=1) -> numpy.ndarray[float]:
    """
    Generate brownian motion with drift.

    Parameters
    ----------
    μ: float
        Drift coefficient.
    σ: float
        Standard deviation factor of brownian motion term. The actual standard 
        deviation is given by σ * sqrt(Δt).
    n: int
        Number of simulated values.
    Δt: float
        Width of time step. (default 1)
    
    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    samples = numpy.zeros(n)
    for i in range(1, n):
        Δ = numpy.random.normal()
        samples[i] = samples[i-1] + (σ*Δ*numpy.sqrt(Δt)) + (μ*Δt)
    return samples

def bm_geometric(μ: float, σ: float, S0: float, n: int, Δt: float=1) -> numpy.ndarray[float]:
    """
    Generate geometric brownian motion.

    Parameters
    ----------
    μ: float
        Drift coefficient.
    σ: float
        Standard deviation factor of brownian motion term. The actual standard 
        deviation is given by σ * sqrt(Δt).
    S0: float
        Initial value.
    n: int
        Number of simulated values.
    Δt: float
        Width of time step. (default 1)
    
    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    gbm_drift = μ - 0.5*σ**2
    samples = bm_with_drift(gbm_drift, σ, n, Δt)
    return S0*numpy.exp(samples)
