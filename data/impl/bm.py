"""
data.impl.bm.oy

Interface to data.models.bm.py
"""

import numpy
from typing import Tuple

from lib.models import bm
from lib import stats

from lib.utils import (get_param_throw_if_missing, get_param_default_if_missing,
                       verify_type, create_space)

def compute_mean(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute theoretical brownian motion mean.

    Parameters
    ----------
    npts: int
        Number of points.  (default 10)
    μ: float
        Mean value. (default 0.0)
    Δt: float
        Width of time step. (default 1.0)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)

    return Δt * create_space(xmin=1, npts=npts), numpy.full(npts, μ)

def compute_sd(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute theoretical brownian motion with drift standard deviation.

    Parameters
    ----------
    npts: int
        Number of points.  (default 10)
    μ: float
        Mean value. (default 0.0)
    Δt: float
        Width of time step. (default 1.0)
    σ: float
        Standard deviation factor of brownian motion term. The actual standard 
        deviation is given by σ * sqrt(Δt). (default 1)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and standard deviation.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)

    t = Δt * create_space(xmin=1, npts=npts)

    return t, σ*numpy.sqrt(t)

def compute_bm_drift_mean(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute theoretical brownian motion with drift mean.

    Parameters
    ----------
    npts: int
        Number of points.  (default 10)
    μ: float
        Mean value. (default 0.0)
    Δt: float
        Width of time step. (default 1.0)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    μ = get_param_throw_if_missing("μ", **kwargs)

    t = Δt * create_space(xmin=1, npts=npts)

    return t, μ*t

def compute_bm_geometric_mean(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute theoretical geometrical brownian motion mean.

    Parameters
    ----------
    npts: int
        Number of points.  (default 10)
    μ: float
        Mean value. (default 0.0)
    S0: float
        Initial value (default 1.0).
    Δt: float
        Width of time step. (default 1.0)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and standard deviation.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    S0 = get_param_default_if_missing("S0", 1.0, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)

    t = Δt * create_space(xmin=1, npts=npts)

    return t, S0*numpy.exp(μ*t)


def compute_bm_geometric_sd(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute theoretical geometrical brownian motion standard deviation.

    Parameters
    ----------
    npts: int
        Number of points.  (default 10)
    μ: float
        Mean value. (default 0.0)
     σ: float
        Standard deviation factor of brownian motion term. The actual standard 
        deviation is given by σ * sqrt(Δt). (default 1)
    S0: float
        Initial value (default 1.0).
    Δt: float
        Width of time step. (default 1.0)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and standard deviation.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    S0 = get_param_default_if_missing("S0", 1.0, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)

    t = Δt * create_space(xmin=1, npts=npts)

    return t, numpy.sqrt(S0**2*numpy.exp(2*μ*t)*(numpy.exp(t*σ**2)-1))


def compute_bm_from_noise(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute brownian motion from brownian noise. 

    Parameters
    ----------
    dB: numpy.ndarray[float]
        Brownian noise.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and brownian motion time series.
    """

    dB = get_param_throw_if_missing("dB", **kwargs)
    verify_type(dB, numpy.ndarray[float])

    npts = len(dB)

    return create_space(xmax=npts - 1, npts=npts), stats.from_noise(dB)

def create_bm_noise_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate brownian motion noise with zero mean and unit variance
    and the specified number of points.

    Parameters
    ----------
    npts: int
        Number of points.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and brownian noise time series.
    """

    npts = get_param_throw_if_missing("npts", **kwargs)

    return create_space(xmax=npts - 1, npts=npts), bm.noise(npts)

def create_bm_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate brownian motion with zero mean and variance specified by Δt
    and the specified number of points.

    Parameters
    ----------
    npts: int
        Number of points.
    Δt: float
        Width of time step. (default 1.0)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and brownian noise time series.
    """

    npts = get_param_throw_if_missing("npts", **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)

    return create_space(xmax=npts - 1, npts=npts), bm.bm(npts, Δt)

def create_bm_drift_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate brownian motion with drift with the specified parameters
    and the specified number of points.

    Parameters
    ----------
    npts: int
        Number of points.
    μ: float
        Drift coefficient. (default 0.0)
    σ: float
        Standard deviation factor of brownian motion term. The actual standard 
        deviation is given by σ * sqrt(Δt).  (default 1.0)
    Δt: float
        Width of time step. (default 1.0)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and brownian noise time series.
    """

    npts = get_param_throw_if_missing("npts", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)

    return create_space(xmax=npts - 1, npts=npts), bm.bm_with_drift(μ, σ, npts, Δt)

def create_bm_geometric_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate brownian motion with drift with the specified parameters
    and the specified number of points.

    Parameters
    ----------
    npts: int
        Number of points.
    μ: float
        Drift coefficient. (default 0.0)
    σ: float
        Standard deviation factor of brownian motion term. The actual standard 
        deviation is given by σ * sqrt(Δt). (default 1.0)
    S0: float
        Initial value. (default 1.0)
    Δt: float
        Width of time step. (default 1.0)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and brownian noise time series.
    """

    npts = get_param_throw_if_missing("npts", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    S0 = get_param_default_if_missing("S0", 1.0, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)

    return create_space(xmax=npts - 1, npts=npts), bm.bm_geometric(μ, σ, S0, npts, Δt)

