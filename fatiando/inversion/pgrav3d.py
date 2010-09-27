# Copyright 2010 The Fatiando a Terra Development Team
#
# This file is part of Fatiando a Terra.
#
# Fatiando a Terra is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Fatiando a Terra is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Fatiando a Terra.  If not, see <http://www.gnu.org/licenses/>.
"""
3D Gravity inversion using right rectangular prisms.

Functions:
  * solve: Solve the inverse problem for a given data set and model space mesh
  * clear: Erase garbage from previous inversions.
  * fill_mesh: Fill the 'value' keys of mesh with the inversion estimate.
  * extract_data_vector: Put all the gravity field data in a single array.
  * cal_adjustment: Calculate the adjusted data produced by a given estimate.
  * residuals: Calculate the residuals produced by a given estimate
  * use_depth_weights :Use depth weighting in the next inversions
  * set_bounds: Set lower and upper bounds on the density values
  * grow: Grow the solution around given 'seeds' 
  * get_seed: Returns as a seed the cell in mesh that has point inside it
"""
__author__ = 'Leonardo Uieda (leouieda@gmail.com)'
__date__ = 'Created 14-Jun-2010'

import time
import logging

import numpy

import fatiando
import fatiando.gravity.prism
from fatiando.inversion import solvers
        
log = logging.getLogger('fatiando.inversion.pgrav3d')       
log.setLevel(logging.DEBUG)
log.addHandler(fatiando.default_log_handler)


# The Jacobian only needs to be calculate once per data and mesh
_jacobian = None
# Depth weights are also only calculated once
_depth_weights = None
# This will hold solvers._build_tk_weights so that I don't loose when it's
# overwritten with _build_tk_depth_weights
_solvers_tk_weights = None
# The distances to the mass elements in the Minimum Moment of Inertia 
# regularization
_distances = None
# Keep the mesh and data global to access them to build the Jacobian and derivs
_mesh = None
_data = None
_data_vector = None
_calculators = {'gz':fatiando.gravity.prism.gz,
                'gxx':fatiando.gravity.prism.gxx,
                'gxy':fatiando.gravity.prism.gxy,
                'gxz':fatiando.gravity.prism.gxz,
                'gyy':fatiando.gravity.prism.gyy,
                'gyz':fatiando.gravity.prism.gyz,
                'gzz':fatiando.gravity.prism.gzz}


def clear():
    """
    Erase garbage from previous inversions.
    Only use if changing the data and/or mesh (otherwise it saves time to keep
    the garbage)
    """
    
    global _jacobian, _mesh, _data, _data_vector, \
           _depth_weights, _solvers_tk_weights, _distances
               
    _jacobian = None
    _mesh = None
    _data = None
    _data_vector = None
    _depth_weights = None
    _solvers_tk_weights = None
    _distances = None
    reload(solvers)
    

def fill_mesh(estimate, mesh):
    """
    Fill the 'value' keys of mesh with the values in the inversion estimate
    
    Parameters:
    
      estimate: array-like parameter vector produced by the inversion
      
      mesh: model space discretization mesh used in the inversion to produce the
            estimate (see fatiando.geometry.prism_mesh function)
    """
    
    for value, cell in zip(estimate, mesh.ravel()):
        
        cell['value'] = value


