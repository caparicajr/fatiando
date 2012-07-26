"""
3D potential field inversion by planting anomalous densities.

Implements the method of Uieda and Barbosa (2011).

A "heuristic" inversion for compact 3D geologic bodies. Performs the inversion
by iteratively growing the estimate around user-specified "seeds". Supports
various kinds of data (gravity, gravity tensor).

The inversion is performed by function
:func:`~fatiando.potential.harvester.harvest`. The required information, such as
observed data, seeds, and regularization, are passed to the function though
seed classes and data modules.

**Functions**

* :func:`~fatiando.potential.harvester.harvest`: Performs the inversion
* :func:`~fatiando.potential.harvester.wrapdata`: Creates the data modules
  required by ``harvest``
* :func:`~fatiando.potential.harvester.loadseeds`: Loads a set of points and
  physical properties that specify the seeds from a file
* :func:`~fatiando.potential.harvester.sow`: Creates the seeds from a set of
  points that specify their locations

**Usage**

The recommened way of generating the required seeds and data modules is to use
the helper functions :func:`~fatiando.potential.harvester.wrapdata`,
:func:`~fatiando.potential.harvester.loadseeds`, and
:func:`~fatiando.potential.harvester.sow`.

A typical script to run the inversion on a data set looks like::

    import numpy
    import fatiando as ft
    # Load the data from a file
    xp, yp, zp, gz = numpy.loadtxt('mydata.xyz', unpack=True)
    # Create a mesh assuming that 'bounds' are the limits of the mesh and
    # 'shape' is the number of prisms in each dimension
    bounds = (xmin, xmax, ymin, ymax, zmin, zmax)
    shape = (nz, ny, nx)
    mesh = ft.msh.ddd.PrismMesh(bounds, shape)
    # Make the data modules
    dms = ft.pot.harvester.wrapdata(mesh, xp, yp, zp, gz=gz)
    # Read the seeds from a file with 4 columns: x  y  z  density
    points, densities = ft.pot.harvester.loadseeds('myseedfile.txt')
    seeds = ft.pot.harvester.sow(points, {'density':densities}, mesh, mu=0.1)
    # Run the inversion
    estimate, goals, misfits = ft.pot.harvester.harvest(dms, seeds)
    # fill the mesh with the density values
    mesh.addprop('density', estimate['density'])
    # Save the mesh in UBC-GIF format
    mesh.dump('result')


**Seeds**

A seed class determines what kind of geometric element is used to parametrize
the anomalous density distribution. For example, if you use a SeedPrism, the
output of :func:`~fatiando.potential.harvester.harvest` will be a list of prisms
that make up the estimated density distribution.

* :class:`~fatiando.potential.harvester.SeedPrism`

**Data Modules**

Data modules wrap the observed data and calculate the predicted data for a given
parametrization.

* :class:`~fatiando.potential.harvester.DMPrismGz`
* :class:`~fatiando.potential.harvester.DMPrismGxx`
* :class:`~fatiando.potential.harvester.DMPrismGxy`
* :class:`~fatiando.potential.harvester.DMPrismGxz`
* :class:`~fatiando.potential.harvester.DMPrismGyy`
* :class:`~fatiando.potential.harvester.DMPrismGyz`
* :class:`~fatiando.potential.harvester.DMPrismGzz`
* :class:`~fatiando.potential.harvester.DMPrismI2`

**References**

Uieda, L., and V. C. F. Barbosa, 2011, Robust 3D gravity gradient inversion by
planting anomalous densities: SEG Expanded Abstracts, v. 30, 820-824.

----

"""
import time
import math
import bisect

import numpy

from fatiando.potential import prism as pot_prism
from fatiando import utils, logger

log = logger.dummy('fatiando.potential.harvester')


