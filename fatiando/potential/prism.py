"""
Calculate the potential fields of the 3D right rectangular prism.

**Gravity**
 
The gravitational fields are calculated using the forumla of Nagy et al. (2000)

* :func:`~fatiando.potential._prism.pot`
* :func:`~fatiando.potential._prism.gx`
* :func:`~fatiando.potential._prism.gy`
* :func:`~fatiando.potential._prism.gz`
* :func:`~fatiando.potential._prism.gxx`
* :func:`~fatiando.potential._prism.gxy`
* :func:`~fatiando.potential._prism.gxz`
* :func:`~fatiando.potential._prism.gyy`
* :func:`~fatiando.potential._prism.gyz`
* :func:`~fatiando.potential._prism.gzz`

**Magnetic**


**References**

Nagy, D., G. Papp, and J. Benedek, 2000, The gravitational potential and its
derivatives for the prism: Journal of Geodesy, 74, 552--560,
doi: 10.1007/s001900000116.
    
----

"""

try:
    from fatiando.potential._cprism import *
except ImportError:
    from fatiando.potential._prism import *