def extract_data_vector(data, inplace=False):
    """
    Put all the gravity field data in a single array for use in inversion.
    
    Parameters:
    
      data: dictionary with the gravity component data as:
            {'gz':gzdata, 'gxx':gxxdata, 'gxy':gxydata, ...}
            If there is no data for a given component, omit the respective key.
            Each g*data is a data grid as loaded by fatiando.gravity.io
            
      inplace: wether or not to erase the values in 'data' as they are put into
               the array (use to save memory when data set is large)
    
    Return:
        
      1D array-like with the data in the following order:
        gz, gxx, gxy, gxz, gyy, gyz, gzz
    """
    
    data_vector = []
    
    if 'gz' in data.keys():
        
        data_vector.extend(data['gz']['value'])
        
        if inplace:
            
            del data['gz']['value']
        
    if 'gxx' in data.keys():
        
        data_vector.extend(data['gxx']['value'])
        
        if inplace:
            
            del data['gxx']['value']
        
    if 'gxy' in data.keys():
        
        data_vector.extend(data['gxy']['value'])
        
        if inplace:
            
            del data['gxy']['value']
        
    if 'gxz' in data.keys():
        
        data_vector.extend(data['gxz']['value'])
        
        if inplace:
            
            del data['gxz']['value']
        
    if 'gyy' in data.keys():
        
        data_vector.extend(data['gyy']['value'])
        
        if inplace:
            
            del data['gyy']['value']
        
    if 'gyz' in data.keys():
        
        data_vector.extend(data['gyz']['value'])
        
        if inplace:
            
            del data['gyz']['value']
        
    if 'gzz' in data.keys():
        
        data_vector.extend(data['gzz']['value'])
        
        if inplace:
            
            del data['gzz']['value']
        
    return  numpy.array(data_vector)


def residuals(data, estimate):
    """
    Calculate the residuals produced by a given estimate.
    
    Parameters:
    
      data: gravity field data in a dictionary (as loaded by 
            fatiando.gravity.io)
    
      estimate: array-like parameter vector produced by the inversion.
      
    Return:
    
      array-like vector of residuals
    """       

    adjusted = calc_adjustment(estimate)
    
    key = data.keys()[0]
    
    if 'value' in data[key].keys():
        
        data_vector = extract_data_vector(data)
        
    else:
        
        assert _data_vector is not None, \
            "Missing 'value' key in %s data" % (key)
            
        data_vector = _data_vector        

    residuals = data_vector - adjusted
    
    return residuals


def calc_adjustment(estimate, grid=False):
    """
    Calculate the adjusted data produced by a given estimate.
    
    Parameters:
    
      estimate: array-like parameter vector produced by the inversion.
      
      grid: if True, return a dictionary of grids like the one given to solve
            function.
            (grids compatible with load and dump in fatiando.gravity.io and the
             plotters in fatiando.visualization).
            if False, return a data vector to use in inversion
    """
    
    jacobian = _build_pgrav3d_jacobian(estimate)
    
    adjusted = numpy.dot(jacobian, estimate)
    
    if grid:
        
        adjusted_grid = {}
                
        for field in ['gz', 'gxx', 'gxy', 'gxz', 'gyy', 'gyz', 'gzz']:
            
            if field in _data:
                
                adjusted_grid[field] = _data[field].copy()
                
                ndata = len(_data[field]['x'])
                          
                adjusted_grid[field]['value'] = adjusted[:ndata]
                
                adjusted_grid[field]['error'] = None       
                
                adjusted = adjusted[ndata:]      
    
        adjusted = adjusted_grid
        
    return adjusted


def _build_pgrav3d_jacobian(estimate):
    """Build the Jacobian matrix of the gravity field"""
    
    assert _mesh is not None, "Can't build Jacobian. No mesh defined"
    assert _data is not None, "Can't build Jacobian. No data defined"
    
    global _jacobian
    
    if _jacobian is None:
        
        start = time.time()
        
        _jacobian = []
        append_row = _jacobian.append
        
        for field in ['gz', 'gxx', 'gxy', 'gxz', 'gyy', 'gyz', 'gzz']:
            
            if field in _data:
                
                coordinates =  zip(_data[field]['x'], _data[field]['y'], 
                                   _data[field]['z'])
                
                function = _calculators[field]
                
                for x, y, z in coordinates:
                    
                    row = [function(1., cell['x1'], cell['x2'], cell['y1'], 
                                    cell['y2'], cell['z1'], cell['z2'], 
                                    x, y, z)
                           for cell in _mesh.ravel()]
                        
                    append_row(row)
                    
        _jacobian = numpy.array(_jacobian)
        
        end = time.time()
        
        log.info("  Built Jacobian (sensibility) matrix (%g s)"
                 % (end - start))
        
    return _jacobian                   


