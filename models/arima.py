"""
data.models.arima.py

Simulations and analysis of ARIMA(p,d,q) random process.
"""

import numpy
import statsmodels.api as sm
import statsmodels.tsa as tsa

def maq_sigma(θ: list[float], σ: float=1) -> float:
    """
    Compute MA(q) standard deviation.

    Parameters
    ----------
    θ: list[float]
        List of MA(q) coefficients.
    σ: float
        Standard deviation of noise term.
    
    Returns
    -------
    float
        Standard deviation.
    """

    v = 0
    for u in θ:
        v += u**2
    return σ * numpy.sqrt(v + 1)

def maq_cov(θ: list[float], σ: float=1) -> numpy.ndarray[float]:
    """
    Compute MA(q) auto covariance.

    Parameters
    ----------
    θ: list[float]
        List of MA(q) coefficients.
    σ: float
        Standard deviation of noise term.
    
    Returns
    -------
    numpy.ndarray[float]
        Autocovariance.
    """

    q = len(θ)
    c = numpy.zeros(q)
    s = numpy.zeros(q)
    for n in range(1,q):
        for i in range(q-n):
            c[n] += θ[i]*θ[i+n]
    for n in range(q):
        s[n] = θ[n]
    return σ**2 * (c + s)

def maq_acf(θ: list[float], σ: float=1, max_lag: float=15) -> numpy.ndarray[float]:
    """
    Compute MA(q) auto correlation function.

    Parameters
    ----------
    θ: list[float]
        List of MA(q) coefficients.
    σ: float
        Standard deviation of noise term.
    max_lag: float
        Maximum lag setting time lag limit used in calculation.
    
    Returns
    -------
    numpy.ndarray[float]
        Autocorrelation function.
    """

    ac = maq_cov(θ, σ) / maq_sigma(θ, σ)**2
    ac_eq = numpy.zeros(max_lag + 1)
    ac_eq[0] = 1
    for i in range(len(ac)):
        ac_eq[i + 1] = ac[i]
    return ac_eq

def ar1_sigma(φ: float, σ: float=1) -> float:
    """
    Compute AR(1) standard deviation.

    Parameters
    ----------
    φ: float
        AR(1) coefficient.
    σ: float
        Standard deviation of noise term.
        
    Returns
    -------
    float
        Standard deviation.
    """

    return numpy.sqrt(σ**2/(1.0-φ**2))

def ar1_acf(φ: float, nvals: int) -> list[float]:
    """
    Compute AR(1) standard deviation.

    Parameters
    ----------
    φ: float
        AR(1) coefficient.
    nvals: int
        Number of terms computed.
    
    Returns
    -------
    list[float]
        Autocorrelation function.
    """

    return [φ**n for n in range(nvals)]

def ar1_offset_mean(φ: float, μ: float) -> float:
    """
    Compute AR(1) with offset mean.

    Parameters
    ----------
    φ: float
        AR(1) coefficient.
    μ: float
        Constant offset.

    Returns
    -------
    float
        Mean value.
    """

    return μ / (1.0 - φ)

def ar1_offset_sigma(φ: float, σ: float) -> float:
    """
    Compute AR(1) with offset standard deviation.

    Parameters
    ----------
    φ: float
        AR(1) coefficient.
    μ: float
        Constant offset.

    Returns
    -------
    float
        Standard deviation.
    """

    return σ / numpy.sqrt(1.0 - φ**2)

def noise(n: int) -> numpy.ndarray[float]:
    """
    Generate gaussian noise with unit variance.

    Parameters
    ----------
    n: int
        Number of values generated.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    return numpy.random.normal(0.0, 1.0, n)

def ar(φ: list[float], x0: list[float], n: int, σ: float) -> numpy.ndarray[float]:
    """
    Generate an AR(p) process using specified parameters.

    Parameters
    ----------
    φ: list[float]
        AR(p) parameters.
    x0: list[float]
        List of initial values.
    n: int
        Number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
   """
    
    p = len(φ)
    samples = numpy.zeros(n)
    for i in range(0, p):
        samples[i] = x0[i]
    ε = σ*noise(n)
    for i in range(p, n):
        samples[i] = ε[i]
        for j in range(0, p):
            samples[i] += φ[j] * samples[i-(j+1)]
    return samples

def ou(λ: float, μ: float, n: int, σ: int=1.0) -> numpy.ndarray[float]:
    """
    Generate the Ornstein-Uhlenbeck process using an AR(1) with offset simulation
    using the specified parameters.
    
    Parameters
    ----------
    λ: float
        Ornstein-Uhlenbeck parameter (0 < λ < 2).
    μ: float
        Mean value.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    φ = 1.0 - λ
    m = μ*λ
    return arp_offset([φ], m, n, σ)

