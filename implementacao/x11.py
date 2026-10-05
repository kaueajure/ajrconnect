"""Typed X11 control protocol. No synthesized keys or window-manager toggles."""
import ctypes as C
import ctypes.util

Window = C.c_ulong
ERROR_HANDLER_TYPE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)
ERROR_HANDLER = ERROR_HANDLER_TYPE(lambda _display, _event: 0)


class MessageData(C.Union):
    _fields_ = [('b', C.c_char * 20), ('s', C.c_short * 10), ('l', C.c_long * 5)]


class ClientMessage(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
                ('display', C.c_void_p), ('window', Window), ('message_type', C.c_ulong),
                ('format', C.c_int), ('data', MessageData)]


class XEvent(C.Union):
    _fields_ = [('message', ClientMessage), ('pad', C.c_long * 24)]


class X11:
    def __init__(self):
        self.lib = C.CDLL(ctypes.util.find_library('X11'))
        signatures = {
            'XOpenDisplay': (C.c_void_p, [C.c_char_p]),
            'XCloseDisplay': (C.c_int, [C.c_void_p]),
            'XDefaultRootWindow': (Window, [C.c_void_p]),
            'XInternAtom': (C.c_ulong, [C.c_void_p, C.c_char_p, C.c_int]),
            'XGetWindowProperty': (C.c_int, [C.c_void_p, Window, C.c_ulong,
                C.c_long, C.c_long, C.c_int, C.c_ulong, C.POINTER(C.c_ulong),
                C.POINTER(C.c_int), C.POINTER(C.c_ulong), C.POINTER(C.c_ulong),
                C.POINTER(C.POINTER(C.c_ubyte))]),
            'XSendEvent': (C.c_int, [C.c_void_p, Window, C.c_int, C.c_long, C.POINTER(XEvent)]),
            'XFlush': (C.c_int, [C.c_void_p]),
            'XFree': (C.c_int, [C.c_void_p]),
            'XGetGeometry': (C.c_int, [C.c_void_p, Window, C.POINTER(Window),
                C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_uint),
                C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint)]),
            'XTranslateCoordinates': (C.c_int, [C.c_void_p, Window, Window,
                C.c_int, C.c_int, C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(Window)]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(self.lib, name)
            fn.restype, fn.argtypes = result, args
        # A disappearing window must return an error, never terminate the GUI.
        self.lib.XSetErrorHandler.argtypes = [ERROR_HANDLER_TYPE]
        self.lib.XSetErrorHandler(ERROR_HANDLER)
        self.display = self.lib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError('Não foi possível acessar o XWayland.')

    def close(self):
        if self.display:
            self.lib.XCloseDisplay(self.display)
            self.display = None

    def atom(self, name):
        return self.lib.XInternAtom(self.display, name.encode(), False)

    def property(self, window, name, delete=False):
        actual = C.c_ulong()
        fmt = C.c_int()
        count, remaining = C.c_ulong(), C.c_ulong()
        data = C.POINTER(C.c_ubyte)()
        result = self.lib.XGetWindowProperty(self.display, window, self.atom(name),
            0, 4096, delete, 0, C.byref(actual), C.byref(fmt), C.byref(count),
            C.byref(remaining), C.byref(data))
        if result or not data:
            return None
        try:
            if fmt.value == 32:
                return list(C.cast(data, C.POINTER(C.c_ulong))[:count.value])
            if fmt.value == 8:
                return C.string_at(data, count.value)
            return None
        finally:
            self.lib.XFree(data)

    def find_window(self, pid):
        root = self.lib.XDefaultRootWindow(self.display)
        for window in self.property(root, '_NET_CLIENT_LIST') or []:
            if self.property(window, '_NET_WM_PID') == [pid] and \
                    self.property(window, '_AJR_CONTROL_VERSION') == [1]:
                return window
        return None

    def control(self, pid, token, command):
        window = self.find_window(pid)
        if window is None:
            raise RuntimeError('A janela da sessão ainda não está disponível.')
        event = XEvent()
        msg = event.message
        msg.type, msg.send_event = 33, True
        msg.display, msg.window = self.display, window
        msg.message_type, msg.format = self.atom('_AJR_CONTROL_V1'), 32
        msg.data.l[0], msg.data.l[1] = command, int(token, 16)
        if not self.lib.XSendEvent(self.display, window, False, 0, C.byref(event)):
            raise RuntimeError('Não foi possível enviar o comando à sessão.')
        self.lib.XFlush(self.display)

    def state(self, pid):
        window = self.find_window(pid)
        return self.property(window, '_AJR_STATE_V1') if window else None

    def geometry(self, pid):
        window = self.find_window(pid)
        if not window:
            return None
        root, child = Window(), Window()
        x, y, rx, ry = C.c_int(), C.c_int(), C.c_int(), C.c_int()
        w, h, border, depth = C.c_uint(), C.c_uint(), C.c_uint(), C.c_uint()
        if not self.lib.XGetGeometry(self.display, window, C.byref(root),
            C.byref(x), C.byref(y), C.byref(w), C.byref(h), C.byref(border), C.byref(depth)):
            return None
        self.lib.XTranslateCoordinates(self.display, window, root, 0, 0,
                                       C.byref(rx), C.byref(ry), C.byref(child))
        return rx.value, ry.value, w.value, h.value
