# GromacsWrapper: xpm.py
# Copyright (c) 2012 Oliver Beckstein <orbeckst@gmail.com>
# Copyright (c) 2010 Tsjerk Wassenaar <tsjerkw@gmail.com>
# Released under the GNU Public License 3 (or higher, your choice)
# See the file COPYING for details.
"""
Gromacs XPM file format
=======================

Gromacs stores matrix data in the xpm file format. This implementation
of a Python reader is based on Tsjerk Wassenaar's post to gmx-users
`numerical matrix from xpm file`_ (Mon Oct 4 13:05:26 CEST 2010). This
version returns a NumPy array and can guess an appropriate dtype for
the array.

.. _numerical matrix from xpm file:
   http://lists.gromacs.org/pipermail/gmx-users/2010-October/054557.html

Classes
-------

.. autoclass:: XPM
   :members:

Example: Analysing H-bonds
--------------------------

Run :func:`gromacs.g_hbond` to produce the existence map (and the log
file for the atoms involved in the bonds; the ndx file is also
useful)::

  gromacs.g_hbond(s=TPR, f=XTC, g="hbond.log", hbm="hb.xpm", hbn="hb.ndx")

Load the XPM::

  hb = XPM("hb.xpm")

Calculate the fraction of time that each H-bond existed::

  hb_fraction = hb.array.mean(axis=0)

Get the descriptions of the bonds (should be ordered in the same way
as the rows in the xpm file)::

  desc = [line.strip() for line in open("hbond.log") if not line.startswith('#')]

and show the results::

  print "\\n".join(["%-40s %4.1f%%" % p for p in zip(desc, 100*hb_fraction)])

"""

from __future__ import with_statement
import os, errno
import re
import warnings

import numpy

from gromacs import ParseError, AutoCorrectionWarning
import gromacs.utilities as utilities
from convert import Autoconverter

import logging

class XPM(utilities.FileUtils):
    """Class to make a Gromacs XPM matrix available as a NumPy :class:`numpy.ndarray`.

    The data is available as :attr:`XPM.array`.
    """
    default_extension = "xpm"
    logger = logging.getLogger('gromacs.formats.XPM')
    #: compiled regular expression to parse the colors in the xpm file::
    #:
    #:   static char *gromacs_xpm[] = {
    #:   "14327 9   2 1",
    #:   "   c #FFFFFF " /* "None" */,
    #:   "o  c #FF0000 " /* "Present" */,
    #:
    #: Matches are named "symbol", "color" (hex string), and "value". "value"
    #: is typically autoconverted to appropriate values with
    #: :class:`gromacs.fileformats.convert.Autoconverter`.
    COLOUR = re.compile("""\
            ^.*"                   # start with quotation mark
            (?P<symbol>[ a-zA-Z])  # ASCII symbol used in the actual pixmap
            \s+                    # white-space separated
            c\s+                   # 'c' to prefix colour??
            (?P<color>\#[0-9A-F]+) # colour as hex string (always??)
            \s*"                   # close with quotes
            \s*/\*\s*              # white space then opening C-comment /*
            "                      # start new string
            (?P<value>.*)          # description/value as free form string
            "                      # ... terminated by quotes
            """, re.VERBOSE)

    def __init__(self, filename=None, **kwargs):
        """Initialize xpm structure.

        :Arguments:
          *filename*
              read from mdp file
          *autoconvert*
              try to guess the type of the output array from the
              colour legend [``True``]
        """
        self.autoconvert = kwargs.pop("autoconvert", True)
        self.__array = None
        super(XPM, self).__init__(**kwargs)  # can use kwargs to set dict! (but no sanity checks!)

        if not filename is None:
            self._init_filename(filename)
            self.read(filename)

    @property
    def array(self):
        """XPM matrix as a :class:`numpy.ndarray` (read-only)"""
        return self.__array

    def read(self, filename=None):
        """Read and parse mdp file *filename*."""
        self._init_filename(filename)
        self.parse()

    def parse(self):
        with open(self.real_filename) as xpm:
            # Read in lines until we fidn the start of the array
            meta = [xpm.readline()]
            while not meta[-1].startswith("static char *gromacs_xpm[]"):
                meta.append(xpm.readline())

            # The next line will contain the dimensions of the array
            dim = xpm.readline()
            # There are four integers surrounded by quotes
            # nx: points along x, ny: points along y, nc: ?, nb: stride x
            nx, ny, nc, nb = [int(i) for i in self.unquote(dim).split()]

            # The next dim[2] lines contain the color definitions
            # Each pixel is encoded by dim[3] bytes, and a comment
            # at the end of the line contains the corresponding value
            colors = dict([self.col(xpm.readline()) for i in xrange(nc)])

            if self.autoconvert:
                autoconverter = Autoconverter(mode="singlet")
                for symbol, value in colors.items():
                    colors[symbol] = autoconverter.convert(value)
                self.logger.debug("Autoconverted colours: %r", colors)

            # make an array containing all possible values and let numpy figure out the dtype
            dtype = numpy.array(colors.values()).dtype
            self.logger.debug("Guessed array type: %s", dtype.name)

            # pre-allocate array
            data = numpy.zeros((nx/nb, ny), dtype=dtype)

            self.logger.debug("dimensions: NX=%d NY=%d strideX=%d (NC=%d) --> (%d, %d)",
                              nx, ny, nb, nc, nx/nb, ny)

            iy = 0
            for line in xpm:
                if line.startswith("/*"):
                    # lines '/* x-axis:' ... and '/* y-axis:' contain the
                    # values of x and y coordinates
                    # TODO: extract them, too
                    continue
                s = self.unquote(line)
                data[:, iy] = [colors[s[k:k+nb]] for k in xrange(0,nx,nb)]
                self.logger.debug("read row %d with %d columns: '%s....%s'",
                                  iy, data.shape[0], s[:4], s[-4:])
                iy += 1  # for next row
        self.__array = data

    @staticmethod
    def unquote(s):
        return s[1+s.find('"'):s.rfind('"')]

    @staticmethod
    def uncomment(s):
        return s[2+s.find('/*'):s.rfind('*/')]

    def col(self, c):
        m = self.COLOUR.search(c)
        if not m:
            self.logger.fatal("Cannot parse colour specification %r.", c)
            raise ParseError("XPM reader: Cannot parse colour specification %r." % c)
        value = m.group('value')
        color = m.group('symbol')
        self.logger.debug("%s: %s %s\n", c.strip(), color, value)
        return color, value

