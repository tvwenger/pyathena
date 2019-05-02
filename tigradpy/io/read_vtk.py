"""
Read athena vtk file
"""

from __future__ import print_function

import os
import os.path as osp
import glob, re, struct
import numpy as np


class AthenaDataSet(object):
    
    def __init__(self, filename, id0_only=False):
        """Class to read athena vtk file.
        
        Parameters
        ----------
        filename : string
            Name of the file to open, including extension
        id0_only : bool
            Flag to enforce to read only id0 vtk file. Default value is False.
        """
        
        if not osp.exists(filename):
            raise IOError(('File does not exist: {0:s}'.format(filename)))

        dirname, problem_id, num, ext, mpi_mode = _parse_filename(filename)
        
        if id0_only:
            mpi_mode = False

        self.dirname = dirname
        self.problem_id = problem_id
        self.num = int(num)
        self.ext = ext
        self.mpi_mode = mpi_mode
        self.fnames = [filename]

        # Find all vtk file names and add to flist
        if mpi_mode:
            fname_pattern = osp.join(dirname, 'id*/{0:s}-id*.{1:s}.{2:s}'.\
                                     format(problem_id, num, ext))
            fnames = glob.glob(fname_pattern)
            self.fnames += fnames
        
        self.grid = self._set_grid()
        self.domain = self._set_domain()
        
        # Need separte field_map for different grids
        if self.domain['all_grid_equal']:
            self._field_map = _set_field_map(self.grid[0])
            for g in self.grid:
                g['field_map'] = self._field_map
        else:
            for g in self.grid:
                g['field_map'] = _set_field_map(g)
            self._field_map = self.grid[0]['field_map']

        self.field_list = self._field_map.keys()

    def set_region(self, le=None, re=None):
        """Set region.
        Find overlapping grids.
        """

        if le is None:
            le = self.domain['le']
        if re is None:
            re = self.domain['re']

        le = np.array(le)
        re = np.array(re)
        if (re < le).any():
            raise ValueError('Check left/right edge.')

        # Find all overlapping grids and their edges 
        gle_all = []
        gre_all = []
        gidx = []
        for i, g in enumerate(self.grid):
            if (g['re'] > le).all() and (g['le'] < re).all():
                gidx.append(i)
                gle_all.append(g['le'])
                gre_all.append(g['re'])
                
        gidx = np.array(gidx)
        if len(gidx) == 0:
            raise ValueError('Check left/right edge. Domain left/right edges are ', \
                             self.domain['le'], self.domain['re'])

        gle_all = np.array(gle_all)
        gre_all = np.array(gre_all)

        # Unique edges
        gleu = np.array([np.unique(gle_all[:, i]) for i in range(3)])
        greu = np.array([np.unique(gre_all[:, i]) for i in range(3)])
        gle = np.array([gle.min() for gle in gleu])
        gre = np.array([gre.max() for gre in greu])
        
        # Number of grids in each direction
        NGrid = np.array([len(gleu_) for gleu_ in gleu])
        
        # Number of cells
        Nxg = (np.ravel((greu - gleu))/self.domain['dx'])
        Nxr = np.empty(Nxg.shape[0], dtype=int)
        for i, Nxg_ in enumerate(Nxg):
            Nxr[i] = np.sum(Nxg_.astype(int))

        assert len(gidx) == NGrid.prod(),\
            print('Unexpected error: Number of grids {0:d} != '.format(len(gidx)) +
                  'number of unique edges {0:d}.'.format(NGrid.prod()))
        
        self.region = dict(le=le, re=re, gidx=gidx,
                           gleu=gleu, greu=greu,\
                           gle=gle, gre=gre,
                           NGrid=NGrid, Nxg=Nxg, Nxr=Nxr)
        
    def get_field(self, field='density', le=None, re=None):

        # Check field name
        
        # Check and create region
        if not hasattr(self, 'region'):
            self.set_region(le=le, re=re)
        elif le is not None or re is not None:
            if (le == self.region['le']).all() and \
               (re == self.region['re']).all():
                pass
            else:
                self.set_region(le=le, re=re)

        data = self._set_data_array(field)

        # Read from individual grids and copy to data
        le = self.region['gle']
        dx = self.domain['dx']
        for i in self.region['gidx']:
            g = self.grid[i]
            il = ((g['le'] - le)/dx).astype(int)
            iu = il + g['Nx']
            slc = tuple([slice(l, u) for l, u in zip(il[::-1], iu[::-1])])
            data[slc] = self._get_field_grid(g, field)
            
        return data
    
    def _get_field_grid(self, grid, field):

        if field in grid['data']:
            return grid['data'][field]
        elif field in self.field_list:
            fm = grid['field_map'][field]
            fp = open(grid['filename'], 'rb')
            fp.seek(fm['offset'])
            fp.readline() # skip header
            if fm['read_table']:
                fp.readline()
            grid['data'][field] = np.asarray(
                struct.unpack('>' + fm['ndata']*fm['dtype'],
                              fp.read(fm['dsize'])))
            fp.close()
            
            if fm['nvar'] == 1:
                shape = np.flipud(grid['Nx'])
            else:
                shape = (*np.flipud(grid['Nx']), fm['nvar'])
            
            grid['data'][field].shape = shape
            
            return grid['data'][field]

    def _read_field_grid(self, grid, field):

        fm = self.domain['field_map']
        nvar = fm[field]['nvar']
        var = self._read_field(file,fm[field])
        if nvar == 1: 
            var.shape = (nx3, nx2, nx1)
        else: 
            var.shape = (nx3, nx2, nx1, nvar)
        file.close()
        grid['data'][field] = var
        if nvar == 3: self._set_vector_field(grid,field)
        
    def _set_data_array(self, field):
        
        dtype = self._field_map[field]['dtype']
        nvar = self._field_map[field]['nvar']
        Nxr = self.region['Nxr']
        if 'face_centered_B' in field:
            Nxr[int(field[-1])-1] += 1
        if nvar == 1:
            shape = np.flipud(Nxr)
        else:
            shape = (*np.flipud(Nxr), nvar)

        return np.empty(shape, dtype=dtype)

    def _set_domain(self):
        
        domain = dict()
        grid = self.grid
        ngrid = len(grid)
        
        # Grid left/right edges
        gle = np.empty((ngrid, 3), dtype='float32')
        gre = np.empty((ngrid, 3), dtype='float32')
        dx = np.empty((ngrid, 3), dtype='float32')
        Nx = np.ones_like(dx, dtype='int')
        
        for i, g in enumerate(grid):
            gle[i, :] = g['le']
            gre[i, :] = g['re']
            Nx[i, :] = g['Nx']
            dx[i, :] = g['dx']

        # Check if all grids have the equal size
        if (Nx[0] == Nx).all():
            domain['all_grid_equal'] = True
        else:
            domain['all_grid_equal'] = False

        # Set domain
        le = gle.min(axis=0)
        re = gre.max(axis=0)
        domain['ngrid'] = ngrid
        domain['le'] = le
        domain['re'] = re
        domain['dx'] = dx[0, :]
        domain['Lx'] = re - le
        domain['center'] = 0.5*(le + re)
        domain['Nx'] = np.round(domain['Lx']/domain['dx']).astype('int')
        domain['ndim'] = 3 # should be revised

        file = open(self.fnames[0], 'rb')
        tmpgrid = dict()
        tmpgrid['time'] = None
        while tmpgrid['time'] is None:
            line = file.readline()
            _vtk_parse_line(line, tmpgrid)
        file.close()
        domain['time'] = tmpgrid['time']
        
        return domain
    
    def _set_grid(self):
        grid = []

        # Record filename and data_offset
        for i, fname in enumerate(self.fnames):
            file = open(fname, 'rb')
            g = dict()
            g['data'] = dict()
            g['filename'] = fname
            g['read_field'] = None
            g['read_type'] = None
            
            while g['read_field'] is None:
                g['data_offset'] = file.tell()
                line = file.readline()
                _vtk_parse_line(line, g)
                
            file.close()
            
            g['Nx'] -= 1
            g['Nx'][g['Nx'] == 0] = 1
            g['dx'][g['Nx'] == 1] = 1.
            # Right edge
            g['re'] = g['le'] + g['Nx']*g['dx']
            grid.append(g)

        return grid
       


