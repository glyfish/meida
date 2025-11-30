import numpy
from typing import Tuple
import uuid

from statsmodels.tsa.vector_ar.var_model import LagOrderResults
from statsmodels.tsa.vector_ar.vecm import JohansenTestResult, VECMResults

from lib.models import vecm
from lib.utils import get_param_throw_if_missing, get_param_default_if_missing, verify_type, create_space
from lib.data.hyp_test import VAROrderTestReport, __var_order_test_report_from_result
from lib.data.hyp_test import JohansenCointTestReport, JohansenCointTestStatistic, JohansenCointTestRank, JohansenCointTestEigenVector
from lib.data.reports import JohansenTestReport
from lib.data.param_est import VECMEst, ParamEst, VECMParamType

def compute_estimate(samples: numpy.ndarray[float, float], **kwargs) -> Tuple[VECMResults, VECMEst]:
    """
    Estimate the parameters for and assumed VECM(n) model.

    Parameters
    ----------
    endog: DataFrame
        VAR(n) process endogenous variable samples.
    maxlags: int
        Maximum number of time lags tried. (default is 12)
     rank: int
        Cointegration rank.
    trend: str
        "n" - no deterministic terms
        "co" - constant outside the cointegration relation
        "ci" - constant within the cointegration relation
        "lo" - linear trend outside the cointegration relation
        "li" - linear trend within the cointegration relation

    Returns
    -------
    VECMResults
        Analysis results.
    """
    
    maxlags = get_param_default_if_missing("maxlags", '12', **kwargs)
    trend = get_param_default_if_missing("trend", 'co', **kwargs)
    rank = get_param_default_if_missing("rank", 1, **kwargs)

    result = vecm.fit(samples.T, maxlags=maxlags, trend=trend, rank=rank)

    return result, __vecm_estimate_from_result(result)

def compute_order(samples: numpy.ndarray[float, float], **kwargs) -> Tuple[LagOrderResults, VAROrderTestReport]:
    """
    Determine the order of a VAR process using the AIC criterion.

    Parameters
    ----------
    samples: numpy.ndarray[float, float]
        Samples analyzed.    
    maxlags: int
        Maximum number of lags.
    trend: str
        "n" - no deterministic terms
        "co" - constant outside the cointegration relation
        "ci" - constant within the cointegration relation
        "lo" - linear trend outside the cointegration relation
        "li" - linear trend within the cointegration relation

    Returns
    -------
    LagOrderResults
        Order results.
    """

    maxlags = get_param_default_if_missing("maxlags", 12, **kwargs)
    trend = get_param_default_if_missing("trend", 'co', **kwargs)

    result = vecm.order_estimate(samples.T, maxlags, trend)
    return result, __var_order_test_report_from_result(result)


def compute_johansen_coint_test(samples: numpy.ndarray[float, float], max_lags: int, **kwargs) -> Tuple[JohansenTestReport, JohansenCointTestReport, JohansenTestResult]:
    """
    Compute the Johansen cointegration test.

    Parameters
    ----------
    samples: numpy.ndarray[float, float]
        Samples analyzed.
    max_lags: int
        maximum number of lags.
    trend: int
        Trend to include in cointegration test.
            -1 - no trend
             0 - constant
             1 - linear trend.
        default is no trend.

    Returns
    -------
    numpy.ndarray[float, float]
        Eigenvalues.
    numpy.ndarray[float, float]
        Eigenvectors.
    numpy.ndarray[float, float]
        Trace statistic.
    """

    trend = get_param_default_if_missing("trend", 0, **kwargs)
    result = vecm.johansen_test_coint(samples.T, max_lags, trend)

    return JohansenTestReport(result), __vecm_johansen_coint_test_report_from_result(result), result


def compute_prediction(vecm_result: VECMResults, steps: int, **kwargs) -> Tuple[numpy.ndarray[float, float], numpy.ndarray[float, float], numpy.ndarray[float, float]]:
    """
    Predict values for the specified number of steps.

    Parameters
    ----------
    vecm_result: VECMResults
        VECM model.
    steps: int
        Number of steps to predict.
    alpha: float
        Confidence interval (default 0.5).

    Returns
    -------
    Tuple[numpy.ndarray[float, float], numpy.ndarray[float, float], numpy.ndarray[float, float]]
        Predicted values.
    """

    alpha = get_param_default_if_missing("alpha", 0.05, **kwargs)
    return vecm_result.predict(steps, alpha=alpha)


def create_vecm1_source(λ: numpy.ndarray[float, float], β: numpy.ndarray[float, float], a: numpy.ndarray[float, float], **kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float, float]]:
    """
    Simulate a first order Vector Error Correction Model (VECM) process with the specified parameters.

    Parameters
    ----------
    λ: numpy.ndarray[float, float]
        Damping matrix.
    β: numpy.ndarray[float, float]
        Transpose of cointegration vector.
    a: numpy.ndarray[float, float]
        Coefficient matrix.
    Ω: numpy.ndarray[float, float]
        Noise covariance matrix. (default identity matrix)
    npts: int
        Number of samples generated (default 1000).

    Returns
    -------
    numpy.ndarray[float, float]
        Simulation results.
    """

    n, _ = a.shape
    Ω_default = numpy.matrix(numpy.eye(n))
    Ω = get_param_default_if_missing("Ω", Ω_default, **kwargs)
    npts = get_param_default_if_missing("npts", 1000, **kwargs)

    return create_space(npts=npts), numpy.array(vecm.vecm1(λ, β, a, Ω, npts))


