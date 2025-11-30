"""
data.impl.ecm.py

Interface to models.ecm.py
"""

import numpy

from lib.models import ecm
import statsmodels.tsa as tsa
from typing import Tuple
import statsmodels.api as sm
import uuid

from lib.data.param_est import (ParamEst, OLSResult, OLSTransform, OLSParamType)
from lib.utils import (get_param_throw_if_missing, get_param_default_if_missing,
                       verify_type, create_space)
from lib.data.impl.stats import OLS
from lib.stats import diff


def compute_xt_mean(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the ARIMA process mean value.

    Parameters
    ----------
    npts: int
        Number of points to evaluate
    Δt: float
        Width of time step. (default 1.0)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    npts = get_param_throw_if_missing("npts", **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)

    return create_space(xmax=npts - 1, npts=npts, Δx=Δt), numpy.full(npts, 0.0)


def compute_yt_mean(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the ECM process mean value.

    Parameters
    ----------
    npts: int
        Number of points to evaluate
    Δt: float
        Width of time step. (default 1.0)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    npts = get_param_throw_if_missing("npts", **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)

    return create_space(xmax=npts - 1, npts=npts, Δx=Δt), numpy.full(npts, 0.0)


def compute_xt_var(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the ARIMA process variance value.

    Parameters
    ----------
    φ: float
        AR(1) parameter satisfying |φ| < 1.
    σ: float
        Residual variance.
    tmax: int
        Maximum time. (default None)
    Δt: float
        Width of time step. (default 1.0)
    npts: int
        Number of points to evaluate

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    tmax = get_param_default_if_missing("tmax", None, **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)

    t_vals = create_space(xmin=0, npts=npts, xmax=tmax, Δx=Δt)
    return t_vals, ecm.xt_var(φ, σ, t_vals)


def compute_yt_var(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the ECM process variance value.

    Parameters
    ----------
    φ: float
        AR(1) parameter satisfying |φ| < 1.
    β: float
        ECM correlation parameter.
    σ: float
        Residual variance.
    tmax: int
        Maximum time. (default None)
    Δt: float
        Width of time step. (default 1.0)
    npts: int
        Number of points to evaluate

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    β = get_param_throw_if_missing("β", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    tmax = get_param_default_if_missing("tmax", None, **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)

    t_vals = create_space(xmin=0, npts=npts, xmax=tmax, Δx=Δt)
    return t_vals, ecm.yt_var(φ, σ, β, t_vals)


def compute_cov(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Compute the ECM process variance value.

    Parameters
    ----------
    φ: float
        AR(1) parameter satisfying |φ| < 1.
    σ: float
        Residual variance.
    β: float
        ECM correlation parameter.
    npts: int
        Number of points to evaluate

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Time and mean value.
    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    β = get_param_throw_if_missing("β", **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    Δt = get_param_default_if_missing("Δt", 1.0, **kwargs)
    tmax = get_param_default_if_missing("tmax", None, **kwargs)
    npts = get_param_throw_if_missing("npts", **kwargs)

    t_vals = create_space(xmin=0, npts=npts, xmax=tmax, Δx=Δt)
    return t_vals, ecm.cov(φ, σ, β, t_vals)


def compute_beta_estimate(yt: numpy.ndarray[float], xt: numpy.ndarray[float]) -> Tuple[sm.regression.linear_model.RegressionResults, OLSResult]:
    """
    Compute OLS estimate of ECM β parameter.

    Parameters
    ----------
    xt: numpy.ndarray[float]
        ECM variable.
    yt: numpy.ndarray[float]
        ECM variable.

    Returns
    -------
    Tuple[sm.regression.linear_model.RegressionResults, OLSResult]
        Ols report and result model.
    """

    report, result = OLS.LINEAR.single_variable_estimate(yt, xt)
    __add_beta_transform(result)
    return report, result


def compute_gamma_lambda_estimate(yt: numpy.ndarray[float], xt: numpy.ndarray[float], est_beta: float) -> Tuple[sm.regression.linear_model.RegressionResults, OLSResult]:
    """
    Compute OLS estimate of ECM β parameter.

    Parameters
    ----------
    xt: numpy.ndarray[float]
        ECM variable.
    yt: numpy.ndarray[float]
        ECM variable.
    est_beta: float
        Estimated beta.

    Returns
    -------
    Tuple[sm.regression.linear_model.RegressionResults, OLSResult]
        Ols report and result model.
    """

    εt = yt - est_beta * xt
    dxt = diff(xt)
    dyt = diff(yt)

    report, result = OLS.LINEAR.two_variable_estimate(dyt, dxt, εt[:-1])
    __add_gamma_lambda_transform(result)
    return report, result


def create_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float, float]]:
    """
    Generate an ECM time series from an AR(1) process using the specified parameters.

    Parameters
    ----------
    φ: float
        AR(1) parameter satisfying |φ| < 1.
    δ: float
        ECM term parameter. (default 0.0)
    α: float
        ECM term offset parameter. (default 0.0)
    β: float
        ECM correlation parameter.
    γ: float
        ECM X(t) scale parameter.
    λ: float
        ECM relaxation rate.
    σ: float
        Residual variance. (default 1.0)
    npts: int
        Number of samples generated. (default 1000)

    Returns
    -------
    Tuple[numpy.ndarray[float], numpy.ndarray[float]]
        Generated x(t) and y(t) ECM time series.
    """

    φ = get_param_throw_if_missing("φ", **kwargs)
    β = get_param_throw_if_missing("β", **kwargs)
    γ = get_param_throw_if_missing("γ", **kwargs)
    λ = get_param_throw_if_missing("λ", **kwargs)
    δ = get_param_default_if_missing("δ", 0.0, **kwargs)
    α = get_param_default_if_missing("α", 0.0, **kwargs)
    σ = get_param_default_if_missing("σ", 1.0, **kwargs)
    npts = get_param_default_if_missing("npts", 1000, **kwargs)

    xt, yt = ecm.ecm(φ, δ, α, β, γ, λ, npts, σ)

    return create_space(xmax=npts - 1, npts=npts), numpy.array([xt, yt])


def __add_beta_transform(result: OLSResult):
    """
    Add transformation OLS beta parameter estimate.

    Parameters
    ----------
    result: OLSResult
        OLS analysis results.
    """

    model = r"$\hat{\alpha} + \hat{\beta} x_t$"

    param = ParamEst(est_id=result.est_id,
                     est=result.params[0].est,
                     err=result.params[0].err,
                     est_label=r"$\hat{\beta}$",
                     err_label=r"$\sigma_{\hat{\beta}}$",
                     order=1,
                     row=0,
                     column=0,
                     param_type=OLSParamType.TRANS_PARAM.value)

    const = ParamEst(est_id=result.est_id,
                     est=result.const.est,
                     err=result.const.err,
                     est_label=r"$\hat{\alpha}$",
                     err_label=r"$\sigma_{\hat{\alpha}}$",
                     order=1,
                     row=0,
                     column=0,
                     param_type=OLSParamType.TRANS_CONST.value)
    
    result.set_transforms(model, [OLSTransform(param)], OLSTransform(const))


def __add_gamma_lambda_transform(result: OLSResult):
    """
    Add transformation OLS beta parameter estimate.

    Parameters
    ----------
    result: OLSResult
        OLS analysis results.
    """

    model = r"$\hat{\alpha} + \hat{\beta} x_t$"

    param1 = ParamEst(est_id=result.est_id,
                      est=result.params[0].est,
                      err=result.params[0].err,
                      est_label=r"$\hat{\gamma}$",
                      err_label=r"$\sigma_{\hat{\gamma}}$",
                      order=1,
                      row=0,
                      column=0,
                      param_type=OLSParamType.TRANS_PARAM.value)

    param2 = ParamEst(est_id=result.est_id,
                      est=result.params[0].est,
                      err=result.params[0].err,
                      est_label=r"$\hat{\lambda}$",
                      err_label=r"$\sigma_{\hat{\lambda}}$",
                      order=1,
                      row=0,
                      column=0,
                      param_type=OLSParamType.TRANS_PARAM.value)

    const = ParamEst(est_id=result.est_id,
                     est=result.const.est,
                     err=result.const.err,
                     est_label=r"$\hat{\lambda}$",
                     err_label=r"$\sigma_{\hat{\lambda}}$",
                     order=1,
                     row=0,
                     column=0,
                     param_type=OLSParamType.TRANS_CONST.value)
    
    result.set_transforms(model, [OLSTransform(param1), OLSTransform(param2)], OLSTransform(const))
