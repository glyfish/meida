import numpy
from enum import Enum

class PlotType(Enum):
    """
    Supported plot types supported

    Values
    ------
    LINEAR : 1
        Linear x, y plot axis.
    LOG : 2
        Log scale on both x and y axis.
    XLOG : 3
        Log scale on x axis and linear scale on y axis.
    YLOG : 4
        Log scale on y axis and linear scale on x axis.
    """
    LINEAR = 1
    LOG = 2
    XLOG = 3
    YLOG = 4

def logStyle(axis, x: numpy.ndarray, y: numpy.ndarray):
    """
    Configure axis for log x and y axis.

    Parameters
    ----------
    x : numpy.ndarray
        x axis values.
    y : numpy.ndarray
        y axis values
    """
    minx = min(x) if min(x) > 0.0 else 1.0
    if numpy.log10(max(x)/minx) < 4:
        axis.tick_params(axis='both', which='minor', length=8, color="#b0b0b0", direction="in")
        axis.tick_params(axis='both', which='major', length=15, color="#b0b0b0", direction="in", pad=10)
        axis.spines['bottom'].set_color("#b0b0b0")
        axis.spines['left'].set_color("#b0b0b0")
        axis.set_xlim([min(x)/1.5, 1.5*max(x)])

def logXStyle(axis, x: numpy.ndarray, y: numpy.ndarray):
    """
    Configure axis for log x and linear y axis.

    Parameters
    ----------
    x : numpy.ndarray
        x axis values.
    y : numpy.ndarray
        y axis values
    """
    minx = min(x) if min(x) > 0.0 else 1.0
    if numpy.log10(max(x)/minx) < 4:
        axis.tick_params(axis='x', which='minor', length=8, color="#b0b0b0", direction="in")
        axis.tick_params(axis='x', which='major', length=15, color="#b0b0b0", direction="in", pad=10)
        axis.spines['bottom'].set_color("#b0b0b0")
        axis.set_xlim([min(x)/1.5, 1.5*max(x)])

def logYStyle(axis, x: numpy.ndarray, y: numpy.ndarray):
    """
    Configure axis for linear x and log y axis.

    Parameters
    ----------
    x : numpy.ndarray
        x axis values.
    y : numpy.ndarray
        y axis values
    """
    if numpy.log10(max(y)/min(y)) < 4:
        axis.tick_params(axis='y', which='minor', length=8, color="#b0b0b0", direction="in")
        axis.tick_params(axis='y', which='major', length=15, color="#b0b0b0", direction="in", pad=10)
        axis.spines['left'].set_color("#b0b0b0")
