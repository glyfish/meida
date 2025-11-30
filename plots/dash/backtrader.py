from matplotlib import pyplot
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D

import numpy
from pandas import DataFrame

from lib.utils import get_param_default_if_missing
from lib.plots import comp
from typing import Callable
from lib.data import stats
from lib.trading.metrics import compute_sharpe_ratio, compute_rate_of_return, compute_daily_rate_of_return


def price_series(data: DataFrame, **kwargs):
    """
    Plot asset price series.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize)

    date = data.date.to_numpy()
    close = data.close_price.to_numpy()
    ticker = data.ticker[0]

    mean = numpy.full(len(data), numpy.mean(close))

    title = f"{ticker} Price Series"

    comp.comparison(axis, [close, mean], date, title=title, xlabel="Date", ylabel="Price", labels=[ticker, 'Mean'], lw=1)


def asset_price(data: DataFrame, **kwargs):
    """
    Plot asset price series.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize)

    ticker = data.ticker[0]
    run_id = data.run_id[0]
    ensemble_id = data.ensemble_id[0]

    title = f"{ticker} Asset Price Series\nRun ID: {run_id}, Ensemble ID: {ensemble_id}"

    __asset_price(axis, data, title=title)


def zscore_indicator(data: DataFrame, **kwargs):
    """
    Plot zscore indicator time series.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    mean_reversion_half_life : int
        Mean reversion half life for price series.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize)

    ticker = data.ticker[0]
    mean_reversion_half_life = data.half_life.iloc[0]
    stake_multiple = data.stake_multiple.iloc[0]
    run_id = data.run_id[0]
    ensemble_id = data.ensemble_id[0]

    title = f"{ticker}, Z-Score Indicator Time Series\n" + \
            f"$t_{{1/2}}$={mean_reversion_half_life}, Stake Multiple={stake_multiple}\n" + \
            f"Run ID: {run_id}, Ensemble ID: {ensemble_id}"

    __zscore_indicator(axis, data, title=title)  


def cash_value(data: DataFrame, **kwargs):
    """
    Plot cash and value time series.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize)

    run_id = data.run_id[0]
    ensemble_id = data.ensemble_id[0]

    title = f"Account Balance\nRun ID: {run_id}, Ensemble ID: {ensemble_id}"

    __cash_value(axis, data, title=title)


def position(data: DataFrame, **kwargs):
    """
    Plot position size and value time series.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize    = get_param_default_if_missing("figsize", (10,6), **kwargs)
    lw         = get_param_default_if_missing("lw", 2, **kwargs)
    legend_loc = get_param_default_if_missing("legend_loc", "best", **kwargs)
    alpha      = get_param_default_if_missing("alpha", 0.5, **kwargs)

    _, axis = pyplot.subplots(2, figsize=figsize, sharex=True, sharey=False)

    position = data['size'].to_numpy()
    price = data.price.to_numpy()
    date = data.date.to_numpy()
    value = -price * position

    date = data.date.to_numpy()
    ticker = data.ticker.iloc[0]
    run_id = data.run_id.iloc[0]
    ensemble_id = data.ensemble_id.iloc[0]

    position_colors = ['#ff8c1a', '#5900b3']
    
    title = f"{ticker} Position Size and Value\nRun ID: {run_id}, Ensemble ID: {ensemble_id}"

    comp.positive_negative_bar(axis[0], position, date, title=title, xlabel=None, ylabel="Size", lw=lw, 
                               colors=position_colors, alpha=alpha)

    comp.positive_negative_bar(axis[1], value, date, xlabel="Date", ylabel="Value (Dollars)", lw=lw, alpha=alpha)
        
    custom_lines = [Line2D([0], [0], color=position_colors[0], lw=2, alpha=alpha),
                    Line2D([0], [0], color=position_colors[1], lw=2, alpha=alpha)]
    axis[0].legend(custom_lines, ['Long', 'Short'], loc=legend_loc, 
                   bbox_to_anchor=(0.05, 0.05, 0.95, 0.95)).set_zorder(20)


def position_value(data: DataFrame, **kwargs):
    """
    Plot profit and loss time series. Inputs data must be a closed trade or order,

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (9,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize, sharex=True, sharey=False)


    ticker = data.ticker.iloc[0]
    run_id = data.run_id.iloc[0]
    ensemble_id = data.ensemble_id.iloc[0]

    title = f"{ticker} Position Value\nRun ID: {run_id}, Ensemble ID: {ensemble_id}"

    __position_value(axis, data, title=title)