def create_vecm_source(λ: numpy.ndarray[float, float], β: numpy.ndarray[float, float], a: numpy.ndarray[float, float], **kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float, float]]:
    """
    Simulate a first order Vector Error Correction Model (VECM) process with the specified parameters.

    Parameters
    ----------
    λ: numpy.ndarray[float, float]
        Damping matrix.
    β: numpy.ndarray[float, float]
        Transpose of cointegration vector.
    a: numpy.ndarray[float, float, float]
        Coefficient matrix.
    Ω: numpy.ndarray[float, float]
        Noise covariance matrix. (default identity matrix)
    npts: int
        Number of samples generated (default 1000).

    Returns
    -------
    numpy.ndarray[float, float]
        Simulation results.
    """

    _, n, _ = a.shape
    Ω_default = numpy.matrix(numpy.eye(n))
    Ω = get_param_default_if_missing("Ω", Ω_default, **kwargs)
    npts = get_param_default_if_missing("npts", 1000, **kwargs)

    return create_space(npts=npts), numpy.array(vecm.vecm(λ, β, a, Ω, npts))


def __vecm_johansen_coint_test_report_from_result(result: JohansenTestResult) -> JohansenCointTestReport:
    """
    Create a Johansen test report from a Johansen test result.

    Parameters
    ----------
    result: JohansenTestResult
        Johansen test result.

    Returns
    -------
    JohansenTestReport
        Johansen test report.
    """

    eigen_values = result.eig
    eigen_vectors = result.evec
    trace_critical_vals = result.cvt
    trace_statistic = result.lr1
    eigen_value_critical_values = result.cvm
    eigen_value_statistic = result.lr2

    def compute_rank():
        test_result = []
        n = len(trace_statistic)
        for i in range(n):
            test_result.append(trace_statistic[i] > trace_critical_vals[i])
        test_result = numpy.array(test_result)               
        return [len(test_result[:,i][test_result[:,i]]) for i in range(n)]

    ranks = compute_rank()
    n = len(eigen_values)
    test_id = str(uuid.uuid4())

    trace_statistic_report = [JohansenCointTestStatistic(test_id, i, trace_statistic[i], trace_critical_vals[i]) for i in range(n)]
    eigen_value_statistic_report = [JohansenCointTestStatistic(test_id, i, eigen_value_statistic[i], eigen_value_critical_values[i]) for i in range(n)]
    rank_report = JohansenCointTestRank(test_id, ranks)
    eigen_value_report = [JohansenCointTestEigenVector(test_id, eigen_values[i], eigen_vectors[i]) for i in range(n)]

    return JohansenCointTestReport(test_id, trace_statistic_report, eigen_value_statistic_report, rank_report, eigen_value_report)


def __vecm_estimate_from_result(result: VECMResults) -> VECMResults:
    rank = result.coint_rank
    order = result.k_ar - 1
    neq, _ = result.alpha.shape

    const_est = result.det_coef
    const_err = result.stderr_det_coef
    a_est = result.gamma
    a_err = result.stderr_gamma
    beta_est = result.beta
    beta_err = result.stderr_beta
    lambda_est = result.alpha
    lambda_err = result.stderr_alpha
    omega_est = result.sigma_u

    est_id = str(uuid.uuid4())
    lambda_result = []
    beta_result = []
    omega_result = []
    const_result = []
    a_result = []

    for j in range(rank):
        for i in range(neq):
            lambda_result.append(ParamEst(est_id=est_id, 
                                 est=lambda_est[i,j], 
                                 err=lambda_err[i,j], 
                                 est_label=f"$\\hat{{\\lambda}}$", 
                                 err_label=f"$\\sigma_{{\\lambda}}$", 
                                 order=0,
                                 row=i,
                                 column=j,                     
                                 param_type=VECMParamType.VECM_LAMBDA.value))
            beta_result.append(ParamEst(est_id=est_id, 
                               est=beta_est[i,j], 
                               err=beta_err[i,j], 
                               est_label=f"$\\hat{{\\beta}}$", 
                               err_label=f"$\\sigma_{{\\beta}}$", 
                               order=0,
                               row=i,
                               column=j,                     
                               param_type=VECMParamType.VECM_BETA.value))
            
    for i in range(neq):
        const_result.append(ParamEst(est_id=est_id, 
                            est=const_est[i,0], 
                            err=const_err[i,0], 
                            est_label=f"$\\hat{{M}}$", 
                            err_label=f"$\\sigma_{{M}}$", 
                            order=0,
                            row=i,
                            column=0,                     
                            param_type=VECMParamType.VECM_CONST.value))
            
    
            
    for i in range(neq):
        for j in range(neq):
            omega_result.append(ParamEst(est_id=est_id, 
                                est=omega_est[i,j],
                                err=0.0,
                                est_label=f"$\\hat{{\\Omega}}$", 
                                err_label=f"$\\sigma_{{\\Omega}}$", 
                                order=0,
                                row=i,
                                column=j,
                                param_type=VECMParamType.VECM_OMEGA.value))

    for k in range(order):
        for j in range(neq):
            for i in range(neq):
                a_result.append(ParamEst(est_id=est_id, 
                                         est=a_est[i,j], 
                                         err=a_err[i,j],
                                         est_label=f"$\\hat{{A}}$", 
                                         err_label=f"$\\sigma_A$", 
                                         order=k + 1,
                                         row=i,
                                         column=j,
                                         param_type=VECMParamType.VECM_ALPHA.value))

    return VECMEst(rank=rank, order=order, const=const_result, lambda_est=lambda_result, beta_est=beta_result, a_est=a_result, omega=omega_result)
