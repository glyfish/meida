
from typing import Tuple
import numpy
import uuid

from lib.models import adf
from lib.data.hyp_test import (StatisticalTestParam, StatisticalTestData, StatisticalTestReport, 
                               HypothesisTestType, HypothesisType, HypothesisTestStatus)
from lib.data.reports import ADFTestReport

from lib.utils import get_param_default_if_missing, create_space

def create_df_source(**kwargs) -> Tuple[numpy.ndarray[float], numpy.ndarray[float]]:
    """
    Generate the Dickey-Fuller distribution by simulating an ensemble of solutions
    to the stochastic integral that defines it.

    Parameters
    ----------
    nstep: int
        Number od steps in integral simulations.
    nsim: int
        Number of simulations in ensemble.
    """
    
    nstep = get_param_default_if_missing("nstep", 100, **kwargs)
    nsim = get_param_default_if_missing("nsim", 1000, **kwargs)

    return create_space(xmax=nsim, npts=nsim + 1), adf.dist_ensemble(nstep, nsim)

def compute_adf_test(samples: numpy.ndarray[float], **kwargs) -> Tuple[ADFTestReport, StatisticalTestReport]:
    """
    Perform ADF test on provided samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Samples to test.
    max_lag : {None, int}
        Maximum lag which is included in test, default value of
        12*(nobs/100)^{1/4} is used when ``None``.

    Returns
    -------
    Tuple[ADFTestReport, StatisticalTestReport]
        ADF result report and test result model.
    """

    max_lag = get_param_default_if_missing("max_lag", 12, **kwargs)

    result = adf.adf_test(samples, max_lag=max_lag)
    return result, __adf_report_from_result(result, HypothesisTestType.STATIONARITY)

def compute_adf_offset_test(samples: numpy.ndarray[float], **kwargs) -> Tuple[ADFTestReport, StatisticalTestReport]:
    """
    Perform ADF test assuming a constant offset on provided samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Samples to test.
    max_lag : {None, int}
        Maximum lag which is included in test, default value of
        12*(nobs/100)^{1/4} is used when ``None``.

    Returns
    -------
    Tuple[ADFTestReport, StatisticalTestReport]
        ADF result report and test result model.
    """

    max_lag = get_param_default_if_missing("max_lag", 12, **kwargs)

    result = adf.adf_test_offset(samples, max_lag=max_lag)
    return result, __adf_report_from_result(result, HypothesisTestType.STATIONARITY_OFFSET)

def compute_adf_drift_test(samples: numpy.ndarray[float], **kwargs) -> Tuple[ADFTestReport, StatisticalTestReport]:
    """
    Perform ADF test assuming offset and drift terms on provided samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Samples to test.      
    max_lag : {None, int}
        Maximum lag which is included in test, default value of
        12*(nobs/100)^{1/4} is used when ``None``.

    Returns
    -------
    Tuple[ADFTestReport, StatisticalTestReport]
        ADF result report and test result model.
    """

    max_lag = get_param_default_if_missing("max_lag", 12, **kwargs)

    result = adf.adf_test_drift(samples, max_lag=max_lag)
    return result, __adf_report_from_result(result, HypothesisTestType.STATIONARITY_DRIFT)

def __adf_report_from_result(result: ADFTestReport, hyp_test_type: HypothesisTestType) -> StatisticalTestReport:
    """
    Perform ADF test on provided samples.

    Parameters
    ----------
    samples: numpy.ndarray[float]
        Samples to test.
    max_lag : {None, int}
        Maximum lag which is included in test, default value of
        12*(nobs/100)^{1/4} is used when ``None``.

    Returns
    -------
    Tuple[ADFTestReport, StatisticalTestReport]
        ADF result report and test result model.
    """
    
    test_id = str(uuid.uuid4())

    sigs = [StatisticalTestParam(test_id=test_id, label=result.sig_str[i], value=result.sig[i]) for i in range(3)]
    stat = StatisticalTestParam(test_id=test_id, label=r"$t$", value=result.stat)
    pval = StatisticalTestParam(test_id=test_id, label=r"$p-value$", value = result.pval)
    lower_vals = [StatisticalTestParam(test_id=test_id, label=r"$t_L$", value=val) for val in result.critical_vals]
    test_data = []
    for i in range(3):
        status = HypothesisTestStatus.from_bool(result.status_vals[i])
        data = StatisticalTestData(test_id=test_id,
                                   status=status,
                                   stat=stat,
                                   pval=pval,
                                   params=[],
                                   sig=sigs[i],
                                   lower=lower_vals[i],
                                   upper=None)
        test_data.append(data)
    return StatisticalTestReport(test_id=test_id,
                                 status=hyp_test_type.status(result.status_vals),
                                 hyp_type=HypothesisType.LOWER_TAIL,
                                 hyp_test_type=hyp_test_type,
                                 test_data=test_data)
