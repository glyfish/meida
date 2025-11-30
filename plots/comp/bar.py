import numpy
import pandas
import matplotlib.dates as mdates
import matplotlib.units as munits
from matplotlib import rcParams
from matplotlib import pyplot
from datetime import datetime, date
from numpy.typing import NDArray

from lib.plots.comp.plot_utils import (__plot_curve, __plot_curves, __twinx_ticks, __plot_bar, __axis_twinx)

from lib.utils import get_param_default_if_missing

from lib import config
from lib.config import SharedCycler

def bar(axis: pyplot.axis, y: NDArray, x: NDArray=None, **kwargs):
    """
    Plot samples in a bar chart.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : numpy.ndarray[float]
        Value plotted on y-axis.
    x : numpy.ndarray
        Value plotted in x axis (default use y index)
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
    title_offset   = get_param_default_if_missing("title_offset", 0.0, **kwargs)

    if title is not None:
        axis.set_title(title, y=title_offset + 1.0)

    color_cycler = SharedCycler(rcParams['axes.prop_cycle'])
    __plot_bar(axis, x, y, color_cycler, 0, **kwargs)


def positive_negative_bar(axis: pyplot.axis, y: NDArray, x: NDArray=None, **kwargs):
    """
    Plot data in a bar chart with different colors for positive and negative values.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    pos : numpy.ndarray
        Positive data values.
    neg : numpy.ndarray
        Negative data values.
    x_pos : numpy.ndarray
        Value plotted in x axis for positive values (default use pos index)
    x_neg : numpy.ndarray
        Value plotted in x axis for negative values (default use neg index)
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
    colors : list[float]
        Bar colors
    """

    title          = get_param_default_if_missing("title", None, **kwargs)
    title_offset   = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    colors         = get_param_default_if_missing("colors", ('#006600', '#990000'), **kwargs)

    if title is not None:
        axis.set_title(title, y=title_offset + 1.0)
    
    kwargs["bar_colors"] = numpy.where(y > 0, colors[0], colors[1])

    __plot_bar(axis, x, y, 0, **kwargs)


def twinx_bar_line(axis: pyplot.axis, y_bar: NDArray, y_line: NDArray, x_bar: NDArray=None,
                    x_line: NDArray=None, **kwargs):
    """
    Bar plot and line plot using same x-axis but different scales on y-axis. Bar plot is on left y-axis
    and line plot is on right y-axis.
    
    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y_bar : numpy.ndarray
        Bar y axis plot data.
    y_line : numpy.ndarray
        Line y axis plot data.
    x_bar : numpy.array or numpy.ndarray, optional
        Value plotted on x-axis for bar plot. If property is an list each x is plotted with y of 
        same index (default is index values of y)
    x_line : numpy.array or numpy.ndarray, optional
        Value plotted on x-axis for bar plot. If property is an list each x is plotted with y of 
        same index (default is index values of y)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is None)
    bar_ylabel : string, optional
        Bar plot y-axis label (default is None)
    line_ylabel : string, optional
        Line plot left y-axis label (default is None)
    labels : [string], optional
        Curve labels shown in legend. Must have length of 2.
    lw : int, optional
        Plot line width (default is 2)
    npts : int, optional
        Number of points plotted (default is length of y)
    bar_ylim : (float, float)
        Specify the limits for the bar y axis. (default None)
    line_ylim : (float, float)
        Specify the limits for the right y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis is labeled using scientific notation. (default (-3, 3))
    legend_loc : string
        Specify legend location. (default best)
    prec : int
        Precision shown for y axis ticks.
    alpha : float
        Bar alpha (default 0.5)
    border_width : float
        Bar border width (default)
    bar_width : float
        Bar width ras faction of x delta.
    colors : list[float]
        Colors. Default uses color cycler
    """

    title           = get_param_default_if_missing("title", None, **kwargs)
    title_offset    = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    bar_ylabel      = get_param_default_if_missing("bar_ylabel", None, **kwargs)
    line_ylabel      = get_param_default_if_missing("line_ylabel", None, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    bar_ylim        = get_param_default_if_missing("bar_ylim", None, **kwargs)
    line_ylim       = get_param_default_if_missing("line_ylim", None, **kwargs)
    legend_loc      = get_param_default_if_missing("legend_loc", "best", **kwargs)

    if x_bar is None:
        x_bar = numpy.linspace(0, len(y_bar) - 1, len(y_bar))

    if x_line is None:
        x_line = numpy.linspace(0, len(y_line) - 1, len(y_line))

    if title is not None:
        axis.set_title(title, y=title_offset + 1.0)
    
    list1 = __plot_bar(axis, x_bar, y_bar, 0, 10, **dict(kwargs, ylim=bar_ylim, ylabel=bar_ylabel))
    axis2 = __axis_twinx(axis, ylabel=line_ylabel)
    list2 = __plot_curve(axis2, x_line, y_line, 1, **dict(kwargs, ylim=line_ylim, ylabel=line_ylabel))
    
    __twinx_ticks(axis, axis2)

    if labels is not None:
        list = [list1] + list2
        labs = [l.get_label() for l in list]
        axis.legend(list, labs, loc=legend_loc, bbox_to_anchor=(0.1, 0.1, 0.9, 0.9))



def twinx_bar_line_comparison(axis: pyplot.axis, y_bar: NDArray, y_line: NDArray, x_bar: NDArray=None,
                              x_line: NDArray=None, **kwargs):
    """
    Bar plot and comparison line plot using same x-axis but different scales on y-axis. Bar plot is on left y-axis
    and line plot is on right y-axis.
    
    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y_bar : numpy.ndarray
        Bar y axis plot data.
    y_line : numpy.ndarray
        Line y axis plot data.
    x_bar : numpy.array or numpy.ndarray, optional
        Value plotted on x-axis for bar plot. If property is an list each x is plotted with y of 
        same index (default is index values of y)
    x_line : numpy.array or numpy.ndarray, optional
        Value plotted on x-axis for bar plot. If property is an list each x is plotted with y of 
        same index (default is index values of y)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is None)
    bar_ylabel : string, optional
        Bar plot y-axis label (default is None)
    line_ylabel : string, optional
        Line plot left y-axis label (default is None)
    labels : [string], optional
        Curve labels shown in legend. Must have length of 2.
    lw : int, optional
        Plot line width (default is 2)
    npts : int, optional
        Number of points plotted (default is length of y)
    bar_ylim : (float, float)
        Specify the limits for the bar y axis. (default None)
    line_ylim : (float, float)
        Specify the limits for the right y axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis is labeled using scientific notation. (default (-3, 3))
    legend_loc : string
        Specify legend location. (default best)
    prec : int
        Precision shown for y axis ticks.
    alpha : float
        Bar alpha (default 0.5)
    border_width : float
        Bar border width (default)
    bar_width : float
        Bar width ras faction of x delta.
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    bar_color : list[float]
        Colors to use for bars. Default uses color cycler
    line_colors : list[float]
        Colors to use for lines. Default uses color cycler
    """

    title           = get_param_default_if_missing("title", None, **kwargs)
    title_offset    = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    bar_ylabel      = get_param_default_if_missing("bar_ylabel", None, **kwargs)
    line_ylabel      = get_param_default_if_missing("line_ylabel", None, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    bar_ylim        = get_param_default_if_missing("bar_ylim", None, **kwargs)
    line_ylim       = get_param_default_if_missing("line_ylim", None, **kwargs)
    legend_loc      = get_param_default_if_missing("legend_loc", "best", **kwargs)
    bar_color       = get_param_default_if_missing("bar_color", "#0067C4", **kwargs)
    line_colors      = get_param_default_if_missing("line_colors", None, **kwargs)

    if x_bar is None:
        x_bar = numpy.linspace(0, len(y_bar) - 1, len(y_bar))

    if x_line is None:
        x_line = numpy.linspace(0, len(y_line) - 1, len(y_line))

    if title is not None:
        axis.set_title(title, y=title_offset + 1.0)
    
    list1 = __plot_bar(axis, x_bar, y_bar, 0, 10, **dict(kwargs, ylim=bar_ylim, ylabel=bar_ylabel, colors=[bar_color]))
    axis2 = __axis_twinx(axis, ylabel=line_ylabel)
    list2 = __plot_curves(axis2, x_line, y_line, **dict(kwargs, ylim=line_ylim, ylabel=line_ylabel, colors=line_colors))
    
    __twinx_ticks(axis, axis2)

    if labels is not None:
        list = [list1] + list2
        labs = [l.get_label() for l in list]
        axis.legend(list, labs, loc=legend_loc, bbox_to_anchor=(0.1, 0.1, 0.9, 0.9))


def hist(axis: pyplot.axis, samples: NDArray, fx=None, **kwargs):
    """
    Plot samples in histogram and compare with given function.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    samples : numpy.ndarray
        Value plotted on y-axis.
    fx : function of x
        Comparison function (default is None)
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is None)
    ylabel : string, optional
        Plot y-axis label (default is 'y')
    lw : int, optional
        Plot line width if fx is present (default is 2)
    nbins : int, optional
        Number of histogram bins (default is 50)
    density : int, optional
        Normalize histogram to represent a probability density (dealt is True)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    labels : [string], optional
        Curve labels shown in legend. The first is for histogram and second is f(x) if provided
        and the labels are only shown of fx is not None (default None).
    legend_loc : string
        Specify legend location. (default best)
    """

    title           = get_param_default_if_missing("title", None, **kwargs)
    title_offset    = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel          = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel          = get_param_default_if_missing("ylabel", None, **kwargs)
    lw              = get_param_default_if_missing("lw", 2, **kwargs)
    nbins           = get_param_default_if_missing("nbins", None, **kwargs)
    density         = get_param_default_if_missing("density", True, **kwargs)
    ylim            = get_param_default_if_missing("ylim", None, **kwargs)
    xlim            = get_param_default_if_missing("xlim", None, **kwargs)
    labels          = get_param_default_if_missing("labels", None, **kwargs)
    legend_loc      = get_param_default_if_missing("legend_loc", "best", **kwargs)

    if title is not None:
        axis.set_title(title, y=title_offset)
    if xlabel is not None:
        axis.set_ylabel(xlabel)
    if ylabel is not None:
        axis.set_ylabel(ylabel)

    axis.set_prop_cycle(config.distribution_sample_cycler)

    if labels is not None:
        hist_label = labels[0] 
        fx_label = labels[1]

    _, bins, _ = axis.hist(samples, nbins, rwidth=0.8, density=density, label=hist_label, zorder=5)

    delta = (bins[-1] - bins[0]) / 500.0
    x = numpy.arange(bins[0], bins[-1], delta)

    if fx is not None:
        axis.plot(x, fx(x), lw=lw, zorder=6, label=fx_label)

    if ylim is not None:
        axis.set_ylim(ylim)

    if xlim is None:
        xlim = (x[0], x[-1])
    else:
        xlim = (bins[0], bins[-1])
    axis.set_xlim(xlim)

    if labels is not None:
        axis.legend(loc=legend_loc, bbox_to_anchor=(0.1, 0.1, 0.9, 0.9))

