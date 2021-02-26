#!/usr/bin/env python
# vim: set fileencoding=utf-8 :

from __future__ import print_function

import contextlib
import json
import math
import os
import struct
import sys
import threading
from time import time
import traceback
try:
    from typing import Callable
except:
    pass
try:
    from urllib.request import urlopen
except ImportError:
    from urllib import urlopen

from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
import matplotlib.animation as animation
import minimalmodbus
import numpy as np
from numpy_ringbuffer import RingBuffer
import wx
import wx.lib.agw.floatspin
import wx.lib.dialogs

import rdgui_xrc
import xh_floatspin
import submodpaths
submodpaths.add_to_path()

import rd6006

rdgui_xrc.get_resources().AddHandler(xh_floatspin.FloatSpinCtrlXmlHandler())

_ = wx.GetTranslation

MOCK_DATA=False
POLLING_INTERVAL=0.25
GRAPH_SECONDS=60.0
VOLTAGE_RANGE=5.0
AMPERAGE_RANGE=1.0

def emitter(p=0.1):
    """Return a random value in [0, 1) with probability p, else 0."""
    while True:
        v = np.random.rand(1)
        if v > p:
            yield 0.
        else:
            yield np.random.rand(1)

class RD6006(rd6006.RD6006):
    def __init__(self, *args, **kwargs):
        self._constructing = True
        super(RD6006, self).__init__(*args, **kwargs)
        self._constructing = False
        # It looks like rd6006 tried to change minimalmodbus timeout to 0.5s,
        # but at least the version I have is still using 0.05s.  Change it
        self.instrument.serial.timeout = 0.5

    def _read_registers(self, start, length):
        if self._constructing and start == 0 and length == 4 and self.is_bootloader:
            info = self.bootloader_info
            return (info["model"], (info["serial"] >> 16) & 0xFFFF, info["serial"] & 0xFFFF, int(info["fwver"]*100))
        return super(RD6006, self)._read_registers(start, length)

    def _write_registers(self, register, values):
        try:
            return self.instrument.write_registers(register, values)
        except minimalmodbus.NoResponseError:
            return self._write_registers(register, values)

    @property
    def model(self):
        return self._read_register(0)

    @property
    def measvoltagecurrent(self):
        reg = self._read_registers(10, 2)
        return (reg[0] / self.voltres, reg[1] / self.ampres)

    @property
    def voltagecurrent(self):
        reg = self._read_registers(8, 2)
        return (reg[0] / self.voltres, reg[1] / self.ampres)

    @voltagecurrent.setter
    def voltagecurrent(self, value):
        self._write_registers(8, [int(value[0] * self.voltres), int(value[1] * self.ampres)])

    def reboot_into_bootloader(self):
        py3 = sys.version_info[0] > 2
        f = struct.pack(">BBHH", self.instrument.address, 6, 0x100, 0x1601)
        # stupid minimalmodbus
        if py3:
            f = str(f, encoding='latin1')
        f += minimalmodbus._calculate_crc_string(f)
        if py3:
            f = bytes(f, encoding='latin1')
        if self.instrument.clear_buffers_before_each_transaction:
            self.instrument.serial.reset_input_buffer()
            self.instrument.serial.reset_output_buffer()
        t = self.instrument.serial.timeout
        try:
            self.instrument.serial.timeout = 5.0
            self.instrument.serial.write(f)
            res = self.instrument.serial.read(1)
            if res != b'\xfc':
                raise RuntimeError("Unable to reboot into bootloader")
        finally:
            self.instrument.serial.timeout = t

    @property
    def is_bootloader(self):
        if self.instrument.clear_buffers_before_each_transaction:
            self.instrument.serial.reset_input_buffer()
            self.instrument.serial.reset_output_buffer()
        self.instrument.serial.write(b"queryd\r\n")
        res = self.instrument.serial.read(4)
        return res == b'boot'

    @property
    def bootloader_info(self):
        if self.instrument.clear_buffers_before_each_transaction:
            self.instrument.serial.reset_input_buffer()
            self.instrument.serial.reset_output_buffer()
        self.instrument.serial.write(b"getinf\r\n")
        res = self.instrument.serial.read(13)
        if len(res) != 13:
            raise RuntimeError("Bad getinf response from bootloader: {!r}".format(res))
        rtype, serial, model, bootver, fwver = struct.unpack("<3sIHHH", res)
        if rtype != b'inf':
            raise RuntimeError("Bad getinf response from bootloader: {!r}".format(res))
        return {"serial": serial, "model": model, "bootver": bootver/100., "fwver": fwver/100.}

    def bootloader_update_firmware(self, firmware, progress_callback = lambda pos: None):
        # type: (bytes, Callable[[int], None]) -> None
        if self.instrument.clear_buffers_before_each_transaction:
            self.instrument.serial.reset_input_buffer()
            self.instrument.serial.reset_output_buffer()
        t = self.instrument.serial.timeout
        try:
            self.instrument.serial.timeout = 5.0
            self.instrument.serial.write(b"upfirm\r\n")
            res = self.instrument.serial.read(6)
            if res != b'upredy':
                raise RuntimeError("Unable to enter update firmware mode: {!r}".format(res))
            for pos, block in ((pos, firmware[pos:pos+64]) for pos in range(0, len(firmware), 64)):
                progress_callback(pos)
                self.instrument.serial.write(block)
                res = self.instrument.serial.read(2)
                if res != b'OK':
                    raise RuntimeError("Flash failed: {!r}".format(res))
        finally:
            self.instrument.serial.timeout = t


