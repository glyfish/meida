from matplotlib import pyplot
import numpy

from lib.utils import get_param_default_if_missing
from lib.plots import comp
from typing import Callable


def curve(y: numpy.ndarray, x: numpy.ndarray=None, **kwargs):
    """
    Plot a curve.

    Parameters
    ----------
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
    file_name : str, optional
        Save generated plot to file if present (default is None)
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)
    file_name = get_param_default_if_missing("file_name", None, **kwargs)

    fig, axis = pyplot.subplots(figsize=figsize)
    comp.curve(axis, y, x, **kwargs)

    if file_name is not None:
        fig.savefig(file_name)
        pyplot.close(fig)


def comparison(y: list[numpy.ndarray], x=None, **kwargs):
    """
    Plot multiple curves on same scale.

    Parameters
    ----------
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
        Plot x-axis label (default is 'x')
    labels : [string], optional
        Curve labels shown in legend.
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
    legend_loc : string
        Specify legend location. (default best)
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.comparison(axis, y, x=x, **kwargs)


def stack(y: list[numpy.ndarray], x=None, **kwargs):
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
    lw : int
        Line width. (default 1)
    npts : int
        Number of points to plot. (default len(y))
    figsize : (int, int)
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    nplot = len(y)
    _, axis = pyplot.subplots(nplot, sharex=True, figsize=figsize)
    comp.stack(axis, y=y, x=x, **kwargs)


def comparison_stack(y: list[numpy.ndarray], x=None, **kwargs):
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
    xlim : (float, float)
        X-axis limits. (default None)
    ylim : (float, float)
        Y-axis limits. (default None)
    lw : int
        Line width. (default 1)
    figsize : (int, int)
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    nplot = len(y)
    _, axis = pyplot.subplots(nplot, sharex=True, figsize=figsize)
    comp.comparison_stack(axis, y=y, x=x, **kwargs)


def twinx(left: numpy.ndarray[float], right: numpy.ndarray[float], x=None, **kwargs):
    """
    Plot two curves with different scales on the y-axis that use the same scale on the
    x-axis.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    left_ylabel : string, optional
        Plot left y-axis label (default is 'y')
    right_ylabel : string, optional
        Plot left y-axis label (default is 'y')
    labels : [string], optional
        Curve labels shown in legend.
    lw : int, optional
        Plot line width (default is 2)
    npts : int, optional
        Number of points plotted (default is length of y)
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis are labeled using scientific notation. (default (-3, 3))
    legend_loc : string
        Specify legend location. (default best)
    prec : int
        Precision shown for y axis ticks.
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
   """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.twinx(axis, left, right, x, **kwargs)


def twinx_comparison(left: list[numpy.ndarray], right: list[numpy.ndarray], x: numpy.ndarray=None, **kwargs):
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.twinx_comparison(axis, left=left, right=right, x=x, **kwargs)


def bar(y, x=None, **kwargs):
    """
    Plot samples in a bar chart.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : numpy.ndarray
        Value plotted on y-axis.
    x : numpy.ndarray
        Value plotted in x axis (use y index)
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
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
    file_name : str, optional
        Save generated plot to file if present (default is None)
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)
    file_name = get_param_default_if_missing("file_name", None, **kwargs)

    fig, axis = pyplot.subplots(figsize=figsize)
    comp.bar(axis, y, x, **kwargs)

    if file_name is not None:
        fig.savefig(file_name, bbox_inches='tight', dpi=300)
        pyplot.close(fig)


def twinx_bar_line(y_bar: numpy.ndarray, y_line: numpy.ndarray, x_bar: numpy.ndarray=None, x_line: numpy.ndarray=None, **kwargs):
    """
    Plot two curves with different scales on the y-axis that use the same scale on the
    x-axis.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    bar : numpy.ndarray
        Bar plot data.
    line : numpy.ndarray
        Line plot data.
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
    prec : int
        Precision shown for y axis ticks.
    alpha : float
        Bar alpha (default 0.5)
    border_width : float
        Bar border width (default)
    bar_width : float
        Bar width ras faction of x delta.
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
   """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.twinx_bar_line(axis, y_bar, y_line, x_bar, x_line, **kwargs)


def hist(samples: numpy.ndarray, fx=None, **kwargs):
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.hist(axis, samples, fx, **kwargs)


def fpoints(data: numpy.ndarray[float], func: numpy.ndarray[float], x: numpy.ndarray=None, fx: numpy.ndarray=None, **kwargs):
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (10,8))
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.fpoints(axis, data, func, x, fx, **kwargs)


def fcurve(data: numpy.ndarray[float], func: numpy.ndarray[float], x: numpy.ndarray=None, fx: numpy.ndarray=None, **kwargs):
    """"
    Compare data to a function by plotting the data and functions as curves.

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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (10,8))
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.fcurve(axis, data, func, x, fx, **kwargs)


def fscatter(data: numpy.ndarray[float], func: Callable[[float], float], x: numpy.ndarray[float]=None, **kwargs):
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (10,8))
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
  """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.fscatter(axis, data, func, x, **kwargs)


def fcurve_scatter_comparison(data: list[numpy.ndarray[float]], func: Callable[[float], float], x: numpy.ndarray[float]=None, 
                              fx: numpy.ndarray[float]=None, **kwargs):
    """"
    Compare a function curve to multiple datasets by plotting the functions as a curve and data 
    as a scatter plot.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : numpy.ndarray
        Data compared to function.
    func : numpy.ndarray[float]
        Function plotted as a function of x.
    x : numpy.ndarray[float], optional
        Value plotted on x-axis (default is index values of data)
    fx : numpy.ndarray[float], optional
        function x values (default is index values of data)
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
   """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.fcurve_scatter_comparison(axis, data, func, x, fx, **kwargs)


def fbar(y: numpy.ndarray[float], fy: numpy.ndarray[float], x: numpy.ndarray=None, fx: numpy.ndarray=None, **kwargs):
    """
    Plot samples in a bar chart and compare to a function.

    Parameters
    ----------
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
   """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.fbar(axis, y, fy, x=x, fx=fx, **kwargs)


def scatter(y: numpy.ndarray[float], x: numpy.ndarray[float], **kwargs):
    """"
    Compare data to a function by plotting the functions as a curve and as a scatter plot..

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : numpy.ndarray
        Data plotted on y-axis.
    x : numpy.ndarray[float]
        Value plotted on x-axis
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
    markers : list[string]
        Symbols used to mark data points. (default 'o')
    marker_size : float
        Symbols used to mark data points. (default 'o')
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
   """
    
    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.scatter(axis, y, x, **kwargs)


def scatter_comparison(y: numpy.ndarray[float], x: numpy.ndarray[float], **kwargs):
    """"
    Compare data to a function by plotting the functions as a curve and as a scatter plot..

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : numpy.ndarray
        Data plotted on y-axis.
    x : numpy.ndarray[float]
        Value plotted on x-axis
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    ylabel : string, optional
        Plot y-axis label (default is 'y')
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
   """
    
    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.scatter(axis, y, x, **kwargs)


def positive_negative_bar(y: numpy.ndarray[float], x: numpy.ndarray=None, **kwargs):
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
    figsize : (int, int), optional
        Specify the width and height of plot (default is (8,6))
   """
    
    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.positive_negative_bar(axis, y, x, **kwargs)


