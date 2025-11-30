"""
data.models.fbm.py

Simulation and analysis of Fractional brownian motion.
"""

import numpy
from scipy.stats import norm

from lib.models import bm
from lib import stats
from lib.data.reports import VarianceRatioTestReport
from lib.data.hyp_test import HypothesisType, HypothesisTestType

def var(H: float, t: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Fractional brownian motion variance.

    Parameters
    ----------
    H: float
        Hurst parameter.
    t: numpy.ndarray[float]
        Time

    Returns
    -------
    numpy.ndarray[float]
        Variance as a function of time.
    """
    
    return t**(2.0*H)

def cov(H: float, s: float, t: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Fractional brownian motion covariance.

    Parameters
    ----------
    H: float
        Hurst parameter.
    s: float
        Time offset
    t: numpy.ndarray[float]
        Time

    Returns
    -------
    numpy.ndarray[float]
        Variance as a function of time.
    """

    return 0.5*(t**(2.0*H) + s**(2.0*H) - numpy.abs(t - s)**(2.0*H))

def acf(H: float, t: numpy.ndarray[float]) ->  numpy.ndarray[float]:
    """
    Fractional brownian noise autocorrelation function.

    Parameters
    ----------
    H: float
        Hurst parameter.
    t: int
        Time step.

    Returns
    -------
    numpy.ndarray[float]
        Autocorrelation value at time step t.
    """

    return 0.5*(abs(t - 1.0)**(2.0*H) + (t + 1.0)**(2.0*H) - 2.0*t**(2.0*H))

def cholesky_decompose(H: float, n: int):
    """
    Compute Cholesky decomposition of the fractional brownian motion
    autocorrelation matrix

        Parameters
    ----------
    H: float
        Hurst parameter.
    t: int
        Time step.

    Returns
    -------
    float
        Lower diagonal Cholesky decomposition of autocorrelation matrix.
    """
    
    l = numpy.matrix(numpy.zeros([n+1, n+1]))
    for i in range(n+1):
        for j in range(i+1):
            if j == 0 and i == 0:
                l[i,j] = 1.0
            elif j == 0:
                l[i,j] = acf(H, i) / l[0,0]
            elif i == j:
                l[i,j] = numpy.sqrt(l[0,0] - numpy.sum(l[i,0:i]*l[i,0:i].T))
            else:
                l[i,j] = (acf(H, i - j) - numpy.sum(l[i,0:j]*l[j,0:j].T)) / l[j,j]
    return l

def cholesky_noise(H: float, n: int, dB: numpy.ndarray[float]=None, L=None) ->  numpy.ndarray[float]:
    """
    Generate fractional brownian noise using the Cholesky method and the provided 
    parameters.

    Parameters
    ----------
    H: float
        Hurst parameter.
    n: int
        Number of time steps.
    dB: numpy.ndarray[float]
        Column vector of brownian noise.
    L: numpy.matrix[float]
        Lower diagonal Cholesky decomposition of FBM covariance matrix.

    Returns
    -------
    numpy.ndarray[float]
        Fractional brownian noise as a function of time.
    """

    if dB is None:
        dB = bm.noise(n+1)
    if len(dB) != n + 1:
        raise Exception(f"dB should have length {n + 1}")
    dB = numpy.matrix(dB)
    if L is None:
        R = __acf_matrix(H, n)
        L = numpy.linalg.cholesky(R)
    if len(L) != n + 1:
        raise Exception(f"L should have length {n + 1}")
    return numpy.squeeze(numpy.asarray(L*dB.T))

def generate_cholesky(H: float, n: int, dB: numpy.ndarray[float]=None, L=None) ->  numpy.ndarray[float]:
    """
    Generate fractional brownian motion using the Cholesky method and the provided 
    parameters.

    Parameters
    ----------
    H: float
        Hurst parameter.
    n: int
        Number of time steps.
    dB: numpy.ndarray[float]
        Column vector of brownian noise. If value is none the brownian noise is generated.
    L: numpy.matrix[float]
        Lower diagonal Cholesky decomposition of FBM covariance matrix. If value is None
        The Cholesky method is used to compute L from the ACF matrix.

    Returns
    -------
    numpy.ndarray[float]
        Fractional brownian motion as a function of time..
    """

    if dB is None:
        dB = bm.noise(n+1)
    if L is None:
        R = __acf_matrix(H, n)
        L = numpy.linalg.cholesky(R)
    if len(dB) != n + 1:
        raise Exception(f"dB should have length {n + 1}")
    dZ = cholesky_noise(H, n, dB, L)
    Z = numpy.zeros(len(dB))
    for i in range(1, len(dB)):
        Z[i] = Z[i - 1] + dZ[i]
    return Z

def fft_noise(H: float, n: int, dB: numpy.ndarray[float]=None) ->  numpy.ndarray[float]:
    """
    Generate fractional brownian noise using the FFT method and the provided 
    parameters.

    Parameters
    ----------
    H: float
        Hurst parameter.
    n: int
        Number of time steps.
    dB: numpy.ndarray[float]
        Column vector of brownian noise. If value is none the brownian noise is generated.

    Returns
    -------
    numpy.ndarray[float]
        Fractional brownian noise as a function of time.
    """

    if dB is None:
        dB = bm.noise(2*n)
    if len(dB) != 2*n:
        raise Exception(f"dB should have length {2*n}")

    # Compute first row of circulant matrix with embedded autocorrelation
    C = numpy.zeros(2*n)
    for i in range(2*n):
        if i == 0:
            C[i] = 1.0
        if i == n:
            C[i] = 0.0
        elif i < n:
            C[i] = acf(H, i)
        else:
            C[i] = acf(H, 2*n-i)

    # Compute circulant matrix eigen values
    Λ = numpy.fft.fft(C).real
    if numpy.any([l < 0 for l in Λ]):
        raise Exception(f"Eigenvalues are negative")

    # Compute product of Fourier Matrix and Brownian noise
    J = numpy.zeros(2*n, dtype=numpy.cdouble)
    J[0] = numpy.sqrt(Λ[0])*complex(dB[0], 0.0) / numpy.sqrt(2.0 * n)
    J[n] = numpy.sqrt(Λ[n])*complex(dB[n], 0.0) / numpy.sqrt(2.0 * n)

    for i in range(1, n):
        J[i] = numpy.sqrt(Λ[i])*complex(dB[i], dB[n+i]) / numpy.sqrt(4.0 * n)
        J[2*n-i] = numpy.sqrt(Λ[2*n-i])*complex(dB[i], -dB[n+i]) / numpy.sqrt(4.0 * n)

    Z = numpy.fft.fft(J)

    return Z[:n].real

def generate_fft(H: float, n:int, dB: numpy.ndarray[float]=None) ->  numpy.ndarray[float]:
    """
    Generate fractional brownian motion using the FFT method with the provided 
    parameters.

    Parameters
    ----------
    H: float
        Hurst parameter.
    n: int
        Number of time steps.
    dB: numpy.ndarray[float]
        Column vector of brownian noise. If value is None the brownian noise is generated.

    Returns
    -------
    numpy.ndarray[float]
        Fractional brownian motion as a function of time.
    """

    if dB is None:
        dB = bm.noise(2*n)
    if len(dB) != 2*n:
        raise Exception(f"dB should have length {2*n}")
    dZ = fft_noise(H, n, dB=dB)
    Z = numpy.zeros(n)
    for i in range(1, n):
        Z[i] = Z[i - 1] + dZ[i]
    return Z

def vr_homo_test(samples: numpy.ndarray[float], s_vals: list[int]=[4, 6, 10, 16, 24], sig_level: float=0.1, hyp_type: HypothesisType=HypothesisType.TWO_TAIL) -> VarianceRatioTestReport:
    """
    Perform homoscedasticity variance ratio test on given samples using provided parameters.

    Parameters
    ----------
    Samples: numpy.ndarray[float]
        samples to be tested.
    sig_level: float
        Significance level used in test (default 0.1).
    s: list[int]
        Lag values used in analysis (default [4, 6, 10, 16, 24]).
    hyp_type: HypothesisType
        Hypothesis type. (default HypothesisType.TWO_TAIL)
    
    Returns
    -------
    VarianceRatioTestReport
        Test report.
    """

    test_stats = vr_stat_homo_scan(samples, s_vals)
    return __vr_test(test_stats, s_vals, sig_level, hyp_type)

def vr_hetero_test(samples: numpy.ndarray[float], s_vals: list[int]=[4, 6, 10, 16, 24], sig_level: float=0.1, hyp_type: HypothesisType=HypothesisType.TWO_TAIL) -> VarianceRatioTestReport:
    """
    Perform heteroscedasticity variance ratio test on given samples using provided parameters.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Samples to be tested.
    sig_level: float
        Significance level used in test (default 0.1).
    s: list[int]
        Lag values used in analysis (default [4, 6, 10, 16, 24]).
    hyp_type: HypothesisType
        Hypothesis type. (default HypothesisType.TWO_TAIL)
    
    Returns
    -------
    VarianceRatioTestReport
        Test report.
    """

    test_stats = vr_stat_hetero_scan(samples, s_vals)
    return __vr_test(test_stats, s_vals, sig_level, hyp_type)

def __vr_test(test_stats: numpy.ndarray[float], s_vals: list[int]=[4, 6, 10, 16, 24], sig_level: float=0.1, hyp_type: HypothesisType=HypothesisType.TWO_TAIL) -> VarianceRatioTestReport:    
    """
    Perform variance ratio test analysis on provided test statistics using given parameters.

    Parameters
    ----------
    test_stats: numpy.ndarray[float]
        samples to be tested.
    s_vals: list[int]
        Lag values used in analysis (default [4, 6, 10, 16, 24]).
    sig_level: float
        Significance level used in test (default 0.1).
    hyp_type: HypothesisType
        Hypothesis type. (default HypothesisType.TWO_TAIL)
    
    Returns
    -------
    VarianceRatioTestReport
        Test report.
    """

    if hyp_type.value == HypothesisType.TWO_TAIL.value:
        return __var_test_two_tail(test_stats, s_vals, sig_level, hyp_type)
    elif hyp_type.value == HypothesisType.UPPER_TAIL.value:
        return __var_test_upper_tail(test_stats, s_vals, sig_level, hyp_type)
    elif hyp_type.value == HypothesisType.LOWER_TAIL.value:
        return __var_test_lower_tail(test_stats, s_vals, sig_level, hyp_type)
    else:
        raise Exception(f"Hypothesis test type is invalid: {hyp_type}")

def __var_test_two_tail(test_stats: list[float], s_vals: list[int], sig_level: float, hyp_type: HypothesisType) -> VarianceRatioTestReport:
    """
    Perform two tailed variance ratio test analysis on provided test statistics using given parameters.

    Parameters
    ----------
    test_stats: numpy.ndarray[float]
        samples to be tested.
    s_vals: list[int]
        Lag values used in analysis.
    sig_level: float
        Significance level used in test.
    hyp_type: HypothesisType
        Hypothesis type.
    
    Returns
    -------
    VarianceRatioTestReport
        Test report.
    """

    sig_level = sig_level/2.0
    lower_critical_value = norm.ppf(sig_level)
    upper_critical_value = norm.ppf(1.0 - sig_level)
    p_values = [2.0*(1.0 - norm.cdf(numpy.abs(stat))) for stat in test_stats]
    return VarianceRatioTestReport(2.0*sig_level, 
                                   hyp_type,
                                   HypothesisTestType.BM, 
                                   s_vals, 
                                   test_stats,
                                   p_values, 
                                   [lower_critical_value, upper_critical_value])

def __var_test_upper_tail(test_stats: list[float], s_vals: list[int], sig_level: float, hyp_type: HypothesisType) -> VarianceRatioTestReport:
    """
    Perform upper tailed variance ratio test analysis on provided test statistics using given parameters.

    Parameters
    ----------
    test_stats: numpy.ndarray[float]
        samples to be tested.
    s_vals: list[int]
        Lag values used in analysis.
    sig_level: float
        Significance level used in test.
    hyp_type: HypothesisType
        Hypothesis type.
    
    Returns
    -------
    VarianceRatioTestReport
        Test report.
    """

    upper_critical_value = norm.ppf(1.0 - sig_level)
    p_values = [1.0 - norm.cdf(stat) for stat in test_stats]
    return VarianceRatioTestReport(sig_level, 
                                   hyp_type, 
                                   HypothesisTestType.FBM_AUTO_CORR, 
                                   s_vals, 
                                   test_stats, 
                                   p_values,
                                   [None, upper_critical_value])

def __var_test_lower_tail(test_stats: list[float], s_vals: list[int], sig_level: float, hyp_type: HypothesisType) -> VarianceRatioTestReport:
    """
    Perform lower tailed variance ratio test analysis on provided test statistics using given parameters.

    Parameters
    ----------
    test_stats: numpy.ndarray[float]
        samples to be tested.
    s_vals: list[int]
        Lag values used in analysis.
    sig_level: float
        Significance level used in test.
    hyp_type: HypothesisType
        Hypothesis type.
    
    Returns
    -------
    VarianceRatioTestReport
        Test report.
    """

    lower_critical_value = norm.ppf(sig_level)
    p_values = [norm.cdf(stat) for stat in test_stats]
    return VarianceRatioTestReport(sig_level, 
                                   hyp_type, 
                                   HypothesisTestType.FBM_NEG_AUTO_CORR, 
                                   s_vals, 
                                   test_stats, 
                                   p_values, 
                                   [lower_critical_value, None])

def vr_scan(samples: numpy.ndarray[float], s_vals: list[int]) -> numpy.ndarray[float]:
    """
    Compute the variance ratio using the provided samples and the lags.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Test samples.
    s_vals: list[int]
        Lags

    Returns
    -------
    numpy.ndarray[float]
        Variance ratios as a function of lag.
    """

    return numpy.array([__vr(samples, s) for s in s_vals])

def vr_stat_homo_scan(samples: numpy.ndarray[float], s_vals: list[int]) -> numpy.ndarray[float]:
    """
    Compute the variance ratio homoscedastic test statistics using the provided samples and lags.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Test samples.
    s_vals: list[int]
        Lags.

    Returns
    -------
    numpy.ndarray[float]
         Homoscedastic variance ratio test statistics as a function of lag.
    """

    return numpy.array([__vr_stat_homo(samples, s) for s in s_vals])

def vr_stat_hetero_scan(samples: numpy.ndarray[float], s_vals: list[int]) -> numpy.ndarray[float]:
    """
    Compute the variance ratio heteroscedastic test statistics using the provided samples and lags.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Test samples.
    s_vals: list[int]
        Lags.

    Returns
    -------
    numpy.ndarray[float]
        Heteroscedastic variance ratio test statistics as a function of lag.
    """

    return numpy.array([__vr_stat_hetero(samples, s) for s in s_vals])

def __vr_stat_homo(samples: numpy.ndarray[float], s: int) -> float:
    """
    Compute the variance ratio homoscedastic test statistic using the provided samples and lag.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Test samples.
    s: int
        Lag.

    Returns
    -------
    numpy.ndarray[float]
        Homoscedastic variance ratio test statistic.
    """

    if s == 1:
        return 0
    t = len(samples) - 1
    r = __vr(samples, s)
    θ = 2.0*(2.0*s - 1.0)*(s - 1.0)/(3.0*s*t)
    return (r - 1.0)/numpy.sqrt(θ)


def __vr_stat_hetero(samples: numpy.ndarray[float], s: int) -> float:
    """
    Compute the variance ratio heteroscedastic test statistic using the provided samples and lag.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Test samples.
    s: int
        Lag.

    Returns
    -------
    float
        Heteroscedastic variance ratio test statistic.
    """

    r = __vr(samples, s)
    θ = __theta_factor(samples, s)
    return (r - 1.0)/numpy.sqrt(θ)

def __delta_factor(samples: numpy.ndarray[float], j: int) -> float:
    """
    Compute the delta factor used in calculation of the variance ratio heteroscedastic test statistic.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Test samples.
    j: int
        Iteration index.

    Returns
    -------
    float
        Heteroscedastic variance ratio test delta factor.
    """

    t = len(samples) - 1
    μ = (samples[t] - samples[0]) / t
    factor = 0.0
    for i in range(j+1, t):
        f1 = (samples[i] - samples[i-1] - μ)**2
        f2 = (samples[i-j] - samples[i-j-1] - μ)**2
        factor += f1*f2
    return factor / stats.lag_var(samples, 1)**2

def __theta_factor(samples: numpy.ndarray[float], s: int) -> float:
    """
    Compute the delta factor used in calculation of the variance ratio heteroscedastic test statistic.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Test samples.
    s: int
        Lag.

    Returns
    -------
    float
        Heteroscedastic variance ratio test theta factor.
    """

    t = len(samples) - 1
    factor = 0.0
    for j in range(1, s):
        delta = __delta_factor(samples, j)
        factor += delta*(2.0*(s-j)/s)**2
    return factor/t**2

def __vr(samples: numpy.ndarray[float], s: int) -> float:
    """
    Compute the variance ratio using the specified samples and lag.

    
    Parameters
    ----------
    samples: numpy.ndarray[float]
        Test samples.
    s: int
        Lag.

    Returns
    -------
    float
        Variance ratio.
    """

    vars = stats.lag_var(samples, s)
    var1 = stats.lag_var(samples, 1)
    return vars/(s*var1)

def __acf_matrix(H: float, n: int):
    """
    Fractional brownian motion autocorrelation function matrix.

    Parameters
    ----------
    H: float
        Hurst parameter.
    n: int
        maximum number of time steps

    Returns
    -------
    numpy.ndarray[float]
        Autocorrelation as a matrix.
    """

    γ = numpy.matrix(numpy.zeros([n+1, n+1]))
    for i in range(n+1):
        for j in range(n+1):
            if i != j :
                γ[i,j] = acf(H, numpy.abs(i-j))
            else:
                γ[i,j] = 1.0
    return γ