class RDWrapper(object):
    def __init__(self):
        super(RDWrapper, self).__init__()
        self.rd = None # type: RD6006
        self.lock = threading.Lock()

    def open(self, port):
        with self.lock:
            if self.rd is not None:
                self.rd.instrument.serial.close()
            self.rd = RD6006(port)


rdwrap = RDWrapper()

class ReaderThread(threading.Thread):
    def __init__(self):
        # type: (str) -> None
        super(ReaderThread, self).__init__()
        self.daemon = True
        config = wx.Config.Get() # type: wx.ConfigBase
        self.polling_interval = config.ReadFloat("polling_interval", POLLING_INTERVAL) # type: float
        self.mock = config.ReadBool("mock_data", MOCK_DATA) # type: bool
        graph_seconds = config.ReadFloat("graph_seconds", GRAPH_SECONDS) # type: float
        self.running = True
        self.datalock = threading.Lock()
        self.shutdowncond = threading.Condition(self.datalock)
        self.t = RingBuffer(int(graph_seconds/self.polling_interval), float)
        self.v = RingBuffer(int(graph_seconds/self.polling_interval), float)
        self.a = RingBuffer(int(graph_seconds/self.polling_interval), float)

    def cancel(self):
        with self.datalock:
            self.running = False
            self.shutdowncond.notify()

    def run(self):
        if self.mock:
            vgen = emitter()
            agen = emitter()
        while self.running:
            t = time()
            if self.mock:
                v = next(vgen)
                a = next(agen)
            else:
                with rdwrap.lock:
                    v, a = rdwrap.rd.measvoltagecurrent
            print (time() - t, v, a)
            with self.datalock:
                self.t.append(t)
                self.v.append(v)
                self.a.append(a)
                if self.running:
                    self.shutdowncond.wait(max((t + self.polling_interval) - time(), 0))

class DlgPortSelector(rdgui_xrc.xrcdlgPortSelector):
    def __init__(self, parent):
        super(DlgPortSelector, self).__init__(parent)
        self.ctlComportList = self.ctlComportList # type: wx.ListCtrl
        self.ctlComportList.InsertColumn(self.ctlComportList.GetColumnCount(), "port")
        self.ctlComportList.InsertColumn(self.ctlComportList.GetColumnCount(), "desc", width=150)
        self.ctlComportList.InsertColumn(self.ctlComportList.GetColumnCount(), "hwid", width=200)
        if wx.Config.Get().ReadBool("mock_data", MOCK_DATA):
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

