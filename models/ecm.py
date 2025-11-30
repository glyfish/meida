"""
data.models.ecm.py

Simulation and analysis if ECM random process.
"""

import numpy
import statsmodels.api as sm
import statsmodels.tsa as tsa
from typing import Tuple

from lib.models import arima

def xt_var(φ: float, σ: float, t_vals: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Compute the variance of x(t) ARIMA process in the ECM.

    Parameters
    ----------
    φ: float
        AR(1) parameter satisfying |φ| < 1.
    σ: float
        Residual variance (default 1.0).
    t_vals: numpy.ndarray[float]
        Time values desired.
    
    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        variance calculation.
    """

    def xt_var_t(npts: int) -> float:
        sum = 0.0
        for k in range(1, npts):
            sum += 2.0*(npts - k)*φ**k
        return (npts + sum) * σ**2 / (1.0 - φ**2)
    
    return numpy.array([xt_var_t(int(t)) for t in t_vals])

def yt_var(φ: float, σ: float, β: float, t_vals: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Compute the variance of the y(t) ECM process.

    Parameters
    ----------
    φ: float
        AR(1) parameter satisfying |φ| < 1.
    σ: float
        Residual variance (default 1.0).
    β: float
        ECM correlation parameter.
    t_vals: numpy.ndarray[float]
        Time values desired.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        variance calculation.
    """

    return xt_var(φ, σ, t_vals) * β**2

def cov(φ: float, σ: float, β: float, t_vals: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Compute the covariance of the two process for the ECM process.

    Parameters
    ----------
    φ: float
        AR(1) parameter satisfying |φ| < 1.
    β: float
        ECM correlation parameter.
    σ: float
        Residual variance (default 1.0).
    t_vals: numpy.ndarray[float]
        Time values desired.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        variance calculation.
    """

    return xt_var(φ, σ, t_vals) * β

def ecm(φ: float, δ: float, α: float, β: float, γ: float, λ: float, npts: int, σ: float=1.0) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate an ECM time series from an AR(1) process using the specified parameters.

    Parameters
    ----------
    φ: float
        AR(1) parameter satisfying |φ| < 1.
    δ: float
        ECM term parameter (default 0.0).
    α: float
        ECM term offset parameter (default 0.0).
    β: float
        ECM correlation parameter.
    γ: float
        ECM X(t) scale parameter.
    λ: float
        ECM relaxation rate.
    σ: float
        Residual variance (default 1.0).
    npts: int
        Number of samples generated (default 1000)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Generated x(t) and y(t) ECM time series.
    """

    ar = arima.ar1(φ, npts, σ)
    xt = arima.arima_from_arma(ar, 1)
    yt = numpy.zeros(npts)
    ξt = numpy.random.normal(0.0, σ, npts)
    for i in range(1, npts):
        Δxt = xt[i] - xt[i-1]
        Δyt = δ + γ*Δxt + λ*(yt[i-1] - α - β*xt[i-1]) + ξt[i]
        yt[i] = Δyt + yt[i-1]

    return xt, yt