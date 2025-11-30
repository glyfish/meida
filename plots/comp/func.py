"""
Basic plot components for comparing data to functions.

Functions
---------
fpoints
    Plot x and y data on specified axis type.
fcurve
    Plot multiple curves on the same x-scale
"""

import numpy
import pandas
from datetime import datetime, date
from matplotlib import pyplot
import matplotlib.dates as mdates
import matplotlib.units as munits
from typing import Callable
from numpy.typing import NDArray

from lib.plots.comp.axis import (PlotType, logStyle, logXStyle, logYStyle)
from lib.utils import (get_param_throw_if_missing, get_param_default_if_missing)
from lib.plots.comp.plot_utils import (__plot_curve, __plot_curves, __twinx_ticks, __plot_symbols,
                                       __plot_symbol, __plot_bar)
from lib import config

def fpoints(axis: pyplot.axis, data: NDArray, func: NDArray, x: NDArray=None, fx: NDArray=None, **kwargs):
    """"
    Compare data to a function by plotting the data as a curve
    and the function as points.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : numpy.ndarray
        Data compared to function.
    func : numpy.ndarray
        Function data plotted as points
    x : numpy.ndarray, optional
        Value plotted on x-axis (default is index values of data)
    fx : numpy.ndarray, optional
        Value plotted on x-axis for function (default is index values of data)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    ylabel : string, optional
        Plot y-axis label (default is 'y')
    lw : int, optional
        Plot line width (default is 2)
    labels : [string], optional
        Curve labels shown in legend.
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis are labeled using scientific notation. (default (-3, 3))
    plot_axis_type : PlotAxisType
        The type of axis used in the plot
    legend_loc : string
        Specify legend location. (default best)
    legend_title : string
        Specify legend title. (default None) 
    """

    title           = get_param_default_if_missing("title", None, **kwargs)
    title_offset    = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel          = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel          = get_param_default_if_missing("ylabel", None, **kwargs)
    lw              = get_param_default_if_missing("lw", 2, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    ylim            = get_param_default_if_missing("ylim", None, **kwargs)
    xlim            = get_param_default_if_missing("xlim", None, **kwargs)
    yscilimits      = get_param_default_if_missing("yscilimits", (-4, 4), **kwargs)
    xscilimits      = get_param_default_if_missing("xscilimits", (-4, 4), **kwargs)
    plot_axis_type  = get_param_default_if_missing("plot_axis_type", PlotType.LINEAR, **kwargs)
    legend_loc      = get_param_default_if_missing("legend_loc", "best", **kwargs)
    legend_title    = get_param_default_if_missing("legend_title", None, **kwargs)

    if x is None:
        npts = len(data)
        x = numpy.linspace(0.0, float(npts-1), npts)

    if fx is None:
        npts = len(func)
        fx = numpy.linspace(0.0, float(npts-1), npts)

    if isinstance(x[0], pandas.Timestamp) or isinstance(x[0], datetime) or isinstance(x[0], numpy.datetime64) or isinstance(x[0], date):
        converter = mdates.ConciseDateConverter()
        munits.registry[numpy.datetime64] = converter
        munits.registry[date] = converter
        munits.registry[datetime] = converter 
    else:
        axis.ticklabel_format(style='sci', axis='x', scilimits=xscilimits, useMathText=True)

    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)
    axis.set_title(title, y=1.0 + title_offset)

    if xlim is not None:
        axis.set_xlim(xlim)

    if ylim is not None:
        axis.set_ylim(ylim)

    axis.ticklabel_format(style='sci', axis='y', scilimits=yscilimits, useMathText=True)

    data_label = None
    func_label = None
    if labels is not None and len(labels) == 2:
        data_label = labels[0]
        func_label = labels[1]

    if plot_axis_type.value == PlotType.LOG.value:
        if x[0] == 0.0:
            x = x[1:]
            data = data[1:]
        if fx[0] == 0.0:
            fx = fx[1:]
            func = func[1:]
        logStyle(axis, x, data)
        axis.loglog(x, data, label=data_label, lw=lw)
        axis.loglog(fx, func, label=func_label, marker='o', linestyle="None", markeredgewidth=1.0, markersize=10.0)
    elif plot_axis_type.value == PlotType.XLOG.value:
        if x[0] == 0.0:
            x = x[1:]
            data = data[1:]
        if fx[0] == 0.0:
            fx = fx[1:]
            func = func[1:]
        logXStyle(axis, x, data)
        axis.semilogx(x, data, label=data_label, lw=lw)
        axis.semilogx(fx, func, label=func_label, marker='o', linestyle="None", markeredgewidth=1.0, markersize=10.0)
    elif plot_axis_type.value == PlotType.YLOG.value:
        logYStyle(axis, x, data)
        axis.semilogy(x, data, label=data_label, lw=lw)
        axis.semilogy(fx, func, label=func_label, marker='o', linestyle="None", markeredgewidth=1.0, markersize=10.0)
    else:
        axis.plot(x, data, label=data_label, lw=lw)
        axis.plot(fx, func, label=func_label, marker='o', linestyle="None", markeredgewidth=1.0, markersize=10.0)

    if labels is not None:
        axis.legend(loc=legend_loc, bbox_to_anchor=(0.1, 0.1, 0.8, 0.8))

