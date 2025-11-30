"""
data.models.adf.py

Simulation of Dickey-Fuller distribution
"""

import numpy
from lib.data.reports import ADFTestReport
import statsmodels.api as sm

def scaled_brownian_noise(n: int) -> numpy.ndarray[float]:
    """
    Simulate scaled Brownian noise. Scaled Brownian noise has mean of zero and
    variance given by sqrt(1.0/n) where n is the number of simulated values.

    Parameters
    ----------
    n: int
        Number of simulated values.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    return numpy.random.normal(0.0, 1.0/numpy.sqrt(n), n)

def brownian_motion(bn: numpy.ndarray, t: int) -> float:
    """
    Compute Brownian motion at time step t from Brownian noise by
    integrating up to time step t.

    Parameters
    ----------
    bn: numpy.ndarray
        Brownian noise.
    t: int
        
    """

    return sum(bn[:t])

def modified_chi_squared(x: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Compute the PDF of the modified chi-squared distribution using the
    specified values.

    Parameters
    ----------
    x: numpy.ndarray
        Array of random variables.

    Returns
    -------
    numpy.ndarray[float]
        Computed modified chi-squared distribution PDF.
    """

    return 2.0*numpy.exp(-(2.0*x+1.0)/2.0) / numpy.sqrt(2.0*numpy.pi*(2.0*x+1.0))

def stochastic_integral_ensemble_1(n: int, nsample: int) -> numpy.ndarray[float]:
    """
    Simulate the stochastic integral $\int_0^1{B(s)dB(s)}$ ensemble

    Parameters
    ----------
    n: int
        Number of steps in the integral.
    nsample: int
        Number of simulations in ensemble.

    Returns
    -------
    numpy.ndarray[float]
        Simulation ensemble.
    """

    vals = numpy.zeros(nsample)
    for i in range(nsample):
        vals[i] = stochastic_integral_simulation_1(scaled_brownian_noise(n))
    return vals

def stochastic_integral_simulation_1(bn: numpy.ndarray[float]) -> float:
    """
    Simulate a stochastic integral $\int_0^1{B(s)dB(s)}$ using the input brownian noise.

    Parameters
    ----------
    bn: numpy.ndarray[float]
        Scaled brownian noise.

    Returns
    -------
    float
        Simulation result of stochastic integral.
    """

    n = len(bn)
    val = 0.0
    for i in range(1, n):
        val += brownian_motion(bn, i-1)*bn[i]
    return val

def stochastic_integral_solution_1(n: int) -> numpy.ndarray[float]:
    """
    Simulation of the random process defined by \frac{1}{2}[B^2(1) - 1].

    Parameters
    ----------
    n: int
        Number of values simulated.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    return 0.5*(numpy.random.normal(0.0, 1.0, n)**2 - 1.0)

def stochastic_integral_ensemble_2(n: int, nsample: int) -> numpy.ndarray[float]:
    """
    Simulation of stochastic integral \int_0^1{B^2(s)ds} ensemble.

    Parameters
    ----------
    n: int
        Number of values simulated in stochastic integral.

    nsample: int
        Number od samples in ensemble.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    vals = numpy.zeros(nsample)
    for i in range(nsample):
        vals[i] = stochastic_integral_simulation_2(scaled_brownian_noise(n))
    return vals

def stochastic_integral_simulation_2(bn: numpy.ndarray[float]) -> float:
    """
    Simulation of stochastic integral \int_0^1{B^2(s)ds} using the input brownian noise.

    Parameters
    ----------
    bn: numpy.ndarray[float]
        Scaled brownian noise.

    Returns
    -------
    float
        Simulation result of stochastic integral.
    """

    n = len(bn)
    val = 0.0
    for i in range(1, n+1):
        val += brownian_motion(bn, i-1)**2
    return val/n

