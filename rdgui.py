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

MOCK_DATA=True
POLLING_INTERVAL=0.25
GRAPH_SECONDS=60.0

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
        self.d = RingBuffer(int(graph_seconds/self.polling_interval), float)

    def cancel(self):
        with self.datalock:
            self.running = False
            self.shutdowncond.notify()

    def run(self):
        if self.mock:
            gen = emitter()
        else:
            rd = rd6006.RD6006(self.port)
        while self.running:
            a = time()
            if self.mock:
                v = next(gen)
            else:
                v = rd.measvoltage
            t = time()
            #print (t - a)
            with self.datalock:
                self.t.append(t)
                self.d.append(v)
                if self.running:
                    self.shutdowncond.wait(max((a + self.polling_interval) - time(), 0))

class DlgPortSelector(rdgui_xrc.xrcdlgPortSelector):
    def __init__(self, parent):
        super(DlgPortSelector, self).__init__(parent)
        self.ID_COMPORT_LIST = self.ID_COMPORT_LIST # type: wx.ListCtrl
        self.ID_COMPORT_LIST.AppendColumn("port")
        self.ID_COMPORT_LIST.AppendColumn("desc", width=150)
        self.ID_COMPORT_LIST.AppendColumn("hwid", width=200)
        if wx.Config.Get().ReadBool("mock_data", MOCK_DATA):
            self.ID_COMPORT_LIST.Append(("port", "desc", "hwid"))
        import serial.tools.list_ports
        for port, desc, hwid in serial.tools.list_ports.comports():
            self.ID_COMPORT_LIST.Append((port, desc, hwid))
        self.wxID_OK.Enable(False)

    def OnButton_wxID_CANCEL(self, evt):
        # type: (wx.CommandEvent) -> None
        self.EndModal(evt.Id)

    def OnButton_wxID_OK(self, evt):
        # type: (wx.CommandEvent) -> None
        sel = self.ID_COMPORT_LIST.GetFirstSelected()
        if (sel != -1):
            self.port = self.ID_COMPORT_LIST.GetItemText(sel) # type: str
            self.EndModal(evt.Id)

    def OnList_item_deselected_ID_COMPORT_LIST(self, evt):
        # type: (wx.ListEvent) -> None
        self.wxID_OK.Enable(False)

    def OnList_item_selected_ID_COMPORT_LIST(self, evt):
        # type: (wx.ListEvent) -> None
        self.wxID_OK.Enable(True)

    def OnList_item_activated_ID_COMPORT_LIST(self, evt):
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
        axes = self.figure.add_subplot(111)
        self.line = Line2D(self.reader.t, self.reader.d)
        axes.add_line(self.line)
        axes.set_ylim(-.1, 5.1)
        axes.set_xlim(-config.ReadFloat("graph_seconds", GRAPH_SECONDS), 0)

        axes.set_xlabel('t')
        axes.set_ylabel('V')
        self.figure_canvas = FigureCanvas(self, wx.ID_ANY, self.figure)
        rdgui_xrc.get_resources().AttachUnknownControl("ID_FIGURE", self.figure_canvas, self)

        # Note that event is a MplEvent
        self.figure_canvas.mpl_connect(
            'motion_notify_event', self.UpdateStatusBar)

        self.Fit()
        self.MinSize = self.Size
        self.reader.start()
        self.ani = animation.FuncAnimation(self.figure, self.update,
                interval=int(config.ReadFloat("polling_interval", POLLING_INTERVAL)*1000), blit=True)

    def UpdateStatusBar(self, event):
        if event.inaxes:
            self.SetStatusText(
                "t={}  V={}".format(event.xdata, event.ydata))
        else:
            self.SetStatusText("")

    def update(self, d):
        with self.reader.datalock:
            self.line.set_data(self.reader.t - time(), np.asarray(self.reader.d))
        return self.line,

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
        wx.Config.Set(wx.Config("RDGUI"))

        frame = CanvasFrame()
        self.SetTopWindow(frame)
        frame.Show(True)
        return True


if __name__ == '__main__':
    app = App()
    app.MainLoop()
