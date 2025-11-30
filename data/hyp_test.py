from enum import Enum
import json
import uuid
import numpy
from statsmodels.tsa.vector_ar.vecm import JohansenTestResult

class HypothesisTestStatus(str, Enum):
    """
    Hypothesis test status.

    Values
    ------

    PASSED
        The test passed.
    FAILED
        The test failed
    """

    PASSED = "PASSED"
    FAILED = "FAILED"

    def to_bool(self) -> bool:
        return self.value == "PASSED"

    @staticmethod
    def from_bool(status: bool):
        return HypothesisTestStatus.PASSED if status else HypothesisTestStatus.FAILED

# ##############################################################
# Hypothesis test models
# ##############################################################

class HypothesisTestType(str, Enum):
    """
    Supported hypothesis tests.

    Values
    ------
    STATIONARITY
        ADF test for stationarity of an AR(p) process. To pass a failure of the ADF 
        test at a significance level of 10% is required.
    STATIONARITY_OFFSET
        ADF test for a stationarity of an AR(p) process with a constant offset. To pass a failure of the ADF 
        test at a significance level of 10% is required.
    STATIONARITY_DRIFT
        ADF test for a stationarity of an AR(p) process with drift.To pass a failure of the ADF 
        test at a significance level of 10% is required.
    BM
        Test for brownian motion using the Lo and Mackinlay variance ratio test. The process is 
        brownian motion if the test passes at the specified significance level.
    FBM_AUTO_CORR
        Test for positive correlation in a fractional brownian motion process using the Lo and Mackinlay 
        variance ratio test. The FBM process has positive autocorrelation if the upper tail test fails at the specified
        significance level.
    FBM_NEG_AUTO_CORR
        Test for negative correlation in a fractional brownian motion process using the Lo and Mackinlay variance ratio 
        test. The FBM process has negative autocorrelation if the lower tail test fails at the specified
        significance level.
    """

    STATIONARITY = "STATIONARITY"
    STATIONARITY_OFFSET = "STATIONARITY_OFFSET"
    STATIONARITY_DRIFT = "STATIONARITY_DRIFT"
    BM = "BM"
    FBM_AUTO_CORR = "AUTO_CORR"
    FBM_NEG_AUTO_CORR = "NEG_AUTO_CORR"

    def status(self, status: bool) -> HypothesisTestStatus:
        if self.value == HypothesisTestType.STATIONARITY.value:
            return HypothesisTestStatus.from_bool(not status[2])
        elif self.value == HypothesisTestType.STATIONARITY_OFFSET.value:
            return HypothesisTestStatus.from_bool(not status[2])
        elif self.value == HypothesisTestType.STATIONARITY_DRIFT.value:
            return HypothesisTestStatus.from_bool(not status[2])
        elif self.value == HypothesisTestType.BM.value:
            npass = 0
            for stat in status:
                if stat:
                    npass += 1
            return HypothesisTestStatus.from_bool(npass >= 1)
        elif self.value == HypothesisTestType.FBM_AUTO_CORR.value:
            for stat in status:
                if not stat:
                    return HypothesisTestStatus.PASSED
            return HypothesisTestStatus.FAILED
        elif self.value == HypothesisTestType.FBM_NEG_AUTO_CORR.value:
            for stat in status:
                if not stat:
                    return HypothesisTestStatus.PASSED
            return HypothesisTestStatus.FAILED
        else:
            raise Exception(f"Test type is invalid: {self}")

    def desc(self):
        if self.value == HypothesisTestType.STATIONARITY.value:
            return "Stationarity Test"
        elif self.value == HypothesisTestType.STATIONARITY_OFFSET.value:
            return "Stationarity Test with Constant Offset."
        elif self.value == HypothesisTestType.STATIONARITY_DRIFT.value:
            return "Stationarity Test with Drift."
        elif self.value == HypothesisTestType.BM.value:
            return "Brownian Motion Test"
        elif self.value == HypothesisTestType.FBM_AUTO_CORR.value:
            return "Autocorrelation Test"
        elif self.value == HypothesisTestType.FBM_NEG_AUTO_CORR.value:
            return "Negative Autocorrelation Test"
        else:
            raise Exception(f"Test type is invalid: {self}")


class HypothesisType(str, Enum):
    """
    Hypotheses type.

    Values
    ------
    TWO_TAIL
        Two tail test type.
    LOWER_TAIL
        Lower tail test type.
    UPPER_TAIL
        Upper tail test type.
    """

    TWO_TAIL = "TWO_TAIL"
    LOWER_TAIL = "LOWER_TAIL"
    UPPER_TAIL = "UPPER_TAIL"