def _parse_filename(filename):
    """Break up a filename into its component 
    to check the extension and extract the output number.

    Parameters
    ----------
    filename : string
        Name of the file, including extension

    Returns
    -------
    tuple containing dirname, problem_id, output number, extension, and mpi flag
    
    Examples
    --------
    >>> _parse_filename('/basedir/id0/problem_id.0000.vtk')
    ('/basedir', 'problem_id', '0000', 'vtk', True)
    
    >>> _parse_filename('/basedir/problem_id.0000.vtk')
    ('/basedir', 'problem_id', '0000', 'vtk', False)
    """

    sep = os.path.sep
    dirname = os.path.dirname(filename)
    
    # Check if dirname ends with id0
    if dirname.split(sep)[-1] == 'id0':
        dirname = sep.join(dirname.split(sep)[:-1])
        mpi_mode = True
    else:
        mpi_mode = False

    base = os.path.basename(filename)
    base_split = base.split('.')
    problem_id = '.'.join(base_split[:-2])
    num = base_split[-2]
    ext = base_split[-1]

    return dirname, problem_id, num, ext, mpi_mode

    
def _set_field_map(grid):

    fp = open(grid['filename'], 'rb')
    fp.seek(0, 2)
    eof = fp.tell()
    offset = grid['data_offset']
    fp.seek(offset)

    field_map = dict()
    if 'Nx' in grid:
        Nx = grid['Nx']

    while offset < eof:
        line = fp.readline()
        sp = line.strip().split()
        field = sp[1].decode('utf-8')
        field_map[field] = dict()
        field_map[field]['read_table'] = False
        if b"SCALARS" in line:
            tmp = fp.readline()
            field_map[field]['read_table'] = True
            field_map[field]['nvar'] = 1
        elif b"VECTORS" in line:
            field_map[field]['nvar'] = 3
        else:
            raise TypeError(sp[0] + ' is unknown type.')

        field_map[field]['offset'] = offset
        field_map[field]['ndata'] = field_map[field]['nvar']*grid['ncells']
        if field == 'face_centered_B1':
            field_map[field]['ndata'] = (Nx[0]+1)*Nx[1]*Nx[2]
        elif field == 'face_centered_B2':
            field_map[field]['ndata'] = Nx[0]*(Nx[1]+1)*Nx[2]
        elif field == 'face_centered_B3':
            field_map[field]['ndata'] = Nx[0]*Nx[1]*(Nx[2]+1)
        
        if sp[2] == b'int':
            dtype = 'i'
        elif sp[2] == b'float':
            dtype = 'f'
        elif sp[2] == b'double':
            dtype = 'd'
            
        field_map[field]['dtype'] = dtype
        field_map[field]['dsize'] = field_map[field]['ndata']*struct.calcsize(dtype)
        fp.seek(field_map[field]['dsize'], 1)
        offset = fp.tell()
        tmp = fp.readline()
        if len(tmp) > 1:
            fp.seek(offset)
        else:
            offset = fp.tell()

    return field_map


