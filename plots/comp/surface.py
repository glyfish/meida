import numpy
from matplotlib import pyplot, figure, colors
from labellines import labelLines, labelLine

from lib.plots.comp.axis import (PlotType, logStyle, logXStyle, logYStyle)
from lib.utils import get_param_default_if_missing
from lib import config


def contour(axis: pyplot.axis,  f: numpy.ndarray[float, float], x: numpy.ndarray[float, float],  y: numpy.ndarray[float, float], 
            values: numpy.ndarray[float], **kwargs):
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
    """

    title             = get_param_default_if_missing("title", None, **kwargs)
    title_offset      = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel            = get_param_default_if_missing("xlabel", "x", **kwargs)
    ylabel            = get_param_default_if_missing("ylabel", "y", **kwargs)
    xlim              = get_param_default_if_missing("xlim", None, **kwargs)
    ylim              = get_param_default_if_missing("ylim", None, **kwargs)
    contour_font_size = get_param_default_if_missing("contour_font_size", 15, **kwargs)

    if xlim is None:
        xlim = (numpy.min(x), numpy.max(x))
    if ylim is None:
        ylim = (numpy.min(y), numpy.max(y))
    axis.set_xlim(xlim)
    axis.set_ylim(ylim)

    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)

    axis.set_title(title, y=1.0 + title_offset)

    contour = axis.contour(x, y, f, values, cmap=config.contour_color_map)
    axis.clabel(contour, contour.levels, fmt="%.3f", inline=True, fontsize=contour_font_size)


def contour_hist(axis: pyplot.axis, figure: figure.Figure, samples: numpy.ndarray[float, float], f: numpy.ndarray[float, float], x: numpy.ndarray[float, float], 
                 y: numpy.ndarray[float, float], values: numpy.ndarray[float], **kwargs):
    """
    Overlay data shown in a contour plot with samples shown in a histogram.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    figure: matplotlib.figure.Figure
        Plot figure which is needed to add histogram scale.
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

    title             = get_param_default_if_missing("title", None, **kwargs)
    title_offset      = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel            = get_param_default_if_missing("xlabel", "x", **kwargs)
    ylabel            = get_param_default_if_missing("ylabel", "y", **kwargs)
    xlim              = get_param_default_if_missing("xlim", None, **kwargs)
    ylim              = get_param_default_if_missing("ylim", None, **kwargs)
    nbins             = get_param_default_if_missing("nbins", 100, **kwargs)
    contour_font_size = get_param_default_if_missing("contour_font_size", 15, **kwargs)

    if xlim is None:
        xlim = (numpy.min(x), numpy.max(x))
    if ylim is None:
        ylim = (numpy.min(y), numpy.max(y))
    axis.set_xlim(xlim)
    axis.set_ylim(ylim)

    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)

    axis.set_title(title, y=1.0 + title_offset)

    bins = [numpy.linspace(numpy.min(x), numpy.max(x), nbins), numpy.linspace(numpy.min(y), numpy.max(y), nbins)]
    _, _, _, image = axis.hist2d(samples[0], samples[1], density=True, bins=bins, cmap=config.alternate_color_map)
    figure.colorbar(image)

    contour = axis.contour(x, y, f, values, cmap=config.contour_color_map)
    axis.clabel(contour, contour.levels, fmt="%.3f", inline=True, fontsize=contour_font_size)


def colored_scatter(axis: pyplot.axis, figure: figure.Figure, y: numpy.ndarray[float], x: numpy.ndarray[float], color_values: numpy.ndarray[float], **kwargs):
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

    title             = get_param_default_if_missing("title", None, **kwargs)
    title_offset      = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel            = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel            = get_param_default_if_missing("ylabel", None, **kwargs)
    npts              = get_param_default_if_missing("npts", None, **kwargs)
    ylim              = get_param_default_if_missing("ylim", None, **kwargs)
    xlim              = get_param_default_if_missing("xlim", None, **kwargs)
    xscilimits        = get_param_default_if_missing("xscilimits", (-3, 3), **kwargs)
    yscilimits        = get_param_default_if_missing("yscilimits", (-3, 3), **kwargs)
    color_bar_label   = get_param_default_if_missing("color_bar_label", None, **kwargs)
    color_bar_limit   = get_param_default_if_missing("color_bar_limit", None, **kwargs)
    plot_axis_type    = get_param_default_if_missing("plot_axis_type", PlotType.LINEAR, **kwargs)
    labels            = get_param_default_if_missing("labels", None, **kwargs)
    legend_loc        = get_param_default_if_missing("legend_loc", "best", **kwargs)

    if title is not None:
        offset = 1.0 + title_offset
        axis.set_title(title, y=offset)

    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)

    axis.ticklabel_format(style='sci', axis='y', scilimits=yscilimits, useMathText=True)
    axis.ticklabel_format(style='sci', axis='x', scilimits=xscilimits, useMathText=True)

    if xlim is not None:
        axis.set_xlim(xlim)

    if ylim is not None:
        axis.set_ylim(ylim)

    if npts is None or npts > len(y):
        npts = len(y)
    
    if plot_axis_type.value == PlotType.LINEAR.value:
        plt = axis.scatter(x, y, marker="o", c=color_values, cmap=config.contour_color_map, zorder=5)
    elif plot_axis_type.value == PlotType.YLOG.value:
        logYStyle(axis, x, y)
        plt = axis.scatter(x, y, marker="o", c=color_values, cmap=config.contour_color_map, zorder=5)
        axis.set_yscale('log')
    elif plot_axis_type.value == PlotType.XLOG.value:
        logXStyle(axis, x, y)
        plt = axis.scatter(x, y, marker="o", c=color_values, cmap=config.contour_color_map, zorder=5)
        axis.set_xscale('log')
    elif plot_axis_type.value == PlotType.XYLOG.value:
        logStyle(axis, x, y)
        plt = axis.scatter(x, y, marker="o", c=color_values, cmap="magma", zorder=5, norm=colors.LogNorm())
        axis.set_yscale('log')
        axis.set_xscale('log')
    else:
        raise Exception("Invalid PlotAxisType")
    
    if labels is not None:
        axis.legend(loc=legend_loc, bbox_to_anchor=(0.1, 0.1, 0.9, 0.9))
    else:
        color_bar = figure.colorbar(plt, ax=axis)
        color_bar.set_label(color_bar_label, rotation = -90, labelpad=20)
        if color_bar_limit is not None:
            color_bar.mappable.set_clim(color_bar_limit[0], color_bar_limit[1])


