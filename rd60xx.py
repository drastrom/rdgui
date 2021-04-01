#!/usr/bin/env python
# vim: set fileencoding=utf-8 :

from __future__ import print_function

import struct
import sys
import threading
try:
    from typing import Callable
except:
    pass
from weakref import WeakSet

import minimalmodbus

from utils import AttributeSetterCtx

import submodpaths
submodpaths.add_to_path()
import rd6006


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