def arp_offset(φ: list[float], μ: float, n: int, σ: float) -> numpy.ndarray[float]:
    """
    Generate AR(p) with a constant offset using the specified parameters.

    Parameters
    ----------
    φ: list[float]
        AR(p) parameters.
    u: float
        Offset.
    n: int
        Number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    return arp_drift(φ, μ, 0.0, n, σ)

def arp_drift(φ: list[float], μ: float, γ: float, n: int, σ: float) -> numpy.ndarray[float]:
    """
    Generate AR(p) with drift using the specified parameters.

    Parameters
    ----------
    φ: list[float]
        AR(p) parameters.
    u: float
        Offset.
    γ: float
        Drift parameter.
    n: int
        Number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    p = len(φ)
    samples = numpy.zeros(n)
    ε = σ*noise(n)
    for i in range(p, n):
        samples[i] = ε[i] + γ*i + μ
        for j in range(0, p):
            samples[i] += φ[j] * samples[i-(j+1)]
    return samples

def ar1(φ: float, n: int, σ: float=1.0) -> numpy.ndarray[float]:
    """
    Generate AR(1) using specified parameters.

    Parameters
    ----------
    φ: float
        AR(2) parameter.
    n: int
        Number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    return arp(numpy.array([φ]), n, σ)

def arp(φ: numpy.ndarray[float], n: int, σ: float=1.0) -> numpy.ndarray[float]:
    """
    Generate AR(p) using specified parameters and the statsmodels.tas simulator.

    Parameters
    ----------
    φ: numpy.ndarray[float]
        AR(p) parameters.
    n: int
        Number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    φ_sim = numpy.r_[1, -φ]
    δ_sim = numpy.array([1.0])
    return sm.tsa.arma_generate_sample(φ_sim, δ_sim, n, σ)

def maq(θ: numpy.ndarray[float], n: int, σ: float=1.0) -> numpy.ndarray[float]:
    """
    Generate MA(q) using specified parameters and the statsmodels.tas simulator.

    Parameters
    ----------
    θ: numpy.ndarray[float]
        MA(q) parameters.
    n: int
        Number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    φ_sim = numpy.array([1.0])
    θ_sim = numpy.r_[1, θ]
    return sm.tsa.arma_generate_sample(φ_sim, θ_sim, n, σ)

def arma(φ: numpy.ndarray[float], θ: numpy.ndarray[float], n: int, σ: float=1.0) -> numpy.ndarray[float]:
    """
    Generate ARMA(p, q) using specified parameters and the statsmodels.tas simulator.

    Parameters
    ----------
    φ: numpy.ndarray[float]
        AR(p) parameters.
    θ: numpy.ndarray[float]
        MA(q) parameters.
    n: int
        Number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.
    """

    φ_sim = numpy.r_[1, -φ]
    θ_sim = numpy.r_[1, θ]
    return sm.tsa.arma_generate_sample(φ_sim, θ_sim, n, σ)

def arima(φ: numpy.ndarray[float], δ: numpy.ndarray[float], d: int, n: int, σ: float=1.0) -> numpy.ndarray[float]:
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
    n: int
        Number of steps in simulation.
    σ: float
        Standard deviation of noise term.

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.

    Raises
    ______
    Exception
        d < 1 or d > 2
    """

    assert d <= 2, "d must equal 1 or 2"
    assert d >= 1, "d must equal 1 or 2"
    samples = arma(φ, δ, n, σ)
    if d == 1:
        return numpy.cumsum(samples)
    else:
        for i in range(2, n):
            samples[i] = samples[i] + 2.0*samples[i-1] - samples[i-2]
        return samples

def arima_from_arma(samples: numpy.ndarray[float], d: int) -> numpy.ndarray[float]:
    """
    Generate ARIMA(p,d,q) using the samples from a ARMA(p,q) process
    by integrating d times,.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        ARMA(p,q) processes samples
    d: int
        Number of integrations to perform (d = 1 or 2).

    Returns
    -------
    numpy.ndarray[float]
        Simulation results.

    Raises
    ______
    Exception
        d < 1 or d > 2
    """

    assert d <= 2, "d must equal 1 or 2"
    assert d >= 1, "d must equal 1 or 2"
    n = len(samples)
    if d == 1:
        return numpy.cumsum(samples)
    else:
        result = numpy.zeros(n)
        result[0] = samples[0]
        result[1] = samples[1]
        for i in range(2, n):
            result[i] = samples[i] + 2.0*result[i-1] - result[i-2]
        return result