def wrapdata(mesh, xp, yp, zp, gz=None, gxx=None, gxy=None, gxz=None, gyy=None,
    gyz=None, gzz=None, inv2=None, norm=1):
    """
    Takes the observed data vectors (measured at the same points) and generates
    the data modules required by :func:`~fatiando.potential.harvester.harvest`.

    If your data sets where measured at different points, make multiple calls
    to this function. For example, if gz was measured at x1, y1, z1 while gzz
    and gxx were measured at x2, y2, z2, use::

        dms = wrapdata(mesh, x1, y1, z1, gz=gz)
        dms.extend(wrapdata(mesh, x2, y2, z2, gxx=gxx, gzz=gzz))

    Accepted data:

    * gz: vertical component of the gravitational attraction (i.e., gravity
      anomaly)
    * gxx, gxy, etc: the components of the gravity gradient tensor
    * inv2: the second invariant of the gravity gradient tensor (see
      :mod:`fatiando.potential.tensor`)

    Parameters:

    * mesh : :class:`fatiando.mesher.ddd.PrismMesh`
        The model space mesh (or interpretative model)
    * xp, yp, zp : arrays
        The x, y, and z coordinates of the observation points.
    * gz, gxx, gxy, etc. : arrays
        The observed data, measured at xp, yp, and zp, of the respective
        components.
    * norm : int
        Order of the norm of the residual vector to use. Can be:

        * 1 -> l1 norm
        * 2 -> l2 norm

    Returns

    * dms : list
        List of data modules

    """
    log.info("Creating prism data modules:")
    log.info("  data misfit norm: %d" % (norm))
    log.info("  observations per data type: %d" % (len(xp)))
    dms = []
    fields = []
    if gz is not None:
        dms.append(DMPrismGz(gz, xp, yp, zp, mesh, norm))
        fields.append('gz')
    if gxx is not None:
        dms.append(DMPrismGxx(gxx, xp, yp, zp, mesh, norm))
        fields.append('gxx')
    if gxy is not None:
        dms.append(DMPrismGxy(gxy, xp, yp, zp, mesh, norm))
        fields.append('gxy')
    if gxz is not None:
        dms.append(DMPrismGxz(gxz, xp, yp, zp, mesh, norm))
        fields.append('gxz')
    if gyy is not None:
        dms.append(DMPrismGyy(gyy, xp, yp, zp, mesh, norm))
        fields.append('gyy')
    if gyz is not None:
        dms.append(DMPrismGyz(gyz, xp, yp, zp, mesh, norm))
        fields.append('gyz')
    if gzz is not None:
        dms.append(DMPrismGzz(gzz, xp, yp, zp, mesh, norm))
        fields.append('gzz')
    if inv2 is not None:
        dms.append(DMPrismI2(inv2, xp, yp, zp, mesh, norm))
        fields.append('second invariant')
    log.info("  data types: %s" % (', '.join(fields)))
    log.info("  total number of observations: %d" % (len(xp)*len(fields)))
    return dms

def sow(points, props, mesh, mu=0., delta=0.0001, reldist=False):
    """
    Generate a set of :class:`~fatiando.potential.harvester.SeedPrism` from a
    list of points.

    This is the preferred method for generating seeds! We strongly discourage
    using :class:`~fatiando.potential.harvester.SeedPrism` directly unless you
    know what you're doing!

    Parameters:

    * points : list of lists
        List of ``[x, y, z]`` coordinates where the seeds should be placed. Each
        point generates a seed (prism in *mesh*) that has the point inside it.
    * props : dict
        Dictionary with the physical properties assigned to each seed.
        Ex: ``props={'density':[10, 28, ...], 'susceptibility':[100, 23, ...]}``
    * mesh : :class:`fatiando.mesher.ddd.PrismMesh`
        The model space mesh (or interpretative model).
    * mu : float
        Compactness regularizing parameters. Positive scalar that measures the
        trade-off between fit and regularization. This applies only to this
        seeds contribution to the total regularizing function. This way you can
        assign different mus to different seeds.
    * delta : float
        Minimum percentage of change required in the goal function to perform
        an accretion. The smaller this is, the less the solution is able to
        grow. If None, will use the values passed to each seed. If not None,
        will overwrite the values passed to the seeds.
    * reldist : True or False
        Wether or not to use relative distances on the regularizing function.
        The standard way is use the distances between the centers of a prism and
        the respective seed. If ``reldist == True``, will use distance in number
        of cells instead (e.g., the prism right on top is ``dist = 1`` away).
        Using this is when mesh cells are not cubic (flattened or rectangular).

    Returns:

    * seeds : list
        List of :class:`~fatiando.potential.harvester.SeedPrism`

    """
    log.info("Generating prism seeds:")
    log.info("  regularizing parameter (mu): %g" % (mu))
    log.info("  delta (threshold): %g" % (delta))
    log.info("  distance type: %s" %
                ({True:'relative', False:'absolute'}[reldist]))
    log.info("  physical properties: %s" % (', '.join(p for p in props)))
    log.info("  points: %d" % (len(points)))
    seeds = []
    for i, point in enumerate(points):
        sprops = {}
        for p in props:
            sprops[p] = props[p][i]
        seed = SeedPrism(point, sprops, mesh, mu=mu, delta=delta,
                         reldist=reldist)
        if seed.seed[0] not in (s.seed[0] for s in seeds):
            seeds.append(seed)
        else:
            log.warning(
                "  Duplicate seed found at point %s! Will ignore this one."
                % (str(point)))
    log.info("  seeds found: %d" % (len(seeds)))
    return seeds