class StatisticalTestParam:
    """
    Statistical test parameter value.

    Properties
    ----------
    label: str
        Test parameter label.
    value: float
        Test parameter value.
    test_id: str
        Hypothesis test identifier.   
    """

    def __init__(self, test_id: str, label: str, value: float):
        self.test_id = test_id
        self.label = label
        self.value = value

    def __repr__(self):
        return f"TestParam({self._props()})"

    def __str__(self):
        return self._props()

    def _props(self):
        return f"label=({self.label}), " \
               f"value=({self.value}), " \
               f"test_id=({self.test_id})"

    def to_json(self, pretty: bool=False):
        indent = 4 if pretty else None
        return json.dumps(self, indent=indent, default=lambda o: o.__dict__)

    @staticmethod
    def from_dict(data):
        return StatisticalTestParam(label=data["label"],
                                    value=data["value"],
                                    test_id=data["test_id"])

class StatisticalTestData:
    """
    Statistical test data.

    Properties
    ----------
    test_id: str
        Hypothesis test identifier.   
    status: HypothesisTestStatus
        Test status.
    stat: StatisticalTestParam
        Value of test statistic.
    pval: StatisticalTestParam
        Probability of occurrence of test statistic value.
    params: list[StatisticalTestParam]
        Any parameters used to configure test.
    sig: StatisticalTestParam
        Statistical test significance.
    lower: StatisticalTestParam
        Value of test statistic used for lower tail test.
    upper: StatisticalTestParam
        Value of test statistic used for upper tail test.
    """

    def __init__(self, 
                 test_id: str,
                 status: HypothesisTestStatus, 
                 stat: StatisticalTestParam, 
                 pval: StatisticalTestParam, 
                 params: list[StatisticalTestParam], 
                 sig: StatisticalTestParam, 
                 lower: StatisticalTestParam, 
                 upper: StatisticalTestParam):
        self.status = status
        self.stat = stat
        self.pval = pval
        self.params = params
        self.sig = sig
        self.lower = lower
        self.upper = upper
        self.test_id = test_id

    def __repr__(self):
        return f"StatisticalTestData({self.__props()})"

    def __str__(self):
        return self.__props()

    def __props(self):
        return f"test_id=({self.test_id}), " \
               f"status=({self.status}), " \
               f"stat=({self.stat}), " \
               f"pval=({self.pval}, " \
               f"params=({self.params}), " \
               f"sig=({self.sig}), " \
               f"lower=({self.lower}), " \
               f"upper=({self.upper})"
               

    def to_json(self, pretty: bool=False):
        indent = 4 if pretty else None
        return json.dumps(self, indent=indent, default=lambda o: o.__dict__)

    @staticmethod
    def from_dict(data):
        status = data["status"] if "status" in data else HypothesisTestStatus.FAILED
        stat = StatisticalTestParam.from_dict(data["stat"]) if "stat" in data else None
        pval = StatisticalTestParam.from_dict(data["pval"]) if "pval" in data else None
        params = [StatisticalTestParam.from_dict(param) for param in dict["params"]]
        sig = StatisticalTestParam.from_dict(data["sig"]) if "sig" in data else None
        lower = StatisticalTestParam.from_dict(data["lower"]) if "lower" in data else None
        upper = StatisticalTestParam.from_dict(data["upper"]) if "upper" in data else None
        test_id = data["test_id"] if "test_id" in data else None

        return StatisticalTestData(status=status, stat=stat, pval=pval, params=params, sig=sig,
                                   lower=lower,upper=upper, test_id=test_id)