def orders(order_data: DataFrame, asset_price_data: DataFrame, **kwargs):
    """
    Plot order size and value time series.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    symbol_offset_factor : float
        Symbol offset factor.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize, sharex=True, sharey=False)

    ticker = order_data.ticker.iloc[0]
    run_id = order_data.run_id.iloc[0]
    ensemble_id = order_data.ensemble_id.iloc[0]

    title = f"{ticker} Order Size and Value\nRun ID: {run_id}, Ensemble ID: {ensemble_id}"

    __orders(axis, order_data, asset_price_data, title=title)


def order_value(order_data: DataFrame, **kwargs):
    """
    Plot order value time series. Sell orders have positive value and buy 
    orders have negative value.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    symbol_offset_factor : float
        Symbol offset factor.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize, sharex=True, sharey=False)

    ticker = order_data.ticker.iloc[0]
    run_id = order_data.run_id.iloc[0]
    ensemble_id = order_data.ensemble_id.iloc[0]

    title = f"{ticker} Order Value\nRun ID: {run_id}, Ensemble ID: {ensemble_id}"

    __order_value(axis, order_data, title=title)


def order_pnl(data: DataFrame, **kwargs):
    """
    Plot profit and loss time series computed from orders.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    pnl(data.query('order_status == "Completed"'))


def trade_pnl(data: DataFrame, **kwargs):
    """
    Plot profit and loss time series computed from trades.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    pnl(data.query('status == "Closed"'))


def pnl(data: DataFrame, **kwargs):
    """
    Plot profit and loss time series. Inputs data must be a closed trade or order,

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (9,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize, sharex=True, sharey=False)


    ticker = data.ticker.iloc[0]
    run_id = data.run_id.iloc[0]
    ensemble_id = data.ensemble_id.iloc[0]

    title = f"{ticker} Profit and Loss\nRun ID: {run_id}, Ensemble ID: {ensemble_id}"

    __pnl(axis, data, title=title)


def returns(data: DataFrame, **kwargs):
    """
    Returns time series,

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (9,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize, sharex=True, sharey=False)


    ticker = data.ticker.iloc[0]
    run_id = data.run_id.iloc[0]
    ensemble_id = data.ensemble_id.iloc[0]

    title = f"{ticker} Daily and Cumulative Returns\nRun ID: {run_id}, Ensemble ID: {ensemble_id}"
    __returns(axis, data, title=title)


def sharpe_ratio(data: DataFrame, **kwargs):
    """
    Returns time series,

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (9,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize, sharex=True, sharey=False)


    ticker = data.ticker.iloc[0]
    run_id = data.run_id.iloc[0]
    ensemble_id = data.ensemble_id.iloc[0]

    sharpe_ratio = compute_sharpe_ratio(data)

    title = f"{ticker} Sharpe Ratio\nRun ID: {run_id}, Ensemble ID: {ensemble_id}\nSharpe Ratio: {sharpe_ratio:2.2f}"
    __sharpe_ratio(axis, data, title=title)


def zscore_indicator_position(zscore: DataFrame, position: DataFrame, **kwargs):
    """
    Plot comparing zscore indicator and position time series.

    Parameters
    ----------
    zscore : DataFrame
        Z-Score data to plot.
    position : DataFrame
        Position data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize)

    mean_reversion_half_life = zscore.half_life.iloc[0]
    stake_multiple = zscore.stake_multiple.iloc[0]
    ticker = zscore.ticker.iloc[0]
    run_id = zscore.run_id.iloc[0]
    ensemble_id = zscore.ensemble_id.iloc[0]

    title = f"{ticker}, Z-Score Indicator Time Series\n" + \
            f"$t_{{1/2}}$={mean_reversion_half_life}, Stake Multiple={stake_multiple}\n" + \
            f"Run ID: {run_id}, Ensemble ID: {ensemble_id}"

    __zscore_indicator_position(axis, zscore, position, title=title)