def loadseeds(fname):
    """
    Load a set of seed locations and physical properties from a file.

    The file should have columns: x  y  z  prop1  prop2  ...
    x, y, and z are the coordinates where the seed should be put. prop1, prop2
    etc, are the values of the physical properties of the seeds (like density,
    susceptibility, etc)

    Remember: the coordinate system is x->North, y->East, and z->Down

    Parameters:

    * fname : str or file
        Open file object or filename string

    Returns:

    * [points, props1, props2, ...]
        *points* is a list of (x, y, z) points where the seeds will be placed
        and *props1* is list with the values of the first physical property,
        *props2* the second, etc.

    Example:

        >>> from StringIO import StringIO
        >>> file = StringIO("1 2 3 4 5\\n6 7 8 9 -1")
        >>> points, props1, props2 = loadseeds(file)
        >>> print points
        [[ 1.  2.  3.]
         [ 6.  7.  8.]]
        >>> print props1
        [ 4.  9.]
        >>> print props2
        [ 5. -1.]

        >>> from StringIO import StringIO
        >>> file = StringIO("1 2 3 4 5")
        >>> points, props1, props2 = loadseeds(file)
        >>> print points
        [[ 1.  2.  3.]]
        >>> print props1
        [ 4.]
        >>> print props2
        [ 5.]

    """
    data = numpy.loadtxt(fname, unpack=True)
    # In case there is only one seed
    if len(data.shape) == 1:
        data.shape = (data.shape[0], 1)
    points = data[0:3].T
    output = [points]
    for prop in data[3:]:
        output.append(prop)
    return output

class DMPrism(object):
    """
    Generic data module for the right rectangular prism.

    This class wraps the observed data and measurement points. Its derived
    classes should knows how to calculate the predicted data for their
    respective components.

    Use this class as a base for developing data modules for individual
    components, like gz, gzz, etc.

    The only method that needs to be implemented by the derived classes is
    :meth:`~fatiando.potential.harvester.DMPrism._effect_of_prism`. This method
    is used to calculate the effect of a prism on the computation points (i.e.,
    the column of the Jacobian matrix corresponding to the prism times the
    prisms physical property value).

    Derived classes must also set the variable ``prop_type`` to the apropriate
    physical property that the data module uses.

    Examples:

    To build a prism data module for the gravity anomaly::

        class DMPrismGz(DMPrism):

            def __init__(self, data, xp, yp, zp, mesh, norm=1):
                DMPrism.__init__(self, data, xp, yp, zp, mesh, norm)
                self.prop_type = 'density'

            def _effect_of_prism(self, index, props):
                return fatiando.potential.prism.gz(self.xp, self.yp, self.zp,
                    [self.mesh[index]])

    Parameters:

    * data : array
        The observed data values of the component of the potential field
    * xp, yp, zp : arrays
        Arrays with the x, y, and z coordinates of the observation points.
    * mesh : :class:`fatiando.mesher.ddd.PrismMesh`
        The model space mesh (or interpretative model).
    * norm : int
        Order of the norm of the residual vector to use. Can be:

        * 1 -> l1 norm
        * 2 -> l2 norm

    """

    def __init__(self, data, xp, yp, zp, mesh, norm):
        if norm not in [1, 2]:
            raise ValueError("Invalid norm %s: must be 1 or 2" % (str(norm)))
        if len(xp) != len(yp) != len(zp) != len(data):
            raise ValueError("xp, yp, zp, and data must have same length")
        self.data = data
        self.predicted = numpy.zeros_like(data)
        self.xp, self.yp, self.zp = xp, yp, zp
        self.mesh = mesh
        self.norm = norm
        self.weight = 1./numpy.linalg.norm(data, norm)
        self.effect = {}
        self.prop_type = None

    def _effect_of_prism(self, index, props):
        """
        Calculate the effect of the *index*th prism with the given physical
        properties.

        This is the only function that need to be implemented by the derived
        classes!

        Parameters:

        * index : int
            Index of the prism in the mesh
        * props : dict
            A dictionary with the physical properties of the prism.

        Returns:

        * effect : array
            Array with the values of the effect of the *index*th prism

        """
        msg = "Oops, effect calculation not implemented"
        raise NotImplementedError(msg)

    def update(self, element):
        """
        Updated the precited data to include element.

        Parameters:

        * element : list
            List ``[index, props]`` where ``index`` is the index of the element
            in the mesh and ``props`` is a dictionary with the physical
            properties of the element.

        """
        index, props = element
        # Only updated if the element doesn't have a physical property that
        # influences this data module
        if self.prop_type in props:
            if index not in self.effect:
                self.effect[index] = self._effect_of_prism(index, props)
            self.predicted += self.effect[index]
            del self.effect[index]

    def testdrive(self, element):
        """
        Calculate the value that the data misfit would have if *element* was
        included in the estimate.

        Parameters:

        * element : list
            List ``[index, props]`` where ``index`` is the index of the element
            in the mesh and ``props`` is a dictionary with the physical
            properties of the element.

        Returns:

        * misfit : float
            The misfit value

        """
        index, props = element
        # If the element doesn't have a physical property that influences this
        # data module, then return the previous misfit
        if self.prop_type not in props:
            # TODO: keep track of the misfit value on update so that don't have
            # to calculate it every time.
            return self.misfit(self.predicted)
        if index not in self.effect:
            self.effect[index] = self._effect_of_prism(index, props)
        tmp = self.predicted + self.effect[index]
        return self.misfit(tmp)

    def misfit(self, predicted):
        """
        Return the value of the data misfit given a predicted data vector.

        Parameters:

        * predicted : array
            Array with the predicted data

        Returns:

        * misfit : float
            The misfit value

        """
        return self.weight*numpy.linalg.norm(self.data - predicted, self.norm)

    def get_predicted(self):
        """
        Get the predicted data vector out of this data module.

        Use this method to get the predicted data after an inversion has been
        performed using the data module.

        Returns:

        * predicted : array
            Array with the predicted data

        """
        return self.predicted

