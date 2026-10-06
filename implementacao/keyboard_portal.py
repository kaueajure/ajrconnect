"""Local keyboard input through the desktop's consent-based portal.

No screen, pointer or clipboard access is requested. The restore token is kept
separate from profiles and is replaced after every successful authorization.
"""
import json
import uuid
from gi.repository import Gio, GLib
from core import DATA_DIR, atomic_json

BUS = 'org.freedesktop.portal.Desktop'
PATH = '/org/freedesktop/portal/desktop'
INTERFACE = 'org.freedesktop.portal.RemoteDesktop'


class KeyboardPortal:
    def __init__(self, changed, token_path=None):
        self.changed = changed
        self.token_path = token_path or DATA_DIR / 'keyboard-portal.json'
        self.bus = None
        self.session = ''
        self.ready = self.pending = False
        self._subscriptions = set()
        self._callbacks = []
        self._generation = 0
        self._closed_signal = 0
        self._timeout = 0

    def start(self, callback=None):
        if self.ready:
            if callback:
                callback(True, '')
            return
        if callback:
            self._callbacks.append(callback)
        if self.pending:
            return
        self.pending = True
        self._generation += 1
        self.changed(False, 'Aguardando autorização para os atalhos locais…')
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._timeout = GLib.timeout_add_seconds(120, self._expired)
            self._request('CreateSession', None, {'session_handle_token': GLib.Variant('s', 'ajr' + uuid.uuid4().hex)},
                          self._created)
        except GLib.Error as error:
            self._fail('Não foi possível acessar a autorização do sistema: ' + error.message)

    def _expired(self):
        self._timeout = 0
        self._fail('A autorização expirou. Clique em Autorizar para tentar novamente.')
        return GLib.SOURCE_REMOVE

    def _request(self, method, prefix, options, callback):
        generation = self._generation
        token = 'ajr' + uuid.uuid4().hex
        options = dict(options, handle_token=GLib.Variant('s', token))
        sender = self.bus.get_unique_name()[1:].replace('.', '_')
        request_path = '/org/freedesktop/portal/desktop/request/' + sender + '/' + token

        def response(bus, _sender, _path, _interface, _signal, parameters):
            bus.signal_unsubscribe(subscription)
            self._subscriptions.discard((subscription, request_path))
            if generation != self._generation:
                return
            code, results = parameters.unpack()
            if code:
                self._fail('Atalhos locais não autorizados. Clique em Autorizar para tentar novamente.')
            else:
                try:
                    callback(results)
                except (GLib.Error, KeyError, ValueError, OSError) as error:
                    self._fail('Não foi possível ativar os atalhos locais: ' + str(error))

        subscription = self.bus.signal_subscribe(BUS, 'org.freedesktop.portal.Request', 'Response', request_path,
            None, Gio.DBusSignalFlags.NONE, response)
        self._subscriptions.add((subscription, request_path))
        signature = '(a{sv})' if prefix is None else ('(osa{sv})' if method == 'Start' else '(oa{sv})')
        arguments = (options,) if prefix is None else (*prefix, options)

        def called(bus, result):
            try:
                returned_path = bus.call_finish(result).unpack()[0]
                if generation == self._generation and returned_path != request_path:
                    self._fail('O sistema retornou uma autorização incompatível.')
            except GLib.Error as error:
                if generation == self._generation:
                    self._fail('Portal de teclado indisponível: ' + error.message)
        self.bus.call(BUS, PATH, INTERFACE, method, GLib.Variant(signature, arguments),
                      GLib.VariantType.new('(o)'), Gio.DBusCallFlags.NONE, 10000, None, called)

    def _created(self, results):
        self.session = results['session_handle']
        self._closed_signal = self.bus.signal_subscribe(BUS, 'org.freedesktop.portal.Session', 'Closed', self.session,
            None, Gio.DBusSignalFlags.NONE, lambda *_: self._fail('Autorização de teclado encerrada. Clique em Autorizar.'))
        options = {'types': GLib.Variant('u', 1), 'persist_mode': GLib.Variant('u', 2)}
        try:
            token = json.loads(self.token_path.read_text())['restore_token']
            if isinstance(token, str) and token:
                options['restore_token'] = GLib.Variant('s', token)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self._request('SelectDevices', (self.session,), options, self._selected)

    def _selected(self, _results):
        # The portal owns the permission dialog; never approve it on behalf of
        # the user. No ScreenCast.SelectSources call is made.
        self._request('Start', (self.session, ''), {}, self._started)

    def _started(self, results):
        if not results.get('devices', 0) & 1:
            self._fail('O sistema não autorizou o teclado. Clique em Autorizar.')
            return
        token = results.get('restore_token')
        if isinstance(token, str) and token:
            atomic_json(self.token_path, {'restore_token': token})
        else:
            self.token_path.unlink(missing_ok=True)
        self.ready, self.pending = True, False
        if self._timeout:
            GLib.source_remove(self._timeout)
            self._timeout = 0
        self.changed(True, '')
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            callback(True, '')

    def send(self, keyval, modifiers, callback):
        """Replay after the native client has released its keyboard grab."""
        if not self.ready:
            callback(False, 'Autorize os atalhos locais primeiro.')
            return
        if not keyval or modifiers & ~77:
            callback(False, 'Combinação de teclado inválida.')
            return
        keys = [key for mask, key in ((4, 65507), (8, 65513), (1, 65505), (64, 65515))
                if modifiers & mask] + [keyval]
        bus, session = self.bus, self.session
        def worker():
            pressed = []
            error = ''
            try:
                # Always release already pressed keys, including on a denied
                # call/session closure. Never leave a modifier held in Linux.
                for key in keys:
                    if session != self.session or not self.ready:
                        raise GLib.Error.new_literal(Gio.io_error_quark(), 'Autorização de teclado encerrada.', 0)
                    bus.call_sync(BUS, PATH, INTERFACE, 'NotifyKeyboardKeysym',
                        GLib.Variant('(oa{sv}iu)', (session, {}, key, 1)), None,
                        Gio.DBusCallFlags.NONE, 1000, None)
                    pressed.append(key)
            except GLib.Error as exc:
                error = exc.message
            finally:
                for key in reversed(pressed):
                    try:
                        bus.call_sync(BUS, PATH, INTERFACE, 'NotifyKeyboardKeysym',
                            GLib.Variant('(oa{sv}iu)', (session, {}, key, 0)), None,
                            Gio.DBusCallFlags.NONE, 1000, None)
                    except GLib.Error as exc:
                        error = exc.message
                GLib.idle_add(lambda: callback(not error, error))
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _fail(self, message):
        self.close()
        self.changed(False, message)
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            callback(False, message)

    def close(self):
        self._generation += 1
        self.ready = self.pending = False
        if self._timeout:
            GLib.source_remove(self._timeout)
            self._timeout = 0
        if self.bus:
            for subscription, path in self._subscriptions:
                self.bus.signal_unsubscribe(subscription)
                self.bus.call(BUS, path, 'org.freedesktop.portal.Request', 'Close', None, None,
                              Gio.DBusCallFlags.NONE, 1000, None, None)
            self._subscriptions.clear()
            if self._closed_signal:
                self.bus.signal_unsubscribe(self._closed_signal)
                self._closed_signal = 0
            if self.session:
                self.bus.call(BUS, self.session, 'org.freedesktop.portal.Session', 'Close', None, None,
                              Gio.DBusCallFlags.NONE, 1000, None, None)
        self.session = ''
