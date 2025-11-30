"""
metrics.py

Metrics in used in financial analysis.

"""

import numpy
from pandas import DataFrame

from typing import Tuple

from lib.utils import verify_condition

def compute_sharpe_ratio(orders: numpy.ndarray[float], risk_free_return: float=0.0) -> float:
    """
    Calculate the Sharpe ratio for a time series using a rolling window. The order of the
    time series is assumed oldest data to most recent data.

    Parameters
    ----------
    orders : numpy.ndarray[float]
        Orders DataFrame.
    risk_free_return: float
        The risk-free return.
    Returns
    -------
    float
        The Sharpe ratio.
    """

    completed_orders = orders.query('order_status == "Completed"')

    pnl = completed_orders.pnl.to_numpy()
    cost = numpy.abs(completed_orders['size'].to_numpy() * completed_orders.price.to_numpy())
    daily_return = 100.0 * (pnl / cost) - risk_free_return

    return numpy.mean(daily_return) / numpy.std(daily_return)


def compute_rate_of_return(orders: numpy.ndarray[float]) -> float:
    """
    Calculate the rate of return.

    Parameters
    ----------
    orders : numpy.ndarray[float]
        Orders DataFrame.

    Returns
    -------
    float
        The Sharpe ratio.
    """

    completed_orders = orders.query('order_status == "Completed"')

    pnl = completed_orders.pnl.to_numpy()
    cost = numpy.abs(completed_orders['size'].to_numpy() * completed_orders.price.to_numpy())

    return 100.0 * numpy.sum(pnl) / numpy.sum(cost)


def compute_daily_rate_of_return(orders: numpy.ndarray[float]) -> float:
    """
    Calculate the rate of return.

    Parameters
    ----------
    orders : numpy.ndarray[float]
        Orders DataFrame.

    Returns
    -------
    float
        The Sharpe ratio.
    """

    completed_orders = orders.query('order_status == "Completed"')

    pnl = completed_orders.pnl.to_numpy()
    cost = numpy.abs(completed_orders['size'].to_numpy() * completed_orders.price.to_numpy())

    daily_return = 100.0 * (pnl / cost)

    return completed_orders.date.to_numpy(), daily_return


def compute_zscore(time: numpy.ndarray[float], data: numpy.ndarray[float], window: int) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Calculate the z-score for a time series using a rolling window. The order of the
    time series is assumed oldest data to most recent data.

    Parameters
    ----------
    data : numpy.ndarray[float]
        The time series.
    time : numpy.ndarray[float]
        The time series time.
    window : int
        The lookback window.

    Returns
    -------
    numpy.ndarray[float]
        The z-score series.
    """

    npts = len(data) - window + 1
    zscores = [zscore(data[i:i + window]) for i in range(npts)]
    return time[window - 1:], numpy.array(zscores)


def compute_std(time: numpy.ndarray[float], data: numpy.ndarray[float], window: int) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Calculate the standard deviation for a time series using a rolling window. The order of the
    time series is assumed oldest data to most recent data.

    Parameters
    ----------
    data : numpy.ndarray[float]
        The time series.
    time : numpy.ndarray[float]
        The time series time.
    window : int
        The lookback window.

    Returns
    -------
    numpy.ndarray[float]
        The standard deviation series.
    """

    npts = len(data) - window + 1
    stds = [std(numpy.flip(data[i:i + window])) for i in range(npts)]
    return time[window - 1:], numpy.array(stds)


def zscore(samples: numpy.ndarray[float]) -> float:
    """
    Calculate the z-score using samples to compute the mean and standard deviation
    and use the last value in samples as the test value.

    Parameters
    ----------
    samples : numpy.ndarray
        The time series.

    Returns
    -------
    float
        The z-score.
    """

    verify_condition(samples, len(samples) > 0, "No samples to compute z-score")

    mean = numpy.mean(samples)
    std = numpy.std(samples)
    val = samples[-1]

    return (val - mean) / std if std > 0 else 0.0


def std(samples: numpy.ndarray[float]) -> float:    
    """
    Calculate the standard deviation of the samples.

    Parameters
    ----------
    samples : numpy.ndarray[float]
        The time series.

    Returns
    -------
    float
        The standard deviation.
    """

    return numpy.std(samples)