class CanvasFrame(rdgui_xrc.xrcCanvasFrame):
    def __init__(self, parent=None):
        super(CanvasFrame, self).__init__(parent)

        # no-op self-assignment for typing
        self.ctlVoltage = self.ctlVoltage   # type: wx.lib.agw.floatspin.FloatSpin
        self.ctlAmperage = self.ctlAmperage # type: wx.lib.agw.floatspin.FloatSpin
        self.btnEnable = self.btnEnable     # type: wx.ToggleButton

        config = wx.Config.Get() # type: wx.ConfigBase
        port = config.Read("port") # type: str
        if port == "":
            with DlgPortSelector(self) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    port = dlg.port
                    config.Write("port", port)

        try:
            rdwrap.open(port)
            if rdwrap.rd.is_bootloader:
                self.OnMenu_ID_FWUPDATE(None)
            voltage, current = rdwrap.rd.voltagecurrent
            # assume model number is (max_voltage * 100) + max_amperage
            inc = 1.0/rdwrap.rd.voltres
            self.ctlVoltage.SetIncrement(inc)
            self.ctlVoltage.SetDigits(int(-math.floor(math.log10(inc))))
            self.ctlVoltage.SetRange(0, int(rdwrap.rd.type / 100) * 1.1)
            self.ctlVoltage.SetValue(voltage)

            inc = 1.0/rdwrap.rd.ampres
            self.ctlAmperage.SetIncrement(inc)
            self.ctlAmperage.SetDigits(int(-math.floor(math.log10(inc))))
            self.ctlAmperage.SetRange(0, (rdwrap.rd.type % 100) * 1.1)
            self.ctlAmperage.SetValue(current)

            self.btnEnable.SetValue(rdwrap.rd.enable)
        except:
            traceback.print_exc()

        self.reader = ReaderThread()
        self.figure = Figure()

        self.vaxis = self.figure.add_subplot(111)
        self.vline = Line2D([], [])
        self.vaxis.add_line(self.vline)
        self.vaxis.set_ylim(0, config.ReadFloat("voltage_range", VOLTAGE_RANGE))
        self.vaxis.set_xlim(-config.ReadFloat("graph_seconds", GRAPH_SECONDS), 0)
        self.vaxis.set_xlabel('t')
        self.vaxis.set_ylabel('V')

        self.aaxis = self.vaxis.twinx()
        self.aline = Line2D([], [], color='#80000080')
        self.aaxis.add_line(self.aline)
        self.aaxis.set_ylim(0, config.ReadFloat("amperage_range", AMPERAGE_RANGE))
        self.aaxis.set_ylabel('A')

        self.figure_canvas = FigureCanvas(self, wx.ID_ANY, self.figure)
        rdgui_xrc.get_resources().AttachUnknownControl("ID_FIGURE", self.figure_canvas, self)

        # Note that event is a MplEvent
        self.figure_canvas.mpl_connect(
            'motion_notify_event', self.UpdateStatusBar)

        self.figure.tight_layout()
        self.Fit()
        self.MinSize = self.Size
        self.reader.start()
        self.ani = animation.FuncAnimation(self.figure, self.update,
                interval=int(config.ReadFloat("polling_interval", POLLING_INTERVAL)*1000), blit=True)

    def UpdateStatusBar(self, event):
        if event.inaxes:
            if event.inaxes == self.vaxis:
                v = event.ydata
                a = self.aaxis.transData.inverted().transform((event.x, event.y))[1]
            else:
                v = self.vaxis.transData.inverted().transform((event.x, event.y))[1]
                a = event.ydata
            self.SetStatusText(
                "t={:.3f}  V={:.3f}  A={:.3f}".format(event.xdata, v, a))
        else:
            self.SetStatusText("")

    def update(self, d):
        with self.reader.datalock:
            t = np.asarray(self.reader.t) - time()
            v = np.asarray(self.reader.v)
            a = np.asarray(self.reader.a)
            self.vline.set_data(t, v)
            self.aline.set_data(t, a)
            if self and len(v) > 0 and len(a) > 0:
                self.SetStatusText("Last V={:.3f}  A={:.3f}".format(v[-1], a[-1]), 1)
        return self.vline, self.aline

    def OnButton_btnUpdate(self, evt):
        voltage = self.ctlVoltage.GetValue()
        current = self.ctlAmperage.GetValue()
        with rdwrap.lock:
            rdwrap.rd.voltagecurrent = (voltage, current)
            # read back in case the setting didn't take
            voltage, current = rdwrap.rd.voltagecurrent
        self.ctlVoltage.SetValue(voltage)
        self.ctlAmperage.SetValue(current)

    def OnTogglebutton_btnEnable(self, evt):
        # type: (wx.CommandEvent) -> None
        with rdwrap.lock:
            rdwrap.rd.enable = evt.IsChecked()

    def OnMenu_wxID_OPEN(self, evt):
        with DlgPortSelector(self) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                port = dlg.port
                rdwrap.open(port)
                wx.Config.Get().Write("port", port)

    def OnMenu_ID_FWUPDATE(self, evt):
        if wx.Config.Get().ReadBool("mock_data", MOCK_DATA):
            model = 60062
            fwver = 1.23
        else:
            with rdwrap.lock:
                if rdwrap.rd.is_bootloader:
                    info = rdwrap.rd.bootloader_info
                    model = info["model"]
                    fwver = info["fwver"]
                else:
                    model = rdwrap.rd.model
                    fwver = rdwrap.rd.fw

        url = "http://www.ruidengkeji.com/rdupdate/firmware/RD{0}/RD{0}.json".format(model)
        with contextlib.closing(urlopen(url)) as fp:
            updata = json.load(fp, strict=False)

        with wx.lib.dialogs.MultiMessageDialog(self, _("Device firmware version {:.2f} -> Online version {:.2f}, released {}").format(
            fwver, float(updata["Version"]), updata["Time"]), _("Update firmware?"),
            _("{}\nHistory:\n\n{}").format(updata["UpdateContent"], updata["History"]),
             wx.YES_NO|wx.ICON_QUESTION
        ) as mb:
            mb = mb # type: wx.lib.dialogs.MultiMessageDialog
            # this is evil
            for w in mb.Children:
                if isinstance(w, wx.TextCtrl) and (w.WindowStyle & wx.TE_DONTWRAP) != 0:
                    new = wx.TextCtrl(mb, value=w.Value, style=(w.WindowStyle & ~(wx.TE_DONTWRAP|wx.HSCROLL)) | wx.TE_BESTWRAP)
                    new.SetMinSize(w.GetMinSize())
                    print(mb.Sizer.Replace(w, new, True))
                    w.Destroy()
            mb.Layout()
            ans = mb.ShowModal()
        if ans == wx.YES:
            def read_firmware():
                # type: () -> bytes
                with contextlib.closing(urlopen(updata["DownloadUri"])) as fh:
                    return fh.read()
            self._update_firmware(int(updata["Size"]), read_firmware)

    def OnMenu_ID_FWFILE(self, evt):
        filename = wx.FileSelector(_("Open Firmware File"), wildcard=_("Firmware File (*.bin)|*.bin"), flags=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST, parent=self) # type: str
        if filename.strip():
            def read_firmware():
                with open(filename, "rb") as fh:
                    return fh.read()
            self._update_firmware(int(os.stat(filename).st_size), read_firmware)

    def OnMenu_wxID_EXIT(self, evt):
        self.Close()

    def OnClose(self, evt):
        self.reader.cancel()
        self.reader.join()
        evt.Skip()

    def _update_firmware(self, firmware_size, read_firmware_func):
        # type: (int, Callable[[], bytes]) -> None
        with wx.ProgressDialog(_("Updating Firmware"), _("Getting firmware..."), maximum=firmware_size, parent=self, style=wx.PD_APP_MODAL) as pd:
            firmware = read_firmware_func()
            def progress(pos):
                pd.Update(pos, _("Updating {}/{}: {:.2f}%").format(pos, len(firmware), pos*100./len(firmware)))
            pd.Update(1, _("Restarting into bootloader..."))
            with rdwrap.lock:
                if not rdwrap.rd.is_bootloader:
                    rdwrap.rd.reboot_into_bootloader()
                    wx.Sleep(3)
                rdwrap.rd.bootloader_update_firmware(firmware, progress)
                wx.Sleep(5)
            pd.Close()


class App(wx.App):
    def OnInit(self):
        """Create the main window and insert the custom frame."""
        self.AppName = "RDGUI"
        self.VendorName = "Drastrom"
        self.VendorDisplayName = "Drästrøm"
        frame = CanvasFrame()
        self.SetTopWindow(frame)
        frame.Show(True)
        return True


if __name__ == '__main__':
    app = App()
    app.MainLoop()
