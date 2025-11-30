
import numpy
from statsmodels.tsa.vector_ar.var_model import VAR, VARResults, LagOrderResults

from lib.stats import multivariate_normal_samples

def mean(φ: list[numpy.ndarray[float, float]], μ: numpy.ndarray[float]) -> numpy.ndarray[float, float]:
    """
    Compute the stationary mean matrix for a VAR(n) process with the given parameters.

    Parameters
    ----------
    φ: list[numpy.ndarray[float, float]]
        VAR(n) process coefficient matrix.
    μ: numpy.ndarray[float]
        VAR(n) process offset matrix.

    Returns
    -------
    numpy.matrix[float]
        Stationary mean matrix.
    """

    n, m, _ = φ.shape
    Φ = phi_comp(φ)
    Μ = mean_comp(μ, n)
    tmp = numpy.matrix(numpy.eye(n * m)) - Φ
    return numpy.linalg.inv(tmp)*Μ


def cov(φ: numpy.matrix[float], ω: numpy.ndarray[float, float]) -> numpy.ndarray[float, float]:
    """
    Compute the stationary covariance matrix for the given VAR(n) process
    parameters.

    Parameters
    ----------
    φ: list[numpy.ndarray[float, float]]
        VAR(n) process coefficient matrix.
    ω: numpy.matrix[float]
        VAR(n) process gaussian noise autocovariance matrix.

    Returns
    -------
    numpy.matrix[float]
        Stationary covariance matrix.
    """

    n, m, _ = φ.shape

    Ω = omega_comp(ω, n)
    Φ = phi_comp(φ)
    eye = numpy.matrix(numpy.eye(m**2 * n**2))
    tmp = eye - numpy.kron(Φ, Φ)
    inv_tmp = numpy.linalg.inv(tmp)
    vec_var = inv_tmp * vec(Ω)
    return unvec(vec_var)


def acov(φ: list[numpy.ndarray[float, float]], ω: numpy.ndarray[float, float], n: int) -> numpy.ndarray[float, float]:
    """
    Compute the stationary auto covariance matrix for the given VAR(n)
    parameters.

    Parameters
    ----------
    φ: list[numpy.ndarray[float, float]]
        VAR(n) process coefficient matrix.
    ω: numpy.ndarray[float, float]
        VAR(n) process gaussian noise autocovariance matrix.
    n: int
        Maximum lag.

    Returns
    -------
    numpy.matrix[float]
        Stationary mean matrix.
    """

    Φ = phi_comp(φ)
    Σ = cov(φ, ω)
    l, _ = Φ.shape
    γ = numpy.zeros((n, l, l))
    γ[0] = numpy.matrix(numpy.eye(l))
    for i in range(1,n):
        γ[i] = γ[i-1]*Φ
    for i in range(n):
        γ[i] = Σ*γ[i].T
    return γ


def eig(φ: list[numpy.ndarray[float, float]]) -> numpy.ndarray[float]:
    """
    Compute eigen values of VAR(n) parameter matrix transformed to VAR(1) companion form. 
    Stationarity requires that |λ| < 1.

    Parameters
    ----------
    φ: list[numpy.ndarray[float, float]]
       VAR(n) coefficient matrix in companion form.

    Returns
    -------
    numpy.ndarray[float]
        Array of eigen values.
    """

    Φ = phi_comp(φ)
    λ, _ = numpy.linalg.eig(Φ)
    return λ


def is_stationary(φ: list[numpy.ndarray[float, float]]) -> bool:
    """
    Return True if the VAR(n) parameter matrix is stationary.

    Parameters
    ----------
    φ: list[numpy.ndarray[float, float]]
        VAR(n) covariance matrix.

    Returns
    -------
    bool
        True if VAR(n) process is stationary.
    """

    for λ in eig(φ):
        if abs(λ) >= 1:
            return False
    return True


def phi_comp(φ: list[numpy.matrix[float]]) -> numpy.ndarray[float, float]:
    """
    Convert the VAR(n) coefficient matrix to the VAR(1) companion form used for calculations. 

    Parameters
    ----------
   φ: list[numpy.matrix[float]]
         VAR(n) coefficient matrix

    Returns
    -------
    numpy.ndarray[float, float]
        Companion form of noise covariance matrix.
    """

    n, m, _ = φ.shape
    p = φ[0]
    for i in range(1, n):
        p = numpy.concatenate((p, φ[i]), axis=1)
    for i in range(n-1):
        if i == 0:
            r = numpy.eye(m)
        else:
            r = numpy.zeros((m, m))
        for j in range(1, n):
            if j == i:
                r = numpy.concatenate((r, numpy.eye(m)), axis=1)
            else:
                r = numpy.concatenate((r, numpy.zeros((m, m))), axis=1)
        p = numpy.concatenate((p, r), axis=0)

    return numpy.matrix(p)


def mean_comp(Μ: numpy.matrix[float], n: int) -> numpy.ndarray[float, float]:
    """
    Convert the VAR(n) offset matrix the VAR(1) companion form used for calculations.

    Parameters
    ----------
    Μ: numpy.matrix[float]
        VAR(n) offset matrix.
    n: int
        Order of VAR process.

    Returns
    -------
    numpy.ndarray[float, float]
        Companion form of VAR(n) offset matrix.
    """

    m = len(Μ)
    p = numpy.zeros(m * n)
    p[:m] = Μ
    return numpy.matrix([p]).T