class StatisticalTestReport:
    """
    Data used to construct the statistical test report.

    Parameters
    ----------
    test_id: str
        Hypothesis test identifier.   
    status: HypothesisTestStatus
        Test status. This status may be the negation from the status of the performed test if the 
        desired result is the alternative hypothesis not the null hypothesis.
    hyp_type: HypothesistType
        Hypothesis test type performed (two tailed, upper tail or lower tail).
    hyp_test_type: HypothesisTestType
        Type of hypothesis test performed.
    test_data: list[StatisticalTestData]
        Results from test.
    """

    def __init__(self,
                 test_id: str,
                 status: HypothesisTestStatus, 
                 hyp_type: HypothesisType, 
                 hyp_test_type: HypothesisTestType, 
                 test_data: list[StatisticalTestData]):
        self.status = status
        self.hyp_type = hyp_type
        self.hyp_test_type = hyp_test_type
        self.test_data = test_data
        self.desc = hyp_test_type.desc()
        self.test_id = test_id

    def __repr__(self):
        return f"TestReport({self.__props()})"

    def __str__(self):
        return self.__props()

    def __props(self):
        return f"test_id=({self.test_id}), " \
               f"status=({self.status}), " \
               f"hyp_type=({self.hyp_type}), " \
               f"hyp_test_type=({self.hyp_test_type}), " \
               f"desc=({self.desc}, " \
               f"test_data=({self.test_data})"

    def to_json(self, pretty: bool=False):
        indent = 4 if pretty else None
        return json.dumps(self, indent=indent, default=lambda o: o.__dict__)

    @staticmethod
    def from_dict(data):
        status = data["status"] if "status" in data else HypothesisTestStatus.FAILED
        hyp_type = data["hyp_type"] if "hyp_type" in data else None
        hyp_test_type = data["hyp_test_type"] if "hyp_test_type" in data else None
        test_data = [StatisticalTestData.from_dict(test_data) for test_data in data["test_data"]]
        test_id = data["test_id"] if "test_id" in data else None

        return StatisticalTestReport(status=status, hyp_type=hyp_type, hyp_test_type=hyp_test_type, test_data=test_data,
                                     test_id=test_id)

# ##############################################################
# VAR lag order tests models
# ##############################################################

class ErrorMetric(str, Enum):
    """
    Error metric.

    Values
    ------
    AIC
        Akaike information criterion.
    BIC
        Bayesian information criterion.
    FPE
        Final prediction error.
    HQIC
        Hannan-Quinn information criterion.
    """

    AIC = "AIC"
    BIC = "BIC"
    FPE = "FPE"
    HQIC = "HQIC"

    def __str__(self):
        return self.value

    def __repr__(self):
        return f"ErrorMetric({self.value})"


class LagOrderTestResult:
    """
    Lag order estimate result.

    Properties
    ----------
    test_id: str
        Test identifier.
    order: int
        Order estimate.
    error_metric: ErrorMetric
        Error metric used to estimate order.
    value: float
        Error metric value.
    """

    def __init__(self, test_id: str, order: StatisticalTestParam, error_metric: ErrorMetric, value: StatisticalTestParam):
        self.test_id = test_id
        self.order = order
        self.error_metric = error_metric
        self.value = value

    def __repr__(self):
        return f"LagOrderTestResult({self.__props()})"
    
    def __str__(self):
        return self.__props()
    
    def __props(self):     
        return f"test_id={self.test_id}, " \
               f"order=({self.order}), " \
               f"error_metric=({self.error_metric}), " \
               f"value=({self.value})"


class VAROrderTestReport:
    """
    VAR order test report.

    Properties
    ----------
    order: StatisticalTestParam
        Order estimate.
    test_id: str
        Test identifier.
    aic: LagOrderTestResult
        AIC values.
    bic: LagOrderTestResult
        BIC values.
    fpe: LagOrderTestResult
        FPE values.
    hqic: LagOrderTestResult
        HQIC values.
    """

    def __init__(self, test_id: str, order: StatisticalTestParam, aic: LagOrderTestResult, bic: LagOrderTestResult, fpe: LagOrderTestResult, hqic: LagOrderTestResult):
        self.__test_id = test_id
        self.__order = order
        self.__aic = aic
        self.__bic = bic
        self.__fpe = fpe
        self.__hqic = hqic


    def __repr__(self):
        return f"VAROrderTestReport({self.__props()})"

    def __str__(self):
        return self.__props()

    def __props(self):
        return f"test_id={self.__test_id}, " \
               f"order=({self.__order}), " \
               f"aic=({self.__aic}), " \
               f"bic=({self.__bic}), " \
               f"fpe=({self.__fpe}), " \
               f"hqic=({self.__hqic})"

    def to_json(self, pretty: bool=False):
        if pretty:
            return json.dumps(self, indent=3, default=lambda o: o.__dict__)
        else:
            return json.dumps(self, default=lambda o: o.__dict__)


