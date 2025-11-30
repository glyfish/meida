"""
lib.data.impl.ou.py

Simulation and analysis of the Ornstein-Uhlenbeck process.
"""

from typing import Tuple
import numpy
import statsmodels.api as sm

from lib.models import ou
from lib.data.param_est import (ParamEst, OLSResult, OLSTransform, OLSParamType)
from lib.data.impl.stats import OLS

from lib.utils import (get_param_throw_if_missing, get_param_default_if_missing,
                       verify_type, create_space, create_logspace)


def compute_mean(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Mean value of Ornstein-Uhlenbeck process.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δt: float
        Width of time step. (default 1.0)
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    x0: float
        Initial value.

    Returns
    -------
    numpy.ndarray[float]
        Mean as a function of time for given parameters.
    """

    npts = get_param_default_if_missing("npts", 11, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)
    x0 = get_param_default_if_missing("x0", 0.0, **kwargs)

    t = create_space(xmin=0, npts=npts, Δx=Δt)

    return t, ou.mean(μ, λ, t, x0)

def compute_mean_limit(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Limit as t -> infinity of Ornstein-Uhlenbeck process mean value.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δt: float
        Width of time step. (default 1.0)
    μ: float
        Drift coefficient.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time anf mean
    """

    npts = get_param_default_if_missing("npts", 11, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    
    return create_space(xmin=0, npts=npts, Δx=Δt), numpy.full(npts, μ)


def compute_var(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Variance of Ornstein-Uhlenbeck process.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δt: float
        Width of time step. (default 1.0)
    λ: float
        Mean reversion rate.
    σ: float
        Standard deviation of random component.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and variance.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)

    t = create_space(xmin=0, npts=npts, Δx=Δt)

    return t, ou.var(λ, t, σ)

def compute_var_limit(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Limit as t -> infinity of Ornstein-Uhlenbeck process variance.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δt: float
        Width of time step. (default 1.0)
    λ: float
        Mean reversion rate.
    σ: float
        Standard deviation of random component.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and variance.
    """


    npts = get_param_default_if_missing("npts", 10, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)

    return create_space(xmin=0, npts=npts, Δx=Δt), numpy.full(npts, ou.var_limit(λ, σ))

def compute_cov(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Covariance of Ornstein-Uhlenbeck process.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δt: float
        Width of time step. (default 1.0)
    λ: float
        Mean reversion rate.
    s: float
        Time offset.
    σ: float
        Standard deviation of random component.

            Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and covariance.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)
    s = get_param_default_if_missing("s", 1.0, **kwargs)

    xmin = s
    xmax = npts * Δt
    t = create_space(xmin=xmin, xmax=xmax, Δx=Δt)

    return t, ou.cov(λ, s, t, σ)

def compute_cov_limit(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Limit as t -> infinity of Ornstein-Uhlenbeck process variance.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δt: float
        Width of time step. (default 1.0)
    s: float
        Time offset.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and covariance limit.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    s = get_param_default_if_missing("s", 1.0, **kwargs)

    xmin = int(s/Δt)
    t = create_space(xmin=xmin, npts=npts, Δx=Δt)

    return t, numpy.full(npts, 0.0)

def compute_pdf(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Ornstein-Uhlenbeck process PDF for a specified time.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δx: float
        Width of variable increment. (default 1.0)
    xmin: float
        Minimum value of modeled variable. (default 0.0)
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
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Modeled variable and PDF.
    """

    t = get_param_throw_if_missing("t", **kwargs)
    npts = get_param_default_if_missing("npts", 10, **kwargs)
    xmax = get_param_default_if_missing("xmax", 5.0, **kwargs)
    xmin = get_param_default_if_missing("xmin", -5.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    x0 = get_param_default_if_missing("x0", 0.0, **kwargs)

    x = create_space(xmin=xmin, xmax=xmax, npts=npts)

    return x, ou.pdf(x, μ, λ, t, σ=σ, x0=x0)

def compute_cdf(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Ornstein-Uhlenbeck process CDF for a specified time.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δx: float
        Width of variable increment. (default 1.0)
    xmin: float
        Minimum value of modeled variable. (default 0.0)
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
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Modeled variable and CDF.
    """

    t = get_param_throw_if_missing("t", **kwargs)
    npts = get_param_default_if_missing("npts", 10, **kwargs)
    xmax = get_param_default_if_missing("xmax", 5.0, **kwargs)
    xmin = get_param_default_if_missing("xmin", -5.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    x0 = get_param_default_if_missing("x0", 0.0, **kwargs)
    
    x = create_space(xmin=xmin, xmax=xmax, npts=npts)

    return x, ou.cdf(x, μ, λ, t, σ=σ, x0=x0)

def compute_pdf_limit(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
     Limit as t -> infinity of Ornstein-Uhlenbeck process PDF.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δx: float
        Width of variable increment. (default 1.0)
    xmin: float
        Minimum value of modeled variable. (default 0.0)
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    σ: float
        Standard deviation of random component.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]] 
        Modeled variable and PDF limit.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    xmax = get_param_default_if_missing("xmax", 5.0, **kwargs)
    xmin = get_param_default_if_missing("xmin", -5.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)

    x = create_space(xmin=xmin, xmax=xmax, npts=npts)

    return x, ou.pdf_limit(x, μ, λ, σ=σ)

def compute_cdf_limit(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Ornstein-Uhlenbeck process CDF for t -> infinity.

    Parameters
    ----------
    npts: int
        Number of points. (default 11)
    Δx: float
        Width of variable increment. (default 1.0)
    xmin: float
        Minimum value of modeled variable. (default 0.0)
    μ: float
        Drift coefficient.
    λ: float
        Mean reversion rate.
    σ: float
        Standard deviation of random component.

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]] 
        Modeled variable and PDF limit.
    """

    npts = get_param_default_if_missing("npts", 10, **kwargs)
    xmax = get_param_default_if_missing("xmax", 5.0, **kwargs)
    xmin = get_param_default_if_missing("xmin", -5.0, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    x0 = get_param_default_if_missing("x0", 0.0, **kwargs)

    x = create_space(xmin=xmin, xmax=xmax, npts=npts)

    return x, ou.cdf_limit(x, μ, λ, σ=σ, x0=x0)

def compute_mean_half_life(**kwargs) -> float:
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

    λ = get_param_default_if_missing("λ", 1.0, **kwargs)

    return ou.mean_halflife(λ)


def compute_mean_half_life_estimate(xt: numpy.ndarray[float], dt: float=1.0) -> Tuple[sm.regression.linear_model.RegressionResults, OLSResult]:
    """
    Estimate Ornstein-Uhlenbeck half life to limiting mean.

    Parameters
    ----------
    xt: numpy.ndarray[float]
        Modeled variable.

    Returns
    -------
    Tuple[sm.regression.linear_model.RegressionResults, OLSResult]
        OLS analysis results.
    """

    dxt = numpy.diff(xt)
    x_lagged = xt[:-1]

    report, result = OLS.LINEAR.single_variable_estimate(dxt, x_lagged)
    __half_life_transform(result, dt)
    return report, result

def create_xt_source(**kwargs) -> numpy.ndarray[float]:
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

    t = get_param_throw_if_missing("t", **kwargs)
    npts = get_param_default_if_missing("npts", 10, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    x0 = get_param_default_if_missing("x0", 0.0, **kwargs)
    
    return ou.xt(μ, λ, t, σ, x0, npts)

def create_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
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

    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    npts = get_param_default_if_missing("npts", 10, **kwargs)
    μ = get_param_default_if_missing("μ", 0.0, **kwargs)
    λ = get_param_default_if_missing("λ", 1.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    x0 = get_param_default_if_missing("x0", 0.0, **kwargs)

    t = create_space(xmin=0, npts=npts, Δx=Δt)

    return t, ou.ou(μ, λ, Δt, npts, σ, x0)


def __half_life_transform(result: OLSResult, dt: float):
    """
    Add transformation used for half life OLS analysis.

    Parameters
    ----------
    result: OLSResult
        OLS analysis results.
    """

    model = r"$\Delta X_t = \lambda X_{t-1} \Delta t + \mu \Delta t + \sqrt{\Delta t} \varepsilon_t$"
    λ = result.params[0].est / dt
    half_life_param = ParamEst(est_id=result.est_id,
                               est=-numpy.log(2.0) / λ,
                               err=(numpy.log(2.0) / λ**2) * (result.params[0].err / dt),
                               est_label=r"$t_{1/2}$",
                               err_label=r"$\sigma_{t_H}$",
                               order=1,
                               row=0,
                               column=0,
                               param_type=OLSParamType.TRANS_PARAM.value)

    lambda_param = ParamEst(est_id=result.est_id,
                            est=λ,
                            err=result.params[0].err / dt,
                            est_label=r"$\lambda$",
                            err_label=r"$\sigma_\lambda$",
                            order=1,
                            row=1,
                            column=0,
                            param_type=OLSParamType.TRANS_PARAM.value)

    const = ParamEst(est_id=result.est_id,
                     est=result.const.est,
                     err=result.const.err,
                     est_label=r"$\mu$",
                     err_label=r"$\sigma_{\mu}$",
                     order=1,
                     row=0,
                     column=0,
                     param_type=OLSParamType.TRANS_CONST.value)    
    
    result.set_transforms(model, [OLSTransform(half_life_param), OLSTransform(lambda_param)], OLSTransform(const))

