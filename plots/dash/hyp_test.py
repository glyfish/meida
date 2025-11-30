import numpy
from matplotlib import pyplot
from scipy.stats import norm

from lib.utils import get_param_default_if_missing
from lib.data.hyp_test import HypothesisType
from lib.data.reports import VarianceRatioTestReport

def variance_ratio_test(report: VarianceRatioTestReport, **kwargs):
    title = get_param_default_if_missing("title", "Variance Ratio Test", **kwargs)
    npts  = get_param_default_if_missing("npts", 100, **kwargs)
    figsize = get_param_default_if_missing("figsize", (10,6), **kwargs)

    test_stats = report.stats
    x_vals = [-5.0, 5.0]
    min_stats = min(test_stats)
    max_stats = max(test_stats)
    min_stats = x_vals[0] if x_vals[0] < min_stats else min_stats
    max_stats = x_vals[-1] if x_vals[-1] > max_stats else max_stats
    x_vals = numpy.linspace(min_stats, max_stats, npts)
    y_vals = norm.cdf(x_vals)

    lower_critical_value = None
    lower_label = None
    upper_critical_value = None
    upper_label = None

    labels = [f"s={format(s, '4.0f')}" for s in report.s_vals]

    sig_level = report.sig_level
    if  report.hyp_type.value == HypothesisType.TWO_TAIL.value:
        sig_level_2 = sig_level/2.0
        lower_critical_value = norm.ppf(sig_level_2)
        upper_critical_value = norm.ppf(1.0 - sig_level_2)
        lower_label = f"Lower Tail={format(sig_level_2, '1.3f')}"
        upper_label = f"Upper Tail={format(1.0 - sig_level_2, '1.3f')}"
    elif report.hyp_type.value == HypothesisType.LOWER_TAIL.value:
        lower_critical_value = norm.ppf(sig_level)
        lower_label = f"Lower Tail={format(sig_level, '1.3f')}"
    elif report.hyp_type.value == HypothesisType.UPPER_TAIL.value:
        upper_critical_value = norm.ppf(1.0 - sig_level)
        upper_label = f"Upper Tail={format(1.0 - sig_level, '1.3f')}"

    _, axis = pyplot.subplots(figsize=figsize)

    text = axis.text(x_vals[0], 0.05*y_vals[-1], f"Significance={format(100.0*sig_level, '2.0f')}%", fontsize=18)
    text.set_bbox(dict(facecolor='white', alpha=0.75, edgecolor='white'))

    axis.set_ylim([-0.05, 1.05])

    axis.set_title(title)
    axis.set_ylabel("Normal(CDF)")
    axis.set_xlabel(r"$Z(s)$")

    axis.plot(x_vals, y_vals)
    if lower_critical_value is not None:
        axis.plot([lower_critical_value, lower_critical_value], [0.0, 1.0], color='red', label=lower_label, lw=4)
    if upper_critical_value is not None:
        axis.plot([upper_critical_value, upper_critical_value], [0.0, 1.0], color='black', label=upper_label, lw=4)

    for i in range(len(test_stats)):
        if labels is None:
            axis.plot([test_stats[i], test_stats[i]], [0.0, 1.0])
        else:
            axis.plot([test_stats[i], test_stats[i]], [0.0, 1.0], label=labels[i])

    axis.legend(loc='best', bbox_to_anchor=(0.1, 0.1, 0.8, 0.8))
