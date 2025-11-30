import numpy
from typing import Tuple
from matplotlib import pyplot

from lib.utils import get_param_default_if_missing
from lib.plots import comp
from lib.plots.comp.axis import PlotType
from lib.data import OLSResult, stats

def training(forecast_data: numpy.ndarray[float], observed_data: numpy.ndarray[float], upper_bound_error: numpy.ndarray[float], 
             lower_bound_error: numpy.ndarray[float], x: numpy.ndarray[float]=None, title: str=None, title_offset: float=0.015,
             figsize: Tuple[int, int]=(10, 6), alpha: float=0.05, ylabel=None):
    """"
    Plot the result of a training analysis.

    Parameters
    ----------
    forecast_data : numpy.ndarray
        Model forecast data.
    observed_data : numpy.ndarray
        Observation data.
    upper_bound_error : numpy.ndarray
        Observation data.
    lower_bound_error : numpy.ndarray
        Observation data.
    x : numpy.ndarray[float], optional
        Value plotted on x-axis (default is index values of data)
    ylabel : string, optional
        Plot y-axis label (default is None)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    figsize : (int, int), optional
        Specify the width and height of plot (default is (10,8))
    """
   
    _, axis = pyplot.subplots(figsize=figsize)

    bias = stats.compute_bias(forecast_data, observed_data)
    mae = stats.compute_mae(forecast_data, observed_data)
    rmse = stats.compute_rmse(forecast_data, observed_data)

    title = f"Training Analysis, $\\alpha$={alpha: 2.2f}\nBIAS={bias: 2.2f}, MAE={mae: 2.2f}, RMSE={rmse: 2.2f}" if title is None else title
    ylabel = r"$X_t$" if ylabel is None else ylabel
    x = numpy.arange(len(forecast_data)) if x is None else x
    labels = ["Observation", "Forecast"]

    comp.comparison(axis, [observed_data, forecast_data], x, title=title, title_offset=title_offset, labels=labels, xlabel="$t$", 
                    ylabel=ylabel, legend_loc="upper left")
    axis.fill_between(x, lower_bound_error, upper_bound_error, alpha=0.3, color="lightgrey", edgecolor="black", zorder=10)


def prediction(training_data: numpy.ndarray[float], forecast_data: numpy.ndarray[float], upper_bound_error: numpy.ndarray[float], 
               lower_bound_error: numpy.ndarray[float], x: numpy.ndarray[float]=None, title: str=None, title_offset: float=0.0,
               figsize: Tuple[int, int]=(10, 6), alpha: float=0.05, ylabel=None):
    """"
    Plot the result of a training analysis.

    Parameters
    ----------
    training_data : numpy.ndarray
        Model forecast data.
    forecast_data : numpy.ndarray
        Observation data.
    upper_bound_error : numpy.ndarray
        Observation data.
    lower_bound_error : numpy.ndarray
        Observation data.
    x : numpy.ndarray[float], optional
        Value plotted on x-axis (default is index values of data)
    ylabel : string, optional
        Plot y-axis label (default is None)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    figsize : (int, int), optional
        Specify the width and height of plot (default is (10,8))
    """
   
    _, axis = pyplot.subplots(figsize=figsize)

    title = f"Prediction, $\\alpha$={alpha: 2.2f}" if title is None else title
    x = numpy.arange(len(training_data)) if x is None else x
    ylabel = r"$X_t$" if ylabel is None else ylabel

    x_forecast = numpy.arange(len(training_data), len(training_data) + len(forecast_data))
    labels = ["Observation", "Forecast"]

    comp.comparison(axis, [training_data, forecast_data], [x, x_forecast], title=title, title_offset=title_offset, labels=labels, xlabel="$t$", 
                    ylabel=ylabel, legend_loc="upper left")
    cycle = pyplot.rcParams['axes.prop_cycle'].by_key()['color']
    axis.plot([x[-1], x_forecast[0]], [training_data[-1], forecast_data[0]], color=cycle[0])
    axis.fill_between(x_forecast, lower_bound_error, upper_bound_error, alpha=0.3, color="lightgrey", edgecolor="black", zorder=10)


