"""
Reusable plot components.

Functions
---------
__plot_curve
    Plot x and y data on specified axis type.
__plot_curves
    Plot multiple curves on the same x-scale
"""

import numpy
import pandas
import math
from datetime import datetime, date
import matplotlib.ticker
import matplotlib.dates as mdates
import matplotlib.units as munits
from matplotlib import pyplot

from lib.plots.comp.axis import (PlotType, logStyle, logXStyle, logYStyle)
from lib.utils import get_param_default_if_missing


def __plot_curve(axis, x, y, n, shared_cycler, **kwargs):
    lw              = get_param_default_if_missing("lw", 2, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    colors          = get_param_default_if_missing("colors", None, **kwargs)
    plot_axis_type  = get_param_default_if_missing("plot_axis_type", PlotType.LINEAR, **kwargs)
    scilimits       = get_param_default_if_missing("scilimits", (-4, 4), **kwargs)
    ylim            = get_param_default_if_missing("ylim", None, **kwargs)
    xlim            = get_param_default_if_missing("xlim", None, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    xlabel          = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel          = get_param_default_if_missing("ylabel", None, **kwargs)
    npts            = get_param_default_if_missing("npts", min(len(y), len(x)), **kwargs)

    if isinstance(x[0], pandas.Timestamp) or isinstance(x[0], datetime) or isinstance(x[0], numpy.datetime64) or isinstance(x[0], date):
        converter = mdates.ConciseDateConverter()
        munits.registry[numpy.datetime64] = converter
        munits.registry[date] = converter
        munits.registry[datetime] = converter 
    else:
        axis.ticklabel_format(style='sci', axis='x', scilimits=scilimits, useMathText=True)

    if xlabel is not None:
        axis.set_xlabel(xlabel)
    if ylabel is not None:
        axis.set_ylabel(ylabel)

    if xlim is not None:
        axis.set_xlim(xlim)

    if ylim is not None:
        axis.set_ylim(ylim)

    color = colors[n] if colors is not None else shared_cycler.get_next()['color']

    axis.ticklabel_format(style='sci', axis='y', scilimits=scilimits, useMathText=True)

    x = x[:npts]
    y = y[:npts]

    label = labels[n] if labels is not None and n < len(labels) else None

    if plot_axis_type.value == PlotType.LINEAR.value:
        return axis.plot(x, y, lw=lw, label=label, color=color, zorder=5)
    elif plot_axis_type.value == PlotType.YLOG.value:
        logYStyle(axis, x, y)
        return axis.semilogy(x, y, lw=lw, label=label, color=color, zorder=5)
    elif plot_axis_type.value == PlotType.XLOG.value:
        logXStyle(axis, x, y)
        return axis.semilogx(x, y, lw=lw, label=label, color=color, zorder=5)
    elif plot_axis_type.value == PlotType.LOG.value:
        logStyle(axis, x, y)
        return axis.loglog(x, y, lw=lw, label=label, color=color, zorder=5)
    else:
        raise Exception("Invalid PlotAxisType")


# Plot curves
def __plot_curves(axis, x, y, **kwargs):
    labels         = get_param_default_if_missing("labels", None, **kwargs)
    legend_loc     = get_param_default_if_missing("legend_loc", "best", **kwargs)
    legend_title   = get_param_default_if_missing("legend_title", None, **kwargs)
    npts           = get_param_default_if_missing("npts", None, **kwargs)

    ncurve = len(y)

    for i in range(ncurve):
        xplot = x[i]
        yplot = y[i]

        if npts is None or npts > len(yplot):
            npts = len(yplot)
        
        if not isinstance(xplot, (numpy.ndarray, numpy.generic)):
            raise Exception("x must be a numpy.array")

        if not isinstance(yplot, (numpy.ndarray, numpy.generic)):
            raise Exception("y must be a numpy.array")

        __plot_curve(axis, xplot, yplot, i, **kwargs)

    if labels is not None:
        ncol = math.ceil(ncurve / 6 )
        axis.legend(loc=legend_loc, ncol=ncol, title=legend_title, bbox_to_anchor=(0.1, 0.1, 0.9, 0.9)).set_zorder(20)


def __plot_symbols(axis, x, y, loc, **kwargs):
    labels         = get_param_default_if_missing("labels", None, **kwargs)
    legend_loc     = get_param_default_if_missing("legend_loc", "best", **kwargs)
    legend_title   = get_param_default_if_missing("legend_title", None, **kwargs)
    markers        = get_param_default_if_missing("markers", None, **kwargs)
    marker_colors  = get_param_default_if_missing("marker_colors", None, **kwargs)
    npts           = get_param_default_if_missing("npts", None, **kwargs)

    ncurve = len(y)

    for i in range(ncurve):
        xplot = x[i]
        yplot = y[i]

        if npts is None or npts > len(yplot):
            npts = len(yplot)
        
        if not isinstance(xplot, (numpy.ndarray, numpy.generic)):
            raise Exception("x must be a numpy.array")

        if not isinstance(yplot, (numpy.ndarray, numpy.generic)):
            raise Exception("y must be a numpy.array")

        kwargs['marker'] = markers[i] if markers is not None else 'o'
        kwargs['color'] = marker_colors[i] if marker_colors is not None else None
        __plot_symbol(axis, xplot, yplot, loc+i, **kwargs)

    if labels is not None:
        ncol = math.ceil(ncurve / 6 )
        axis.legend(loc=legend_loc, ncol=ncol, title=legend_title, bbox_to_anchor=(0.1, 0.1, 0.9, 0.9)).set_zorder(20)


def __plot_symbol(axis, x, y, n, **kwargs):
    lw              = get_param_default_if_missing("lw", 2, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    color           = get_param_default_if_missing("color", None, **kwargs)
    plot_axis_type  = get_param_default_if_missing("plot_axis_type", PlotType.LINEAR, **kwargs)
    scilimits       = get_param_default_if_missing("scilimits", (-4, 4), **kwargs)
    ylim            = get_param_default_if_missing("ylim", None, **kwargs)
    xlim            = get_param_default_if_missing("xlim", None, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    npts            = get_param_default_if_missing("npts", min(len(y), len(x)), **kwargs)
    marker          = get_param_default_if_missing("marker", 'o', **kwargs)
    marker_size     = get_param_default_if_missing("marker_size", 5.0, **kwargs)
    alpha           = get_param_default_if_missing("alpha", 0.75, **kwargs)  

    if isinstance(x[0], pandas.Timestamp) or isinstance(x[0], datetime) or isinstance(x[0], numpy.datetime64) or isinstance(x[0], date):
        converter = mdates.ConciseDateConverter()
        munits.registry[numpy.datetime64] = converter
        munits.registry[date] = converter
        munits.registry[datetime] = converter 
    else:
        axis.ticklabel_format(style='sci', axis='x', scilimits=scilimits, useMathText=True)

    axis.ticklabel_format(style='sci', axis='y', scilimits=scilimits, useMathText=True)

    if xlim is not None:
        axis.set_xlim(xlim)

    if ylim is not None:
        axis.set_ylim(ylim)

    x = x[:npts]
    y = y[:npts]

    label = labels[n] if labels is not None and n < len(labels) else None

    if plot_axis_type.value == PlotType.LOG.value:
        logStyle(axis, x, y)
        axis.loglog(x, y, marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, 
                    alpha=alpha, zorder=5, label=label, color=color)
    elif plot_axis_type.value == PlotType.XLOG.value:
        logXStyle(axis, x, y)
        axis.semilogx(x, y, marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, 
                      alpha=alpha, zorder=5, label=label, color=color)
    elif plot_axis_type.value == PlotType.YLOG.value:
        logYStyle(axis, x, y)
        axis.semilogy(x, y, marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, 
                      alpha=alpha, zorder=5, label=label, color=color)
    else:
        axis.plot(x, y, marker=marker, markersize=marker_size, linestyle="None", markeredgewidth=1.0, 
                  alpha=alpha, zorder=5, label=label, color=color)


def __plot_bar(axis, x, y, shared_cycler, n, zorder=10, **kwargs):
    alpha            = get_param_default_if_missing("alpha", 0.5, **kwargs)
    border_width     = get_param_default_if_missing("border_width", 1, **kwargs)
    bar_width        = get_param_default_if_missing("bar_width", 1.0, **kwargs)
    labels           = get_param_default_if_missing("labels", None, **kwargs)
    colors           = get_param_default_if_missing("colors", None, **kwargs)
    bar_colors       = get_param_default_if_missing("bar_colors", None, **kwargs)
    scilimits        = get_param_default_if_missing("scilimits", (-3, 3), **kwargs)
    xlabel           = get_param_default_if_missing("xlabel", "x", **kwargs)
    xlabel_rotation  = get_param_default_if_missing("xlabel_rotation", None, **kwargs)
    ylabel           = get_param_default_if_missing("ylabel", "y", **kwargs)
    xlim             = get_param_default_if_missing("xlim", None, **kwargs)
    ylim             = get_param_default_if_missing("ylim", None, **kwargs)

    if x is None:
        x = numpy.linspace(0, len(y) - 1, len(y))

    if isinstance(x[0], pandas.Timestamp) or isinstance(x[0], datetime) or isinstance(x[0], numpy.datetime64) or isinstance(x[0], date):
        converter = mdates.ConciseDateConverter()
        munits.registry[numpy.datetime64] = converter
        munits.registry[date] = converter
        munits.registry[datetime] = converter 
    else:
        axis.ticklabel_format(style='sci', axis='x', scilimits=scilimits, useMathText=True)

    axis.ticklabel_format(style='sci', axis='y', scilimits=scilimits, useMathText=True)

    alpha_value = alpha[n] if isinstance(alpha, list) else alpha        

    if bar_colors is not None:
        color = bar_colors
    else:
        color = colors[n] if colors is not None and len(colors) > n else shared_cycler.get_next()['color']    


    label = labels[n] if labels is not None and len(labels) > n else None
    axis.set_ylabel(ylabel)
    axis.set_xlabel(xlabel)

    if xlim is not None:
        axis.set_xlim(xlim)

    if ylim is not None:
        axis.set_ylim(ylim)

    if isinstance(x[0], float) or isinstance(x[0], int):
        width = bar_width*(x[1]-x[0])
    else:
        width = bar_width

    if xlabel_rotation is not None:
        axis.tick_params("x", rotation=xlabel_rotation)

    return axis.bar(x, y, align='center', width=width, zorder=zorder, alpha=alpha_value, linewidth=border_width, label=label, color=color)


def __axis_twinx(axis, **kwargs):
    ylabel      = get_param_default_if_missing("ylabel", None, **kwargs)
    scilimits   = get_param_default_if_missing("scilimits", (-3, 3), **kwargs)

    axis2 = axis.twinx()
    axis2._get_lines.prop_cycler = axis._get_lines.prop_cycler

    if ylabel is not None:
        axis2.set_ylabel(ylabel, rotation=-90, labelpad=20)
    axis2.ticklabel_format(style='sci', axis='y', scilimits=scilimits, useMathText=True)

    __twinx_ticks(axis, axis2)
    axis2.grid(False)

    return axis2


def __twinx_ticks(axis1, axis2):
    y1_lim = axis1.get_ylim()
    y2_lim = axis2.get_ylim()
    f = lambda x : y2_lim[0] + (x - y1_lim[0])*(y2_lim[1] - y2_lim[0])/(y1_lim[1] - y1_lim[0])
    ticks = f(axis1.get_yticks())
    axis2.yaxis.set_major_locator(matplotlib.ticker.FixedLocator(ticks))