def yw(samples: numpy.ndarray[float], order: int) -> numpy.ndarray[float]:
    """
    Compute the coefficients of an AR(p) processes by solving the Yule-Walker equations.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    order: int
        The assumed order of the AR9p) process.

    Returns
    -------
    numpy.ndarray[float]
        Estimate of AR(p) coefficients.
    """

    pacf, _ = sm.regression.yule_walker(samples, order=order, method='mle')
    return pacf

def pacf(samples: numpy.ndarray[float], nlags: int) -> numpy.ndarray[float]:
    """
    Compute the partial auto-correlation function using statsmodels.tsa.stattools.pacf.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    nlags: int
        The number of lags desired for the PACF.

    Returns
    -------
    numpy.ndarray[float]
        The of AR(p) partial autocorrelation function.
    """

    return sm.tsa.stattools.pacf(samples, nlags=nlags)

def ___ar_model(samples: numpy.ndarray[float], order: int) -> tsa.arima.model.ARIMA:
    """
    Create an AR(p) of the specified order with the specified samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    order: int
        Model order.

    Returns
    -------
    tsa.arima.model.ARIMA
        The of AR(p) model.
    """

    return tsa.arima.model.ARIMA(samples, order=(order, 0, 0))

def ar_fit(samples: numpy.ndarray[float], order: int) -> tsa.arima.model.ARIMAResults:
    """
    Estimate the parameters for the assumed AR(p) model from the samples
    assuming the specified order.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    order: int
        Model order.

    Returns
    -------
    tsa.arima.model.ARIMAResults
        Contains the AR(p) estimation results.
    """

    return ___ar_model(samples, order).fit()

def __ar_offset_model(samples: numpy.ndarray[float], order: int) -> tsa.arima.model.ARIMA:
    """
    Create and AR(p) with an offset of the specified order with the specified samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    order: int
        Model order.

    Returns
    -------
    tsa.arima.model.ARIMA
        The of AR(p) with offset model.
    """

    return tsa.arima.model.ARIMA(samples, order=(order, 0, 0), trend='c')

def ar_offset_fit(samples: numpy.ndarray[float], order: int) -> tsa.arima.model.ARIMAResults:
    """
    Estimate the parameters for the assumed AR(p) with offset model from the samples
    assuming the specified order.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    order: int
        Model order.

    Returns
    -------
    tsa.arima.model.ARIMAResults
        Contains the AR(p) estimation results.
    """

    return __ar_offset_model(samples, order).fit()

def __ma_model(samples: numpy.ndarray[float], order: int) -> tsa.arima.model.ARIMA:
    """
    Create a MA(p) model of the specified order with the specified samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        MA(p) processes samples
    order: int
        Model order.

    Returns
    -------
    tsa.arima.model.ARIMA
        The of MA(p) model.
    """

    return tsa.arima.model.ARIMA(samples, order=(0, 0, order))

def ma_fit(samples: numpy.ndarray[float], order: int) -> tsa.arima.model.ARIMAResults:
    """
    Estimate the parameters for the assumed MA(q) model from the samples
    assuming the specified order.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    order: int
        Model order.

    Returns
    -------
    tsa.arima.model.ARIMAResults
        Contains the AR(p) estimation results.
    """

    return __ma_model(samples, order).fit()

def __ma_offset_model(samples: numpy.ndarray[float], order: int) -> tsa.arima.model.ARIMA:
    """
    Create a MA(p) model with offset of the specified order with the specified samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    order: int
        Model order.

    Returns
    -------
    tsa.arima.model.ARIMA
        The of MA(q) with offset model.
    """

    return tsa.arima.model.ARIMA(samples, order=(0, 0, order), trend='c')

def ma_offset_fit(samples: numpy.ndarray[float], order: int) -> tsa.arima.model.ARIMAResults:
    """
    Estimate the parameters for the assumed MA(q) model from the samples
    assuming the specified order.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        AR(p) processes samples
    order: int
        Model order.

    Returns
    -------
    tsa.arima.model.ARIMAResults
        Contains the AR(p) estimation results.
    """

    return __ma_offset_model(samples, order).fit()