def fcurve(axis: pyplot.axis, data: NDArray, func: NDArray, x: NDArray=None, fx: NDArray=None, **kwargs):
    """"
    Compare data to a function by plotting both as curves.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : numpy.ndarray
        Data compared to function.
    func : numpy.ndarray
        Function data plotted as points
    x : numpy.ndarray, optional
        Value plotted on x-axis (default is index values of data)
    fx : numpy.ndarray, optional
        Value plotted on x-axis for function (default is index values of data)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    ylabel : string, optional
        Plot y-axis label (default is 'y')
    lw : int, optional
        Plot line width (default is 2)
    labels : [string], optional
        Curve labels shown in legend.
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis are labeled using scientific notation. (default (-3, 3))
    plot_axis_type : PlotAxisType
        The type of axis used in the plot    
    """

    title           = get_param_default_if_missing("title", None, **kwargs)
    title_offset    = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel          = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel          = get_param_default_if_missing("ylabel", None, **kwargs)
    lw              = get_param_default_if_missing("lw", 2, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    ylim            = get_param_default_if_missing("ylim", None, **kwargs)
    xlim            = get_param_default_if_missing("xlim", None, **kwargs)
    scilimits      = get_param_default_if_missing("scilimits", (-4, 4), **kwargs)
    plot_axis_type  = get_param_default_if_missing("plot_axis_type", PlotType.LINEAR, **kwargs)

    if x is None:
        npts = len(data)
        x = numpy.linspace(0.0, float(npts-1), npts)

    if fx is None:
        npts = len(func)
        fx = numpy.linspace(0.0, float(npts-1), npts)

    if isinstance(x[0], pandas.Timestamp) or isinstance(x[0], datetime) or isinstance(x[0], numpy.datetime64) or isinstance(x[0], date):
        converter = mdates.ConciseDateConverter()
        munits.registry[numpy.datetime64] = converter
        munits.registry[date] = converter
        munits.registry[datetime] = converter 
    else:
        axis.ticklabel_format(style='sci', axis='x', scilimits=scilimits, useMathText=True)

    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)
    axis.set_title(title, y=1.0 + title_offset)

    if xlim is not None:
        axis.set_xlim(xlim)

    if ylim is not None:
        axis.set_ylim(ylim)

    axis.ticklabel_format(style='sci', axis='y', scilimits=scilimits, useMathText=True)

    data_label = None
    func_label = None
    if labels is not None and len(labels) == 2:
        data_label = labels[0]
        func_label = labels[1]

    if plot_axis_type.value == PlotType.LOG.value:
        if x[0] == 0.0:
            x = x[1:]
            data = data[1:]
        if fx[0] == 0.0:
            fx = fx[1:]
            func = func[1:]
        logStyle(axis, x, data)
        axis.loglog(x, data, label=data_label, lw=lw)
        axis.loglog(fx, func, label=func_label, lw=lw)
    elif plot_axis_type.value == PlotType.XLOG.value:
        if x[0] == 0.0:
            x = x[1:]
            data = data[1:]
        if fx[0] == 0.0:
            fx = fx[1:]
            func = func[1:]
        logXStyle(axis, x, data)
        axis.semilogx(x, data, label=data_label, lw=lw)
        axis.semilogx(fx, func, label=func_label, lw=lw)
    elif plot_axis_type.value == PlotType.YLOG.value:
        logYStyle(axis, x, data)
        axis.semilogy(x, data, label=data_label, lw=lw)
        axis.semilogy(fx, func, label=func_label, lw=lw)
    else:
        axis.plot(x, data, label=data_label, lw=lw)
        axis.plot(fx, func, label=func_label, lw=lw)

    if labels is not None:
        axis.legend(loc='best', bbox_to_anchor=(0.1, 0.1, 0.8, 0.8))

