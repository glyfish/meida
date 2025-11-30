from typing import List, Tuple, Optional
from enum import Enum

from datetime import datetime
import pandas
import os
import numpy

from sqlalchemy import create_engine, String, Float, Date, Integer, ForeignKey, BigInteger, Boolean, DateTime
from sqlalchemy.orm import Mapped, DeclarativeBase, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

import backtrader as bt

from lib.utils import read_yahoo_data

class MappedEnum(Enum):

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


class OrderExecutionType(str, MappedEnum):
    """
    Order execution type.
    """

    Market = 'Market'
    Close = 'Close'
    Limit = 'Limit'
    Stop = 'Stop'
    StopLimit = 'StopLimit'
    StopTrail = 'StopTrail'
    StopTrailLimit = 'StopTrailLimit'
    Historical = 'Historical'


class OrderStatusType(str, MappedEnum):
    """
    Order status type.
    """

    Created = 'Created'
    Submitted = 'Submitted'
    Accepted = 'Accepted'
    Partial = 'Partial'
    Completed = 'Completed'
    Canceled = 'Canceled'
    Expired = 'Expired'
    Margin = 'Margin'
    Rejected = 'Rejected'


class OrderType(str, MappedEnum):
    """
    Order type.
    """

    Buy = 'Buy'
    Sell = 'Sell'


class TradeStatus(str, MappedEnum):
    """
    Trade status.
    """

    Created ='Created'
    Open = 'Open'
    Closed = 'Closed'


class Base(DeclarativeBase):
    pass


class BackTest(Base):
    __tablename__ = "backtests"

    run_id: Mapped[str]          = mapped_column(String(256), primary_key=True)
    time_stamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ensemble_id: Mapped[str]     = mapped_column(String(256), nullable=False)
    strategy: Mapped[str]        = mapped_column(String(256), primary_key=True)


class Broker(Base):
    __tablename__ = "broker"

    run_id: Mapped[str]          = mapped_column(String(256), primary_key=True)
    time_stamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    date: Mapped[datetime.date]  = mapped_column(Date, primary_key=True)
    ensemble_id: Mapped[str]     = mapped_column(String(256), nullable=False)
    strategy: Mapped[str]        = mapped_column(String(256), primary_key=False)
    cash: Mapped[float]          = mapped_column(Float, nullable=False)
    value: Mapped[float]         = mapped_column(Float, nullable=False)


class Position(Base):
    __tablename__ = "positions"

    run_id: Mapped[str]          = mapped_column(String(256), primary_key=True)
    date: Mapped[datetime.date]  = mapped_column(Date, primary_key=True)
    ticker: Mapped[str]          = mapped_column(String(256), nullable=False)
    ensemble_id: Mapped[str]     = mapped_column(String(256), nullable=False)
    adjbase: Mapped[float]       = mapped_column(Float, nullable=False)
    price: Mapped[float]         = mapped_column(Float, nullable=False)
    price_orig: Mapped[float]    = mapped_column(Float, nullable=False)
    size: Mapped[int]            = mapped_column(Integer, nullable=False)
    upclosed: Mapped[float]      = mapped_column(Float, nullable=False)
    upopened: Mapped[float]      = mapped_column(Float, nullable=False)
    updt: Mapped[datetime.date]  = mapped_column(Date, nullable=False)


class Trade(Base):
    __tablename__ = "trades"

    run_id: Mapped[str]             = mapped_column(String(256), primary_key=True)
    ref: Mapped[str]                = mapped_column(Integer)
    date: Mapped[datetime.date]     = mapped_column(Date, primary_key=True)
    ensemble_id: Mapped[str]        = mapped_column(String(256), nullable=False)
    ticker: Mapped[str]             = mapped_column(String(256), nullable=False)
    status: Mapped[str]             = mapped_column(String(256), nullable=False)
    trade_id: Mapped[int]           = mapped_column(Integer, nullable=False)
    size: Mapped[float]             = mapped_column(Integer, nullable=False)
    price: Mapped[float]            = mapped_column(Float, nullable=False)
    value: Mapped[float]            = mapped_column(Float, nullable=False)
    commission: Mapped[float]       = mapped_column(Float, nullable=False)
    pnl: Mapped[float]              = mapped_column(Float, nullable=False)
    pnlcomm: Mapped[float]          = mapped_column(Float, nullable=False)
    dtclose: Mapped[datetime.date]  = mapped_column(Date, nullable=False)
    dtopen: Mapped[datetime.date]   = mapped_column(Date, nullable=False)
    baropen: Mapped[int]            = mapped_column(Integer, nullable=False)
    barclose: Mapped[int]           = mapped_column(Integer, nullable=False)
    barlen: Mapped[int]             = mapped_column(Integer, nullable=False)
    is_long: Mapped[bool]           = mapped_column(Boolean, nullable=False)
    pnlcomm: Mapped[float]          = mapped_column(Float, nullable=False)


