from typing import Tuple
import numpy
import statsmodels.api as sm
from pandas import DataFrame

from lib.data.impl import ou, bm, ecm, adf, arima, fbm, stats, var, vecm
from lib.data.param_est import (ParamEst, OLSResult, OLSTransform, OLSParamType)


def compute_mean_reversion_halflife(data: numpy.ndarray[float]) -> Tuple[float, sm.regression.linear_model.RegressionResults, OLSResult]:
    """
    Compute mean reversion half-life.

    Parameters
    ----------
    data : numpy.ndarray[float]
        Time series data.
    """

    mean = numpy.full(len(data), numpy.mean(data))
    xt = data - mean
    result, result_model = ou.compute_mean_half_life_estimate(xt)
    return result_model.param_transforms[0].param.est, result, result_model