def __var_order_test_report_from_result(result: LagOrderTestResult) -> VAROrderTestReport:
    test_id = str(uuid.uuid4())

    order = StatisticalTestParam(test_id, r"$\tau_{AIC}$", int(result.aic))
    metric_value = StatisticalTestParam(test_id, r"$\varepsilon_{AIC}$", result.ics['aic'][result.aic])
    aic_test = LagOrderTestResult(test_id, order, ErrorMetric.AIC, metric_value)

    order = StatisticalTestParam(test_id, r"$\tau_{BIC}$", int(result.bic))
    metric_value = StatisticalTestParam(test_id, r"$\varepsilon_{BIC}$", result.ics['bic'][result.aic])
    bic_test = LagOrderTestResult(test_id, order, ErrorMetric.BIC, metric_value)

    order = StatisticalTestParam(test_id, r"$\tau_{FPE}$", int(result.fpe))
    metric_value = StatisticalTestParam(test_id, r"$\varepsilon_{FPE}$", result.ics['fpe'][result.aic])
    fpe_test = LagOrderTestResult(test_id, order, ErrorMetric.FPE, metric_value)

    order = StatisticalTestParam(test_id, r"$\tau_{HQIC}$", int(result.hqic))
    metric_value = StatisticalTestParam(test_id, r"$\varepsilon_{HQIC}$", result.ics['hqic'][result.aic])
    hqic_test = LagOrderTestResult(test_id, order, ErrorMetric.HQIC, metric_value)

    order_results = numpy.bincount([result.aic, result.bic, result.hqic])
    order = StatisticalTestParam(test_id, r"$\tau_{min}$", int(numpy.argmax(order_results)))
    return VAROrderTestReport(test_id=test_id, order=order, aic=aic_test, bic=bic_test, fpe=fpe_test, hqic=hqic_test)
    

# ##############################################################
#  Granger causality test models
# ##############################################################

class GrangerCausalityTestResult:
    """
    Result of Granger causality test for two time series.

    Properties
    ----------
    pvalue: float
        P-value.
    critical_value: float
        Critical value.
    result: bool
        Granger causality result the right variable causal of the left variable.
    dependent_var: int
        Tested dependent variable index.
    causal_var: int
        Tested causal variable index.
    """

    def __init__(self, est_id: str, dependent_var: int, causal_var: int, pvalue: float, critical_value: float, result: bool):
        self.__est_id = est_id
        self.__dependent_var = dependent_var
        self.__causal_var = causal_var
        self.__pvalue = pvalue
        self.__critical_value = critical_value
        self.__result = result

    def __repr__(self):
        return f"GrangerCausalityTestResult({self.__props()})"

    def __str__(self):
        return self.__props()

    def __props(self):
        return f"causal_var=({self.__causal_var}), " \
               f"dependent_var=({self.__dependent_var}), " \
               f"pvalue=({self.__pvalue}), " \
               f"est_id=({self.__est_id}), " \
               f"critical_value=({self.__critical_value}), " \
               f"result=({self.__result}), " \
               
    
    @staticmethod
    def from_dict(data, est_id):
        dependent_var = data["dependent_var"] if "dependent_var" in data else None
        causal_var = data["causal_var"] if "causal_var" in data else None
        pvalue = data["pvalue"] if "pvalue" in data else None
        critical_value = data["critical_value"] if "critical_value" in data else None
        result = data["result"] if "result" in data else None
        return GrangerCausalityTestResult(est_id, dependent_var, causal_var, pvalue, critical_value, result)


class GrangerCausalityTestReport:
    """
    Result of Granger causality test for multivariate time series.

    Properties
    ----------
    test_id: str
        Test identifier.
    rank: int
        Rank of VECM process.
    results: list[GrangerCausalityTestResult]
        Results of Granger causality test for each pair of time series.
    """

    def __init__(self, test_id: str, rank: int, results: list[GrangerCausalityTestResult]):
        self.test_id = test_id
        self.rank = rank
        self.results = results

    def __repr__(self):
        return f"GrangerCausalityTestReport({self.__props()})"

    def __str__(self):
        return self.__props()

    def __props(self):
        return f"test_id=({self.test_id}), " \
               f"rank = ({self.rank}), " \
               f"results=({self.results})"

    def to_json(self, pretty: bool=False):
        if pretty:
            return json.dumps(self, indent=3, default=lambda o: o.__dict__)
        else:
            return json.dumps(self, default=lambda o: o.__dict__)
     

# ##############################################################
#  Johansen cointegration test models
# ##############################################################

