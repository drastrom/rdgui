#!/usr/bin/env python

from time import time

from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
import matplotlib.animation as animation
import numpy as np
import wx

import rdgui_xrc
import submodpaths
submodpaths.add_to_path()

from numpy_ringbuffer import RingBuffer


class CanvasFrame(rdgui_xrc.xrcCanvasFrame):
    def __init__(self, parent=None):
        super(CanvasFrame, self).__init__(parent)

        self.figure = Figure()
        axes = self.figure.add_subplot(111)
        self.t = RingBuffer(175, float)
        self.d = RingBuffer(175, float)
        self.line = Line2D(self.t, self.d)
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

    def UpdateStatusBar(self, event):
        if event.inaxes:
            self.SetStatusText(
                "t={}  V={}".format(event.xdata, event.ydata))
        else:
            self.SetStatusText("")

    def update(self, d):
        t = time()
        self.t.append(t)
        self.d.append(d)
        self.line.set_data(self.t - t, self.d)
        return self.line,

    def OnMenu_wxID_EXIT(self, evt):
        self.Close()


def emitter(p=0.1):
    """Return a random value in [0, 1) with probability p, else 0."""
    while True:
        v = np.random.rand(1)
        if v > p:
            yield 0.
        else:
            yield np.random.rand(1)


class App(wx.App):
    def OnInit(self):
        """Create the main window and insert the custom frame."""
        frame = CanvasFrame()
        self.SetTopWindow(frame)
        # pass a generator in "emitter" to produce data for the update func
        self.ani = animation.FuncAnimation(frame.figure, frame.update, emitter,
                interval=50, blit=True)

        frame.Show(True)
        return True


if __name__ == '__main__':
    app = App()
    app.MainLoop()
