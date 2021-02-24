# rdgui
Cross-platform wxPython GUI for RD60{06,12,18}

## installation
Potentially packaged pre-requisites include:
* wxPython
* numpy
* pyserial
* matplotlib

If your OS has packages for these, I recommend installing them.  Then, either
```
$ virtualenv --system-site-packages venv
```
or
```
$ python -m venv --system-site-packages venv
```

Then
```
$ . venv/bin/activate
```
or
```
C:\> venv\Scripts\activate
```

Finally
```
$ git clone --recursive https://github.com/drastrom/rdgui.git
$ cd rdgui
$ pip install -r requirements.txt
$ python build.py
$ python rdgui.py
```

## development
This project uses an XRCed extension, so you need to set XRCEDPATH.
```
$ set XRCEDPATH=xrced
$ set PYTHONPATH=.
$ xrced rdgui.xrc
```

Note that XRCed doesn't come with wxPython anymore as of version 4, but a compatible version is at https://github.com/drastrom/XRCed on the `py3_phoenix` branch.
```
$ set XRCEDPATH=xrced
$ set PYTHONPATH=.:../XRCed (or .;..\XRCed on Windows)
$ python -m wx.tools.XRCed rdgui.xrc
```

