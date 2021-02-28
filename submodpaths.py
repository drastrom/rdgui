import sys, os

_mypath = os.path.dirname(os.path.abspath(__file__))

_submodules = (
    'rd6006',
)

def add_to_path():
    for _submodule in _submodules:
        sys.path.append(os.path.join(_mypath, _submodule))