def fscatter(axis: pyplot.axis, data: NDArray, func: Callable[[float], float], x: NDArray=None, **kwargs):
    """"
    Compare data to a function by plotting the functions as a curve and as a scatter plot..

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : numpy.ndarray
        Data compared to function.
    func : Callable[[float], float]
        Function plotted as a function of x.
    x : numpy.ndarray[float], optional
        Value plotted on x-axis (default is index values of data)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    ylabel : string, optional
        Plot y-axis label (default is 'y')
    lw : int, optional
        Plot line width (default is 2)
    labels : [string], optional
        Curve labels shown in legend.
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis are labeled using scientific notation. (default (-3, 3))
    plot_axis_type : PlotAxisType
        The type of axis used in the plot    
    legend_loc : string
        Specify legend location. (default best)
    legend_title : string
        Specify legend title. (default None) 
   """

    plot_axis_type = get_param_default_if_missing("plot_axis_type", PlotType.LINEAR, **kwargs)
    title          = get_param_default_if_missing("title", None, **kwargs)
    xlabel         = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel         = get_param_default_if_missing("ylabel", None, **kwargs)
    labels         = get_param_default_if_missing("labels", None, **kwargs)
    title_offset   = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    lw             = get_param_default_if_missing("lw", 2, **kwargs)
    ylim           = get_param_default_if_missing("ylim", None, **kwargs)
    xlim           = get_param_default_if_missing("xlim", None, **kwargs)
    scilimits      = get_param_default_if_missing("scilimits", (-4, 4), **kwargs)
    legend_loc     = get_param_default_if_missing("legend_loc", "best", **kwargs)
    legend_title   = get_param_default_if_missing("legend_title", None, **kwargs)

    if x is None:
        npts = len(data)
        x = numpy.linspace(0.0, float(npts - 1), npts)

    if isinstance(x[0], pandas.Timestamp) or isinstance(x[0], datetime) or isinstance(x[0], numpy.datetime64) or isinstance(x[0], date):
        converter = mdates.ConciseDateConverter()
        munits.registry[numpy.datetime64] = converter
        munits.registry[date] = converter
        munits.registry[datetime] = converter 
    else:
        axis.ticklabel_format(style='sci', axis='x', scilimits=scilimits, useMathText=True)

    axis.ticklabel_format(style='sci', axis='y', scilimits=scilimits, useMathText=True)

    if labels is None:
        labels = ["Data", "Fit"]

    if xlim is not None:
        axis.set_xlim(xlim)

    if ylim is not None:
        axis.set_ylim(ylim)

    if title is not None:
        axis.set_title(title, y=1.0 + title_offset)

    axis.set_ylabel(ylabel)
    axis.set_xlabel(xlabel)
    
    if plot_axis_type.value == PlotType.LOG.value:
        data, x = __remove_zeros_if_needed(data, x)
        logStyle(axis, x, data)
        axis.loglog(x, data, marker='o', markersize=5.0, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[0])
        axis.loglog(x, func(x), zorder=10, label=labels[1], lw=lw)
    elif plot_axis_type.value == PlotType.XLOG.value:
        data, x = __remove_zeros_if_needed(data, x)
        logXStyle(axis, x, data)
        axis.semilogx(x, data, marker='o', markersize=5.0, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[0])
        axis.semilogx(x, func(x), zorder=10, label=labels[1], lw=lw)
    elif plot_axis_type.value == PlotType.YLOG.value:
        data, x = __remove_zeros_if_needed(data, x)
        logYStyle(axis, x, data)
        axis.semilogy(x, data, marker='o', markersize=5.0, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[0])
        axis.plot(x,func(x), zorder=10, label=labels[1], lw=lw)
    else:
        axis.plot(x, data, marker='o', markersize=5.0, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[0])
        axis.plot(x, func(x), zorder=10, label=labels[1], lw=lw)

    if labels is not None:
        axis.legend(loc=legend_loc, bbox_to_anchor=(0.1, 0.1, 0.85, 0.85), title=legend_title).set_zorder(10)