def daily_returns_distribution(orders: DataFrame, **kwargs):
    """
    Plot daily returns distribution.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    orders : DataFrame
        Data to plot.
    title : str
        Figure title.
    nbins : iny
        Number of distribution bins.
    """

    figsize = get_param_default_if_missing("figsize", (10,5), **kwargs)
    _, axis = pyplot.subplots(figsize=figsize)

    ticker = orders.ticker.iloc[0]
    run_id = orders.run_id.iloc[0]
    ensemble_id = orders.ensemble_id.iloc[0]

    title = f"{ticker}, Distribution of Returns\n" + \
            f"Run ID: {run_id}, Ensemble ID: {ensemble_id}"
    
    __daily_returns_distribution(axis, orders, title=title)


def zscore_backtest(broker: DataFrame, zscore_indicator: DataFrame, position: DataFrame, asset: DataFrame, 
                         orders: DataFrame, **kwargs):
    """
    Plot backtest results for long z-score strategy.

    Parameters
    ----------
    broker : DataFrame
        Broker data.
    indicator : DataFrame
        Indicator data.
    position : DataFrame
        Position data.
    asset : DataFrame
        Asset data.
    orders : DataFrame
        Order data.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,14), **kwargs)
    strategy = get_param_default_if_missing("strategy", "Backtest for Long-Short Z-Score Strategy", **kwargs)

    completed_orders = orders.query('order_status == "Completed"')

    fig = pyplot.figure(constrained_layout=True, figsize=figsize)

    spec = gridspec.GridSpec(ncols=1, nrows=11, figure=fig)

    ax1 = fig.add_subplot(spec[0, 0])
    ax2 = fig.add_subplot(spec[1, 0], sharex=ax1)
    ax3 = fig.add_subplot(spec[2:5, 0], sharex=ax1)
    ax4 = fig.add_subplot(spec[5:7, 0], sharex=ax1)
    ax5 = fig.add_subplot(spec[7:9, 0], sharex=ax1)
    ax6 = fig.add_subplot(spec[9:, 0], sharex=ax1)

    ticker = orders.ticker.iloc[0]
    run_id = orders.run_id.iloc[0]
    ensemble_id = orders.ensemble_id.iloc[0]
    mean_reversion_half_life = zscore_indicator.half_life.iloc[0]
    stake_multiple = zscore_indicator.stake_multiple.iloc[0]
    
    title = f"{strategy}, {ticker}\n" + \
            f"$t_{{1/2}}$={mean_reversion_half_life:2.2f}, Stake Multiple={stake_multiple}\n" + \
            f"Run ID: {run_id}, Ensemble ID: {ensemble_id}"
    ax1.set_title(title, y=1.1)

    __cash_value(ax1, broker, lw=1)
    __position_value(ax2, position)
    __orders(ax3, orders, asset)
    __pnl(ax4, completed_orders, lw=1)
    __order_value(ax5, orders)
    __zscore_indicator_position(ax6, zscore_indicator, position)

    ax1.set_xlabel(None)
    ax2.set_xlabel(None)
    ax3.set_xlabel(None)
    ax4.set_xlabel(None)
    ax5.set_xlabel(None)

    pyplot.setp(ax1.get_xticklabels(), visible=False)
    pyplot.setp(ax2.get_xticklabels(), visible=False)
    pyplot.setp(ax3.get_xticklabels(), visible=False)
    pyplot.setp(ax4.get_xticklabels(), visible=False)
    pyplot.setp(ax5.get_xticklabels(), visible=False)


def metrics(backtest: DataFrame, orders: DataFrame, **kwargs):
    """
    Plot backtest results for long z-score strategy.

    Parameters
    ----------
    backtest: DataFrame
        Backtest data
    orders : DataFrame
        Order data.
    figsize : Tuple[int, int]
        Figure size.
    """

    figsize = get_param_default_if_missing("figsize", (10,12), **kwargs)

    completed_orders = orders.query('order_status == "Completed"')

    fig = pyplot.figure(constrained_layout=True, figsize=figsize)

    spec = gridspec.GridSpec(ncols=1, nrows=8, figure=fig)

    ax1 = fig.add_subplot(spec[0:2, 0])
    ax2 = fig.add_subplot(spec[2:4, 0], sharex=ax1)
    ax3 = fig.add_subplot(spec[4:6, 0], sharex=ax1)
    ax4 = fig.add_subplot(spec[6:, 0], sharex=ax1)

    ticker = orders.ticker.iloc[0]
    strategy = backtest.strategy.iloc[0]
    run_id = orders.run_id.iloc[0]
    ensemble_id = orders.ensemble_id.iloc[0]
    
    sharpe_ratio = compute_sharpe_ratio(orders)
    rate_of_return = compute_rate_of_return(orders)

    title = f"Strategy Metrics: {ticker}, {strategy}\n" + \
            f"Run ID: {run_id}, Ensemble ID: {ensemble_id}\n" + \
            f"Sharpe Ratio: {sharpe_ratio:2.2f}, Rate of Return: {rate_of_return:2.2f}"
    
    ax1.set_title(title, y=1.1)

    __pnl(ax1, completed_orders, lw=1)
    __gross_value(ax2, orders)
    __returns(ax3, orders)
    __sharpe_ratio(ax4, orders)

    ax1.set_xlabel(None)
    ax2.set_xlabel(None)
    ax3.set_xlabel(None)

    pyplot.setp(ax1.get_xticklabels(), visible=False)
    pyplot.setp(ax2.get_xticklabels(), visible=False)
    pyplot.setp(ax3.get_xticklabels(), visible=False)


"""
Reusable plot components.