class DMPrismI2(DMPrism):
    """
    Data module for the second invariant of the gravity gradient tensor of a
    right rectangular prism. (see :mod:`fatiando.potential.tensor`)

    See :class:`~fatiando.potential.harvester.DMPrism` for details.

    **WARNING**: It is not recommended that you use this class directly. Use
    function :func:`~fatiando.potential.harvester.wrapdata` to generate data
    modules instead.

    """

    def __init__(self, data, xp, yp, zp, mesh, norm=1):
        DMPrism.__init__(self, data, xp, yp, zp, mesh, norm)
        self.prop_type = 'density'
        self.estimate = []

    def _effect_of_cells(self, cells):
        gxx = pot_prism.gxx(self.xp, self.yp, self.zp, cells)
        gxy = pot_prism.gxy(self.xp, self.yp, self.zp, cells)
        gxz = pot_prism.gxz(self.xp, self.yp, self.zp, cells)
        gyy = pot_prism.gyy(self.xp, self.yp, self.zp, cells)
        gyz = pot_prism.gyz(self.xp, self.yp, self.zp, cells)
        gzz = pot_prism.gzz(self.xp, self.yp, self.zp, cells)
        inv2 = (gxx*(gyy*gzz - gyz**2) + gxy*(gyz*gxz - gxy*gzz)
                + gxz*(gxy*gyz - gxz*gyy))
        return inv2

    def update(self, element):
        """
        Updated the precited data to include element.

        Parameters:

        * element : list
            List ``[index, props]`` where ``index`` is the index of the element
            in the mesh and ``props`` is a dictionary with the physical
            properties of the element.

        """
        index, props = element
        cell = self.mesh[index]
        for p in props:
            cell.addprop(p, props[p])
        self.estimate.append(cell)
        self.predicted = self._effect_of_cells(self.estimate)

    def testdrive(self, element):
        """
        Calculate the value that the data misfit would have if *element* was
        included in the estimate.

        Parameters:

        * element : list
            List ``[index, props]`` where ``index`` is the index of the element
            in the mesh and ``props`` is a dictionary with the physical
            properties of the element.

        Returns:

        * misfit : float
            The misfit value

        """
        index, props = element
        # If the element doesn't have a physical property that influences this
        # data module, then return the previous misfit
        if self.prop_type not in props:
            # TODO: keep track of the misfit value on update so that don't have
            # to calculate it every time.
            return self.misfit(self.predicted)
        cell = self.mesh[index]
        for p in props:
            cell.addprop(p, props[p])
        tmp = self._effect_of_cells(self.estimate + [cell])
        return self.misfit(tmp)

class DMPrismGz(DMPrism):
    """
    Data module for the gravity anomaly of a right rectangular prism.

    See :class:`~fatiando.potential.harvester.DMPrism` for details.

    **WARNING**: It is not recommended that you use this class directly. Use
    function :func:`~fatiando.potential.harvester.wrapdata` to generate data
    modules instead.

    """

    def __init__(self, data, xp, yp, zp, mesh, norm=1):
        DMPrism.__init__(self, data, xp, yp, zp, mesh, norm)
        self.prop_type = 'density'

    def _effect_of_prism(self, index, props):
        return pot_prism.gz(self.xp, self.yp, self.zp, [self.mesh[index]],
            dens=props[self.prop_type])

class DMPrismGxx(DMPrism):
    """
    Data module for the gxx component of the gravity gradient tensor of a right
    rectangular prism.

    See :class:`~fatiando.potential.harvester.DMPrism` for details.

    **WARNING**: It is not recommended that you use this class directly. Use
    function :func:`~fatiando.potential.harvester.wrapdata` to generate data
    modules instead.

    """

    def __init__(self, data, xp, yp, zp, mesh, norm=1):
        DMPrism.__init__(self, data, xp, yp, zp, mesh, norm)
        self.prop_type = 'density'

    def _effect_of_prism(self, index, props):
        return pot_prism.gxx(self.xp, self.yp, self.zp, [self.mesh[index]],
            dens=props[self.prop_type])