class JohansenCointTestStatistic:
    """
    Johansen cointegration test statistic.

    Properties
    ----------
    test_id: str
        Test identifier.
    test_rank: int
        Test rank.
    test_stat: float
        Test statistic.
    critical_values: numpy.ndarray[float]
        Test critical values.
    significance_levels: list[str]
        Test significance levels.
    test_result: bool
        test result.
    """

    def __init__(self, test_id: str, test_rank: int, test_stat: float, critical_values: list[float]):
        self.test_id = test_id
        self.test_rank = test_rank
        self.null_hypothesis = f"r<={test_rank}"
        self.test_stat = test_stat
        self.critical_values = critical_values.tolist()
        self.significance_levels = ["Critical Value 90%", "Critical Value 95%", "Critical Value 99%"]
        self.test_result = [bool(test_stat > cv) for cv in critical_values]

    def __repr__(self):
        return f"JohansenCointTestStatistic({self.__props()})"

    def __str__(self):
        return self.__props()

    def __props(self):
        return f"test_id=({self.test_id}), " \
               f"test_rank=({self.test_rank}), " \
               f"test_stat=({self.test_stat}), " \
               f"null_hypothesis=({self.null_hypothesis}), " \
               f"significance_levels=({self.significance_levels}), " \
               f"critical_values=({self.critical_values})"


class JohansenCointTestRank:
    """
    Johansen cointegration test rank.

    Properties
    ----------
    test_id: str
        Test identifier.
    test_ranks: list[float]
        Rank values for each significance level.
    significance_levels: list[str]
        Test significance levels.
    """

    def __init__(self, test_id: str, test_ranks: list[float]):
        self.test_id = test_id
        self.test_ranks = test_ranks
        self.significance_levels = ["Critical Value 90%", "Critical Value 95%", "Critical Value 99%"]

    def __repr__(self):
        return f"JohansenCointTestRank({self.__props()})"

    def __str__(self):
        return self.__props()

    def __props(self):
        return f"test_id=({self.test_id}), " \
               f"test_ranks=({self.test_ranks})"


class JohansenCointTestEigenVector:
    """
    Johansen cointegration test eigenvalue and eigenvector.

    Properties
    ----------
    test_id: str
        Test identifier.
    eigen_value: str
        Canonical variate eigen value.
    eigen_vector: numpy.ndarray[float]
        Canonical variate eigen vector.
    """

    def __init__(self, test_id: str, eigen_value: str, eigen_vector: numpy.ndarray[float]):
        self.test_id = test_id
        self.eigen_value = eigen_value
        self.eigen_vector = eigen_vector.tolist()

    def __repr__(self):
        return f"JohansenCointTestEigenVector({self.__props()})"

    def __str__(self):
        return self.__props()

    def __props(self):   
        return f"test_id=({self.test_id}), " \
               f"eigen_value=({self.eigen_value}), " \
               f"eigen_vector=({self.eigen_vector})"


class JohansenCointTestReport:
    """
    Johansen cointegration test report.

    Properties
    ----------
    test_id: str
        Test identifier.
    trace_test: list[JohansenCointTestStatistic]
        Trace static test results for each significance level.
    eigen_test: list[JohansenCointTestStatistic]
        Eigenvectors.
    rank: JohansenCointTestRank
        Trace statistic.
    eigen_vectors: list[JohansenCointTestEigenVector]
        Eigenvectors and eigenvalues of canonical variates.
    """

    def __init__(self, test_id: str, trace_test: list[JohansenCointTestStatistic], eigen_test: list[JohansenCointTestStatistic], ranks: JohansenCointTestRank, eigen_vectors: list[JohansenCointTestEigenVector]):
        self.test_id = test_id
        self.trace_test = trace_test
        self.eigen_test = eigen_test
        self.ranks = ranks
        self.eigen_vectors = eigen_vectors
        self.rank = min(self.ranks.test_ranks)

    def __repr__(self):
        return f"JohansenTestResult({self.__props()})"

    def __str__(self):
        return self.__props()

    def __props(self):
        return f"test_id=({self.test_id}), " \
               f"trace_test=({self.trace_test}), " \
               f"eigen_test=({self.eigen_test}), " \
               f"rank=({self.rank}), " \
               f"eigen_vectors=({self.eigen_vectors})"

    def to_json(self, pretty: bool=False):
        if pretty:
            return json.dumps(self, indent=3, default=lambda o: o.__dict__)
        else:
            return json.dumps(self, default=lambda o: o.__dict__)    
