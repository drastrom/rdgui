import wx
import wx.xrc as xrc
import wx.lib.agw.floatspin as floatspin

class FloatSpinCtrlXmlHandler(xrc.XmlResourceHandler):
    def __init__(self):
        super(FloatSpinCtrlXmlHandler, self).__init__()
        # Standard styles
        self.AddWindowStyles()
        # Custom styles
        self.AddStyle('wxFS_LEFT', floatspin.FS_LEFT)
        self.AddStyle('wxFS_RIGHT', floatspin.FS_RIGHT)
        self.AddStyle('wxFS_CENTRE', floatspin.FS_CENTRE)
        self.AddStyle('wxFS_READONLY', floatspin.FS_READONLY)

    def CanHandle(self,node):
        return self.IsOfClass(node, 'FloatSpinCtrl')

    # Process XML parameters and create the object
    def DoCreateResource(self):
        assert self.GetInstance() is None

        if self.HasParam("min"):
            min_val = self.GetFloat("min")
        else:
            min_val = None

        if self.HasParam("max"):
            max_val = self.GetFloat("max")
        else:
            max_val = None

        w = floatspin.FloatSpin(self.GetParentAsWindow(),
                                 self.GetID(),
                                 self.GetPosition(),
                                 self.GetSize(),
                                 self.GetStyle(),
                                 self.GetFloat("value", 0),
                                 min_val,
                                 max_val,
                                 self.GetFloat('inc', 1),
                                 self.GetLong('digits', -1),
                                 self.GetStyle(),
                                 self.GetName())

        if self.HasParam('font'):
            w.SetFont(self.GetFont())
        if self.HasParam('format'):
            w.SetFormat(self.GetText('format'))
        if self.HasParam('snap_to_ticks'):
            w.SetSnapToTicks(self.GetBool('snap_to_ticks'))

        self.SetupWindow(w)
        return w