__zscore_indicator
    Plot zscore indicator time series.
__zscore_indicator_position
    Plot zscore indicator comparison with position..
__asset_price
    Plot asset price series.
__pnl
    Plot profit and loss time series.
___returns
    Plot daily and cumulative returns
__sharpe_ratio
    Plot sharpe ratio and average and daily returns and variance of daily returns
__orders
    Plot when orders type occurs compared with asset price.
__order_value
    Plot but and sell order value time series.
__cash_value
    Plot cash, spend value time series.
__position_value
    Plot position value time series.
__daily_returns_distribution
    Plot daily returns distribution.
"""
def __zscore_indicator(axis: pyplot.axis, data: DataFrame, **kwargs):
    """
    Plot zscore indicator time series.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : DataFrame
        Data to plot.
    """

    title = get_param_default_if_missing("title", None, **kwargs)


    date = data.date.to_numpy()
    zscore = data.zscore.to_numpy()

    zero = numpy.full(len(zscore), 0.0)

    comp.comparison(axis, [zscore, zero], date, title=title, xlabel="Date", 
                    ylabel="Z-Score", lw=1)


def __zscore_indicator_position(axis: pyplot.axis, zscore_data: DataFrame, position_data: DataFrame, **kwargs):
    """
    Plot zscore indicator time series.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    zscore : DataFrame
        Z-Score data to plot.
    position : DataFrame
        Position data to plot.
    colors : list[str]
        Colors to use for positive and negative returns.
    lw : int
        plot line width
    alpha : float
        bar chart alpha.
    """

    title            = get_param_default_if_missing("title", None, **kwargs)
    lw               = get_param_default_if_missing("lw", 1, **kwargs)
    legend_loc       = get_param_default_if_missing("legend_loc", "upper center", **kwargs)
    alpha            = get_param_default_if_missing("alpha", 0.25, **kwargs)

    bar_colors = ( '#007700', '#770000')
    line_colors = ['#FF9500', '#0067C4']

    position = position_data['size'].to_numpy()
    position_max = numpy.max(numpy.abs(position))
    position_date = position_data.date.to_numpy()

    zscore = zscore_data.zscore.to_numpy()
    max_zscore = numpy.max(numpy.abs(zscore))
    zscore_date = zscore_data.date.to_numpy()
    zero = numpy.full(len(zscore), 0.0)

    size_colors = numpy.where(position > 0, bar_colors[0], bar_colors[1])
    comp.twinx_bar_line_comparison(axis, position, [zero, zscore], position_date, [zscore_date, zscore_date], title=title, xlabel="Date", 
                                   bar_ylabel="Position Size", line_ylabel="Z-Score", lw=lw, alpha=alpha, bar_color=size_colors, line_colors=line_colors,
                                   line_ylim=(-max_zscore, max_zscore), bar_ylim=(-position_max, position_max))

    custom_lines = [Line2D([0], [0], color=bar_colors[0], lw=1, alpha=alpha),
                    Line2D([0], [0], color=bar_colors[1], lw=1, alpha=alpha),
                    Line2D([0], [0], color=line_colors[1], lw=1)]
    
    axis.legend(custom_lines, ['Long', 'Short', 'Z-Score'], loc=legend_loc, 
                bbox_to_anchor=(0.05, 0.05, 0.95, 0.95)).set_zorder(20)


def __asset_price(axis: pyplot.axis, data: DataFrame, **kwargs):
    """
    Plot asset price series.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : DataFrame
        Data to plot.
    title : str
        Figure title.
    """

    title = get_param_default_if_missing("title", None, **kwargs)

    date = data.date.to_numpy()
    close = data.close_price.to_numpy()
    ticker = data.ticker.iloc[0]
    run_id = data.run_id.iloc[0]
    ensemble_id = data.ensemble_id.iloc[0]

    comp.curve(axis, close, date, title=title, xlabel="Date", ylabel="Price", label=ticker, lw=1)


def __pnl(axis: pyplot.axis, data: DataFrame, **kwargs):
    """
    Plot profit and loss time series.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : DataFrame
        Data to plot.
    colors : list[str]
        Colors to use for positive and negative returns.
    lw : int
        plot line width
    alpha : float
        bar chart alpha.
    title : str
        Figure title.
    legend_loc : string
        Specify legend location. (default best)
    """

    title            = get_param_default_if_missing("title", None, **kwargs)
    colors           = get_param_default_if_missing("colors", ('#006600', '#990000'), **kwargs)
    lw               = get_param_default_if_missing("lw", 1, **kwargs)
    legend_loc       = get_param_default_if_missing("legend_loc", "lower left", **kwargs)
    alpha            = get_param_default_if_missing("alpha", 0.5, **kwargs)

    pnl = data.pnl.to_numpy()
    pnl_date = data.date.to_numpy()
    cumulative_pnl = data.pnl.cumsum().to_numpy()

    max_pnl = numpy.max(numpy.abs(pnl))
    max_cumulative_pnl = numpy.max(numpy.abs(cumulative_pnl))

    bar_colors = numpy.where(pnl > 0, colors[0], colors[1])

    comp.twinx_bar_line(axis, pnl, cumulative_pnl, pnl_date, pnl_date, title=title, xlabel="Date", 
                        bar_ylabel="Order PnL", line_ylabel="Cumulative PnL", lw=lw, 
                        bar_colors=bar_colors, alpha=alpha, line_ylim=(-max_cumulative_pnl, max_cumulative_pnl),
                        bar_ylim=(-max_pnl, max_pnl))
    
    custom_lines = [Line2D([0], [0], color=colors[0], lw=2, alpha=alpha),
                    Line2D([0], [0], color=colors[1], lw=2, alpha=alpha),
                    Line2D([0], [0], color='#0067C4', lw=2)]
    
    legend = axis.legend(custom_lines, ['Profit', 'Loss', 'Cumulative'], loc=legend_loc, 
                         bbox_to_anchor=(0.05, 0.05, 0.95, 0.95))
    legend.set_zorder(102)


def __returns(axis: pyplot.axis, orders: DataFrame, **kwargs):
    """
    Daily returns are computed using the method described on page 98 of Algorithmic
    Trading by Ernest Chan.

    The gross portfolio market value denoted by G is given by,
        G = abs(order size)

    The daily return is given by,

        r = Daily Profit Loss / G

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : DataFrame
        Data to plot.
    colors : list[str]
        Colors to use for positive and negative returns.
    alpha : float
        bar chart alpha.
    lw : int
        plot line width
    title : str
        Figure title.
    legend_loc : string
        Specify legend location. (default best)
    """

    title            = get_param_default_if_missing("title", None, **kwargs)
    colors           = get_param_default_if_missing("colors", ('#006600', '#990000'), **kwargs)
    lw               = get_param_default_if_missing("lw", 1, **kwargs)
    legend_loc       = get_param_default_if_missing("legend_loc", "lower left", **kwargs)
    alpha            = get_param_default_if_missing("alpha", 0.5, **kwargs)

    completed_orders = orders.query('order_status == "Completed"')
    pnl_date = completed_orders.date.to_numpy()

    pnl = completed_orders.pnl.to_numpy()
    cost = numpy.abs(completed_orders['size'].to_numpy() * completed_orders.price.to_numpy())
    daily_return = 100.0 * (pnl / cost)

    cumulative_pnl = completed_orders.pnl.cumsum().to_numpy()
    cumulative_cost = numpy.cumsum(cost)
    cumulative_return = 100.0 * (cumulative_pnl / cumulative_cost)

    max_daily_return = numpy.max(numpy.abs(daily_return))
    max_cumulative_daily_return = numpy.max(numpy.abs(cumulative_return))

    bar_colors = numpy.where(daily_return > 0, colors[0], colors[1])

    comp.twinx_bar_line(axis, daily_return, cumulative_return, pnl_date, pnl_date, title=title, xlabel="Date", 
                        bar_ylabel="Daily Returns (%)", line_ylabel="Cumulative Returns (%)", lw=lw, bar_colors=bar_colors, alpha=alpha, 
                        line_ylim=(-max_cumulative_daily_return, max_cumulative_daily_return), bar_ylim=(-max_daily_return, max_daily_return))
    
    custom_lines = [Line2D([0], [0], color=colors[0], lw=2, alpha=alpha),
                    Line2D([0], [0], color=colors[1], lw=2, alpha=alpha),
                    Line2D([0], [0], color='#0067C4', lw=2)]
    
    legend = axis.legend(custom_lines, ['Profit', 'Loss', 'Cumulative'], loc=legend_loc, 
                         bbox_to_anchor=(0.05, 0.05, 0.95, 0.95))
    legend.set_zorder(102)


def __sharpe_ratio(axis, orders: DataFrame, risk_free_return: float=0.0, **kwargs):
    """
    Plot sharpe ratio and average and daily returns and variance of daily returns
    
    The gross portfolio market value denoted by G is given by,
        G = abs(order size * cost)

    The daily return is given by,

        r = Daily Profit Loss / G

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : DataFrame
        Data to plot.
    risk_free_return: float
        Risk free return rate.
    colors : list[str]
        Colors to use for positive and negative returns.
    alpha : float
        bar chart alpha.
    lw : int
        plot line width
    title : str
        Figure title.
    legend_loc : string
        Specify legend location. (default best)
    """

    title            = get_param_default_if_missing("title", None, **kwargs)
    lw               = get_param_default_if_missing("lw", 1, **kwargs)

    completed_orders = orders.query('order_status == "Completed"')
    pnl_date = completed_orders.date.to_numpy()

    pnl = completed_orders.pnl.to_numpy()
    cost = numpy.abs(completed_orders['size'].to_numpy() * completed_orders.price.to_numpy())

    daily_return = 100.0 * (pnl / cost) - risk_free_return
    _, cumulative_avg_daily_return = stats.compute_cumu_mean(pnl_date, daily_return)
    _, cumulative_sd_daily_return = stats.compute_cumu_sd(pnl_date, daily_return)

    vals = cumulative_sd_daily_return != 0

    cumulative_share_ratio = cumulative_avg_daily_return[vals] / cumulative_sd_daily_return[vals]

    comp.twinx_comparison(axis, [cumulative_avg_daily_return, cumulative_sd_daily_return], [cumulative_share_ratio], pnl_date[vals], 
                          labels=[r"Return $\mu$", r"Return $\sigma$", 'Sharpe Ratio'], title=title, xlabel="Date", 
                          left_ylabel="Return (%)", right_ylabel="Sharpe Ratio", lw=lw)


def __gross_value(axis: pyplot.axis, data: DataFrame, **kwargs):
    """
    Gross value of buy and sell orders.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : DataFrame
        Data to plot.
    title : str
        Figure title.
    legend_loc : string
        Specify legend location. (default best)
    """

    title            = get_param_default_if_missing("title", None, **kwargs)
    lw               = get_param_default_if_missing("lw", 1, **kwargs)
    alpha            = get_param_default_if_missing("alpha", 0.5, **kwargs)

    completed_orders = data.query('order_status == "Completed"')
    cost = numpy.abs(completed_orders['size'].to_numpy() * completed_orders.price.to_numpy())
    cumulative_cost = numpy.cumsum(cost)

    order_date = completed_orders.date.to_numpy()


    comp.twinx_bar_line(axis, cost, cumulative_cost, order_date, order_date, title=title, xlabel="Date", 
                        bar_ylabel="Gross Value ($)", line_ylabel="Cumulative Cost ($)", lw=lw, alpha=alpha, 
                        line_ylim=(0, numpy.max(cumulative_cost)), bar_ylim=(0.0, numpy.max(cost)), labels=['Order Value', 'Cumulative Cost'])
    


def __order_value(axis: pyplot.axis, data: DataFrame, **kwargs):
    """
    Values of buy and sell orders.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : DataFrame
        Data to plot.
    title : str
        Figure title.
    legend_loc : string
        Specify legend location. (default best)
    """

    title            = get_param_default_if_missing("title", None, **kwargs)
    colors           = get_param_default_if_missing("colors", ('#006600', '#990000'), **kwargs)
    lw               = get_param_default_if_missing("lw", 1, **kwargs)
    legend_loc       = get_param_default_if_missing("legend_loc", "best", **kwargs)
    alpha            = get_param_default_if_missing("alpha", 0.5, **kwargs)

    completed_orders = data.query('order_status == "Completed"')
    size = completed_orders['size'].to_numpy()
    order_date = completed_orders.date.to_numpy()

    value = numpy.where(size > 0, -completed_orders.value.to_numpy(), completed_orders.value.to_numpy())

    comp.positive_negative_bar(axis, value, order_date, title=title, xlabel="Date", ylabel="Order Value", lw=lw, 
                               colors=colors, alpha=alpha)
    
    custom_lines = [Line2D([0], [0], color=colors[0], lw=2, alpha=alpha),
                    Line2D([0], [0], color=colors[1], lw=2, alpha=alpha)]
    
    axis.legend(custom_lines, ['Sell', 'Buy'], loc=legend_loc, 
                bbox_to_anchor=(0.05, 0.05, 0.95, 0.95)).set_zorder(20)


def __orders(axis: pyplot.axis, order_data: DataFrame, asset_price_data: DataFrame, **kwargs):
    """
    Plot order size and value time series.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : DataFrame
        Data to plot.
    symbol_offset_factor : float
        Symbol offset factor.
    title : str
        Figure title.
    """

    title = get_param_default_if_missing("title", None, **kwargs)

    price = asset_price_data.close_price.to_numpy()
    price_date = asset_price_data.date.to_numpy()
    offset = (numpy.max(price) - numpy.min(price)) * 0.05

    buy_orders = order_data.query('order_type == "Buy" and order_status == "Completed"')
    sell_orders = order_data.query('order_type == "Sell" and order_status == "Completed"')

    buy_price = buy_orders.price.to_numpy() - offset
    buy_date = buy_orders.date.to_numpy()
    sell_price = sell_orders.price.to_numpy() + offset
    sell_date = sell_orders.date.to_numpy()

    ticker = sell_orders.ticker.iloc[0]

    comp.fcurve_scatter_comparison(axis, [buy_price, sell_price], price, [buy_date, sell_date], price_date, title=title, xlabel='Date', 
                                   ylabel='Price', lw=1, labels=[ticker, 'Buy', 'Sell'], markers=['^', 'v'], marker_colors=['#006600', '#990000'],
                                   marker_size=6.0, alpha=0.2) 


def __cash_value(axis: pyplot.axis, data: DataFrame, **kwargs):
    """
    Plot cash and value time series.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    data : DataFrame
        Data to plot.
    title : str
        Figure title.
    """

    title = get_param_default_if_missing("title", None, **kwargs)
    lw    = get_param_default_if_missing("lw", 1, **kwargs)

    date = data.date.to_numpy()
    cash = data.cash.to_numpy()
    value = data.value.to_numpy()

    comp.comparison(axis, [cash, value], date, title=title, xlabel="Date", ylabel="Dollars", lw=lw, 
                    labels=["Cash", "Value"])


def __position_value(axis: pyplot.axis, data: DataFrame, **kwargs):
    """
    Plot position value time series.

    Parameters
    ----------
    data : DataFrame
        Data to plot.
    figsize : Tuple[int, int]
        Figure size.
    """

    alpha      = get_param_default_if_missing("alpha", 0.4, **kwargs)
    legend_loc = get_param_default_if_missing("legend_loc", "best", **kwargs)
    title      = get_param_default_if_missing("title", None, **kwargs)

    position = data['size'].to_numpy()
    price = data.price.to_numpy()
    date = data.date.to_numpy()
    value = -price * position

    colors = ('#990000', '#006600')
    
    comp.positive_negative_bar(axis, value, date, xlabel="Date", ylabel="Position Value", alpha=alpha,
                                colors=colors, title=title)
    
    custom_lines = [Line2D([0], [0], color=colors[0], lw=2, alpha=alpha),
                    Line2D([0], [0], color=colors[1], lw=2, alpha=alpha)]
    
    axis.legend(custom_lines, ['Short', 'Long'], loc=legend_loc, 
                bbox_to_anchor=(0.05, 0.05, 0.95, 0.95)).set_zorder(20)


def __daily_returns_distribution(axis, orders: DataFrame, **kwargs):
    """
    Plot daily returns distribution.

    Parameters
    ----------
    axis : matplotlib.pyplot.axis
        Axis used to draw plot.
    orders : DataFrame
        Data to plot.
    title : str
        Figure title.
    nbins : iny
        Number of distribution bins.
    """

    title   = get_param_default_if_missing("title", None, **kwargs)
    nbins   = get_param_default_if_missing("nbins", 20, **kwargs)

    _, daily_returns = compute_daily_rate_of_return(orders)

    pdf, bins = stats.compute_pdf_hist(daily_returns, nbins=nbins)
    pdf = pdf / numpy.sum(pdf)

    comp.bar(axis, pdf, bins, title=title, xlabel="Daily Returns (%)", ylabel="Frequency", bar_width=0.85, alpha=1.0)