class DMPrismGxy(DMPrism):
    """
    Data module for the gxy component of the gravity gradient tensor of a right
    rectangular prism.

    See :class:`~fatiando.potential.harvester.DMPrism` for details.

    **WARNING**: It is not recommended that you use this class directly. Use
    function :func:`~fatiando.potential.harvester.wrapdata` to generate data
    modules instead.

    """

    def __init__(self, data, xp, yp, zp, mesh, norm=1):
        DMPrism.__init__(self, data, xp, yp, zp, mesh, norm)
        self.prop_type = 'density'

    def _effect_of_prism(self, index, props):
        return pot_prism.gxy(self.xp, self.yp, self.zp, [self.mesh[index]],
            dens=props[self.prop_type])

class DMPrismGxz(DMPrism):
    """
    Data module for the gxz component of the gravity gradient tensor of a right
    rectangular prism.

    See :class:`~fatiando.potential.harvester.DMPrism` for details.

    **WARNING**: It is not recommended that you use this class directly. Use
    function :func:`~fatiando.potential.harvester.wrapdata` to generate data
    modules instead.

    """

    def __init__(self, data, xp, yp, zp, mesh, norm=1):
        DMPrism.__init__(self, data, xp, yp, zp, mesh, norm)
        self.prop_type = 'density'

    def _effect_of_prism(self, index, props):
        return pot_prism.gxz(self.xp, self.yp, self.zp, [self.mesh[index]],
            dens=props[self.prop_type])

class DMPrismGyy(DMPrism):
    """
    Data module for the gyy component of the gravity gradient tensor of a right
    rectangular prism.

    See :class:`~fatiando.potential.harvester.DMPrism` for details.

    **WARNING**: It is not recommended that you use this class directly. Use
    function :func:`~fatiando.potential.harvester.wrapdata` to generate data
    modules instead.

    """

    def __init__(self, data, xp, yp, zp, mesh, norm=1):
        DMPrism.__init__(self, data, xp, yp, zp, mesh, norm)
        self.prop_type = 'density'

    def _effect_of_prism(self, index, props):
        return pot_prism.gyy(self.xp, self.yp, self.zp, [self.mesh[index]],
            dens=props[self.prop_type])

class DMPrismGyz(DMPrism):
    """
    Data module for the gyz component of the gravity gradient tensor of a right
    rectangular prism.

    See :class:`~fatiando.potential.harvester.DMPrism` for details.

    **WARNING**: It is not recommended that you use this class directly. Use
    function :func:`~fatiando.potential.harvester.wrapdata` to generate data
    modules instead.

    """

    def __init__(self, data, xp, yp, zp, mesh, norm=1):
        DMPrism.__init__(self, data, xp, yp, zp, mesh, norm)
        self.prop_type = 'density'

    def _effect_of_prism(self, index, props):
        return pot_prism.gyz(self.xp, self.yp, self.zp, [self.mesh[index]],
            dens=props[self.prop_type])

class DMPrismGzz(DMPrism):
    """
    Data module for the gzz component of the gravity gradient tensor of a right
    rectangular prism.

    See :class:`~fatiando.potential.harvester.DMPrism` for details.

    **WARNING**: It is not recommended that you use this class directly. Use
    function :func:`~fatiando.potential.harvester.wrapdata` to generate data
    modules instead.

    """

    def __init__(self, data, xp, yp, zp, mesh, norm=1):
        DMPrism.__init__(self, data, xp, yp, zp, mesh, norm)
        self.prop_type = 'density'

    def _effect_of_prism(self, index, props):
        return pot_prism.gzz(self.xp, self.yp, self.zp, [self.mesh[index]],
            dens=props[self.prop_type])

