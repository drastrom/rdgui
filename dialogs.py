#!/usr/bin/env python
# vim: set fileencoding=utf-8 :

from __future__ import print_function

import wx
import wx.lib.agw.floatspin

import config
import rdgui_xrc

# assume main module added our XmlResourceHandler

_ = wx.GetTranslation


class DlgPortSelector(rdgui_xrc.xrcdlgPortSelector):
    def __init__(self, parent):
        super(DlgPortSelector, self).__init__(parent)
        self.ctlComportList = self.ctlComportList # type: wx.ListCtrl
        self.ctlComportList.InsertColumn(self.ctlComportList.GetColumnCount(), "port")
        self.ctlComportList.InsertColumn(self.ctlComportList.GetColumnCount(), "desc", width=150)
        self.ctlComportList.InsertColumn(self.ctlComportList.GetColumnCount(), "hwid", width=200)
        if wx.GetApp().config.mock_data:
            pos = self.ctlComportList.InsertStringItem(self.ctlComportList.GetItemCount(), "port")
            self.ctlComportList.SetStringItem(pos, 1, "desc")
            self.ctlComportList.SetStringItem(pos, 2, "hwid")
        import serial.tools.list_ports
        for port, desc, hwid in serial.tools.list_ports.comports():
            pos = self.ctlComportList.InsertStringItem(self.ctlComportList.GetItemCount(), port)
            self.ctlComportList.SetStringItem(pos, 1, desc)
            self.ctlComportList.SetStringItem(pos, 2, hwid)
        self.wxID_OK.Enable(False)

    def OnButton_wxID_CANCEL(self, evt):
        # type: (wx.CommandEvent) -> None
        self.EndModal(evt.Id)

    def OnButton_wxID_OK(self, evt):
        # type: (wx.CommandEvent) -> None
        sel = self.ctlComportList.GetFirstSelected()
        if (sel != -1):
            self.port = self.ctlComportList.GetItemText(sel) # type: str
            self.EndModal(evt.Id)

    def OnList_item_deselected_ctlComportList(self, evt):
        # type: (wx.ListEvent) -> None
        self.wxID_OK.Enable(False)

    def OnList_item_selected_ctlComportList(self, evt):
        # type: (wx.ListEvent) -> None
        self.wxID_OK.Enable(True)

    def OnList_item_activated_ctlComportList(self, evt):
        # type: (wx.ListEvent) -> None
        self.port = evt.Text # type: str
        self.EndModal(wx.ID_OK)


class DlgSettings(rdgui_xrc.xrcdlgSettings, config.ConfigChangeHandler):
    def __init__(self, parent):
        super(DlgSettings, self).__init__(parent)
        self.config = wx.GetApp().config # type: config.Config
        self.config.Subscribe(self)

        self.ctlGraphSeconds = self.ctlGraphSeconds       # type: wx.lib.agw.floatspin.FloatSpin
        self.ctlPollingInterval = self.ctlPollingInterval # type: wx.lib.agw.floatspin.FloatSpin
        self.ctlVoltageRange = self.ctlVoltageRange       # type: wx.lib.agw.floatspin.FloatSpin
        self.ctlAmperageRange = self.ctlAmperageRange     # type: wx.lib.agw.floatspin.FloatSpin
        self.wxID_APPLY = self.wxID_APPLY                 # type: wx.Button

        self.ctlGraphSeconds.SetDefaultValue(self.config.graph_seconds)
        self.ctlGraphSeconds.SetToDefaultValue()

        self.ctlPollingInterval.SetDefaultValue(self.config.polling_interval)
        self.ctlPollingInterval.SetToDefaultValue()

        self.ctlVoltageRange.SetDefaultValue(self.config.voltage_range)
        self.ctlVoltageRange.SetToDefaultValue()

        self.ctlAmperageRange.SetDefaultValue(self.config.amperage_range)
        self.ctlAmperageRange.SetToDefaultValue()

    def OnClose(self, evt):
        # type: (wx.CloseEvent) -> None
        self.config.Unsubscribe(self)
        evt.Skip()

    def OnSpinctrl_ctlGraphSeconds(self, evt):
        # type: (wx.CommandEvent) -> None
        self.wxID_APPLY.Enable()

    def OnSpinctrl_ctlPollingInterval(self, evt):
        # type: (wx.CommandEvent) -> None
        self.wxID_APPLY.Enable()

    def OnSpinctrl_ctlVoltageRange(self, evt):
       # type: (wx.CommandEvent) -> None
        self.wxID_APPLY.Enable()

    def OnSpinctrl_ctlAmperageRange(self, evt):
       # type: (wx.CommandEvent) -> None
        self.wxID_APPLY.Enable()

    def OnButton_wxID_OK(self, evt):
        # type: (wx.CommandEvent) -> None
        self.OnApply()
        self.EndModal(evt.Id)

    def OnButton_wxID_CANCEL(self, evt):
        # type: (wx.CommandEvent) -> None
        self.EndModal(evt.Id)

    def OnButton_wxID_APPLY(self, evt):
        # type: (wx.CommandEvent) -> None
        self.OnApply()

    def OnApply(self):
        dirty = False
        if not self.ctlGraphSeconds.IsDefaultValue():
            self.config.graph_seconds = self.ctlGraphSeconds.GetValue()
            dirty = True
        if not self.ctlPollingInterval.IsDefaultValue():
            self.config.polling_interval = self.ctlPollingInterval.GetValue()
            dirty = True
        if not self.ctlVoltageRange.IsDefaultValue():
            self.config.voltage_range = self.ctlVoltageRange.GetValue()
            dirty = True
        if not self.ctlAmperageRange.IsDefaultValue():
            self.config.amperage_range = self.ctlAmperageRange.GetValue()
            dirty = True
        if dirty:
            self.config.Save()
        self.wxID_APPLY.Enable(False)

    def OnConfigChangeEnd(self, updates):
        if 'graph_seconds' in updates:
            self.ctlGraphSeconds.SetDefaultValue(updates['graph_seconds'])
        if 'polling_interval' in updates:
            self.ctlPollingInterval.SetDefaultValue(updates['polling_interval'])
        if 'voltage_range' in updates:
            self.ctlVoltageRange.SetDefaultValue(updates['voltage_range'])
        if 'amperage_range' in updates:
            self.ctlAmperageRange.SetDefaultValue(updates['amperage_range'])