def _vtk_parse_line(line, grid):
    sp = line.strip().split()

    if b"vtk" in sp:
        grid['vtk_version'] = sp[-1]
    elif b"time=" in sp:
        time_index = sp.index(b"time=")
        grid['time'] = float(sp[time_index + 1].rstrip(b','))
        if b'level' in sp:
            grid['level'] = int(sp[time_index + 3].rstrip(b','))
        if b'domain' in sp:
            grid['domain'] = int(sp[time_index + 5].rstrip(b','))
        if sp[0] == b"PRIMITIVE": 
            grid['prim_var_type'] = True
    elif b"DIMENSIONS" in sp:
        grid['Nx'] = np.array(sp[-3:]).astype('int')
    elif b"ORIGIN" in sp: # left_edge
        grid['le'] = np.array(sp[-3:]).astype('float64')
    elif b"SPACING" in sp:
        grid['dx'] = np.array(sp[-3:]).astype('float64')
    elif b"CELL_DATA" in sp:
        grid['ncells'] = int(sp[-1])
    elif b"SCALARS" in sp:
        grid['read_field'] = sp[1]
        grid['read_type'] = 'scalar'
    elif b"VECTORS" in sp:
        grid['read_field'] = sp[1]
        grid['read_type'] = 'vector'
    elif b"POINTS" in sp:
        grid['npoint'] = eval(sp[1])