class SeedPrism(object):
    """
    A 3D right rectangular prism seed.

    One of the types of seed required by
    :func:`~fatiando.potential.harvester.harvest`.

    Wraps the information about a seed. Also knows how to grow a seed and the
    estimate it produced.

    **It is highly recommended** that you use function
    :func:`~fatiando.potential.harvester.sow` to generate the seeds
    because it checks for duplicate seeds.

    Parameters:

    * point : tuple or list
        ``(x, y, z)``: x, y, z coordinates of where you want to place the seed.
        The seed will be a prism of the mesh that has this point inside it.
    * props : dict
        Dictionary with the physical properties assigned to the seed.
        Ex: ``props={'density':10, 'susceptibility':10000}``
    * mesh : :class:`fatiando.mesher.ddd.PrismMesh`
        The model space mesh (or interpretative model).
    * mu : float
        Compactness regularizing parameters. Positive scalar that measures the
        trade-off between fit and regularization. This applies only to this
        seeds contribution to the total regularizing function. This way you can
        assign different mus to different seeds.
    * delta : float
        Minimum percentage of change required in the goal function to perform
        an accretion. The smaller this is, the less the solution is able to grow
    * reldist : True or False
        Wether or not to use relative distances on the regularizing function.
        The standard way is use the distances between the centers of a prism and
        the respective seed. If ``reldist == True``, will use distance in number
        of cells instead (e.g., the prism right on top is ``dist = 1`` away).
        Using this is when mesh cells are not cubic (flattened or rectangular).

    """

    kind = 'prism'

    def __init__(self, point, props, mesh, mu=0., delta=0.0001, reldist=False):
        self.props = props
        self.mesh = mesh
        self.delta = delta
        index = self._get_index(point, mesh)
        self.index = index
        self.seed = [self.index, self.props]
        self.estimate = [index]
        nz, ny, nx = mesh.shape
        dx, dy, dz = mesh.dims
        self.weight = 1./((sum([nx*dx, ny*dy, nz*dz])/3.))
        self.neighbors = []
        self.reg = 0
        self.distance = {}
        self._get_distances = self._get_absolute_distances
        if reldist:
            k = index/(nx*ny)
            j = (index - k*(nx*ny))/nx
            i = (index - k*(nx*ny) - j*nx)
            self.ijk = [i, j, k]
            self._get_distances = self._get_relative_distances
            self.weight = 1./((sum([nx, ny, nz])/3.))
        self.mu = mu*self.weight

    def get_prism(self):
        """
        Return a :func:`~fatiando.mesher.ddd.Prism` corresponding to the seed.
        """
        # TODO: Replace hand setting of physical properties of a prism with an
        # actual addprop function.
        index, props = self.seed
        prism = self.mesh[index]
        for p in props:
            prism.addprop(p, props[p])
        return prism

    def initialize(self, seeds):
        """
        Initialize the neighbor list of this seed.

        Leaves out elements that are already neighbors of other seeds or that
        are the seeds.
        """
        self.neighbors.extend(
            self._not_neighbors(seeds,
                self._are_free(seeds,
                    self._find_neighbors(self.index))))
        self._get_distances(self.neighbors)

    def _get_relative_distances(self, neighbors):
        """
        Add the relative distance of the neighbors to the distance dictionary.
        """
        for n in neighbors:
            nz, ny, nx = self.mesh.shape
            # The i, j, k index of the neighbor in the mesh
            knbr = n/(nx*ny)
            jnbr = (n - knbr*(nx*ny))/nx
            inbr = (n - knbr*(nx*ny) - jnbr*nx)
            isd, jsd, ksd = self.ijk
            dx = isd - inbr
            dy = jsd - jnbr
            dz = ksd - knbr
            self.distance[n] = math.sqrt(dx**2 + dy**2 + dz**2)

    def _get_absolute_distances(self, neighbors):
        """
        Add the absolute distance of the neighbors to the distance dictionary.
        """
        scell = self.mesh[self.index]
        for n in neighbors:
            ncell = self.mesh[n]
            dx = abs(ncell.x1 - scell.x1)
            dy = abs(ncell.y1 - scell.y1)
            dz = abs(ncell.z1 - scell.z1)
            self.distance[n] = math.sqrt(dx**2 + dy**2 + dz**2)

    def _get_index(self, point, mesh):
        """
        Get the index of the prism in mesh that has point inside it.
        """
        x1, x2, y1, y2, z1, z2 = mesh.bounds
        nz, ny, nx = mesh.shape
        xs = mesh.get_xs()
        ys = mesh.get_ys()
        zs = mesh.get_zs()
        x, y, z = point
        found = False
        if x <= x2 and x >= x1 and y <= y2 and y >= y1 and z <= z2 and z >= z1:
            # -1 because bisect gives the index z would have. I want to know
            # what index z comes after
            k = bisect.bisect_left(zs, z) - 1
            j = bisect.bisect_left(ys, y) - 1
            i = bisect.bisect_left(xs, x) - 1
            s = i + j*nx + k*nx*ny
            if mesh[s] is not None:
                return s
        raise ValueError("Couldn't find seed at location %s" % (str(point)))

    def _find_neighbors(self, n, full=False, up=True, down=True):
        """
        Return a list of neighboring prisms (that share a face) of *neighbor*.

        Parameters:

        * n : int
            The index of the neighbor in the mesh.
        * full : True or False
            If True, return also the prisms on the diagonal

        Returns:

        * neighbors : list
            List with the index of the neighbors in the mesh

        """
        nz, ny, nx = self.mesh.shape
        above, bellow, front, back, left, right = [None]*6
        # The guy above
        tmp = n - nx*ny
        if up and tmp > 0:
            above = tmp
        # The guy bellow
        tmp = n + nx*ny
        if down and tmp < self.mesh.size:
            bellow = tmp
        # The guy in front
        tmp = n + 1
        if n%nx < nx - 1:
            front = tmp
        # The guy in the back
        tmp = n - 1
        if n%nx != 0:
            back = tmp
        # The guy to the left
        tmp = n + nx
        if n%(nx*ny) < nx*(ny - 1):
            left = tmp
        # The guy to the right
        tmp = n - nx
        if n%(nx*ny) >= nx:
            right = tmp
        indexes = [above, bellow, front, back, left, right]
        # The diagonal neighbors
        if full:
            append = indexes.append
            if front is not None and left is not None:
                append(left + 1)
            if front is not None and right is not None:
                append(right + 1)
            if back is not None and left is not None:
                append(left - 1)
            if back is not None and right is not None:
                append(right - 1)
            if above is not None and left is not None:
                append(above + nx)
            if above is not None and right is not None:
                append(above - nx)
            if above is not None and front is not None:
                append(above + 1)
            if above is not None and back is not None:
                append(above - 1)
            if above is not None and front is not None and left is not None:
                append(above + nx + 1)
            if above is not None and front is not None and right is not None:
                append(above - nx + 1)
            if above is not None and back is not None and left is not None:
                append(above + nx - 1)
            if above is not None and back is not None and right is not None:
                append(above - nx - 1)
            if bellow is not None and left is not None:
                append(bellow + nx)
            if bellow is not None and right is not None:
                append(bellow - nx)
            if bellow is not None and front is not None:
                append(bellow + 1)
            if bellow is not None and back is not None:
                append(bellow - 1)
            if bellow is not None and front is not None and left is not None:
                append(bellow + nx + 1)
            if bellow is not None and front is not None and right is not None:
                append(bellow - nx + 1)
            if bellow is not None and back is not None and left is not None:
                append(bellow + nx - 1)
            if bellow is not None and back is not None and right is not None:
                append(bellow - nx - 1)
        # Filter out the ones that do not exist or are masked
        neighbors = [i for i in indexes
                     if i is not None and self.mesh[i] is not None]
        return neighbors

    def _not_neighbors(self, seeds, neighbors):
        """
        Remove the neighbors that are already neighbors of a seed.
        """
        return [n for n in neighbors if not self._is_neighbor(n, seeds)]

    def _is_neighbor(self, n, seeds):
        """
        Check is a neighbor is already in a seeds neighbor list (is it shares a
        physical property with this seed)
        """
        for s in seeds:
            for p in self.props:
                if p in s.props and n in s.neighbors:
                    return True
        return False

    def _are_free(self, seeds, neighbors):
        """
        Remove the neighbors that are already part of the estimate
        """
        return [n for n in neighbors if not self._in_estimate(n, seeds)]

    def _in_estimate(self, n, seeds):
        """
        Check is neighbor n is already in the estimate of the seeds that have
        this seeds physical property.
        """
        for s in seeds:
            for p in self.props:
                if p in s.props and n in s.estimate:
                    return True
        return False

    def _update_neighbors(self, n, seeds):
        """
        Remove neighbor n from the list of neighbors and include its neighbors
        """
        new = self._not_neighbors(seeds,
                self._are_free(seeds,
                    self._find_neighbors(n)))
        self.neighbors.remove(n)
        self.neighbors.extend(new)
        del self.distance[n]
        self._get_distances(new)

    def _judge(self, goals, misfits, goal, misfit):
        """
        Choose the best neighbor using the following criteria:

        1. Must decrease the misfit
        2. Must produce the smallest goal function out of all that pass 1.

        """
        decreased = [i for i, m in enumerate(misfits)
                     if m < misfit and abs(m - misfit)/misfit >= self.delta]
        if not decreased:
            return None
        best = decreased[numpy.argmin([goals[i] for i in decreased])]
        return [best, goals[best], misfits[best]]

    def grow(self, dms, seeds, goal, misfit):
        """
        Try to grow this seed by adding a prism to it's periphery.
        """
        # numpy.sum seems to be faster than Python sum
        misfits = [numpy.sum(dm.testdrive((n, self.props)) for dm in dms)
                   for n in self.neighbors]
        regularizer = numpy.sum(s.reg for s in seeds)
        goals = [m + regularizer + self.mu*self.distance[n]
                 for n, m in zip(self.neighbors, misfits)]
        best = self._judge(goals, misfits, goal, misfit)
        if best is None:
            return None
        i, goal, misfit = best
        index = self.neighbors[i]
        self.estimate.append(index)
        self.reg += self.mu*self.distance[index]
        self._update_neighbors(index, seeds)
        return [[index, self.props], goal, misfit]