def _build_pgrav3d_first_deriv():
    """
    Build the first derivative finite differences matrix for the model space
    """
    
    assert _mesh is not None, "Can't build first derivative matrix." + \
        "No mesh defined"
        
    nz, ny, nx = _mesh.shape
                
    deriv_num = (nx - 1)*ny*nz + (ny - 1)*nx*nz + (nz - 1)*nx*ny
            
    first_deriv = numpy.zeros((deriv_num, nx*ny*nz))
    
    deriv_i = 0
    
    # Derivatives in the x direction        
    param_i = 0
    
    for k in xrange(nz):
        
        for j in xrange(ny):
            
            for i in xrange(nx - 1):                
                
                first_deriv[deriv_i][param_i] = 1
                
                first_deriv[deriv_i][param_i + 1] = -1
                
                deriv_i += 1
                
                param_i += 1
            
            param_i += 1
        
    # Derivatives in the y direction        
    param_i = 0
    
    for k in xrange(nz):
    
        for j in range(ny - 1):
            
            for i in range(nx):
        
                first_deriv[deriv_i][param_i] = 1
                
                first_deriv[deriv_i][param_i + nx] = -1
                
                deriv_i += 1
                
                param_i += 1
                
        param_i += nx
        
    # Derivatives in the z direction        
    param_i = 0
    
    for k in xrange(nz - 1):
    
        for j in range(ny):
            
            for i in range(nx):
        
                first_deriv[deriv_i][param_i] = 1
                
                first_deriv[deriv_i][param_i + nx*ny] = -1
                
                deriv_i += 1
                
                param_i += 1
    
    return first_deriv


def _build_tk_depth_weights(nparams):
    """
    Build the Tikhonov weights using depth weighting (Li & Oldenburg, 1998).
    """
        
    weights = _solvers_tk_weights(nparams)
    
    for i, row in enumerate(weights):
        
        row *= _depth_weights[i]*_depth_weights
        
    return weights


def _calc_adjusted_depth_weights(coefs):
    """Calculate the adjusted depth weights for a given set of coefficients"""
    
    assert _mesh is not None, \
        "Can't calculate adjusted depth weights without a mesh"
    
    z0, power = coefs
    
    weights = numpy.zeros(_mesh.size)
    
    for i, cell in enumerate(_mesh.ravel()):
        
        depth = 0.5*(cell['z1'] + cell['z2'])
        
        weights[i] = (depth + z0)**(-0.5*power)
        
    return weights


def _build_depth_weights_jacobian(estimate):
    """Build the Jacobian of the depth weighing function"""
    
    jacobian = []
    
    z0, power = estimate
                    
    for cell in _mesh.ravel():
        
        depth = 0.5*(cell['z1'] + cell['z2'])
                    
        z0_deriv = -0.5*power*(z0 + depth)**(-0.5*(power + 2))
        
        power_deriv = -0.5*(z0 + depth)**(-0.5*power)
        
        jacobian.append([z0_deriv, power_deriv])
        
    return numpy.array(jacobian)    
    