def colored_scatter_contour(axis, figure, ydata, xdata, color_values, cont_ydata, cont_xdata, **kwargs):
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
    """

    title             = get_param_default_if_missing("title", None, **kwargs)
    title_offset      = get_param_default_if_missing("title_offset", 0.0, **kwargs)
    xlabel            = get_param_default_if_missing("xlabel", None, **kwargs)
    ylabel            = get_param_default_if_missing("ylabel", None, **kwargs)
    npts              = get_param_default_if_missing("npts", None, **kwargs)
    ylim              = get_param_default_if_missing("ylim", None, **kwargs)
    xlim              = get_param_default_if_missing("xlim", None, **kwargs)
    xscilimits        = get_param_default_if_missing("xscilimits", (-3, 3), **kwargs)
    yscilimits        = get_param_default_if_missing("yscilimits", (-3, 3), **kwargs)
    color_bar_label   = get_param_default_if_missing("color_bar_label", None, **kwargs)
    color_bar_limit   = get_param_default_if_missing("color_bar_limit", None, **kwargs)
    labels            = get_param_default_if_missing("labels", None, **kwargs)
    plot_axis_type    = get_param_default_if_missing("plot_axis_type", PlotType.LINEAR, **kwargs)
    lw                = get_param_default_if_missing("lw", 2, **kwargs)
    yoffsets          = get_param_default_if_missing("yoffsets", 0, **kwargs)
    xvals             = get_param_default_if_missing("xvals", None, **kwargs)

    if title is not None:
        offset = 1.0 + title_offset
        axis.set_title(title, y=offset)

    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)

    axis.ticklabel_format(style='sci', axis='y', scilimits=yscilimits, useMathText=True)
    axis.ticklabel_format(style='sci', axis='x', scilimits=xscilimits, useMathText=True)

    if xlim is not None:
        axis.set_xlim(xlim)

    if ylim is not None:
        axis.set_ylim(ylim)

    if npts is None or npts > len(ydata):
        npts = len(ydata)
    
    if plot_axis_type.value == PlotType.LINEAR.value:
        plt = axis.scatter(xdata, ydata, marker="o", c=color_values, cmap=config.contour_color_map, zorder=5)
    elif plot_axis_type.value == PlotType.YLOG.value:
        logYStyle(axis, xdata, ydata)
        plt = axis.scatter(xdata, ydata, marker="o", c=color_values, cmap=config.contour_color_map, zorder=5)
        axis.set_yscale('log')
    elif plot_axis_type.value == PlotType.XLOG.value:
        logXStyle(axis, xdata, ydata)
        plt = axis.scatter(xdata, ydata, marker="o", c=color_values, cmap=config.contour_color_map, zorder=5)
        axis.set_xscale('log')
    elif plot_axis_type.value == PlotType.XYLOG.value:
        logStyle(axis, xdata, ydata)
        plt = axis.scatter(xdata, ydata, marker="o", c=color_values, cmap=config.alternate_color_map, zorder=5, norm=colors.LogNorm())
        axis.set_yscale('log')
        axis.set_xscale('log')
    else:
        raise Exception("Invalid PlotType")
    
    color_bar = figure.colorbar(plt, ax=axis)
    color_bar.set_label(color_bar_label, rotation = -90, labelpad=20)

    if color_bar_limit is not None:
        color_bar.mappable.set_clim(color_bar_limit[0], color_bar_limit[1])


    ncurve = len(cont_ydata)
    for i in range(ncurve):
        yplot = cont_ydata[i]

        if npts is None or npts > len(yplot):
            npts = len(yplot)
        
        if not isinstance(cont_xdata, (numpy.ndarray, numpy.generic)):
            raise Exception("x must be a numpy.array")

        if not isinstance(yplot, (numpy.ndarray, numpy.generic)):
            raise Exception("y must be a numpy.array")

        label = labels[i] if labels is not None else None
        
        if plot_axis_type.value == PlotType.LINEAR.value:
            axis.plot(cont_xdata, yplot, lw=lw, label=label, color='grey')
        elif plot_axis_type.value == PlotType.YLOG.value:
            logYStyle(axis, cont_xdata, yplot)
            axis.semilogy(cont_xdata, yplot, lw=lw, label=label, color='grey')
        elif plot_axis_type.value == PlotType.XYLOG.value:
            axis.loglog(cont_xdata, yplot, lw=lw, label=label, color='grey')
        else:
            raise Exception("Invalid PlotAxisType")

    labelLines(axis.get_lines(), zorder=10, align=False, xvals=xvals, yoffsets=yoffsets)