def _cat_estimate(seeds):
    """
    Concatenate the estimate of all seeds to produce the final estimate.
    What estimate is depends on the kind of seed.
    """
    estimate = None
    kind = seeds[0].kind
    if kind == 'prism':
        estimate = {}
        for seed in seeds:
            for prop in seed.props:
                values = [(i, seed.props[prop]) for i in seed.estimate]
                if prop not in estimate:
                    estimate[prop] = values
                else:
                    estimate[prop].extend(values)
        size = seeds[0].mesh.size
        for prop in estimate:
            estimate[prop] = utils.SparseList(size, dict(estimate[prop]))
    return estimate

def _harvest_iterator(dms, seeds, first_goal):
    """
    Iterator that yields the growth iterations of a 3D potential field inversion
    by planting anomalous densities.
    For more details on the parameters, see
    :func:`~fatiando.potential.harvester.harvest`.

    Yields:

    * changeset
        A dictionary with keys:

        * 'estimate'
            The estimate at this growth iteration
        * 'goal'
            Goal function value at this growth iteration
        * 'misfit'
            Data misfit value at this growth iteration

    """
    pass

def _harvest_solver(dms, seeds, first_goal):
    """
    Solve a 3D potential field inversion by planting anomalous densities.
    For more details on the parameters and return values, see
    :func:`~fatiando.potential.harvester.harvest`.
    """
    goals = [first_goal]
    upgoal = goals.append
    # Since the compactness regularizing function is zero in the begining
    misfits = [first_goal]
    upmisfit = misfits.append
    while True:
        grew = False
        for seed in seeds:
            change = seed.grow(dms, seeds, goals[-1], misfits[-1])
            if change is not None:
                grew = True
                params, goal, misfit = change
                upgoal(goal)
                upmisfit(misfit)
                for dm in dms:
                    dm.update(params)
        if not grew:
            break
    estimate = _cat_estimate(seeds)
    return [estimate, goals, misfits]

