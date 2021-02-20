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


def emitter(p=0.1):
    """Return a random value in [0, 1) with probability p, else 0."""
    while True:
        v = np.random.rand(1)
        if v > p:
            yield 0.
        else:
            yield np.random.rand(1)

class ReaderThread(threading.Thread):
    def __init__(self):
        super(ReaderThread, self).__init__(daemon=True)
        self.running = True
        self.datalock = threading.Lock()
        self.shutdowncond = threading.Condition(self.datalock)
        self.t = RingBuffer(200, float)
        self.d = RingBuffer(200, float)

    def cancel(self):
        with self.datalock:
            self.running = False
            self.shutdowncond.notify()

    def run(self):
        gen = emitter()
        with self.datalock:
            while self.running:
                t = time()
                self.t.append(t)
                self.d.append(next(gen))
                self.shutdowncond.wait(max((t + 0.05) - time(), 0))

class CanvasFrame(rdgui_xrc.xrcCanvasFrame):
    def __init__(self, parent=None):
        super(CanvasFrame, self).__init__(parent)

        self.reader = ReaderThread()

        self.figure = Figure()
        axes = self.figure.add_subplot(111)
        self.line = Line2D(self.reader.t, self.reader.d)
        axes.add_line(self.line)
        axes.set_ylim(-.1, 1.1)
        axes.set_xlim(-10, 0)

        axes.set_xlabel('t')
        axes.set_ylabel('V')
        self.figure_canvas = FigureCanvas(self, wx.ID_ANY, self.figure)
        rdgui_xrc.get_resources().AttachUnknownControl("ID_FIGURE", self.figure_canvas, self)

        # Note that event is a MplEvent
        self.figure_canvas.mpl_connect(
            'motion_notify_event', self.UpdateStatusBar)

        self.Fit()
        self.reader.start()

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

    def OnMenu_wxID_EXIT(self, evt):
        self.Close()

    def OnClose(self, evt):
        self.reader.cancel()
        self.reader.join()
        evt.Skip()

class App(wx.App):
    def OnInit(self):
        """Create the main window and insert the custom frame."""
        frame = CanvasFrame()
        self.SetTopWindow(frame)
        # pass a generator in "emitter" to produce data for the update func
        self.ani = animation.FuncAnimation(frame.figure, frame.update,
                interval=50, blit=True)

        frame.Show(True)
        return True


if __name__ == '__main__':
    app = App()
    app.MainLoop()