def omega_comp(ω: numpy.ndarray[float, float], n: int) -> numpy.ndarray[float, float]:
    """
    Convert VAR(n) gaussian noise covariance matrix to companion form.

    Parameters
    ----------
    ω: numpy.ndarray[float, float]
        VAR(n) noise covariance matrix.
    n: int
        Order of VAR process.

    Returns
    -------
    numpy.ndarray[float, float]
        Companion form of noise covariance matrix.
    """

    m, _ = ω.shape

    p = numpy.zeros((m * n, m * n))
    p[:m, :m] = ω

    return numpy.matrix(p)


def vec(m: numpy.ndarray[float, float]) -> numpy.ndarray[float, float]:
    """
    Apply the vec operator to the given matrix. The vec operation 
    applied to the matrix,

    A = [[a11, a12],
         [a21, a22]]

    gives,

    vec(A) = [[a11],
              [a21],
              [a12],
              [a22]]

    Parameters
    ----------
    m: numpy.ndarray[float, float]
        Matrix to be converted to vec form.

    Returns
    -------
    numpy.ndarray[float, float]
        Input vector converted to vec form.
    """

    _, n = m.shape
    v = numpy.matrix(numpy.zeros(n**2)).T
    for i in range(n):
        d = i*n
        v[d:d+n] = m[:,i]
    return v


def unvec(v: numpy.ndarray[float, float]) -> numpy.ndarray[float, float]:
    """
    Apply the inverse of the vec operation to the given matrix. For the following
    matrix in vec form,

    A = [[a11],
         [a21],
         [a12],
         [a22]]

    apply unvec gives,

    unvec(A) = [[a11, a12],
                [a21, a22]]

    Parameters
    ----------
    m: numpy.ndarray[float, float]
        Matrix to be converted to unvec form.

    Returns
    -------
    numpy.ndarray[float, float]
        Input vector in unvec form.
    """

    n2, _ = v.shape
    n = int(numpy.sqrt(n2))
    m = numpy.matrix(numpy.zeros((n, n)))
    for i in range(n):
        d = i*n
        m[:,i] = v[d:d+n]
    return m


def var(x0: numpy.ndarray[float, float], μ: numpy.ndarray[float], φ: list[numpy.ndarray[float, float]], ω: numpy.ndarray[float, float], npts: int) -> numpy.ndarray[float, float]:
    """
    Simulate a VAR(n) process using the provided parameters.
    
    Parameters
    ----------
    x0: numpy.ndarray[float, float]
        VAR(n) process initial value matrix.
    μ: numpy.ndarray[float, float]
        VAR(n) process offset matrix.
    φ:  list[numpy.ndarray[float, float]]
        VAR(n) process coefficient matrix.
    ω: numpy.ndarray[float, float]
        VAR(n) process gaussian noise autocovariance function.
    npts: int
        Number of samples.

    Returns
    -------
    numpy.matrix[float]
        Simulation results.
    """

    n, m, _ = φ.shape
    xt = numpy.zeros((npts, m))
    ε = multivariate_normal_samples(numpy.zeros(m), ω, npts)
    for i in range(n):
        xt[i] = x0[i]
    for i in range(n, npts):
        xt[i] = ε[i] + μ
        for j in range(n):
            t1 = φ[j]*numpy.matrix(xt[i-j-1]).T
            xt[i] += numpy.squeeze(numpy.array(t1), axis=1)
    return numpy.transpose(xt)
    
def fit(endog: numpy.ndarray[float, float], maxlags: int=12, trend: str="c") -> VARResults:
    """
    Estimate the parameters for and assumed VAR(n) model.

    Parameters
    ----------
    endog: DataFrame
        VAR(n) process endogenous variable samples.
    maxlags: int
        Maximum number of time lags tried. (default is 12)
    trend: str
        Assumed trend (default 'c'). 
        Values 'n'=no trend, 'c'=constant offset, 'ct'=linear trend, 'ctt'=quadratic and linear trend.

    Returns
    -------
    VARResult
        Analysis results.
    """

    return __var_model(endog).fit(maxlags=maxlags, trend=trend)
    
def order_estimate(samples: numpy.ndarray[float, float], maxlags: int=12, trend: str="c") -> LagOrderResults:
    """
    Estimate order of VAR samples.

    Parameters
    ----------
    samples: numpy.ndarray[float, float]
        Samples analyzed.    
    maxlags: int
        Maximum number of lags.
    trend: str
        Assumed trend (default 'c'). 
        Values 'n'=no trend, 'c'=constant offset, 'ct'=linear trend, 'ctt'=quadratic and linear trend.

    Returns
    -------
    LagOrderResults
        Order results.
    """

    return __var_model(samples).select_order(maxlags=maxlags)
        
def __var_model(endog: numpy.ndarray[float, float]) -> VAR:
    """
    Estimate the parameters for and assumed VAR(n) model.

    Parameters
    ----------
    endog: DataFrame
        VAR(n) process endogenous variable samples.

    Returns
    -------
    VAR
        VAR model.
    """

    return VAR(endog)