def harvest(dms, seeds, iterate=False):
    """
    Robust 3D potential field inversion by planting anomalous densities.

    Performs the inversion on a data set by iteratively growing the given seeds
    until the observed data fit the predicted data (according to the misfit
    measure specified).

    Parameters:

    * dms : list
        List of data modules
    * seeds : list
        List of seeds
    * iterate : True or False
        If True, will return an iterator object that yields one growth iteration
        at a time.

    .. note:: See the docs of this module, :mod:`fatiando.potential.harvester`,
        for information on data modules and seeds.

    Returns:

    * if ``iterate == True``: iterator
        An iterator that yields one growth iteration at a time. A growth
        iteration consists of trying to grow each seed.
        **Not implemented!**

    * else: [estimate, goals, misfits]
        *goals* is a list with the goal function value per iteration.
        *misfits* is a list with the data misfit value per iteration.
        *estimate* is a dictionary of physical properties. Each key is a
        physical property name, like ``'density'``, and each value is a list
        of values of that physical property for each element in the given
        model space mesh (interpretative model).

    Example::

        estimate = {'density':[1, 0, 6, 9, 7, 8, ...],
                    'susceptibility':[0, 4, 8, 3, 4, 5.4, ...]}


    """
    log.info("Harvesting inversion results from planting anomalous densities:")
    log.info("  iterate: %s" % (str(iterate)))
    if iterate:
        raise NotImplementedError("Sorry, iteration is not implemented yet")
    # Make sure the seeds are all of the same kind. The .cound hack is from
    # stackoverflow.com/questions/3844801/check-if-all-elements-in-a-list-are-
    # identical
    kinds = [seed.kind for seed in seeds]
    if kinds.count(kinds[0]) != len(kinds):
        raise ValueError, "Seeds must all be of the same kind!"
    # Initialize the seeds and data modules before starting
    for i, seed in enumerate(seeds):
        seed.initialize(seeds)
    for dm in dms:
        # Divide the weight of the dms by the number dms so that the initial
        # goal function is always almost 1, no matter how many dms. This way
        # the regularizing parameter has always the same scale
        dm.weight /= float(len(dms))
        for seed in seeds:
            dm.update(seed.seed)
    # Calculate the initial goal function
    goal = sum(dm.misfit(dm.predicted) for dm in dms)
    log.info("  initial goal function: %g" % (goal))
    # Now run the actual inversion
    if iterate:
        return _harvest_iterator(dms, seeds, goal)
    else:
        tstart = time.clock()
        results = _harvest_solver(dms, seeds, goal)
        tfinish = time.clock() - tstart
        its = len(results[1])
        log.info("  final goal function: %g" % (results[1][-1]))
        log.info("  total number of accretions: %d" % (its))
        log.info("  average time per accretion: %s" %
            (utils.sec2hms(float(tfinish)/its)))
        log.info("  total time for inversion: %s" % (utils.sec2hms(tfinish)))
        return results