class Order(Base):
    __tablename__ = "orders"

    run_id: Mapped[str]         = mapped_column(String(256), primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    ensemble_id: Mapped[str]    = mapped_column(String(256), nullable=False)
    ticker: Mapped[str]         = mapped_column(String(256), nullable=False)
    order_status: Mapped[str]   = mapped_column(String(256), nullable=False)
    order_type: Mapped[str]     = mapped_column(String(256), nullable=False)
    trade_id: Mapped[int]       = mapped_column(Integer, nullable=True)
    price: Mapped[float]        = mapped_column(Float, nullable=False)
    value: Mapped[float]        = mapped_column(Float, nullable=False)
    size: Mapped[int]           = mapped_column(Integer, nullable=False)
    commission: Mapped[float]   = mapped_column(Float, nullable=False)
    pnl: Mapped[float]          = mapped_column(Float, nullable=False)
    exec_type: Mapped[str]      = mapped_column(String(256), nullable=False)


class Analyzer(Base):
    __tablename__ = "analyzers"

    run_id: Mapped[str]                 = mapped_column(String(256), primary_key=True)
    date: Mapped[datetime.date]         = mapped_column(Date, primary_key=True)
    ensemble_id: Mapped[str]            = mapped_column(String(256), nullable=False)
    ticker: Mapped[str]                 = mapped_column(String(256))
    analyzer: Mapped[str]               = mapped_column(String(256), nullable=False)
    value: Mapped[dict]                 = mapped_column(JSONB, nullable=False)
    parameters: Mapped[Optional[dict]]  = mapped_column(JSONB, nullable=True)


class Indicator(Base):
    __tablename__ = "indicators"

    run_id: Mapped[str]                = mapped_column(String(256), primary_key=True)
    date: Mapped[datetime.date]        = mapped_column(Date, primary_key=True)
    ensemble_id: Mapped[str]           = mapped_column(String(256), nullable=False)
    ticker: Mapped[str]                = mapped_column(String(256))
    indicator: Mapped[str]             = mapped_column(String(256), nullable=False)
    value: Mapped[dict]                = mapped_column(JSONB, nullable=False)
    params: Mapped[Optional[dict]]     = mapped_column(JSONB, nullable=True)


class AssetPrice(Base):
    __tablename__ = "asset_prices"

    run_id: Mapped[str]          = mapped_column(String(256), primary_key=True)
    date: Mapped[datetime.date]  = mapped_column(Date, primary_key=True)
    ensemble_id: Mapped[str]     = mapped_column(String(256), nullable=False)
    ticker: Mapped[str]          = mapped_column(String(256))
    open_price: Mapped[float]    = mapped_column(Float, nullable=False)
    high_price: Mapped[float]    = mapped_column(Float, nullable=False)
    low_price: Mapped[float]     = mapped_column(Float, nullable=False)
    close_price: Mapped[float]   = mapped_column(Float, nullable=False)


class PriceSeries(Base):
    __tablename__ = "price_series"

    ticker: Mapped[str]              = mapped_column(String(256), primary_key=True)
    date: Mapped[datetime.date]      = mapped_column(Date, nullable=False, primary_key=True)
    open_price: Mapped[float]        = mapped_column(Float, nullable=False)
    high_price: Mapped[float]        = mapped_column(Float, nullable=False)
    low_price: Mapped[float]         = mapped_column(Float, nullable=False)
    close_price: Mapped[float]       = mapped_column(Float, nullable=False)
    adj_close_price: Mapped[float]   = mapped_column(Float, nullable=False)
    volume: Mapped[float]            = mapped_column(Float, nullable=False)
    open_interest: Mapped[float]     = mapped_column(Float, nullable=False)


class BacktestDb:
    """
    Interface to backtrader database.

    Properties
    ----------
    engine : sqlalchemy.engine.base.Engine
        Database engine.
    """


    def __init__(self):
        self.__db_url = "postgresql://backtrader@localhost/backtest"
        self.engine = create_engine(self.__db_url, isolation_level="AUTOCOMMIT")


    """
    Insert objects into the backtest database.

    Methods
    -------
    insert_backtest(run_id: str, date: datetime.date, strategy: str, broker: bt.BrokerBase, ensemble_id: str = None)
        Insert current backtest financials into the database.
    insert_broker(run_id: str, date: datetime.date, broker: bt.BrokerBase, ensemble_id: str = None)
        Insert current broker state into the database.
    insert_position(run_id: str, date: datetime.date, ticker: str, position: bt.Position, ensemble_id: str = None)
        Insert current position into the database.
    insert_trade(run_id: str, date: datetime.date, ticker: str, trade: bt.Trade, ensemble_id: str = None)
        Insert current trade into the database.
    insert_order(run_id: str, date: datetime.date, ticker: str, order: bt.Order, ensemble_id: str = None)
        Insert current order into the database.
    insert_yahoo_asset_price(run_id: str, datas, ensemble_id: str = None)
        Insert current position into the database from a yahoo CSV input feed.
    insert_price_series(ticker: str, date: datetime.date, open_price: float, high_price: float, low_price: float, close_price: float, 
                        adj_close_price: float, volume: float, open_interest: float)
        Insert current price series into the database.
    """
    def insert_backtest(self, run_id: str, strategy: str, time_stamp: datetime, ensemble_id: str = None):
        """
        Insert backtest info.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        strategy: str
            Strategy used in backtest.
        time_stamp: datetime
            Time stamp of the backtest.
        ensemble_id: str
            Identifier for an ensemble of backtests.
        """

        with self.engine.connect() as connection:
            connection.execute(BackTest.__table__.insert().values(
                run_id=run_id, 
                time_stamp=time_stamp,
                ensemble_id=ensemble_id,
                strategy=strategy
            ))


    def insert_broker(self, run_id: str, date: datetime.date, broker: bt.BrokerBase, ensemble_id: str = None):
        """
        Insert broker state.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        date : datetime.date 
            Date of the indicator.
        broker : bt.BrokerBase
            backtrader broker
        time_stamp: datetime
            Time stamp of the backtest.
        ensemble_id: str
            Identifier for an ensemble of backtests.
        """

        with self.engine.connect() as connection:
            connection.execute(Broker.__table__.insert().values(
                run_id=run_id, 
                ensemble_id=ensemble_id,
                date=date, 
                cash=broker.getcash(), 
                value=broker.getvalue()
            ))


    def insert_position(self, run_id: str, date: datetime.date, ticker: str, position: bt.Position, ensemble_id: str = None):
        """
        Insert current position into the database.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        date : datetime.date 
            Date of the indicator.
        ticker : str
            Ticker symbol.
        position: bt.Position
            Backtrader Position object.
        ensemble_id: str
            Identifier for an ensemble of backtests.
        """

        with self.engine.connect() as connection:
            connection.execute(Position.__table__.insert().values(
                run_id=run_id, 
                date=date,
                ticker=ticker,
                ensemble_id=ensemble_id,
                adjbase=position.adjbase,
                price=position.price,
                price_orig=position.price_orig,
                size=position.size,
                upclosed=position.upclosed,
                upopened=position.upopened,
                updt=position.updt
            ))


    def insert_trade(self, run_id: str, date: datetime.date, ticker: str, trade: bt.Trade, ensemble_id: str = None):
        """
        Insert current trade into the database.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        date : datetime.date 
            Date of the indicator.
        ticker : str
            Ticker symbol.
        trade: bt.Trade
            Backtrader Trade object.
        ensemble_id: str
            Identifier for an ensemble of backtests.
       """

        dtclose = trade.close_datetime() if trade.dtclose > 0.0 else None
        dtopen = trade.open_datetime() if trade.dtopen > 0.0 else None
        trade_status = TradeStatus.list()[trade.status]

        with self.engine.connect() as connection:
            connection.execute(Trade.__table__.insert().values(
                ref=trade.ref,
                run_id=run_id, 
                date=date,
                ticker=ticker,
                ensemble_id=ensemble_id,
                status=trade_status,
                trade_id=trade.tradeid,
                size=trade.size,
                price=trade.price,
                value=trade.value,
                commission=trade.commission,
                pnl=trade.pnl,
                pnlcomm=trade.pnlcomm,
                dtclose=dtclose,
                dtopen=dtopen,
                baropen=trade.baropen,
                barclose=trade.barclose,
                barlen=trade.barlen,
                is_long=trade.long
            ))
        

    def insert_order(self, run_id: str, date: datetime.date, ticker: str, order: bt.Order, ensemble_id: str = None):
        """
        Insert current order into the database.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        date : datetime.date 
            Date of the indicator.
        ticker : str
            Ticker symbol.
        order: bt.Order
            Backtrader Order object.
        ensemble_id: str
            Identifier for an ensemble of backtests.
        """

        order_type = order.ordtypename()
        order_exec_type = OrderExecutionType.list()[order.exectype]
        order_status = OrderStatusType.list()[order.status]

        order_data = order.executed if order_status == OrderStatusType.Completed.value else order.created
        price = order_data.price
        value = order_data.value
        size = order_data.size
        comm = order_data.comm
        pnl = order_data.pnl
        tradeid = order.tradeid

        with self.engine.connect() as connection:
            connection.execute(Order.__table__.insert().values(
                run_id=run_id, 
                date=date,
                ticker=ticker,
                ensemble_id=ensemble_id,
                order_status=order_status,
                order_type=order_type,
                trade_id=tradeid,
                price=price,
                value=value,
                size=size,
                commission=comm,
                pnl=pnl,
                exec_type=order_exec_type
            ))


    def insert_yahoo_asset_price(self, run_id: str, datas, ensemble_id: str = None):
        """
        Insert current position into the database from a yahoo CSV input feed.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        datas : 
            List of data feeds.
        ensemble_id: str
            Identifier for an ensemble of backtests.
        """

        self.__insert_asset_price(run_id, datas.datetime.date(0), datas._name, datas.open[0], 
                                 datas.high[0], datas.low[0], datas.close[0], ensemble_id)


    def insert_price_series(self, ticker: str, date: datetime.date, open_price: float, high_price: float, low_price: float, 
                           close_price: float, adj_close_price: float, volume: float, open_interest: float):
        """
        Insert current price series into the database.

        Parameters
        ----------
        ticker: str
            Ticker symbol.
        date: datetime.date
            Date of the indicator.
        open_price: float
            Opening price.
        high_price: float
            High price for day.
        low_price: float 
            Low price for day.
        close_price: float
            Closing price.
        adj_close_price: float
            Adjusted closing price.
        volume: float
            Trade volume.
        open_interest: float
            Open interest.
        """        

        with self.engine.connect() as connection:
            connection.execute(PriceSeries.__table__.insert().values(
                ticker=ticker, 
                date=date, 
                open_price=open_price, 
                high_price=high_price, 
                low_price=low_price, 
                close_price=close_price, 
                adj_close_price=adj_close_price, 
                volume=volume, 
                open_interest=open_interest
            ))

    
    def insert_zscore_indicator(self, run_id: str, date: datetime.date, ticker: str, zscore: float, period: int, stake_multiple: float, ensemble_id: str = None):
        """
        Insert current Z-score indicator value into the database.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        date : datetime.date 
            Date of the indicator.
        indicator : str
            Name of the indicator.
        value : str
            Value of the indicator.
        params : str
            Indicator parameters.
        ensemble_id: str
            Identifier for an ensemble of backtests.
        """

        params = {'period': period, "stake_multiple": stake_multiple}
        value = {'zscore': zscore}
        self.__insert_indicator(run_id, date, ticker, 'zscore', value, params, ensemble_id)


    def insert_yahoo_price_series(self, ticker: str, file_root: str='../../../data/algorithmic_trading'):
        """
        Insert current price series into the database from a yahoo CSV input feed.        

        Parameters
        ----------
        ticker: str
            Ticker symbol.
        file_root: str
            Root directory of file.            
        """

        file_path = os.path.abspath(f"{file_root}/{ticker}.csv")
        data = read_yahoo_data(file_path)
        data.rename(columns={"Open": "open_price", "High": "high_price", "Low": "low_price", "Close": "close_price", 
                             "Adj Close": "adj_close_price", "Volume": "volume"}, inplace=True)
        data.index.names = ['date']
        data['ticker'] = numpy.full(len(data), ticker)
        data.to_sql("price_series", self.engine, if_exists="append")


    """
    Retrieve objects from the backtest database.
    
    Methods
    -------
    fetch_price_series(ticker: str, start_date: str=None, end_date: str=None) -> pandas.DataFrame
        Fetch price series from the backtest database.
    fetch_zscore_indicator(run_id: str, ensemble: str=None) -> pandas.DataFrame
        Fetch Z-score indicator.
    fetch_asset_prices(run_id: str, ensemble: str=None) -> pandas.DataFrame
        Fetch asset prices backtrader output.
    fetch_trades(run_id: str, ensemble: str=None) -> pandas.DataFrame
        Fetch trades.
    fetch_position(run_id: str, ensemble: str=None) -> pandas.DataFrame
        Fetch position.
    fetch_backtest(run_id: str, ensemble: str=None) -> pandas.DataFrame
        Fetch backtest objects.
    fetch_orders(run_id: str, ensemble: str=None) -> pandas.DataFrame
        Fetch orders.
    """
    def fetch_backtest(self, run_id: str) -> pandas.DataFrame:
        """
        Fetch backtest.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        """

        query = f"""
        SELECT run_id,
               strategy,
               time_stamp,
               ensemble_id
        FROM backtests WHERE run_id='{run_id}'
        """

        return pandas.read_sql(query, self.engine)
    
    
    def fetch_broker(self, run_id: str) -> pandas.DataFrame:
        """
        Fetch broker.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        """

        query = f"""
        SELECT date, 
               run_id,
               ensemble_id,
               cash,
               value
        FROM broker WHERE run_id='{run_id}'
        ORDER BY date ASC
        """

        return pandas.read_sql(query, self.engine)


    def fetch_position(self, run_id: str) -> pandas.DataFrame:
        """
        Fetch position.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        """

        query = f"""
        SELECT date, 
               run_id,
               ticker,
               ensemble_id,
               adjbase,
               price,
               price_orig,
               size,
               upclosed,
               upopened,
               updt
        FROM positions WHERE run_id='{run_id}' 
        ORDER BY date ASC
        """

        return pandas.read_sql(query, self.engine)
    
    
    def fetch_trades(self, run_id: str) -> pandas.DataFrame:
        """
        Fetch trades.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        """

        query = f"""
        SELECT date, 
                run_id,
                ticker,
                ensemble_id,
                status,
                trade_id,
                size,
                price,
                value,
                commission,
                pnl,
                pnlcomm,
                dtclose,
                dtopen,
                baropen,
                barclose,
                barlen,
                is_long
        FROM trades WHERE run_id='{run_id}' 
        ORDER BY date ASC
        """

        return pandas.read_sql(query, self.engine)


    def fetch_asset_price(self, run_id: str) -> pandas.DataFrame:
        """
        Fetch asset price time series.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        """

        query = f"""
        SELECT date, 
                run_id,
                ticker,
                ensemble_id,
                open_price,
                high_price,
                low_price,
                close_price
        FROM asset_prices WHERE run_id='{run_id}' 
        ORDER BY date ASC
        """

        return pandas.read_sql(query, self.engine)
    

    def fetch_price_series(self, ticker: str, start_date: str=None, end_date: str=None) -> pandas.DataFrame:
        """
        Fetch price series from the backtest database.

        Parameters
        ----------
        ticker: str
            Ticker symbol.
        start_date: str
            Start date.
        end_date: str
            End date.

        Returns
        -------
        pandas.DataFrame
            Price series.
        """

        query = f"SELECT * FROM price_series WHERE ticker='{ticker}'"
        if start_date:
            query += f" AND date >= '{start_date}'"
        if end_date:
            query += f" AND date <= '{end_date}'"

        query += "ORDER BY date ASC"

        return pandas.read_sql(query, self.engine)


    def fetch_zscore_indicator(self, run_id: str) -> pandas.DataFrame:
        """
        Fetch Z-score indicator.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        """

        query = f"""
        SELECT date, 
               run_id,
               indicator,
               ensemble_id,
               ticker,
               value->'zscore' zscore,
               params->'period' half_life,
               params->'stake_multiple' stake_multiple
        FROM indicators WHERE run_id='{run_id}' 
            AND indicator='zscore'
        ORDER BY date ASC
        """

        return pandas.read_sql(query, self.engine)

    
    def fetch_orders(self, run_id: str) -> pandas.DataFrame:
        """
        Fetch orders.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        """

        query = f"""
        SELECT date, 
                run_id,
                ticker,
                ensemble_id,
                order_status,
                order_type,
                trade_id,
                price,
                value,
                size,
                commission,
                pnl,
                exec_type
        FROM orders WHERE run_id='{run_id}' 
        ORDER BY date ASC
        """

        return pandas.read_sql(query, self.engine)
    

    """
    Private methods

    Methods
    -------
    __insert_asset_price(run_id: str, date: datetime.date, ticker: str, open_price: float, high_price: float, 
                         low_price: float, close_price: float, ensemble_id: str)
        Insert current position into the database.
    __insert_analyzer(run_id: str, date: datetime.date, analyzer: str, value: float)
        Insert current analyzer value into the database.
    __insert_indicator(run_id: str, date: datetime.date, ticker: str, indicator: str, value: str, 
                      params: str = None, ensemble_id: str = None)
        Insert current indicator value into the database.
    """
    def __insert_asset_price(self, run_id: str, date: datetime.date, ticker: str, open_price: float, 
                             high_price: float, low_price: float, close_price: float, ensemble_id: str):
        """
        Insert current position into the database.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        date : datetime.date 
            Date of the indicator.
        ticker : str
            Ticker symbol.
        open_price : float
            Opening price.
        high_price : float
            High price.
        low_price : float
            Low price.
        close_price : float
            Closing price.            
        ensemble_id: str
            Identifier for an ensemble of backtests.
        """

        with self.engine.connect() as connection:
            connection.execute(AssetPrice.__table__.insert().values(
                run_id=run_id, 
                date=date, 
                ticker=ticker, 
                ensemble_id=ensemble_id,
                open_price=open_price, 
                high_price=high_price, 
                low_price=low_price, 
                close_price=close_price
            ))


    def __insert_analyzer(self, run_id: str, date: datetime.date, analyzer: str, value: float):
        """
        Insert current analyzer value into the database.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        date : datetime.date 
            Date of the indicator.
        analyzer : str
            Name of the analyzer.
        value : float
            Value of the analyzer.
        """

        with self.engine.connect() as connection:
            connection.execute(Analyzer.__table__.insert().values(
                run_id=run_id, 
                date=date, 
                analyzer=analyzer, 
                value=value
            ))


    def __insert_indicator(self, run_id: str, date: datetime.date, ticker: str, indicator: str, value: str, 
                          params: str = None, ensemble_id: str = None):
        """
        Insert current indicator value into the database.

        Parameters
        ----------
        run_id : str
            Unique identifier for the backtest.
        date : datetime.date 
            Date of the indicator.
        indicator : str
            Name of the indicator.
        value : str
            Value of the indicator.
        params : str
            Indicator parameters.
        """

        with self.engine.connect() as connection:
            connection.execute(Indicator.__table__.insert().values(
                run_id=run_id, 
                date=date,
                indicator=indicator, 
                ensemble_id=ensemble_id,
                ticker=ticker,
                value=value,
                params=params
            ))


