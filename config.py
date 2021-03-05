#!/usr/bin/env python
# vim: set fileencoding=utf-8 :

import collections
try:
    from typing import List, Dict
except:
    pass
import wx

class ConfigChangeHandler(object):
    def __init__(self):
        super(ConfigChangeHandler, self).__init__()

    def OnConfigChangeBegin(self):
        pass

    def OnConfigChanged(self, name, value):
        pass

    def OnConfigChangeEnd(self):
        pass


class Config(object):
    _ReadWrite = collections.namedtuple('_ReadWrite', ('read', 'write'))
    _TypeDefault = collections.namedtuple('_TypeDefault', ('typ', 'default'))

    _types = {
        bool: _ReadWrite(wx.Config.ReadBool, wx.Config.WriteBool),
        str: _ReadWrite(wx.Config.Read, wx.Config.Write),
        float: _ReadWrite(wx.Config.ReadFloat, wx.Config.WriteFloat)
    }

    _props = {
        'mock_data': _TypeDefault(bool, False),
        'port': _TypeDefault(str, ""),
        'polling_interval': _TypeDefault(float, 0.25),
        'graph_seconds': _TypeDefault(float, 60.0),
        'voltage_range': _TypeDefault(float, 5.0),
        'amperage_range': _TypeDefault(float, 1.0)
    }

    def __init__(self):
        super(Config, self).__init__()
        self._config = wx.Config.Get() # type: wx.ConfigBase
        self._handlers = [] # type: List[ConfigChangeHandler]
        self._dirtyprops = {} # type: Dict[str]

    def __getattr__(self, name):
        if name in self._dirtyprops:
            return self._dirtyprops[name]
        elif name in self._props:
            p = self._props[name]
            return self._types[p.typ].read(self._config, name, p.default)
        else:
            return super(Config, self).__getattr__(name)

    def __setattr__(self, name, value):
        if name in self._props:
            self._dirtyprops[name] = value
        else:
            super(Config, self).__setattr__(name, value)

    def Subscribe(self, handler):
        # type: (ConfigChangeHandler) -> None
        self._handlers.append(handler)

    def Unsubscribe(self, handler):
        # type: (ConfigChangeHandler) -> None
        self._handlers.remove(handler)

    def Save(self):
        for handler in self._handlers:
            try:
                handler.OnConfigChangeBegin()
            except:
                pass

        for name, value in sorted(self._dirtyprops.items()):
            self._types[self._props[name].typ].write(self._config, name, value)
            for handler in self._handlers:
                try:
                    handler.OnConfigChanged(name, value)
                except:
                    pass

        for handler in self._handlers:
            try:
                handler.OnConfigChangeEnd()
            except:
                pass

    def Revert(self):
        self._dirtyprops = {}