def use_depth_weights(mesh, z0=None, power=None, grid_height=None, 
                      normalize=True):
    """
    Use depth weighting in the next inversions (Li & Oldenburg, 1998).
    
    If z0 or power are set to None, they will be automatically calculated.
    
    Parameters:
    
      mesh: model space discretization mesh (see geometry.prism_mesh function)
    
      z0: compensation depth
      
      power: power of the power law used
      
      grid_height: height of the data grid in meters (only needed is z0 and 
                   power are None)
      
      normalize: whether or not to normalize the weights
    """
    
    if z0 is None or power is None:
    
        log.info("Adjusting depth weighing coefficients:")
        
        import fatiando.inversion.solvers as local_solver
        
        global _mesh
        
        _mesh = mesh
        
        # Make a 'data' array (gzz kernel values)
        kernel_data = []
        
        for cell in mesh.ravel():
            
            x = 0.5*(cell['x1'] + cell['x2'])
            y = 0.5*(cell['y1'] + cell['y2'])
            
            kernel = fatiando.gravity.prism.gzz(1., cell['x1'], cell['x2'], 
                                                cell['y1'], cell['y2'], 
                                                cell['z1'], cell['z2'], 
                                                x, y, -grid_height)
            
            kernel_data.append(kernel)
            
        local_solver._build_jacobian = _build_depth_weights_jacobian
        local_solver._calc_adjustment = _calc_adjusted_depth_weights
        
        coefs, goals = local_solver.lm(kernel_data, None, 
                                       numpy.array([1., 3.]))
        
        z0, power = coefs
        
        _mesh = None
    
    log.info("Setting depth weighting:")
    log.info("  z0 = %g" % (z0))
    log.info("  power = %g" % (power))
    log.info("  normalized = %s" % (str(normalize)))
                  
    weights = numpy.zeros(mesh.size)
    
    for i, cell in enumerate(mesh.ravel()):
        
        depth = 0.5*(cell['z1'] + cell['z2'])
        
        weights[i] = (depth + z0)**(-0.25*power)
        
    if normalize:
        
        weights = weights/weights.max()
        
    global _depth_weights
    
    _depth_weights = weights
        
    # Overwrite the default Tikhonov weights builder but not before saing it
    global _solvers_tk_weights
    
    _solvers_tk_weights = solvers._build_tk_weights
    
    solvers._build_tk_weights = _build_tk_depth_weights

    return z0, power


def set_bounds(lower, upper):
    """Set lower and upper bounds on the density values"""
    
    solvers.set_bounds(lower, upper)


def solve(data, mesh, initial=None, damping=0, smoothness=0, curvature=0, 
          sharpness=0, beta=10**(-5), compactness=0, epsilon=10**(-5), 
          max_it=100, lm_start=1, lm_step=10, max_steps=20):    
    """
    Solve the inverse problem for a given data set and model space mesh.
    
    Parameters:
    
      data: dictionary with the gravity component data as:
            {'gz':gzdata, 'gxx':gxxdata, 'gxy':gxydata, ...}
            If there is no data for a given component, omit the respective key.
            Each g*data is a data grid as loaded by fatiando.gravity.io
      
      mesh: model space discretization mesh (see geometry.prism_mesh function)
      
      initial: initial estimate (only used with sharpness or compactness). 
               If None, will use zero initial estimate
      
      damping: Tikhonov order 0 regularization parameter. Must be >= 0
      
      smoothness: Tikhonov order 1 regularization parameter. Must be >= 0
      
      curvature: Tikhonov order 2 regularization parameter. Must be >= 0
      
      sharpness: Total Variation regularization parameter. Must be >= 0
      
      beta: small constant used to make Total Variation differentiable. 
            Must be >= 0. The smaller it is, the sharper the solution but also 
            the less stable
            
      compactness: Compact regularization parameter. Must be >= 0
      
      epsilon: small constant used in Compact regularization to avoid 
               singularities. Set it small for more compactness, larger for more
               stability.
    
      max_it: maximum number of iterations 
        
      lm_start: initial Marquardt parameter (controls the step size)
    
      lm_step: factor by which the Marquardt parameter will be reduced with
               each successful step
             
      max_steps: how many times to try giving a step before exiting
      
    Return:
    
      [estimate, goals]:
        estimate = array-like parameter vector estimated by the inversion.
                   parameters are the density values in the mesh cells.
                   use fill_mesh function to put the estimate in a mesh so you
                   can plot and save it.
        goals = list of goal function value per iteration    
    """

    for key in data:
        assert key in ['gz', 'gxx', 'gxy', 'gxz', 'gyy', 'gyz', 'gzz'], \
            "Invalid gravity component (data key): %s" % (key)
    
    log.info("Inversion parameters:")
    log.info("  damping     = %g" % (damping))
    log.info("  smoothness  = %g" % (smoothness))
    log.info("  curvature   = %g" % (curvature))
    log.info("  sharpness   = %g" % (sharpness))
    log.info("  beta        = %g" % (beta))
    log.info("  compactness = %g" % (compactness))
    log.info("  epsilon     = %g" % (epsilon))
    
    global _mesh, _data, _data_vector

    _mesh = mesh
    _data = data
        
    _data_vector = extract_data_vector(data)
    
    log.info("  parameters = %d" % (mesh.size))
    log.info("  data = %d" % (len(_data_vector)))

    if initial is None:
        
        initial = 10**(-7)*numpy.ones(mesh.size)
                        
    # Overwrite the needed methods for solvers to work
    solvers._build_jacobian = _build_pgrav3d_jacobian
    solvers._build_first_deriv_matrix = _build_pgrav3d_first_deriv
    solvers._calc_adjustment = calc_adjustment
    
    solvers.damping = damping
    solvers.smoothness = smoothness
    solvers.curvature = curvature
    solvers.sharpness = sharpness
    solvers.beta = beta
    solvers.compactness = compactness
    solvers.epsilon = epsilon
    
    estimate, goals = solvers.lm(_data_vector, None, initial, lm_start, lm_step, 
                                 max_steps, max_it)

    return estimate, goals


