"""
data.impl.arima.py

Interface to models.arima.py
"""
import numpy

from lib.models import arima
import statsmodels.tsa as tsa
from typing import Tuple
import uuid

from lib.data.param_est import (ParamEst, ARMAEst, ARMAEstType, ARMAParamType)
from lib.utils import (get_param_throw_if_missing, get_param_default_if_missing,
                       verify_type, create_space)

def compute_pacf(data: numpy.ndarray[float], **kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the partial autocorrelation function bu solving the Yule-Walker equations.

    Parameters
    ----------
    data: numpy.ndarray[float]
        AR(p) processes samples
    nlags: int
        The assumed order of the AR(p) process.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Lag and estimate of AR(p) coefficients.

    """

    nlags = get_param_throw_if_missing("nlags", **kwargs)

    return create_space(xmin=1.0, xmax=nlags, npts=nlags), arima.yw(data, nlags)

def compute_ar1_acf(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the AR(1) Autocorrelation function.

    Parameters
    ----------
    φ: float
        AR(1) coefficient.
    nlags: int
        number of lags.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time lag and AR(1) autocorrelation function.

    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    nlags = get_param_throw_if_missing("nlags", **kwargs)
    
    lags = create_space(xmax=nlags - 1, npts=nlags)
    return lags, φ**lags

def compute_maq_acf(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the AR(1) Autocorrelation function.

    Parameters
    ----------
    θ: list[float]
        MA(q) coefficients.
    nlags: int
        Number of lags.
    σ : float
        Noise standard deviation.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time lag and AR(1) autocorrelation function.
    """

    θ = get_param_throw_if_missing("θ", **kwargs)
    nlags = get_param_throw_if_missing("nlags", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    verify_type(θ, list)

    return create_space(xmax=nlags, npts=nlags + 1), arima.maq_acf(θ, σ, nlags)

def compute_arma_mean(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the ARMA process mean value.

    Parameters
    ----------
    npts: int
        Number of points to evaluate

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    npts = get_param_throw_if_missing("npts", **kwargs)

    return create_space(xmax=npts - 1, npts=npts), numpy.full(npts, 0.0)

def compute_ar1_sd(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the AR(1) process standard deviation.

    Parameters
    ----------
    φ: float
        AR(1) coefficient.
    σ : float
        Noise standard deviation.
    npts: int
        Number of points evaluate

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and standard deviation value.
    """

    npts = get_param_throw_if_missing("npts", **kwargs)
    φ = get_param_throw_if_missing("φ", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    
    return create_space(xmax=npts - 1, npts=npts), numpy.full(npts, arima.ar1_sigma(φ, σ))

def compute_maq_sd(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the MA(q) process standard deviation.

    Parameters
    ----------
    θ: list[float]
        MA(q) coefficients.
    σ : float
        Noise standard deviation.
    npts: int
        Number of points to evaluate

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and standard deviation value.
    """

    θ = get_param_throw_if_missing("θ", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)
    verify_type(θ, list)

    return create_space(xmax=npts - 1, npts=npts), numpy.full(npts, arima.maq_sigma(θ, σ))

def compute_ar1_offset_mean(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the AR(1) process with offset mean.

    Parameters
    ----------
    φ: float
        AR(1) coefficient.
    μ : float
        Offset.
    npts: int
        Number of points evaluate

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    μ = get_param_throw_if_missing("μ", **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)

    return create_space(xmax=npts - 1, npts=npts), numpy.full(npts, arima.ar1_offset_mean(φ, μ))

def compute_ar1_offset_sd(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the AR(1) process with offset standard deviation.

    Parameters
    ----------
    φ: float
        AR(1) coefficient.
    μ : float
        Offset.
    npts: int
        Number of points evaluate

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)

    return create_space(xmax=npts - 1, npts=npts), numpy.full(npts, arima.ar1_offset_sigma(φ, σ))

def create_ar_source(**kwargs):
    """
    Generate AR(p) using specified parameters and the statsmodels.tas simulator.

    Parameters
    ----------
    φ: list[float]
        AR(p) parameters.
    npts: int
        number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and Simulation results.
    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    verify_type(φ, list)

    return create_space(npts=npts), arima.arp(numpy.array(φ), npts, σ)

def create_ar_drift_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate AR(p) with drift source using specified parameters and the 
    statsmodels.tas simulator.

    Parameters
    ----------
    φ: list[float]
        AR(p) parameters.
    u: float
        Offset.
    γ: float
        Drift parameter.
    npts: int
        number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and Simulation results.
    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)
    μ = get_param_throw_if_missing("μ", **kwargs)
    γ = get_param_throw_if_missing("γ", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    verify_type(φ, list)

    return create_space(npts=npts), arima.arp_drift(numpy.array(φ), μ, γ, npts, σ)

def create_ar_offset_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate AR(p) with a constant offset using the specified parameters.

    Parameters
    ----------
    φ: list[float]
        AR(p) parameters.
    u: float
        Offset.
    npts: int
        number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        (Time steps, Simulation results.)
    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)
    μ = get_param_throw_if_missing("μ", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    verify_type(φ, list)

    return create_space(npts=npts), arima.arp_offset(numpy.array(φ), μ, npts, σ)

def create_ma_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate MA(q) using specified parameters and the statsmodels.tas simulator.

    Parameters
    ----------
    θ: list[float]
        MA(q) parameters.
    npts: int
        number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        (Time steps, Simulation results.)
    """

    θ = get_param_throw_if_missing("θ", **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    verify_type(θ, list)

    return create_space(npts=npts), arima.maq(numpy.array(θ), npts, σ)

def create_arma_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate ARMA(p, q) using specified parameters and the statsmodels.tas simulator.

    Parameters
    ----------
    φ: list[float]
        AR(p) parameters.
    θ: numpy.ndarray[float]
        MA(q) parameters.
    npts: int
        number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        (Time steps, Simulation results.)
    """

    θ = get_param_throw_if_missing("θ", **kwargs)
    φ = get_param_throw_if_missing("φ", **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    verify_type(θ, list)
    verify_type(φ, list)

    return create_space(npts=npts), arima.arma(numpy.array(φ), numpy.array(θ), npts, σ)

def create_arima_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate ARIMA(p,d,q) using specified parameters and the statsmodels.tas simulator arma
    and integrate the result d times to obtain the ARIMA process.

    Parameters
    ----------
    φ: numpy.ndarray[float]
        AR(p) parameters.
    δ: numpy.ndarray[float]
        MA(q) parameters.
    d: int
        Number of integrations to perform (d = 1 or 2).
    npts: int
        Number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        (Time steps, Simulation results.)

    Raises
    ______
    Exception
        d < 1 or d > 2
    """

    θ = get_param_throw_if_missing("θ", **kwargs)
    φ = get_param_throw_if_missing("φ", **kwargs)
    d = get_param_throw_if_missing("d", **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    verify_type(θ, list)
    verify_type(φ, list)

    return create_space(npts=npts), arima.arima(numpy.array(φ), numpy.array(θ), d, npts, σ)

def create_arima_from_arma_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate ARIMA(p,d,q) using the samples from a ARMA(p,q) process
    by integrating d times,.

    Parameters
    ----------
    arma: numpy.ndarray[float]
        ARMA(p,q) processes samples
    d: int
        Number of integrations to perform (d = 1 or 2).

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        (Time steps, Simulation results.)

    Raises
    ______
    Exception
        d < 1 or d > 2
    """

    samples = get_param_throw_if_missing("arma", **kwargs)
    d = get_param_throw_if_missing("d", **kwargs)
    return create_space(npts=len(samples)), arima.arima_from_arma(samples, d)

def compute_ar_estimate(samples: numpy.ndarray[float], **kwargs) -> Tuple[tsa.arima.model.ARIMAResults, ARMAEst]:
    """
    Compute estimates of the AR(p) coefficients assuming the specified order
    for the given samples.

    Parameters
    ----------
    samples : numpy.ndarray[float]
        Samples used for analysis.
    order : int
        Assumed order of sequence used in analysis.
    """

    order = get_param_throw_if_missing("order", **kwargs)
    result = arima.ar_fit(samples, order)
    return result, __arma_estimate_from_result(result, ARMAEstType.AR)

def compute_ar_offset_estimate(samples: numpy.ndarray[float], **kwargs) -> Tuple[tsa.arima.model.ARIMAResults, ARMAEst]:
    """
    Compute estimates of the AR(p) with offset coefficients assuming the specified order
    for the given samples.

    Parameters
    ----------
    samples : numpy.ndarray[float]
        Samples used for analysis.
    order : int
        Assumed order of sequence used in analysis.
    """

    order = get_param_throw_if_missing("order", **kwargs)
    result = arima.ar_offset_fit(samples, order)
    return result, __arma_estimate_from_result(result, ARMAEstType.AR_OFFSET)

def compute_ma_estimate(samples: numpy.ndarray[float], **kwargs) -> Tuple[tsa.arima.model.ARIMAResults, ARMAEst]:
    """
    Compute estimates of the MA(q) coefficients assuming the specified order
    for the given samples.

    Parameters
    ----------
    samples : numpy.ndarray[float]
        Samples used for analysis.
    order : int
        Assumed order of sequence used in analysis.
    """

    order = get_param_throw_if_missing("order", **kwargs)
    result = arima.ma_fit(samples, order)
    return result, __arma_estimate_from_result(result, ARMAEstType.MA)

def compute_ma_offset_estimate(samples: numpy.ndarray[float], **kwargs) -> Tuple[tsa.arima.model.ARIMAResults, ARMAEst]:
    """
    Compute estimates of the MA(q) with offset coefficients assuming the specified order
    for the given samples.

    Parameters
    ----------
    samples : numpy.ndarray[float]
        Samples used for analysis.
    order : int
        Assumed order of sequence used in analysis.
    """

    order = get_param_throw_if_missing("order", **kwargs)
    result = arima.ma_offset_fit(samples, order)
    return result, __arma_estimate_from_result(result, ARMAEstType.MA_OFFSET)

def __arma_estimate_from_result(result: tsa.arima.model.ARIMAResults, arma_est_type) -> ARMAEst:
    """
    Create ARMA(p,q) result object for given result.

    Parameters
    ----------
    result : tsa.arima.model.ARIMAResult
        Samples used for analysis.
    arma_est_type : ARMAEstType
        ARMA estimate type.
    """

    est_id = str(uuid.uuid4())
    nparams = len(result.params)
    params = []

    for i in range(1, nparams-1):
        params.append(ParamEst.from_dict({"est": result.params[i], 
                                          "err": result.bse[i],
                                          "order": i, 
                                          "est_id": est_id,
                                          "param_type": ARMAParamType.ARMA_PARAM.value}))
        
    const = ParamEst.from_dict({"est": result.params[0], 
                                "err": result.bse[0],
                                "est_id": est_id,
                                "param_type": ARMAParamType.ARMA_CONST.value})
    sigma2 = ParamEst.from_dict({"est": result.params[nparams-1], 
                                 "err": result.bse[nparams-1],
                                 "est_id": est_id,
                                 "param_type": ARMAParamType.ARMA_SIG2.value})
    
    return ARMAEst( est_id, const, params, sigma2, arma_est_type)
