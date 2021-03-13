#!/usr/bin/env python
# vim: set fileencoding=utf-8 :

from __future__ import print_function

import itertools
import numpy as np
from numpy_ringbuffer import RingBuffer
import threading
import types
import wx


def appendlistitem(listctrl, *args):
    # type: (wx.ListCtrl, str) -> int
    pos = listctrl.GetItemCount()
    for i, text in zip(itertools.count(), args):
        li = wx.ListItem()
        li.Id = pos
        li.Column = i
        li.Text = text
        if i == 0:
            pos = listctrl.InsertItem(li)
        else:
            listctrl.SetItem(li)
    return pos

def emitter(p=0.1):
    """Return a random value in [0, 1) with probability p, else 0."""
    while True:
        v = np.random.rand(1)
        if v > p:
            yield 0.
        else:
            yield np.random.rand(1)

def ringbuffer_resize(ringbuffer, newcapacity):
    # type: (RingBuffer, int) -> RingBuffer
    newbuffer = RingBuffer(newcapacity, dtype=ringbuffer.dtype)
    n = min(newcapacity, len(ringbuffer))
    newbuffer._arr[0:n] = ringbuffer[-n:]
    newbuffer._right_index = n
    newbuffer._left_index = 0
    return newbuffer


class AttributeSetterCtx(object):
    def __init__(self, obj, attr, value):
        # type: (object, str, object) -> None
        super(AttributeSetterCtx, self).__init__()
        self.obj = obj
        self.attr = attr
        self.value = value

    def __enter__(self):
        # type () -> object
        self.old = getattr(self.obj, self.attr)
        setattr(self.obj, self.attr, self.value)
        return self.obj

    def __exit__(self, exc_type, exc_val, exc_tb):
        # type: (type, BaseException, types.TracebackType) -> bool
        setattr(self.obj, self.attr, self.old)
        return False


class UnlockerCtx(object):
    def __init__(self, lock):
        # type: (threading.Lock) -> None
        super(UnlockerCtx, self).__init__()
        self.lock = lock

    def __enter__(self):
        # type: () -> object
        self.lock.release()
        return self.lock

    def __exit__(self, exc_type, exc_val, exc_tb):
        # type: (type, BaseException, types.TracebackType) -> bool
        self.lock.acquire()
        return False