def get_seed(point, density, mesh):
    """Returns as a seed the cell in mesh that has point inside it."""
    
    x, y, z = point
    
    seed = None
    
    for i, cell in enumerate(mesh.ravel()):
        
        if (x >= cell['x1'] and x <= cell['x2'] and y >= cell['y1'] and  
            y <= cell['y2'] and z >= cell['z1'] and z <= cell['z2']):
            
            seed = {'param':i, 'density':density, 'cell':cell, 'neighbors':[]}
            
            break
        
    if seed is None:
        
        raise ValueError("There is no cell in 'mesh' with 'point' inside it.")
    
    log.info("  seed: %s" % (str(seed)))

    return seed


def _dist_to_seed(cell, seed, dx, dy, dz):
    """Calculate the distance (in number of cells) from cell to seed.
    
    Parameters:
    
      cell: dictionary with the cell bounds (x1, x2, y1, y2, z1, z2)
      
      seed: 
    
    """
                    
    x_distance = abs(cell['x1'] - seed['cell']['x1'])/dx
    y_distance = abs(cell['y1'] - seed['cell']['y1'])/dy
    z_distance = abs(cell['z1'] - seed['cell']['z1'])/dz
    
    distance = max([x_distance, y_distance, z_distance])
    
    return distance   
    

def _calc_mmi_goal(estimate, mmi, power, seeds):
    """Calculate the goal function due to MMI regularization"""
    
    if mmi == 0:
        
        return 0, ''
    
    global _distances
    
    if _distances is None:
        
        _distances = numpy.zeros(_mesh.size)
        
        for i, cell in enumerate(_mesh.ravel()):
                
            dx = float(cell['x2'] - cell['x1'])
            dy = float(cell['y2'] - cell['y1'])
            dz = float(cell['z2'] - cell['z1'])
            
            best_distance = None
            
            for seed in seeds:
                
                distance = _dist_to_seed(cell, seed, dx, dy, dz)
                
                if best_distance is None or distance < best_distance:
                    
                    best_distance = distance
                     
            _distances[i] = best_distance
    
    weights = (_distances**power)
    
    weights = weights/(weights.max())
    
    goal = mmi*((estimate**2)*weights).sum()
    
    msg = ' MMI:%g' % (goal)
    
    return goal, msg