def fcurve_scatter_comparison(axis: pyplot.axis, data: list[NDArray], func: NDArray, 
                              x: list[NDArray]=None, fx: NDArray=None, **kwargs):
    """"
    Compare a function to multiple datasets by plotting the functions as a curve and data 
    as a scatter plot.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : numpy.ndarray
        Data compared to function.
    func : Callable[[float], float]
        Function plotted as a function of x.
    x : list[numpy.ndarray[float]], optional
        Value plotted on x-axis (default is index values of data)
    fx : numpy.ndarray[float], optional
        Value plotted on x-axis for f (default is index values of data)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    ylabel : string, optional
        Plot y-axis label (default is 'y')
    lw : int, optional
        Plot line width (default is 2)
    labels : [string], optional
        Curve labels shown in legend.
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis are labeled using scientific notation. (default (-3, 3))
    plot_axis_type : PlotAxisType
        The type of axis used in the plot    
    legend_loc : string
        Specify legend location. (default best)
    legend_title : string
        Specify legend title. (default None)
    symbols : [string]
        List of symbols to use for scatter plots.
   """

    title             = get_param_default_if_missing("title", None, **kwargs)
    title_offset      = get_param_default_if_missing("title_offset", 0.0, **kwargs)

    if title is not None:
        axis.set_title(title, y=1.0 + title_offset)

    __plot_curve(axis, fx, func, 0, **kwargs)
    __plot_symbols(axis, x, data, 1, **kwargs)


def fbar(axis: pyplot.axis, y: NDArray, fy: NDArray, x: NDArray=None, fx: NDArray=None, **kwargs):
    """
    Plot samples in a bar chart and compare to a function.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : numpy.ndarray
        Value plotted on y-axis.
    fy : numpy.ndarray
        Comparison function y-axis values.
    x : numpy.ndarray
        Value plotted in x axis (use y index)
    fx : numpy.ndarray
        Comparison function x axis values (use func index).
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    ylabel : string, optional
        Plot y-axis label (default is 'y')
    alpha : float
        Bar alpha (default 0.5)
    border_width : float
        Bar border width (default)
    bar_width : float
        Bar width ras faction of x delta.
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    """

    title          = get_param_default_if_missing("title", None, **kwargs)
    xlabel         = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel         = get_param_default_if_missing("ylabel", None, **kwargs)
    labels         = get_param_default_if_missing("labels", None, **kwargs)
    title_offset   = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    lw             = get_param_default_if_missing("lw", 2, **kwargs)
    legend_loc     = get_param_default_if_missing("legend_loc", "best", **kwargs)
    legend_title   = get_param_default_if_missing("legend_title", None, **kwargs)

    if title is not None:
        axis.set_title(title, y=1.0 + title_offset)

    axis.set_prop_cycle(config.distribution_sample_cycler)

    axis.set_ylabel(ylabel)
    axis.set_xlabel(xlabel)

    __plot_bar(axis, x, y, 0, **kwargs)
    
    label = labels[1] if labels is not None else None
    axis.plot(fx, fy, label=label, lw=lw, color="#320075", zorder=6)

    axis.legend(loc=legend_loc, title=legend_title, bbox_to_anchor=(0.1, 0.1, 0.85, 0.85))


def __remove_zeros_if_needed(data, x):
    if x[0] == 0.0:
        return data[1:], x[1:]
    else:
        return data, x
