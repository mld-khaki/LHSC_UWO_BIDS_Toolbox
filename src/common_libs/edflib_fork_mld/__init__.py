"""
Creates an instance of an EDF reader.

Parameters
----------
path : str
    Path to the EDF/BDF file.
read_annotations : bool, optional
    Fork-specific extension. If True, annotations are parsed during
    initialization. This behavior differs from upstream EDFlib.
"""
