#!/usr/bin/env python
# vim: set fileencoding=utf-8 :

from __future__ import print_function

import traceback
import wx
import wx.lib.agw.floatspin
import wx.lib.dialogs
import wx.xrc as xrc

try:
    from typing import Tuple
except:
        pass

import config
import rdgui
import rdgui_xrc
from utils import appendlistitem

# assume main module added our XmlResourceHandler

_ = wx.GetTranslation


class DlgPortSelector(rdgui_xrc.xrcdlgPortSelector):
    def __init__(self, parent):
        super(DlgPortSelector, self).__init__(parent)
        self.ctlComportList = self.ctlComportList # type: wx.ListCtrl
        self.wxID_OK = self.wxID_OK # type: wx.Button
        if wx.GetApp().config.mock_data:
            appendlistitem(self.ctlComportList, "port", "desc", "hwid")
        import serial.tools.list_ports
        for port, desc, hwid in serial.tools.list_ports.comports():
            appendlistitem(self.ctlComportList, port, desc, hwid)
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

    def OnSpinctrl(self, evt):
        # type: (wx.CommandEvent) -> None
        self.wxID_APPLY.Enable()

    OnSpinctrl_ctlGraphSeconds = OnSpinctrl
    OnSpinctrl_ctlPollingInterval = OnSpinctrl
    OnSpinctrl_ctlVoltageRange = OnSpinctrl
    OnSpinctrl_ctlAmperageRange = OnSpinctrl

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


class DlgCalibration(rdgui_xrc.xrcdlgCalibration):
    def __init__(self, parent, rdwrap):
        # type: (wx.Window, rdgui.RDWrapper) -> None
        super(DlgCalibration, self).__init__(parent)
        self.rdwrap = rdwrap

        self.spinctrls = (
            xrc.XRCCTRL(self, "ctlVOutputZero"),
            xrc.XRCCTRL(self, "ctlVOutputScale"),
            xrc.XRCCTRL(self, "ctlVReadbackZero"),
            xrc.XRCCTRL(self, "ctlVReadbackScale"),
            xrc.XRCCTRL(self, "ctlAOutputZero"),
            xrc.XRCCTRL(self, "ctlAOutputScale"),
            xrc.XRCCTRL(self, "ctlAReadbackZero"),
            xrc.XRCCTRL(self, "ctlAReadbackScale"),
        ) # type: Tuple[wx.SpinCtrl, ...]

        if wx.GetApp().config.mock_data:
            self.initial_regs = [18, 22802, 22, 17585, 276, 21458, 77, 17418]
        else:
            with self.rdwrap.lock:
                self.initial_regs = self.rdwrap.rd._read_registers(0x37, 8) # type: list[int]

        for ctrl, reg in zip(self.spinctrls, self.initial_regs):
            ctrl.SetValue(reg)

    def DoCancel(self, id):
        # type: (int) -> None
        try:
            with self.rdwrap.lock:
                self.rdwrap.rd._write_registers(0x37, self.initial_regs)
        except:
            wx.lib.dialogs.MultiMessageBox(
                _("An error occurred while attempting to restore calibration data"),
                _("Error restoring calibration data"),
                traceback.format_exc(), wx.OK|wx.ICON_ERROR, self)
        self.EndModal(id)

    def OnClose(self, evt):
        # type: (wx.CloseEvent) -> None
        self.DoCancel(wx.ID_CLOSE)
        evt.Skip()

    def OnButton_wxID_OK(self, evt):
        # type: (wx.CommandEvent) -> None
        ans = wx.MessageBox(
            "{}\n\n{}".format(
                _("Are you sure you want to commit calibration data?"),
                _("Note: calibration data can be reset to default by holding \"1\" while powering on the unit.")
            ),
            _("Commit calibration data"),
            wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,
            self)
        if ans == wx.YES:
            regs = [ctrl.GetValue() for ctrl in self.spinctrls]
            with self.rdwrap.lock:
                # TODO: should we do this or rely on the SpinEvents?
                self.rdwrap.rd._write_registers(0x37, regs)
                self.rdwrap.rd._write_register(0x36, 0x1501)
            self.EndModal(evt.Id)

    def OnButton_wxID_CANCEL(self, evt):
        # type: (wx.CommandEvent) -> None
        self.DoCancel(evt.Id)

    def OnSpinctrl(self, evt):
        # type: (wx.SpinEvent) -> None
        i = self.spinctrls.index(evt.EventObject)
        with self.rdwrap.lock:
            self.rdwrap.rd._write_register(0x37 + i, evt.GetInt())

    OnSpinctrl_ctlVOutputZero = OnSpinctrl
    OnSpinctrl_ctlVOutputScale = OnSpinctrl
    OnSpinctrl_ctlVReadbackZero = OnSpinctrl
    OnSpinctrl_ctlVReadbackScale = OnSpinctrl
    OnSpinctrl_ctlAOutputZero = OnSpinctrl
    OnSpinctrl_ctlAOutputScale = OnSpinctrl
    OnSpinctrl_ctlAReadbackZero = OnSpinctrl
    OnSpinctrl_ctlAReadbackScale = OnSpinctrl
