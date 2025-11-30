"""
Basic plot components.

Functions
---------
curve
    Plot x and y data on specified axis type.
comparison
    Plot multiple curves on the same x-scale
stack
    Plot a horizontal stack of multiple curves on the same x-scale.
twinx
    Plot two curves with different y scales and the same x scale in the same plot with the scale
    of one curve on the left axis and the other on the right.
twinx_comparisons
    Compare multiple curves with the same x scale and different y scales where the
    different y scales are on the left and right axis.
"""

import numpy
import pandas
import math
from datetime import datetime, date
import matplotlib.ticker
import matplotlib.dates as mdates
import matplotlib.units as munits
from matplotlib import rcParams
from matplotlib import pyplot
from numpy.typing import NDArray


from lib.plots.comp.axis import (PlotType, logStyle, logXStyle, logYStyle)
from lib.plots.comp.plot_utils import (__plot_curve, __plot_curves, __twinx_ticks, __plot_symbols,
                                       __plot_symbol)
from lib.config import SharedCycler

from lib.utils import get_param_default_if_missing


def curve(axis: pyplot.axis, y: NDArray, x: NDArray=None, **kwargs):
    """
    Plot a curve.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : numpy.ndarray
        Value plotted on y-axis.
    x : numpy.ndarray, optional
        Value plotted on x-axis (default is index values of y)
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
    npts : int, optional
        Number of points plotted (default is length of y)
    figsize : (int, int), optional
        Specify the width and height of plot (default is (10,8))
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
    npts            = get_param_default_if_missing("npts", None, **kwargs)
    xlabel          = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel          = get_param_default_if_missing("ylabel", None, **kwargs)

    if npts is None or npts > len(y):
        npts = len(y)

    if x is None:
        x = numpy.linspace(0.0, float(npts-1), npts)

    if not isinstance(x, (numpy.ndarray, numpy.generic)):
        raise Exception("x must be a numpy.array")

    if not isinstance(y, (numpy.ndarray, numpy.generic)):
        raise Exception("y must be a numpy.array")

    if title is not None:
        offset = 1.0 + title_offset
        axis.set_title(title, y=offset)

    color_cycler = SharedCycler(rcParams['axes.prop_cycle'])
    __plot_curve(axis, x, y, 0, color_cycler, **kwargs)

def comparison(axis: pyplot.axis, y: NDArray, x: NDArray=None, **kwargs):
    """
    Plot multiple curves on same scale.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : [numpy.ndarray]
        Value plotted on y-axis.
    x : numpy.array or [numpy.ndarray], optional
        Value plotted on x-axis. If property is an list each x is plotted with y of 
        same index (default is index values of y)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is None)
    labels : [string], optional
        Curve labels shown in legend.
    ylabel : string, optional
        Plot y-axis label (default is None)
    lw : int, optional
        Plot line width (default is 2)
    npts : int, optional
        Number of points plotted (default is length of y)
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis are labeled using scientific notation. (default (-3, 3))
    legend_loc : string
        Specify legend location. (default best)
    legend_title : string
        Specify legend title. (default None)
    plot_axis_type : PlotAxisType
        Axis type. (default PlotAxisType.LINEAR)
    colors : list[str]
        Curve color values (default uses color cycler).
    """
    
    title           = get_param_default_if_missing("title", None, **kwargs)
    title_offset    = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)

    ncurve = len(y)
    
    if ncurve == 0:
        raise Exception("Length of y must be greater than zero.")

    if x is None:
        x = []
        for i in range(ncurve):
            ypts = len(y[i])
            x.append(numpy.linspace(0.0, float(ypts-1), ypts))
    elif not isinstance(x, list):
        x_val = x
        x = []
        for i in range(ncurve):
            x.append(x_val)
    elif isinstance(x, list) and len(x) != len(y):
        for i in range(len(x), ncurve):
            ypts = len(y[i])
            x.append(numpy.linspace(0.0, float(ypts-1), ypts))

    if title is not None:
        offset = 1.0 + title_offset
        axis.set_title(title, y=offset)

    __plot_curves(axis, x, y, **kwargs)


def stack(axis: pyplot.axis, y: list[NDArray], x=None, **kwargs):
    """
    Plot a horizontal stack of curves on the same x-scale.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : list[numpy.ndarray]
        data y-axis values.
    x : list[numpy.ndarray] or numpy.ndarray
        data x-axis values (default None).
    plot_type : PlotType
        Axis type.
    title : str
        Plot title. (default None)
    title_offset : str
        Title offset. (default 0)
    xlabel : str
        X-axis label. (default None)
    ylabels : str or list[str]
        Y-axis label. (default None)
    xlim : (float, float)
        X-axis limits. (default None)
    ylim : (float, float)
        Y-axis limits. (default None)
    lw : int
        Line width. (default 1)
    npts : int
        Number of points to plot. (default len(y))
    """

    title          = get_param_default_if_missing("title", None, **kwargs)
    title_offset   = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel         = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabels        = get_param_default_if_missing("ylabels", None, **kwargs)
    ylim           = get_param_default_if_missing("ylim", None, **kwargs)
    labels         = get_param_default_if_missing("labels", None, **kwargs)
    npts           = get_param_default_if_missing("npts", None, **kwargs)

    nplot = len(y)

    if title is not None:
        axis[0].set_title(title, y=1.0 + title_offset)

    axis[nplot-1].set_xlabel(xlabel)
    kwargs.pop("xlabel", None)

    if x is None:
        x = []
        for i in range(nplot):
            ypts = len(y[i])
            x.append(numpy.linspace(0.0, float(ypts-1), ypts))
    elif isinstance(x, numpy.ndarray):
        x = numpy.tile(x, (nplot, 1))

    for i in range(nplot):
        y_plot = y[i]
        x_plot = x[i]

        if isinstance(ylabels, list):
            ylabel = ylabels[i]
        elif isinstance(ylabels, str):
            ylabel = ylabels
        else:
            ylabel=None

        if labels is not None:
            npts_plot = len(y_plot) if npts is None else npts
            ypos = 0.8*(ylim[1] - ylim[0]) + ylim[0]
            xpos = 0.8*(x_plot[npts_plot-1] - x_plot[0]) + x_plot[0]
            text = axis[i].text(xpos, ypos, labels[i])
            text.set_bbox(dict(facecolor='white', alpha=0.75, edgecolor='white'))

        __plot_curve(axis[i], x_plot, y_plot, i, ylabel=ylabel, **kwargs)


def comparison_stack(axis: pyplot.axis, y: list[NDArray], x: list[NDArray]=None, **kwargs):
    """
    Plot a horizontal stack of multiple curves on the same x-scale.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : list[numpy.ndarray]
        data y-axis values.
    x : list[numpy.ndarray] or numpy.ndarray
        data x-axis values (default None).
    plot_type : PlotType
        Axis type.
    title : str
        Plot title. (default None)
    title_offset : str
        Title offset. (default 0)
    xlabel : str
        X-axis label. (default None)
    ylabels : str or list[str]
        Y-axis label. (default None)
    labels : [string], optional
        Curve labels shown in legend.
    xlim : (float, float)
        X-axis limits. (default None)
    ylim : (float, float)
        Y-axis limits. (default None)
    lw : int
        Line width. (default 1)
    npts : int
        Number of points to plot. (default len(y))
    legend_loc : string
        Specify legend location. (default best)
    legend_title : string
        Specify legend title. (default None)
    """

    title            = get_param_default_if_missing("title", None, **kwargs)
    title_offset     = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel           = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabels          = get_param_default_if_missing("ylabels", None, **kwargs)
    curve_labels     = get_param_default_if_missing("labels", [], **kwargs)

    nplot = len(y)
    ncurve = len(y[0])

    axis[nplot-1].set_xlabel(xlabel)
    kwargs.pop("xlabel", None)
    kwargs.pop("labels", None)

    if title is not None:
        axis[0].set_title(title, y=1.0 + title_offset)

    if x is None:
        x = []
        for i in range(nplot):
            x_curve = []
            for j in range(ncurve):
                ypts = len(y[i][0])
                x_curve.append(numpy.linspace(0.0, float(ypts-1), ypts))
            x.append(x_curve)
    elif isinstance(x, numpy.ndarray):
        x = []
        for _ in range(nplot):
            x.append(numpy.tile(x, (ncurve, 1)))

    for i in range(nplot):
        y_plot = y[i]
        x_plot = x[i]

        if isinstance(ylabels, list):
            axis[i].set_ylabel(ylabels[i])
        elif isinstance(ylabels, str):
            axis[i].set_ylabel(ylabels)

        if len(curve_labels) > i:
            labels = curve_labels[i]  
        else:
            labels = None

        __plot_curves(axis[i], x_plot, y_plot, labels=labels, **kwargs)


def twinx(axis: pyplot.axis, left: NDArray, right: NDArray, x=None, **kwargs):
    """
    Plot two curves with different scales on the y-axis that use the same scale on the
    x-axis.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    left : numpy.ndarray
        Value plotted on left y-axis.
    right : numpy.ndarray
        Value plotted on right y-axis.
    x : numpy.array or numpy.ndarray, optional
        Value plotted on x-axis. If property is an list each x is plotted with y of 
        same index (default is index values of y)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is None)
    left_ylabel : string, optional
        Plot left y-axis label (default is None)
    right_ylabel : string, optional
        Plot left y-axis label (default is None)
    labels : [string], optional
        Curve labels shown in legend. Must have length of 2.
    lw : int, optional
        Plot line width (default is 2)
    npts : int, optional
        Number of points plotted (default is length of y)
    left_ylim : (float, float)
        Specify the limits for the left y axis. (default None)
    right_ylim : (float, float)
        Specify the limits for the right y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis is labeled using scientific notation. (default (-3, 3))
    legend_loc : string
        Specify legend location. (default best)
    legend_title : string
        Specify legend title. (default None)
    plot_axis_type : PlotAxisType
        Axis type. (default PlotAxisType.LINEAR)
    """

    title           = get_param_default_if_missing("title", None, **kwargs)
    title_offset    = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel          = get_param_default_if_missing("xlabel", None, **kwargs)
    left_ylabel     = get_param_default_if_missing("left_ylabel", None, **kwargs)
    right_ylabel    = get_param_default_if_missing("right_ylabel", None, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    left_ylim       = get_param_default_if_missing("left_ylim", None, **kwargs)
    right_ylim      = get_param_default_if_missing("right_ylim", None, **kwargs)
    xlim            = get_param_default_if_missing("xlim", None, **kwargs)
    legend_loc      = get_param_default_if_missing("legend_loc", "best", **kwargs)
    legend_title    = get_param_default_if_missing("legend_title", None, **kwargs)
    npts            = get_param_default_if_missing("npts", None, **kwargs)

    if npts is not None and (npts > len(left) or npts > len(right)):
        npts = min(len(left), len(right))

    if x is None:
        ny = min(len(left), len(right))
        x = numpy.linspace(0.0, float(ny-1), ny)

    if not isinstance(x, list):
        x = numpy.tile(x, (2, 1))

    axis.set_title(title, y=title_offset + 1.0)
    axis.set_ylabel(left_ylabel)
    axis.set_xlabel(xlabel)

    list1 = __plot_curve(axis, x[0], left, 0, **kwargs)

    axis2 = axis.twinx()
    axis2.grid(False)
    axis2._get_lines.prop_cycler = axis._get_lines.prop_cycler
    if right_ylabel is not None:
        axis2.set_ylabel(right_ylabel, rotation=-90, labelpad=15)
    list2 = __plot_curve(axis2, x[1], right, 1, **kwargs)

    if left_ylim is not None:
        axis.set_ylim(left_ylim)

    if right_ylim is not None:
        axis2.set_ylim(right_ylim)

    if xlim is not None:
        axis.set_xlim(xlim)

    __twinx_ticks(axis, axis2)

    if labels is not None:
        labels_list = list1 + list2
        labs = [l.get_label() for l in labels_list]
        axis.legend(labels_list, labs, loc=legend_loc, title=legend_title, bbox_to_anchor=(0.1, 0.1, 0.9, 0.9)).set_zorder(10)


def twinx_comparison(axis: pyplot.axis, left: list[NDArray], right: list[NDArray], x=None, **kwargs):
    """
    Plot two curves with different scales on the y-axis that use the same scale on the
    x-axis.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    left : list[numpy.ndarray]
        Value plotted on left y-axis.
    right : list[numpy.ndarray]
        Value plotted on right y-axis.
    x : numpy.array or numpy.ndarray, optional
        Value plotted on x-axis. If property is an list each x is plotted with y of 
        same index (default is index values of y)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is None)
    left_ylabel : string, optional
        Plot left y-axis label (default is None)
    right_ylabel : string, optional
        Plot left y-axis label (default is None)
    labels : [string], optional
        Curve labels shown in legend. Must have length of 2.
    lw : int, optional
        Plot line width (default is 2)
    npts : int, optional
        Number of points plotted (default is length of y)
    left_ylim : (float, float)
        Specify the limits for the left y axis. (default None)
    right_ylim : (float, float)
        Specify the limits for the right y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis is labeled using scientific notation. (default (-3, 3))
    legend_loc : string
        Specify legend location. (default best)
    legend_title : string
        Specify legend title. (default None)
    plot_axis_type : PlotAxisType
        Axis type. (default PlotAxisType.LINEAR)
    """

    title           = get_param_default_if_missing("title", None, **kwargs)
    title_offset    = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel          = get_param_default_if_missing("xlabel", None, **kwargs)
    left_ylabel     = get_param_default_if_missing("left_ylabel", None, **kwargs)
    right_ylabel    = get_param_default_if_missing("right_ylabel", None, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    left_ylim       = get_param_default_if_missing("left_ylim", None, **kwargs)
    right_ylim      = get_param_default_if_missing("right_ylim", None, **kwargs)
    xlim            = get_param_default_if_missing("xlim", None, **kwargs)
    legend_loc      = get_param_default_if_missing("legend_loc", "best", **kwargs)
    legend_title    = get_param_default_if_missing("legend_title", None, **kwargs)
    npts            = get_param_default_if_missing("npts", None, **kwargs)
    scilimits       = get_param_default_if_missing("scilimits", (-3, 3), **kwargs)

    if title is not None:
        axis.set_title(title, y=title_offset + 1.0)
        
    if left_ylabel is not None:
        axis.set_ylabel(left_ylabel)
    if xlabel is not None:        
        axis.set_xlabel(xlabel)

    n_left = min([len(l) for l in left])
    n_right = min([len(r) for r in right])

    if npts is not None and (npts > n_left or npts > n_right):
        npts = min(n_left, n_right)

    nplots = len(left) + len(right)
    if isinstance(x, numpy.ndarray):
        x = numpy.tile(x, (nplots, 1))

    list1 = [__plot_curve(axis, x[i], left[i], i, **kwargs) for i in range(len(left))]

    axis2 = axis.twinx()
    axis2.grid(False)
    axis2._get_lines.prop_cycler = axis._get_lines.prop_cycler
    if right_ylabel is not None:
        axis2.set_ylabel(right_ylabel, rotation=-90, labelpad=15)

    list2 = [__plot_curve(axis2, x[i], right[i], len(left) + i, **kwargs)  for i in range(len(right))]

    axis.ticklabel_format(style='sci', axis='y', scilimits=scilimits, useMathText=True)
    axis2.ticklabel_format(style='sci', axis='y', scilimits=scilimits, useMathText=True)

    if left_ylim is not None:
        axis.set_ylim(left_ylim)

    if right_ylim is not None:
        axis2.set_ylim(right_ylim)

    if xlim is not None:
        axis.set_xlim(xlim)

    __twinx_ticks(axis, axis2)

    if labels is not None:
        labels_list = [item for sublist in list1 + list2 for item in sublist]
        labs = [l.get_label() for l in labels_list]
        axis.legend(labels_list, labs, title=legend_title, loc=legend_loc, bbox_to_anchor=(0.15, 0.15, 0.85, 0.85))


def scatter(axis: pyplot.axis, data: NDArray, x: NDArray, **kwargs):
    """"
    Plot data in a scatter plot.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : numpy.ndarray
        Data compared to function.
    x : numpy.ndarray[float]
        Value plotted on x-axis.
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    ylabel : string, optional
        Plot y-axis label (default is 'y')
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis are labeled using scientific notation. (default (-3, 3))
    plot_axis_type : PlotAxisType
        The type of axis used in the plot
    marker : string
        Symbol used to mark data points. (default 'o')
    marker_size : float
        Symbols used to mark data points. (default 5.0)
   """

    plot_axis_type = get_param_default_if_missing("plot_axis_type", PlotType.LINEAR, **kwargs)
    title          = get_param_default_if_missing("title", None, **kwargs)
    xlabel         = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel         = get_param_default_if_missing("ylabel", None, **kwargs)
    labels         = get_param_default_if_missing("labels", None, **kwargs)
    title_offset   = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    ylim           = get_param_default_if_missing("ylim", None, **kwargs)
    xlim           = get_param_default_if_missing("xlim", None, **kwargs)
    scilimits      = get_param_default_if_missing("scilimits", (-4, 4), **kwargs)
    marker         = get_param_default_if_missing("marker", 'o', **kwargs)
    marker_size    = get_param_default_if_missing("marker_size", 5.0, **kwargs)
    

    if x is None:
        npts = len(data)
        x = numpy.linspace(0.0, float(npts - 1), npts)

    if isinstance(x[0], pandas.Timestamp) or isinstance(x[0], datetime) or isinstance(x[0], numpy.datetime64):
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
        logStyle(axis, x, data)
        axis.loglog(x, data, marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[0])
    elif plot_axis_type.value == PlotType.XLOG.value:
        logXStyle(axis, x, data)
        axis.semilogx(x, data, marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[0])
    elif plot_axis_type.value == PlotType.YLOG.value:
        logYStyle(axis, x, data)
        axis.semilogy(x, data, marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[0])
    else:
        axis.plot(x, data, marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[0])


def scatter_comparison(axis: pyplot.axis, data: list[NDArray], x: NDArray, **kwargs):
    """"
    Plot multiple data sets that share the same x-axis in a scatter plot.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : numpy.ndarray
        Data compared to function.
    x : numpy.ndarray[float]
        Value plotted on x-axis.
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    labels : [string], optional
        Curve labels shown in legend. Must have length of 2.
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
    markers : list[string]
        Symbols used to mark data points. (default 'o')
    marker_size : float
        Symbols used to mark data points. (default 'o')
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
    ylim           = get_param_default_if_missing("ylim", None, **kwargs)
    xlim           = get_param_default_if_missing("xlim", None, **kwargs)
    scilimits      = get_param_default_if_missing("scilimits", (-4, 4), **kwargs)
    markers        = get_param_default_if_missing("marker", None, **kwargs)
    marker_size    = get_param_default_if_missing("marker_size", 5.0, **kwargs)
    legend_loc     = get_param_default_if_missing("legend_loc", "best", **kwargs)
    legend_title   = get_param_default_if_missing("legend_title", None, **kwargs)

    ncurve = len(data)

    if x is None:
        npts = len(data)
        x = numpy.linspace(0.0, float(npts - 1), npts)

    if isinstance(x[0], pandas.Timestamp) or isinstance(x[0], datetime) or isinstance(x[0], numpy.datetime64):
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
    
    for i in range(ncurve):
        marker = markers[i] if markers is not None else 'o'

        if plot_axis_type.value == PlotType.LOG.value:
            logStyle(axis, x, data[i])
            axis.loglog(x, data[i], marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[i])
        elif plot_axis_type.value == PlotType.XLOG.value:
            logXStyle(axis, x, data[i])
            axis.semilogx(x, data[i], marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[i])
        elif plot_axis_type.value == PlotType.YLOG.value:
            logYStyle(axis, x, data[i])
            axis.semilogy(x, data[i], marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[i])
        else:
            axis.plot(x, data[i], marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, alpha=0.75, zorder=5, label=labels[i])

    if labels is not None:
        ncol = math.ceil(ncurve / 6 )
        axis.legend(loc=legend_loc, ncol=ncol, title=legend_title, bbox_to_anchor=(0.1, 0.1, 0.9, 0.9)).set_zorder(10)
