#!/usr/bin/env python

from time import time
import threading
import traceback

from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
import matplotlib.animation as animation
import minimalmodbus
import numpy as np
import wx

import rdgui_xrc
import submodpaths
submodpaths.add_to_path()

from numpy_ringbuffer import RingBuffer
import rd6006

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
        super(RD6006, self).__init__(*args, **kwargs)

    def _write_registers(self, register, values):
        try:
            return self.instrument.write_registers(register, values)
        except minimalmodbus.NoResponseError:
            return self._write_registers(register, values)

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
        super(ReaderThread, self).__init__(daemon=True)
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
        self.ctlComportList.AppendColumn("port")
        self.ctlComportList.AppendColumn("desc", width=150)
        self.ctlComportList.AppendColumn("hwid", width=200)
        if wx.Config.Get().ReadBool("mock_data", MOCK_DATA):
            self.ctlComportList.Append(("port", "desc", "hwid"))
        import serial.tools.list_ports
        for port, desc, hwid in serial.tools.list_ports.comports():
            self.ctlComportList.Append((port, desc, hwid))
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
        self.ctlVoltage = self.ctlVoltage   # type: wx.SpinCtrlDouble
        self.ctlAmperage = self.ctlAmperage # type: wx.SpinCtrlDouble
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
            voltage, current = rdwrap.rd.voltagecurrent
            # assume model number is (max_voltage * 100) + max_amperage
            self.ctlVoltage.SetIncrement(1.0/rdwrap.rd.voltres)
            self.ctlAmperage.SetMax(int(rdwrap.rd.type / 100) + 0.6)
            self.ctlVoltage.SetValue(voltage)
            self.ctlAmperage.SetIncrement(1.0/rdwrap.rd.ampres)
            self.ctlAmperage.SetMax((rdwrap.rd.type % 100) + 0.6)
            self.ctlAmperage.SetValue(current)
            self.btnEnable.SetValue(rdwrap.rd.enable)
        except:
            traceback.print_exc()

        self.reader = ReaderThread()
        self.figure = Figure()

        self.vaxis = self.figure.add_subplot(111)
        self.vline = Line2D(self.reader.t, self.reader.v)
        self.vaxis.add_line(self.vline)
        self.vaxis.set_ylim(0, config.ReadFloat("voltage_range", VOLTAGE_RANGE))
        self.vaxis.set_xlim(-config.ReadFloat("graph_seconds", GRAPH_SECONDS), 0)
        self.vaxis.set_xlabel('t')
        self.vaxis.set_ylabel('V')

        self.aaxis = self.vaxis.twinx()
        self.aline = Line2D(self.reader.t, self.reader.a, color='#80000080')
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
            t = time()
            v = np.asarray(self.reader.v)
            a = np.asarray(self.reader.a)
            self.vline.set_data(self.reader.t - t, v)
            self.aline.set_data(self.reader.t - t, a)
            if self and len(v) > 0 and len(a) > 0:
                self.SetStatusText("Last V={:.3f}  A={:.3f}".format(v[-1], a[-1]), 1)
        return self.vline, self.aline

    def OnButton_btnUpdate(self, evt):
        with rdwrap.lock:
            rdwrap.rd.voltagecurrent = (self.ctlVoltage.GetValue(), self.ctlAmperage.GetValue())

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

    def OnMenu_wxID_EXIT(self, evt):
        self.Close()

    def OnClose(self, evt):
        self.reader.cancel()
        self.reader.join()
        evt.Skip()

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