def _add_neighbors(param, neighbors, seeds, mesh, estimate):
    """Add the neighbors of 'param' in 'mesh' to 'neighbors'."""
    
    nz, ny, nx = mesh.shape
    
    append = neighbors.append
    
    # The guy above
    neighbor = param - nx*ny
    above = None
    
    if neighbor > 0:
        
        above = neighbor
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
    
    # The guy bellow
    neighbor = param + nx*ny
    bellow = None
    
    if neighbor < mesh.size:
        
        bellow = neighbor
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
    
    # The guy in front
    neighbor = param + 1
    front = None
    
    if param%nx < nx - 1:
        
        front = neighbor
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
    
    # The guy in the back
    neighbor = param - 1
    back = None
    
    if param%nx != 0:
        
        back = neighbor
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
    
    # The guy to the left
    neighbor = param + nx
    left = None
    
    if param%(nx*ny) < nx*(ny - 1):
        
        left = neighbor
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
    
    # The guy to the right
    neighbor = param - nx
    right = None
    
    if param%(nx*ny) >= nx:
        
        right = neighbor
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)

    # The diagonals            
    if front is not None and left is not None:
        
        neighbor = left + 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
    
    if front is not None and right is not None:
        
        neighbor = right + 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if back is not None and left is not None:
        
        neighbor = left - 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if back is not None and right is not None:
    
        neighbor = right - 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if above is not None and left is not None:
        
        neighbor = above + nx
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if above is not None and right is not None:
        
        neighbor = above - nx
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if above is not None and front is not None:
        
        neighbor = above + 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if above is not None and back is not None:
        
        neighbor = above - 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)        
            
    if above is not None and front is not None and left is not None:
        
        neighbor = above + nx + 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if above is not None and front is not None and right is not None:
        
        neighbor = above - nx + 1    
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)

    if above is not None and back is not None and left is not None:
        
        neighbor = above + nx - 1 
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
    
    if above is not None and back is not None and right is not None:
        
        neighbor = above - nx - 1 
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if bellow is not None and left is not None:
        
        neighbor = bellow + nx
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if bellow is not None and right is not None:
        
        neighbor = bellow - nx
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if bellow is not None and front is not None:
        
        neighbor = bellow + 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if bellow is not None and back is not None:
        
        neighbor = bellow - 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)    
            
    if bellow is not None and front is not None and left is not None:
        
        neighbor = bellow + nx + 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if bellow is not None and front is not None and right is not None:
        
        neighbor = bellow - nx + 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
        
    if bellow is not None and back is not None and left is not None:
        
        neighbor =  bellow + nx - 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
            
    if bellow is not None and back is not None and right is not None:
        
        neighbor = bellow - nx - 1
            
        # Need to check if neighbor is not in any seed's neighbors before adding
        is_neighbor = [neighbor not in seed['neighbors'] for seed in seeds]
        
        if False not in is_neighbor and estimate[neighbor] == 0.:
        
            append(neighbor)
        

