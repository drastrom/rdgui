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
from matplotlib.ticker import AutoMinorLocator
import matplotlib.animation as animation
import minimalmodbus
import numpy as np
from numpy_ringbuffer import RingBuffer
import wx
import wx.lib.agw.floatspin

import config
import dialogs
import rdgui_xrc
from utils import AttributeSetterCtx, UnlockerCtx, ringbuffer_resize, emitter
import xh_floatspin

import submodpaths
submodpaths.add_to_path()
import rd6006

rdgui_xrc.get_resources().AddHandler(xh_floatspin.FloatSpinCtrlXmlHandler())

_ = wx.GetTranslation


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
        with AttributeSetterCtx(self.instrument.serial, 'timeout', 5.0):
            self.instrument.serial.write(f)
            res = self.instrument.serial.read(1)
            if res != b'\xfc':
                raise RuntimeError("Unable to reboot into bootloader")

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
        with AttributeSetterCtx(self.instrument.serial, 'timeout', 5.0):
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


class ReaderThread(threading.Thread, config.ConfigChangeHandler):
    class _Command(object):
        NONE = 0
        SHUTDOWN = 1
        CONFIGUPDATE = 2

    def __init__(self):
        super(ReaderThread, self).__init__()
        self.daemon = True
        self.config = wx.GetApp().config # type: config.Config
        self.config.Subscribe(self)
        self.polling_interval = self.config.polling_interval # type: float
        self.mock = self.config.mock_data # type: bool
        self.graph_seconds = self.config.graph_seconds # type: float
        self.command = self._Command.NONE
        self.datalock = threading.Lock()
        self.commandcond = threading.Condition(self.datalock)
        self.t = RingBuffer(int(self.graph_seconds/self.polling_interval), float)
        self.v = RingBuffer(int(self.graph_seconds/self.polling_interval), float)
        self.a = RingBuffer(int(self.graph_seconds/self.polling_interval), float)

    def shutdown(self):
        with self.datalock:
            self.command = self._Command.SHUTDOWN
            self.commandcond.notify()
        self.join()
        self.config.Unsubscribe(self)

    def run(self):
        if self.mock:
            vgen = emitter()
            agen = emitter()
        with self.datalock:
            while self.command != self._Command.SHUTDOWN:
                if self.command == self._Command.CONFIGUPDATE:
                    pass
                self.command = self._Command.NONE
                with UnlockerCtx(self.datalock):
                    t = time()
                    if self.mock:
                        v = next(vgen)
                        a = next(agen)
                    else:
                        with rdwrap.lock:
                            v, a = rdwrap.rd.measvoltagecurrent
                    print (time() - t, v, a)
                self.t.append(t)
                self.v.append(v)
                self.a.append(a)
                if self.command == self._Command.NONE:
                    self.commandcond.wait(max((t + self.polling_interval) - time(), 0))

    def OnConfigChangeEnd(self, updates):
        dirty = False
        for name in ('polling_interval', 'graph_seconds'):
            if name in updates:
                dirty = True
                break
        if dirty:
            with self.datalock:
                if 'polling_interval' in updates:
                    self.polling_interval = updates['polling_interval']
                if 'graph_seconds' in updates:
                    self.graph_seconds = updates['graph_seconds']

                self.t = ringbuffer_resize(self.t, int(self.graph_seconds/self.polling_interval))
                self.v = ringbuffer_resize(self.v, int(self.graph_seconds/self.polling_interval))
                self.a = ringbuffer_resize(self.a, int(self.graph_seconds/self.polling_interval))

                self.command = self._Command.CONFIGUPDATE
                self.commandcond.notify()


