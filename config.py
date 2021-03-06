#!/usr/bin/env python
# vim: set fileencoding=utf-8 :

import collections
try:
    from typing import Dict, Any
except:
    pass
from weakref import WeakSet
import wx


class ConfigChangeHandler(object):
    def __init__(self):
        super(ConfigChangeHandler, self).__init__()

    def OnConfigChangeBegin(self):
        pass

    def OnConfigChanged(self, name, oldvalue, newvalue):
        # type: (str, Any, Any) -> None
        pass

    def OnConfigChangeEnd(self, updates):
        # type: (Dict[str, Any]) -> None
        pass


class Config(object):
    _ReadWrite = collections.namedtuple('_ReadWrite', ('readmethod', 'writemethod'))
    _TypeDefault = collections.namedtuple('_TypeDefault', ('typ', 'default'))

    _types = {
        bool: _ReadWrite('ReadBool', 'WriteBool'),
        str: _ReadWrite('Read', 'Write'),
        float: _ReadWrite('ReadFloat', 'WriteFloat')
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
        self._handlers = WeakSet() # type: WeakSet[ConfigChangeHandler]
        self._dirtyprops = {} # type: Dict[str, Any]

    def __getattr__(self, name):
        if name in self._dirtyprops:
            return self._dirtyprops[name]
        elif name in self._props:
            p = self._props[name]
            return getattr(self._config, self._types[p.typ].readmethod)(name, p.default)
        else:
            return super(Config, self).__getattr__(name)

    def __setattr__(self, name, value):
        if name in self._props:
            self._dirtyprops[name] = value
        else:
            super(Config, self).__setattr__(name, value)

    def Subscribe(self, handler):
        # type: (ConfigChangeHandler) -> None
        self._handlers.add(handler)

    def Unsubscribe(self, handler):
        # type: (ConfigChangeHandler) -> None
        self._handlers.remove(handler)

    def Save(self):
        for handler in self._handlers:
            try:
                handler.OnConfigChangeBegin()
            except:
                pass

        updates = self._dirtyprops
        self._dirtyprops = {}

        for name, newvalue in sorted(updates.items()):
            oldvalue = getattr(self, name)
            getattr(self._config, self._types[self._props[name].typ].writemethod)(name, newvalue)
            for handler in self._handlers:
                try:
                    handler.OnConfigChanged(name, oldvalue, newvalue)
                except:
                    pass

        for handler in self._handlers:
            try:
                handler.OnConfigChangeEnd(updates)
            except:
                pass

    def Revert(self):
        self._dirtyprops = {}