def grow(data, mesh, seeds, mmi, power=5, apriori_variance=1):
    """
    Grow the solution around given 'seeds'.
    
    Parameters:
        
      data: dictionary with the gravity component data as:
            {'gz':gzdata, 'gxx':gxxdata, 'gxy':gxydata, ...}
            If there is no data for a given component, omit the respective key.
            Each g*data is a data grid as loaded by fatiando.gravity.io
      
      mesh: model space discretization mesh (see geometry.prism_mesh function)
      
      seeds: list of seeds (to make a seed, see get_seed function)
      
      mmi: Minimum Moment of Inertia regularization parameter (how compact the
           solution should be around the seeds). Has to be >= 0
           
      power: power to which the distances are raised in the MMI weights
           
      apriori_variance: a priori variance of the data
      
    Return:
    
      [estimate, goals]:
        estimate = array-like parameter vector estimated by the inversion.
                   parameters are the density values in the mesh cells.
                   use fill_mesh function to put the estimate in a mesh so you
                   can plot and save it.
        goals = list of goal function value per iteration    
    """
    

    for key in data:
        assert key in ['gz', 'gxx', 'gxy', 'gxz', 'gyy', 'gyz', 'gzz'], \
            "Invalid gravity component (data key): %s" % (key)
    
    global _mesh, _data, _jacobian

    _mesh = mesh
    
    _data = data
        
    estimate = numpy.zeros(_mesh.size)
    
    # Need to set their densities before so that seeds won't be added as 
    # neighbors
    for seed in seeds:
        
        estimate[seed['param']] = seed['density']
                    
    for seed in seeds:
        
        # Don't send all seeds to _add_neighbors to fool it into allowing common
        # neighbors between the seeds. The conflicts will be resolved later
        _add_neighbors(seed['param'], seed['neighbors'], [seed], mesh, estimate)
        
    # Resolve the conflicts in the neighbors. If the conflicting seeds have 
    # different densities, an AttributeError will be raised.
    for i, seed in enumerate(seeds):
        
        for neighbor in seed['neighbors']:
            
            for j, other_seed in enumerate(seeds):
                
                if i == j:
                    
                    continue
                
                if neighbor in other_seed['neighbors']:
                    
                    if seed['density'] == other_seed['density']:
                        
                        seed['neighbors'].remove(neighbor)
                        
                        # Stop checking this neighbor if it was removed. In case
                        # it appears again in another seed, it will be tested 
                        # against the one in that stayed in other_seed.
                        break
                    
                    else:

                        raise AttributeError("Seeds %d and %d are too close." 
                                             % (i, j))
    
    _build_pgrav3d_jacobian(None)
    
    # Uses the Jacobian.T to calculate the effect of a single cell at all data
    # points. Only do this once to save time. Will revert the transpose before 
    # returning 
    _jacobian = _jacobian.T
    
    # To report the initial status of the inversion
    reg_goal, msg = _calc_mmi_goal(estimate, mmi, power, seeds)
    
    residuals = extract_data_vector(data) - numpy.dot(_jacobian.T, estimate)
    
    rms = (residuals*residuals).sum()
    
    goals = [rms + reg_goal] 
    
    log.info("Growing density model:")
    log.info("  parameters = %d" % (mesh.size))
    log.info("  data = %d" % (len(residuals)))
    log.info("  mmi = %g" % (mmi))
    log.info("  power = %g" % (power))
    log.info("  initial RMS = %g" % (rms))
    log.info("  initial regularizer goals =%s" % (msg))
    log.info("  initial total goal function = %g" % (goals[-1]))
    
    total_start = time.time()
    
    # To keep track of which cell was appended to which seed (used to rearange)
    marked = [[] for seed in seeds]
        
    for iteration in xrange(mesh.size - len(seeds)):
        
        start = time.time()
        
        log.info("  it %d:" % (iteration + 1))
        
        grew = False
            
        # Try to grow each seed by one using the goal function as a criterium
        # NOTE: The order of the seeds affects the growing (goals[-1] changes
        # when a seed grows)!    
        for seed_num, seed in enumerate(seeds):
            
            # Want to find the neighbor that decreases the goal function the 
            # most
            best_goal = goals[-1]
            best_neighbor = None
            # Only used for verbose
            best_rms = None
            best_msg = None
            
            density = seed['density']
            
            for neighbor in seed['neighbors']:
                
                new_residuals = residuals - density*_jacobian[neighbor]
                
                rms = (new_residuals*new_residuals).sum()
                
                estimate[neighbor] = density
    
                reg_goal, msg = _calc_mmi_goal(estimate, mmi, power, seeds)
                
                estimate[neighbor] = 0
                
                goal = rms + reg_goal
                
                if goal < best_goal:
                    
                    best_neighbor = neighbor
                    best_goal = goal
                    best_rms = rms
                    best_msg = msg
                 
            if best_neighbor is not None:
                    
                grew = True
                
                estimate[best_neighbor] = density
                
                residuals -= density*_jacobian[best_neighbor]
                
                goals.append(best_goal)
                
                marked[seed_num].append(best_neighbor)
                                                    
                seed['neighbors'].remove(best_neighbor)     
                    
                _add_neighbors(best_neighbor, seed['neighbors'], seeds, mesh, 
                               estimate)
                
                log.info("    append to seed %d: RMS=%g%s TOTAL=%g" 
                         % (seed_num + 1, best_rms, best_msg, best_goal))
                          
        # If couldn't grow anymore, try to rearange the already marked cells          
        if not grew:
            
            # Try to move at least one already marked cell (max one per seed)                    
            rearanged = False
            
            for seed_num, seed in enumerate(seeds):
                
                # Only rearange the one that decreses the goal function the most 
                best_goal = goals[-1]
                best_param = None
                param_to_remove = None
                best_rms = None
                best_msg = None
                best_neighbors = None
                
                density = seed['density']
                
                tmp_seeds = list(seeds)
                tmp_seeds.remove(seed)
                
                for param in marked[seed_num]:
                    
                    # Find out how many unmarked neighbors this guy still has
                    param_neighbors = []                    
                    _add_neighbors(param, param_neighbors, tmp_seeds, mesh, 
                                   estimate)
            
                    # Only try to rearange the cells that still have unmarked
                    # neighbors (outer cells)
                    if not param_neighbors:
                        
                        continue
                    
                    # Remove the effect of 'param' from the adjusted data
                    tmp_residuals = residuals + density*_jacobian[param]
        
                    # Remove 'param's sole neighbors
                    tmp_neighbors = list(seed['neighbors'])
                    
                    for neighbor in param_neighbors:
                        
                        # If the neighbor has all neighbors available, then
                        # it is a sole neighbor of 'param'
                        
                        # NOTE: DOESN'T WORK BECAUSE THERE MAY BE LESS NEIGHBORS
                        # DUE TO BEING CLOSE TO THE OTHER BODY.
                        neighbor_neighbors = []
                        _add_neighbors(neighbor, neighbor_neighbors, tmp_seeds, 
                                       mesh, estimate)
                        
                        if len(neighbor_neighbors) < 26:
                            
                            tmp_neighbors.remove(neighbor)
                            
                    # 'param' is not added to the neighbor list because putting
                    # it back should not be an option
                                               
                    # Will put it back when done checking
                    estimate[param] = 0.
                    
                    for neighbor in tmp_neighbors:
                        
                        new_residuals = (tmp_residuals - 
                                         density*_jacobian[neighbor])
                        
                        rms = (new_residuals*new_residuals).sum()
                        
                        estimate[neighbor] = density
                        
                        reg_goal, msg = _calc_mmi_goal(estimate, mmi, power, 
                                                       seeds)
                        
                        estimate[neighbor] = 0.
                        
                        goal = rms + reg_goal
                        
                        if goal < best_goal:
                            
                            best_goal = goal
                            best_param = neighbor
                            param_to_remove = param
                            best_rms = rms
                            best_msg = msg
                            
                            # These are the neighbors of seed without the sole
                            # neighbors of 'param' and still not including the
                            # neighbors of the new best
                            best_neighbors = tmp_neighbors
                            best_neighbors.append(param)
                            
                    # Put 'param' back and go try to rearange another one
                    estimate[param] = density                        
                    
                if best_param is not None:
                            
                    rearanged = True
                    
                    estimate[param_to_remove] = 0.
                    
                    residuals += density*_jacobian[param_to_remove]
                    
                    estimate[best_param] = density
                    
                    residuals -= density*_jacobian[best_param]
                    
                    goals.append(best_goal)
                    
                    marked[seed_num].remove(param_to_remove)
                    
                    marked[seed_num].append(best_param)
                    
                    seed['neighbors'] = best_neighbors
                    
                    seed['neighbors'].remove(best_param)
                    
                    _add_neighbors(best_param, seed['neighbors'], seeds, mesh, 
                                   estimate)
                
                    log.info("    rearanged in seed %d: RMS=%g%s TOTAL=%g" 
                             % (seed_num + 1, best_rms, best_msg, best_goal))
                                        
            if not rearanged:
                                
                log.warning("    Exited because couldn't grow or rearange.")
                break
                
        aposteriori_variance = goals[-1]/float(len(residuals))
        
        log.info("    a posteriori variance = %g" % (aposteriori_variance))                    
                    
        end = time.time()
        log.info("    time: %g s" % (end - start))
        
        if aposteriori_variance <= 1.1*apriori_variance and \
           aposteriori_variance >= 0.9*apriori_variance:
            
            break 
    
    _jacobian = _jacobian.T
    
    total_end = time.time()
    
    log.info("  Total inversion time: %g s" % (total_end - total_start))

    return estimate, goals