def stochastic_integral_ensemble_3(n: int, nsample: int) -> numpy.ndarray[float]:
    """
    Simulation of stochastic integral sqrt{\int_0^1{B^2(s)ds}} ensemble.

    Parameters
    ----------
    n: int
        Number of values simulated in stochastic integral.

    nsample: int
        Number od samples in ensemble.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    vals = numpy.zeros(nsample)
    for i in range(nsample):
        vals[i] = stochastic_integral_simulation_3(scaled_brownian_noise(n))
    return vals

def stochastic_integral_simulation_3(bn: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Simulation of stochastic integral sqrt{\int_0^1{B^2(s)ds}} using the input brownian noise.

    Parameters
    ----------
    bn: numpy.ndarray[float]
        Scaled brownian noise.

    Returns
    -------
    float
        Simulation result of stochastic integral.
    """

    n = len(bn)
    val = 0.0
    for i in range(1, n+1):
        val += brownian_motion(bn, i-1)**2
    return numpy.sqrt(val/n)

def dist_ensemble(n: int, nsim: int) -> numpy.ndarray[float]:
    """
    Simulation of the Dickey-Fuller test statistic \frac{\frac{1}{2}[B^2(1) - 1]}{\sqrt{\int_0^1{B^2(s)ds}}
    ensemble.

    Parameters
    ----------
    n: int
        Number of values in integral simulations.
    nsim: int
        Number of simulations in ensemble.

    Returns
    -------
    numpy.ndarray[float]
        Simulation ensemble.
    """

    vals = numpy.zeros(nsim)
    numerator = stochastic_integral_solution_1(nsim)
    for i in range(nsim):
        vals[i] = numerator[i] / stochastic_integral_simulation_3(scaled_brownian_noise(n))
    return vals

def statistic(samples: numpy.ndarray[float], σ: float=1.0) -> float:
    """
    Compute the Dickey-Duller test statistic from the given samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Samples used to compute test statistic.

    Returns
    -------
    float
        Test statistic.
    """

    nsample = len(samples)
    delta_numerator = 0.0
    var = 0.0
    for i in range(1, nsample):
        delta = samples[i] - samples[i-1]
        delta_numerator += samples[i-1] * delta
        var += samples[i-1]**2
    return delta_numerator / (numpy.sqrt(var)*σ**2)

def adf_test(samples: numpy.ndarray[float], max_lag: int=12) -> ADFTestReport:
    """
    Perform the ADF test assuming no trend on the specified samples. If the ADF
    test passes the samples are brownian motion.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    max_lag : {None, int}
        Maximum lag which is included in test, default value of
        12*(nobs/100)^{1/4} is used when ``None``.

    Returns
    -------
    ADFTestReport
        Result of the performed ADF test.
    """

    return __adfuller_test(samples, 'n', max_lag)

def adf_test_offset(samples: numpy.ndarray[float], max_lag: int=12) -> ADFTestReport:
    """
    Perform the ADF test assuming a constant offset in the samples. If the ADF
    test passes the samples are brownian motion.
    
    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    max_lag : {None, int}
        Maximum lag which is included in test, default value of
        12*(nobs/100)^{1/4} is used when ``None``.

    Returns
    -------
    ADFTestReport
        Result of the performed ADF test.
    """

    return __adfuller_test(samples, 'c', max_lag)

def adf_test_drift(samples: numpy.ndarray[float], max_lag: int=12) -> ADFTestReport:
    """
    Perform the ADF test assuming a linear drift terms. If the ADF
    test passes the samples are brownian motion.
    
    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    max_lag : {None, int}
        Maximum lag which is included in test, default value of
        12*(nobs/100)^{1/4} is used when ``None``.

    Returns
    -------
    ADFTestReport
        Result of the performed ADF test.
    """

    return __adfuller_test(samples, 'ct', max_lag)

def __adfuller_test(samples: numpy.ndarray[float], test_type: str, max_lag: int=12) -> ADFTestReport:
    """
    Perform the ADF test assuming no trend on the specified samples. If the ADF
    test passes the samples are brownian motion.
    
    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    test_type : {"c","ct","ctt","n"}
        Constant and trend order to include in regression.

        * "c" : constant only (default).
        * "ct" : constant and trend.
        * "ctt" : constant, and linear and quadratic trend.
        * "n" : no constant, no trend.
    max_lag : {None, int}
        Maximum lag which is included in test, default value of
        12*(nobs/100)^{1/4} is used when ``None``.


    Returns
    -------
    ADFTestReport
        Result of the performed ADF test.
    """

    result = sm.tsa.stattools.adfuller(samples, regression=test_type, maxlag=max_lag)
    return ADFTestReport(result)