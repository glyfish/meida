"""
stats.py

Useful statistical functions.

"""

import numpy
from pandas import DataFrame

import statsmodels.api as sm
from scipy.stats import multivariate_normal
from typing import Tuple
from statsmodels.tsa.stattools import grangercausalitytests


def to_noise(samples: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Difference the given samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.

    Returns
    -------
    numpy.ndarray[float]
        Differenced data
    """

    return diff(samples)


def from_noise(dB: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Integrate the given samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.

    Returns
    -------
    numpy.ndarray[float]
        Integrate data.
    """

    B = numpy.zeros(len(dB))
    for i in range(1, len(dB)):
        B[i] = B[i-1] + dB[i]
    return B


def to_geometric(samples: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Take the exponential of the given samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.

    Returns
    -------
    numpy.ndarray[float]
        Exponential of sampled data.
    """

    return numpy.exp(samples)


def from_geometric(samples: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Take the log of the given samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.

    Returns
    -------
    numpy.ndarray[float]
        Logarithm of sampled data.
    """

    return numpy.log(samples)


def ndiff(samples: numpy.ndarray[float], ndiff: int) -> numpy.ndarray[float]:
    """
    Take the specified number of differences of the samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    ndiff : int
        Number of differences taken.
        
    Returns
    -------
    numpy.ndarray[float]
        Samples differenced n times.
    """

    return numpy.diff(samples, ndiff)


def diff(samples: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Difference the given samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.

    Returns
    -------
    numpy.ndarray[float]
        Differenced data
    """

    return numpy.diff(samples)


def ensemble_mean(samples: numpy.ndarray[Tuple[int, int], float]) -> numpy.ndarray[float]:
    """
    Compute the time varying mean of the sampled ensemble.

    Parameters
    ----------
    samples: numpy.ndarray[Tuple[int, int], float]
        Ensemble of sampled data.

    Returns
    -------
    numpy.ndarray[float]
        Ensemble average mean as a function of time.

    Raises
    ______
    Exception
        Samples are not a two dimensional array.
    """

    if len(samples) == 0:
        raise Exception(f"no data")
    if len(samples.shape) != 2:
        raise Exception(f"Input must be a two dimensional array.")

    nsim = len(samples)
    npts = len(samples[0])
    mean = numpy.zeros(npts)
    for i in range(npts):
        for j in range(nsim):
            mean[i] += samples[j][i] / float(nsim)
    return mean


def ensemble_var(samples: numpy.ndarray[Tuple[int, int], float], Δt: float=1.0) -> numpy.ndarray[float]:
    """
    Compute the time varying variance of the sampled ensemble.

    Parameters
    ----------
    samples: numpy.ndarray[Tuple[int, int], float]
        Ensemble of sampled data.
    Δt: float
        Time delta (default 1.0)

    Returns
    -------
    numpy.ndarray[float]
        Ensemble average variance oas a function of time.

    Raises
    ______
    Exception
        Samples are not a two dimensional array.
    """

    if len(samples) == 0:
        raise Exception(f"no data")
    if len(samples.shape) != 2:
        raise Exception(f"Input must be a two dimensional array.")

    nsim = len(samples)
    mean = ensemble_mean(samples)
    npts = len(samples[0])
    var = numpy.zeros(npts)
    for i in range(npts):
        for j in range(nsim):
            var[i] += (samples[j][i] - mean[i])**2 / float(nsim)
    return var/Δt


def ensemble_sd(samples: numpy.ndarray[Tuple[int, int], float], Δt: float=1.0) -> numpy.ndarray[float]:
    """
    Compute the time varying standard deviation of the sampled ensemble.

    Parameters
    ----------
    samples: numpy.ndarray[Tuple[int, int], float]
        Ensemble of sampled data.
    Δt: float
        Time delta (default 1.0)

    Returns
    -------
    numpy.ndarray[float]
        Ensemble average standard deviation oas a function of time.

    Raises
    ______
    Exception
        Ensemble averaged
    """

    return numpy.sqrt(ensemble_var(samples, Δt))


def ensemble_acf(samples: numpy.ndarray[Tuple[int, int], float], nlags: int=None) -> numpy.ndarray[float]:
    """
    Compute the ensemble averaged autocorrelation function of the sampled ensemble.

    Parameters
    ----------
    samples: numpy.ndarray[Tuple[int, int], float]
        Sampled data.
    nlags: int
        Number of lags (default len(sample))

    Returns
    -------
    numpy.ndarray[float]
        Ensemble averaged auto correlation function.

    Raises
    ______
    Exception
        Samples are not a two dimensional array.
    """

    if len(samples) == 0:
        raise Exception(f"no data")

    if len(samples.shape) != 2:
        raise Exception(f"Input must be a two dimensional array.")

    nsim = len(samples)
    if nlags is None or nlags > len(samples):
        nlags = len(samples[0])
    ac_avg = numpy.zeros(nlags)

    for j in range(nsim):
        ac = acf(samples[j], nlags).real
        for i in range(nlags):
            ac_avg[i] += ac[i]
    return ac_avg / float(nsim)


def ensemble_cov(x: numpy.ndarray[Tuple[int, int], float], y: numpy.ndarray[Tuple[int, int], float]) -> numpy.ndarray[float]:
    """
    Compute the ensemble averaged covariance of the sampled ensemble.

    Parameters
    ----------
    x: numpy.ndarray[Tuple[int, int], float]
        x data samples.
    y: numpy.ndarray[Tuple[int, int], float]
        y data samples.

    Returns
    -------
    numpy.ndarray[float]
        Ensemble averaged auto correlation function.
    """

    x_nsim, x_npts = x.shape
    y_nsim, y_npts = y.shape
    npts = min(x_npts, y_npts)
    nsim = min(x_nsim, y_nsim)

    cov = numpy.zeros(npts)
    mean_x = ensemble_mean(x)
    mean_y = ensemble_mean(y)
    for i in range(npts):
        for j in range(nsim):
            cov[i] += (x[j,i] - mean_x[i])*(y[j,i] - mean_y[i])
    return cov / float(nsim)


def ensemble_correlation_coefficient(x: numpy.ndarray[Tuple[int, int], float], y: numpy.ndarray[Tuple[int, int], float]) -> numpy.ndarray[float]:
    """
    Compute the ensemble averaged correlation coefficient of the sampled ensemble.

    Parameters
    ----------
    x: numpy.ndarray[Tuple[int, int], float]
        x data samples.
    y: numpy.ndarray[Tuple[int, int], float]
        y data samples.

    Returns
    -------
    numpy.ndarray[float]
        Ensemble averaged auto correlation function.

    Raises
    ______
    Exception
        Samples are not a two dimensional array.
    """

    cov = ensemble_cov(x, y)
    std_x = ensemble_sd(x)
    std_y = ensemble_sd(y)
    for i in range(1,len(cov)):
        cov[i] = cov[i] / (std_x[i]*std_y[i])
    return cov


def cumu_mean(samples: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
   Cumulative mean of samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.

    Returns
    -------
    numpy.ndarray[float]
        Cumulative mean of samples as a function of time.
    """

    npts = numpy.arange(1, len(samples) + 1)
    csum = numpy.cumsum(samples)

    return csum / npts


def cumu_var(samples: numpy.ndarray[float], Δt: float=1.0) -> numpy.ndarray[float]:
    """
    Cumulative variance of samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    Δt: float
        Time delta (default 1.0)

    Returns
    -------
    numpy.ndarray[float]
        Cumulative variance of samples as a function of time.
    """

    npts = numpy.arange(1, len(samples) + 1)
    csum = numpy.cumsum(samples)
    mean = csum / npts
    csum2 = numpy.cumsum(samples**2)

    return (csum2 / npts - mean**2) / Δt


def cumu_sd(samples: numpy.ndarray[float], Δt: float=1.0) -> numpy.ndarray[float]:
    """
    Cumulative standard deviation of samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    Δt: float
        Time delta (default 1.0)

    Returns
    -------
    numpy.ndarray[float]
        Cumulative variance of samples as a function of time.
    """

    return numpy.sqrt(cumu_var(samples, Δt))


def moving_avg(samples: numpy.ndarray[float], window: int) -> numpy.ndarray[float]:
    """
    Moving average of samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    window: int
        Window size.

    Returns
    -------
    numpy.ndarray[float]
        Moving average of samples as a function of time.
    """

    result = numpy.cumsum(samples, dtype=float)
    result[window:] = result[window:] - result[:-window]
    return result[window - 1:] / window


def moving_var(samples: numpy.ndarray[float], window: int) -> numpy.ndarray[float]:
    """
    Moving variance of samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    window: int
        Window size.

    Returns
    -------
    numpy.ndarray[float]
        Moving variance of samples as a function of time.
    """

    result = numpy.cumsum(samples, dtype=float)
    result[window:] = result[window:] - result[:-window]
    result2 = numpy.cumsum(samples**2, dtype=float)
    result2[window:] = result2[window:] - result2[:-window]
    return (result2[window - 1:] - result[window - 1:]**2 / window) / window


def moving_std(samples: numpy.ndarray[float], window: int) -> numpy.ndarray[float]:
    """
    Moving standard deviation of samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    window: int
        Window size.

    Returns
    -------
    numpy.ndarray[float]
        Moving variance of samples as a function of time.
    """

    return numpy.sqrt(moving_var(samples, window))


def cumu_cov(x: numpy.ndarray[float], y: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Cumulative covariance of the samples.

    Parameters
    ----------
    x: numpy.ndarray[float]
        Sampled data.
    y: numpy.ndarray[float]
        Sampled data.

    Returns
    -------
    numpy.ndarray[float]
        Cumulative covariance of samples as a function of time.
    """

    nsample = min(len(x), len(y))
    npts = numpy.arange(nsample) + 1
    meanx = cumu_mean(x)
    meany = cumu_mean(y)
    cxy = numpy.cumsum(x * y) / npts

    return cxy - meanx * meany


def cov(x: numpy.ndarray[float], y: numpy.ndarray[float]) -> float:
    """
    Covariance of samples computed using brute force summation.

    Parameters
    ----------
    x: numpy.ndarray[float]
        Sampled data.
    y: numpy.ndarray[float]
        Sampled data.

    Returns
    -------
    float
        Covariance of samples.
    """

    nsample = len(x)
    meanx = numpy.mean(x)
    meany = numpy.mean(y)
    c = 0.0

    for i in range(nsample):
        c += x[i] * y[i]

    return c / nsample - meanx * meany


def cov_fft(x: numpy.ndarray[float], y: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Covariance of samples computed using FFT with isotropic truncation summation.

    Parameters
    ----------
    x: numpy.ndarray[float]
        Sampled data.
    y: numpy.ndarray[float]
        Sampled data.

    Returns
    -------
    numpy.ndarray[float]
        Covariance of samples as a function of time.
    """

    n = len(x)
    x_shifted = x - x.mean()
    y_shifted = y - y.mean()

    x_padded = numpy.concatenate((x_shifted, numpy.zeros(n-1)))
    y_padded = numpy.concatenate((y_shifted, numpy.zeros(n-1)))

    x_fft = numpy.fft.fft(x_padded)
    y_fft = numpy.fft.fft(y_padded)
    h_fft = numpy.conj(x_fft) * y_fft
    cc = numpy.fft.ifft(h_fft)

    return cc[0:n] / float(n)


def acf(samples: numpy.ndarray[float], nlags: int) -> numpy.ndarray[float]:
    """
    Autocorrelation function of samples computed using sm.tsa.stattools.acf.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    nlags: int
        max number of lags computed.

    Returns
    -------
    numpy.ndarray[float]
        Covariance of samples as a function of lag.
    """

    return sm.tsa.stattools.acf(samples, nlags=nlags, fft=True, missing="drop")


def pspec(x: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Power spectrum computed using FFT methods.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    nlags: int
        max number of lags computed.

    Returns
    -------
    numpy.ndarray[float]
        Covariance of samples as a function of lag.
    """

    n = len(x)
    μ = x.mean()
    x_shifted = x - μ
    energy = numpy.sum(x_shifted**2)
    x_padded = numpy.concatenate((x_shifted, numpy.zeros(n-1)))
    
    x_fft = numpy.fft.fft(x_padded)
    power = numpy.conj(x_fft) * x_fft

    return power[1:n].real/(n*energy)


def pdf_hist(samples: numpy.ndarray[float], range: Tuple[float, float]=None, nbins: int=50) -> numpy.ndarray[float]:
    """
    Compute PDF histogram of provided samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    range: Tuple[float, float]
        Value range
    nbins: int
        Number of bind used in calculation.

    Returns
    -------
    numpy.ndarray[float]
        PDF histogram.
    """
    
    if range is None:
        range = (numpy.min(samples), numpy.max(samples))
        
    return numpy.histogram(samples, bins=nbins, range=range, density=True)


def cdf_hist(x: numpy.ndarray[float], pdf: numpy.ndarray[float]) -> numpy.ndarray[float]:
    """
    Compute CDF histogram from x values and PDF histogram using integration

    Parameters
    ----------
    x: numpy.ndarray[float]
        CDF x values.
    pdf: numpy.ndarray[float]
        Value range

    Returns
    -------
    numpy.ndarray[float]
        CDF histogram.
    """

    npoints = len(x)
    cdf = numpy.zeros(npoints)
    dx = x[1] - x[0]
    for i in range(npoints):
        cdf[i] = numpy.sum(pdf[:i]) * dx
    return cdf


def agg(samples: numpy.ndarray[float], m: int) -> numpy.ndarray[float]:
    """
    Aggregate sample averages of m elements into len(samples)/m bins. 

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Sampled data.
    m : int
        Number of aggregates

    Returns
    -------
    numpy.ndarray[float]
        Aggreated sample average.
    """

    n = len(samples)
    d = int(n/m)
    agg = numpy.zeros(d)

    for k in range(d):
        for i in range(m):
            j = k*m+i
            agg[k] += samples[j]
        agg[k] = agg[k] / m

    return agg


def agg_var(samples: numpy.ndarray[float], m_vals: list[int]) -> numpy.ndarray[float]:
    """
    Compute the aggregated variance using the specified bin sizes.. 

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Samples used in calculation.
    m_vals: list[int]
        Desired bun sizes.

    Returns
    -------
    numpy.ndarray[float]
        Array of length m containing results.
    """

    npts = len(m_vals)
    var = numpy.zeros(npts)

    for i in range(npts):
        m = int(m_vals[i])
        vals = agg(samples, m)
        mean = numpy.mean(vals)
        d = len(vals)
        for k in range(d):
            var[i] += (vals[k] - mean)**2 / (d - 1)

    return var


def agg_time(x: numpy.ndarray[float], m: int) -> numpy.ndarray[float]:
    """
    Compute aggregated time values 

    Parameters
    ----------
    x: numpy.ndarray[float]
        Unaggregated time values.
    m: int
        Number of points to aggregate.

    Returns
    -------
    numpy.ndarray[float]
        Aggregated time values.
    """

    n = len(x)
    d = int(n/m)
    return numpy.linspace(x[0], x[n-1], d)


def lag_var(samples: numpy.ndarray[float], s: int) -> float:
    """
    Compute lagged variance with specified lag from provided samples using method
    from Lo and Mackinlay, 1988, "Stock market Prices do not Follow Random Walks".

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Samples
    s: int
       Lag value.

    Returns
    -------
    float
        Lagged variance.
    """

    t = len(samples) - 1
    μ = (samples[t] - samples[0]) / t
    m = (t - s + 1.0)*(1.0 - s/t)
    σ = 0.0

    for i in range(int(s), t+1):
        σ += (samples[i] - samples[i-s] - μ*s)**2

    return σ / m


def lag_var_scan(samples: numpy.ndarray[float], s_vals: list[int]) -> list[float]:
    """
    Compute lagged variance for a specified range of values.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Unaggregated time values.
    m: int
        Number of points to aggregate.

    Returns
    -------
    numpy.ndarray[float]
        lagged variance for specified lag values.
    """

    return [lag_var(samples, s) for s in s_vals]


def multivariate_normal_pdf(vals: numpy.ndarray, 
                            μ: numpy.ndarray[float], 
                            Ω: numpy.ndarray) -> numpy.ndarray[float]:
    """
    Return multivariate normal PDF with the specified parameters.

    Parameters
    ----------
    vals: numpy.array
        PDF coordinate values..
    μ: numpy.ndarray[float]
        Distribution mean values contains m elements
    Ω: numpy.ndarray[float, float]
        Distribution correlation matrix contains mxm elements.

    Returns
    -------
    numpy.ndarray[float]
        PDF values for given coordinates.
    """

    return multivariate_normal.pdf(vals, μ, Ω)

 
def multivariate_normal_samples(μ: numpy.ndarray[float], Ω: numpy.ndarray[float, float], n: int) -> numpy.ndarray[float]:
    """
    Return multivariate normal samples with the specified parameters.

    Parameters
    ----------
    μ: numpy.ndarray[float]
        Distribution mean values contains m elements
    Ω: numpy.ndarray[float, float]
        Distribution correlation matrix contains mxm elements.
    n: int
        Number of samples.

    Returns
    -------
    numpy.ndarray[float]
        Samples for multivariate normal distribution.
    """

    return numpy.random.multivariate_normal(μ, Ω, n)


def causality_matrix(samples: numpy.ndarray[float, float], nlags: int, add_const: bool=False, critical_value: float=0.05) -> DataFrame:
    """
    Compute Granger causality matrix for the given samples.

    Parameters
    ----------
    samples: numpy.ndarray[float, float]
        Samples used in calculation.
    nlags: int
        Maximum number of lags.
    add_const: bool
        Add constant term to model (default False).
    critical_value: float
        Critical value for causality F-test (default 0.05)

    Returns
    -------
    numpy.ndarray[float, float]
        Causality matrix.
    """

    n, _ = samples.shape
    results = []

    for i in range(n):
        for j in range(n):
            test_result = grangercausalitytests(numpy.array([samples[i], samples[j]]).T, nlags)
            pval = min([round(test_result[k][0]['ssr_ftest'][1], 4) for k in range(1, nlags+1)])
            results.append({'pvalue': pval, 
                            'critical_value': critical_value,
                            'result': pval <= critical_value,
                            'dependent_var': i + 1,
                            'causal_var': j + 1})
           
    return DataFrame.from_records(numpy.array(results), index=range(1, len(results) + 1)).sort_values(by=['dependent_var'])


def bias(pred: numpy.ndarray[float], obs: numpy.ndarray[float]) -> float:
    """
    Compute bias of prediction relative to target.

    Parameters
    ----------
    pred: numpy.ndarray[float]
        Predicted values.
    obs: numpy.ndarray[float]
        Observed values.

    Returns
    -------
    float
        Bias of prediction relative to target.
    """

    return numpy.mean(pred - obs)


def mae(pred: numpy.ndarray[float], obs: numpy.ndarray[float]) -> float:
    """
    Compute mean absolute error of prediction relative to target.

    Parameters
    ----------
    pred: numpy.ndarray[float]
        Predicted values.
    obs: numpy.ndarray[float]
        Observed values.

    Returns
    -------
    float
        Mean absolute error of prediction relative to target.
    """

    return numpy.mean(numpy.abs(pred - obs))


def rmse(pred: numpy.ndarray[float], obs: numpy.ndarray[float]) -> float:
    """
    Compute root mean squared error of prediction relative to target.

    Parameters
    ----------
    pred: numpy.ndarray[float]
        Predicted values.
    obs: numpy.ndarray[float]
        Observed values.

    Returns
    -------
    float
        Root mean squared error of prediction relative to target.
    """

    return numpy.sqrt(numpy.mean((pred - obs)**2))


def zscore(samples: numpy.ndarray[float], window: int) -> numpy.ndarray[float]:
    """
    Compute z-score of samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Samples.
    window: int
        Averaging window.

    Returns
    -------
    float
        Z-score of samples.
    """

    return (samples[window - 1:] - moving_avg(samples, window)) / moving_std(samples, window)
