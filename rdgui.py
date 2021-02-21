#!/usr/bin/env python

from time import time

from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
import matplotlib.animation as animation
import numpy as np
import threading
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

class ReaderThread(threading.Thread):
    def __init__(self, port):
        # type: (str) -> None
        super(ReaderThread, self).__init__(daemon=True)
        config = wx.Config.Get() # type: wx.ConfigBase
        self.polling_interval = config.ReadFloat("polling_interval", POLLING_INTERVAL) # type: float
        self.mock = config.ReadBool("mock_data", MOCK_DATA) # type: bool
        graph_seconds = config.ReadFloat("graph_seconds", GRAPH_SECONDS) # type: float
        self.port = port
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
        else:
            rd = rd6006.RD6006(self.port)
        while self.running:
            t = time()
            if self.mock:
                v = next(vgen)
                a = next(agen)
            else:
                reg = rd._read_registers(10, 2)
                v = reg[0] / rd.voltres
                a = reg[1] / rd.ampres
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

        config = wx.Config.Get() # type: wx.ConfigBase
        port = config.Read("port") # type: str
        if port == "":
            dlg = DlgPortSelector(self)
            if dlg.ShowModal() == wx.ID_OK:
                port = dlg.port
                config.Write("port", port)

        self.reader = ReaderThread(port)

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
                "t={}  V={}  A={}".format(event.xdata, v, a))
        else:
            self.SetStatusText("")

    def update(self, d):
        with self.reader.datalock:
            t = time()
            self.vline.set_data(self.reader.t - t, np.asarray(self.reader.v))
            self.aline.set_data(self.reader.t - t, np.asarray(self.reader.a))
        return self.vline, self.aline

    def OnMenu_wxID_OPEN(self, evt):
        port = self.reader.port
        self.reader.cancel()
        dlg = DlgPortSelector(self)
        if dlg.ShowModal() == wx.ID_OK:
            port = dlg.port
            wx.Config.Get().Write("port", port)
        self.reader = ReaderThread(port)
        self.reader.start()

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
