from typing import Type
import numpy
import os.path
from datetime import datetime
import random

from lib.trading.metrics import std, zscore
from lib.utils import get_param_default_if_missing

import backtrader as bt
import shortuuid

from lib.db.backtest_db import BacktestDb


class GlyfishStrategy(bt.Strategy):
    """
    The GlyfishStrategy is a container for reusable elements in Strategies
    """

    def __init__(self, ensemble_id: str):
        # Keep a reference to the "close" line in the data[0] dataseries
        self.dataclose = self.datas[0].close

        # To keep track of pending orders and buy price/commission, current  bar_executed
        self.order = None
        self.buyprice = None
        self.buycomm = None

        # Add database interface
        self.db = BacktestDb()

        # Create run identifier
        self.run_id = shortuuid.ShortUUID().random(length=12)
        self.ensemble_id = ensemble_id
        self.time_stamp = datetime.utcnow()

        # Maintain trade ID
        self.tradeid = None
        self.db.insert_backtest(self.run_id, self.__class__.__name__, self.time_stamp, ensemble_id)
        self.log(f"Run ID={self.run_id}, Ensemble ID={ensemble_id}")


    def get_tradeid(self):
        """
        Create a new trade ID if one does not exist and return it
        or the current value.
        """

        if self.tradeid is None:
            self.tradeid = random.getrandbits(32)
        return self.tradeid
    

    def log(self, txt: str, dt: datetime=None):
        """
        Logging function for strategy.

        Parameters
        ----------
        txt : str
            Text to be logged.
        dt : datetime, optional
            Date and time to be logged. The default is None.
        """

        dt = dt or self.current_date()
        print(f"{dt.isoformat()}, {txt}")


    def current_date(self):
        """
        Get the current date.

        Returns
        -------
        date
            The current date.
        """

        return self.datas[0].datetime.date(0)


    def notify_cashvalue(self, cash, value):
        self.log(f"Cash={cash:.2f}, Value={value:.2f}")


    def notify_trade(self, trade: bt.Trade):
        """
        Called when a trade has a state change.

        Parameters
        ----------
        trade : bt.Trade
            The trade that has changed state.
        """
        
        self.db.insert_trade(self.run_id, self.current_date(), self.datas[0]._name, trade, self.ensemble_id)
        
        if not trade.isclosed:
            return
        self.tradeid = None

        self.log('OPERATION PROFIT, GROSS %.2f, NET %.2f' % (trade.pnl, trade.pnlcomm))


    def notify_order(self, order: bt.Order):
        """
        Called when an order has a state change.

        Parameters
        ----------
        order : bt.Order
            The order that has changed state.
        """
        
        self.db.insert_order(self.run_id, self.current_date(), self.datas[0]._name, order, self.ensemble_id)    

        if order.status in [order.Submitted, order.Accepted]:
            return
        
        # Check if an order has been completed
        # Attention: broker could reject order if not enough cash
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"BUY EXECUTED, Price {order.executed.price:.2f}, Cost {order.executed.value:.2f}, Comm {order.executed.comm:.2f}")
                self.buyprice = order.executed.price
                self.buycomm = order.executed.comm
            else:  # Sell
                self.log(f"SHORT EXECUTED, Price: {order.executed.price:.2f}, Cost: {order.executed.value:.2f}, Comm {order.executed.comm:.2f}")

            # save bar when order was executed
            self.bar_executed = len(self)

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('Order Canceled/Margin/Rejected')

        self.order = None


    def next(self):
        """
        Called on each new bar.
        """

        #  Log the closing price
        self.log(f"Close {self.dataclose[0]:.2f}")

        # Insert broker and asset price data into database
        self.db.insert_broker(self.run_id, self.current_date(), self.broker, self.ensemble_id)
        self.db.insert_yahoo_asset_price(self.run_id, self.datas[0], self.ensemble_id)


    @staticmethod
    def ensemble_id():
        return shortuuid.ShortUUID().random(length=12)
    

    @staticmethod
    def load_yahoo_finance_data(file_path: str, start_date: datetime, end_date: datetime):  
        dataname = os.path.abspath(file_path)
        data = bt.feeds.YahooFinanceCSVData(
            dataname=dataname,
            fromdate = start_date,
            todate = end_date,
            reverse=False)
        return data
    

    @staticmethod
    def backtest(data, strategy: Type[bt.Strategy], ensemble_id: str, cash: float = 1000.0, commission: float = 0.0):
        cerebro = bt.Cerebro()
        # Add the Data Feed to Cerebro
        cerebro.adddata(data)

        # Add a strategy
        cerebro.addstrategy(strategy)

        # Set cash start
        cerebro.broker.setcash(cash)

        # Set the commission - 0.1% ... divide by 100 to remove the %
        cerebro.broker.setcommission(commission=commission)

        # Add analyzers
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name = "sharpe")
        cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name = "sharpe_a")
        cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name = "annual_return")
        cerebro.addanalyzer(bt.analyzers.Returns, _name = "returns")
        cerebro.addanalyzer(bt.analyzers.TimeReturn, _name = "time_return")
        cerebro.addanalyzer(bt.analyzers.VWR, _name = "vwr")
        cerebro.addanalyzer(bt.analyzers.PositionsValue, _name = "position_value")

        # Print out the starting conditions
        print(f"Starting Portfolio Value: {cerebro.broker.getvalue():.2f}")

        # Run over everything
        strats = cerebro.run()

        # Print out the final result
        print(f"Final Portfolio Value: {cerebro.broker.getvalue():.2f}, Run ID: {strats[0].run_id}, Ensemble ID: {ensemble_id}")
        print(f"Sharp Ratio: {strats[0].analyzers.sharpe.get_analysis()}")
        print(f"Annualized Sharp Ratio: {strats[0].analyzers.sharpe_a.get_analysis()}")
        print(f"Annual Return: {strats[0].analyzers.annual_return.get_analysis()}")
        print(f"Returns: {strats[0].analyzers.returns.get_analysis()}")
        print(f"Variable Weight Ratio: {strats[0].analyzers.vwr.get_analysis()}")

        return cerebro
    