class CanvasFrame(rdgui_xrc.xrcCanvasFrame, config.ConfigChangeHandler):
    def __init__(self, parent=None):
        super(CanvasFrame, self).__init__(parent)

        # no-op self-assignment for typing
        self.ctlVoltage = self.ctlVoltage   # type: wx.lib.agw.floatspin.FloatSpin
        self.ctlAmperage = self.ctlAmperage # type: wx.lib.agw.floatspin.FloatSpin
        self.btnEnable = self.btnEnable     # type: wx.ToggleButton

        self.config = wx.GetApp().config # type: config.Config
        port = self.config.port # type: str
        if port == "":
            with dialogs.DlgPortSelector(self) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    config.port = dlg.port
                    config.Save()

        self.config.Subscribe(self)
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
        self.vaxis.set_ylim(0, self.config.voltage_range)
        self.vaxis.set_xlim(-self.config.graph_seconds, 0)
        self.vaxis.set_xlabel('t')
        self.vaxis.set_ylabel('V')
        self.vaxis.yaxis.set_minor_locator(AutoMinorLocator(4))
        self.vaxis.grid(axis='x', linestyle='--')
        self.vaxis.grid(which='both', axis='y', linestyle='--')

        self.aaxis = self.vaxis.twinx()
        self.aline = Line2D([], [], color='#80000080')
        self.aaxis.add_line(self.aline)
        self.aaxis.set_ylim(0, self.config.amperage_range)
        self.aaxis.set_ylabel('A')
        self.aaxis.yaxis.set_minor_locator(AutoMinorLocator(4))

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
                interval=int(self.config.polling_interval*1000), blit=True)

    def UpdateStatusBar(self, event):
        if event.inaxes:
            if event.inaxes == self.vaxis:
                v = event.ydata
                a = self.aaxis.transData.inverted().transform((event.x, event.y))[1]
            else:
                v = self.vaxis.transData.inverted().transform((event.x, event.y))[1]
                a = event.ydata
            self.SetStatusText(
                "t={:.3f}  V={:.2f}  A={:.3f}".format(event.xdata, v, a))
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
                self.SetStatusText("Last V={:.2f}  A={:.3f}".format(v[-1], a[-1]), 1)
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
        with dialogs.DlgPortSelector(self) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                port = dlg.port
                rdwrap.open(port)
                self.config.port = port
                self.config.Save()

    def OnMenu_ID_FWUPDATE(self, evt):
        if self.config.mock_data:
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

        with dialogs.WrappedMultiMessageDialog(self, _("Device firmware version {:.2f} -> Online version {:.2f}, released {}").format(
            fwver, float(updata["Version"]), updata["Time"]), _("Update firmware?"),
            _("{}\nHistory:\n\n{}").format(updata["UpdateContent"], updata["History"]),
             wx.YES_NO|wx.ICON_QUESTION
        ) as mb:
            mb = mb # type: dialogs.WrappedMultiMessageDialog
            ans = mb.ShowModal()
        if ans == wx.ID_YES:
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

    def OnMenu_ID_CALIBRATE(self, evt):
        with dialogs.DlgCalibration(self, rdwrap) as dlg:
            dlg = dlg # type: dialogs.DlgCalibration
            dlg.ShowModal()

    def OnMenu_ID_SETTINGS(self, evt):
        with dialogs.DlgSettings(self) as dlg:
            dlg = dlg # type: dialogs.DlgSettings
            dlg.ShowModal()

    def OnMenu_wxID_EXIT(self, evt):
        self.Close()

    def OnClose(self, evt):
        # type: (wx.CloseEvent) -> None
        self.reader.shutdown()
        self.config.Unsubscribe(self)
        evt.Skip()

    def OnConfigChangeEnd(self, updates):
        graph_dirty = False
        if 'graph_seconds' in updates:
            self.vaxis.set_xlim(-updates['graph_seconds'], 0)
            self.aaxis.set_xlim(-updates['graph_seconds'], 0)
            graph_dirty = True
        if 'polling_interval' in updates:
            # TODO: update animation interval
            pass
        if 'voltage_range' in updates:
            self.vaxis.set_ylim(0, updates['voltage_range'])
            graph_dirty = True
        if 'amperage_range' in updates:
            self.aaxis.set_ylim(0, updates['amperage_range'])
            graph_dirty = True
        if graph_dirty:
            self.figure_canvas.draw()

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
        self.config = config.Config()
        frame = CanvasFrame()
        self.SetTopWindow(frame)
        frame.Show(True)
        return True


if __name__ == '__main__':
    app = App()
    app.MainLoop()
