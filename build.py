#!/usr/bin/env python

from wx.tools.pywxrc import XmlResourceCompiler

XmlResourceCompiler().MakePythonModule(["rdgui.xrc"], "rdgui_xrc.py", embedResources=True, generateGetText=True, assignVariables=False)

