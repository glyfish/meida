import numpy
from matplotlib import pyplot

from lib.utils import get_param_default_if_missing
from lib.plots import comp

def contour(f: numpy.ndarray[float, float], x: numpy.ndarray[float, float], y: numpy.ndarray[float, float], values: numpy.ndarray[float], **kwargs):
    """
    Contour plot for f(x,y)

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    y : numpy.ndarray[float, float]
        Value plotted on y-axis.
    x : numpy.ndarray[float, float]
        Value plotted in x axis
    f : numpy.ndarray[float, float]
        Function contoured.
    values : numpy.ndarray[float]
        Values of contours plotted.
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    ylabel : string, optional
        Plot y-axis label (default is 'y')
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    figsize : (int, int)
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (7, 7), **kwargs)

    _, axis = pyplot.subplots(figsize=figsize)
    comp.contour(axis, f, x, y, values, **kwargs)


def contour_hist(samples: numpy.ndarray[float, float],
                 f: numpy.ndarray[float, float],
                 x: numpy.ndarray[float, float], 
                 y: numpy.ndarray[float, float], 
                 values: numpy.ndarray[float],
                 **kwargs):
    """
    Overlay data shown in a contour plot with samples shown in a histogram.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    samples : numpy.ndarray[float, float]
        Two dimensional array containing sampled data plotted in histogram,
    y : numpy.ndarray[float, float]
        Value plotted on y-axis.
    x : numpy.ndarray[float, float]
        Value plotted in x axis
    f : numpy.ndarray[float, float]
        Function contoured.
    values : numpy.ndarray[float]
        Values of contours plotted.
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is 'x')
    ylabel : string, optional
        Plot y-axis label (default is 'y')
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    nbins : int
        Number of bins used in histogram.
    """

    figsize = get_param_default_if_missing("figsize", (9, 7), **kwargs)

    figure, axis = pyplot.subplots(figsize=figsize)
    comp.contour_hist(axis, figure, samples, f, x, y, values, **kwargs)


def colored_scatter(y, x, color_values, **kwargs):
    """
    Make a scatter plot of the x and y data and color the scatter dots with value 
    specified in colors.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    figure: matplotlib.figure.Figure
        Plot figure which is needed to add histogram scale.
    y : numpy.ndarray[float]
        Data plotted in scatter plot y axis.
    x : numpy.ndarray[float]
        Data plotted in scatter plot x axis.
    color_values : numpy.ndarray[float]
        Data used to compute scatter point color.
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is None)
    ylabel : string, optional
        Plot y-axis label (default is None)
    color_bar_label : str
        Label shown to right of color bar (default None)
    npts : int, optional
        Number of points plotted (default is length of y)
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis are labeled using scientific notation. (default (-3, 3))
    plot_axis_type : PlotAxisType
        Plot axis type.
    color_bar_limit : (float, float)
        Color bar limits. (default None)
    legend_loc : string
        Specify legend location. (default best)
    """

    figsize = get_param_default_if_missing("figsize", (9, 7), **kwargs)

    figure, axis = pyplot.subplots(figsize=figsize)
    comp.colored_scatter(axis, figure, y, x, color_values, **kwargs)


def colored_scatter_contour(ydata, xdata, color_values, cont_ydata, cont_xdata, **kwargs):
    """
    Make a scatter plot of the x and y data and color the scatter dots with value 
    specified in colors.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    ydata : list[numpy.ndarray]
        Data plotted in scatter plot y axis.
    cont_ydata : list[numpy.ndarray]
        Contour y data
    cont_xdata : list[numpy.ndarray]
        Contour x data
    xdata : list[numpy.ndarray]
        Data plotted in scatter plot x axis.
    color_values : list[numpy.ndarray]
        Data used to compute scatter point color.
    cont_ydata : list[numpy.ndarray]
        Contour y data values
    cont_xdata : list[numpy.ndarray]
        Contour x data values
    title : string, optional
        Plot title (default is None)
    title_offset : float (default is 0.0)
        Plot title off set from top of plot.
    xlabel : string, optional
        Plot x-axis label (default is None)
    ylabel : string, optional
        Plot y-axis label (default is None)
    color_bar_label : str
        Label shown to right of color bar (default None)
    npts : int, optional
        Number of points plotted (default is length of y)
    ylim : (float, float)
        Specify the limits for the y axis. (default None)
    xlim : (float, float)
        Specify the limits for the x axis. (default None)
    scilimits : (-int, int)
        Specify the order where axis are labeled using scientific notation. (default (-3, 3))
    labels : [string], optional
        Curve labels shown in legend.
    plot_axis_type : PlotAxisType
        Plot axis type.
    lw : int, optional
        Plot line width (default is 2)
    color_bar_limit : (float, float)
        Color bar limits. (default None)
    legend_loc : string
        Specify legend location. (default best)
    """

    figsize = get_param_default_if_missing("figsize", (9, 7), **kwargs)

    figure, axis = pyplot.subplots(figsize=figsize)
    comp.colored_scatter_contour(axis, figure, ydata, xdata, color_values, cont_ydata, cont_xdata, **kwargs)
