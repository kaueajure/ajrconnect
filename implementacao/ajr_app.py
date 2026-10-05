#!/usr/bin/env python3
"""AJR Connect: profile and session controller for the desktop workspace."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk
from pathlib import Path
import copy
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from core import (DATA_DIR, NATIVE, RUNTIME_DIR, atomic_json, build_command,
                  DEFAULT, PROFILE_KEYS, detect_monitors, host_port, load_cfg,
                  resolve_monitor, save_cfg, select_profile, store_profile)
from x11 import X11
from integration import installed_revision
from dialogs import ShareEditor, ShortcutEditor, shortcut_parts, unique_name
from ui import DesktopView

APP_ID = 'com.ajure.AJRConnect'
EXTENSION_ID = 'ajr-connect@ajure.local'
LOCAL_BUS = 'org.gnome.Shell'
LOCAL_PATH = '/com/ajure/AJRConnect'
LOCAL_INTERFACE = 'com.ajure.AJRConnect.Keyboard'


def secret(server, user, operation, password=None):
    if not shutil.which('secret-tool'):
        return ''
    cmd = ['secret-tool', operation]
    if operation == 'store':
        cmd.append('--label=AJR Connect')
    cmd += ['app', 'ajr-connect', 'server', server, 'user', user]
    try:
        result = subprocess.run(cmd, input=password, text=True, capture_output=True, timeout=5)
        return result.stdout.removesuffix('\n') if operation == 'lookup' and result.returncode == 0 \
            else result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return ''


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='AJR Connect')
        self.cfg = load_cfg()
        try:
            shortcut_parts(self.cfg['fullscreen_shortcut'])
        except ValueError:
            self.cfg['fullscreen_shortcut'] = DEFAULT['fullscreen_shortcut']
        self._profiles_updating = False
        self._password_generation = 0
        self._integration_ready = False
        self.proc, self.session, self.x11 = None, None, None
        self._status_generation = 0
        self._status_source = 0
        self._closing = False
        self._started = False
        self.set_default_size(1120, 820)
        self.set_size_request(620, 480)
        self.connect('close-request', self.close_requested)
        self.ui = DesktopView(self)
        self.refresh_monitors()
        self.render_shares()
        self.refresh_profiles()
        self.profile.connect('notify::selected', self.profile_changed)
        self.set_shortcut(self.cfg['fullscreen_shortcut'], persist=False)
        self.lookup_password()
        self.update_keyboard_options()
        self.schedule_status()
        self.ui.update_summary()
        self._poll = GLib.timeout_add(250, self.poll_session)
        def integration_status():
            try:
                ready = Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync(
                    LOCAL_BUS, LOCAL_PATH, LOCAL_INTERFACE, 'Ping', None,
                    GLib.VariantType.new('(b)'), Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
                message = 'AJR Bar indisponível. Use os controles do aplicativo ou o atalho configurado.'
            except GLib.Error:
                ready, message = False, 'AJR Bar indisponível. Use os controles do aplicativo ou o atalho de tela cheia configurado.'
                try:
                    result = Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync(
                        'org.gnome.Shell', '/org/gnome/Shell', 'org.gnome.Shell.Extensions',
                        'GetExtensionInfo', GLib.Variant('(s)', (EXTENSION_ID,)), None,
                        Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
                    if result and result.get('version', 0) < 8 and installed_revision():
                        message = 'Aplicativo atualizado. A nova integração precisa de um único novo login; depois, a barra poderá ser atualizada nesta sessão.'
                    elif result:
                        message = 'A AJR Bar está desativada. Ative AJR Connect no aplicativo Extensões.'
                except GLib.Error:
                    pass
            def done():
                if self._closing:
                    return
                self._integration_ready = ready
                self.integration_banner.set_title(message)
                self.integration_banner.set_revealed(not ready and 'único novo login' in message)
                self.ui.integration_changed(ready)
                self.update_keyboard_options()
            GLib.idle_add(done)
        threading.Thread(target=integration_status, daemon=True).start()

    def refresh_monitors(self):
        try:
            self.monitors = detect_monitors()
        except (OSError, subprocess.TimeoutExpired):
            self.monitors = []
        selected = resolve_monitor(self.cfg, self.monitors)
        labels = [f"{m['connector']} · {m['width']} × {m['height']}" +
                  (' · Principal' if m['primary'] else '') for m in self.monitors]
        self.monitor.set_model(Gtk.StringList.new(labels or ['Nenhum monitor disponível']))
        self.monitor.set_selected(self.monitors.index(selected) if selected else 0)
        if self.cfg.get('monitor_connector') and selected is None:
            self.show_error('O monitor salvo foi desconectado. Selecione outra tela antes de conectar.')
        if hasattr(self, 'ui'):
            self.ui.update_summary()

    def persist(self):
        self.cfg.update(server=self.server.get_text().strip(), user=self.user.get_text().strip(),
            quality=int(self.quality.get_selected()), fullscreen=self.fullscreen.get_active(),
            keyboard_mode=('fullscreen', 'always', 'local')[self.keyboard_mode.get_selected()],
            capture_keyboard=self.keyboard_mode.get_selected() != 2, clipboard=self.clipboard.get_active(),
            remember=self.remember.get_active())
        self.cfg.update({key: row.get_active() for key, row in self.keyboard_rows.items()})
        i = int(self.monitor.get_selected())
        if 0 <= i < len(self.monitors):
            self.cfg.update(monitor=self.monitors[i]['id'], monitor_connector=self.monitors[i]['connector'])
        if self.cfg['active_profile']:
            store_profile(self.cfg, self.profile_name.get_text())
        save_cfg(self.cfg)
        self.ui.update_summary()

    def refresh_profiles(self):
        self._profiles_updating = True
        profiles = self.cfg['profiles']
        self.profile.set_model(Gtk.StringList.new([p['name'] for p in profiles] or ['Nenhuma conexão salva']))
        index = next((i for i, p in enumerate(profiles) if p['id'] == self.cfg['active_profile']), None)
        self.profile.set_sensitive(bool(profiles))
        self.profile_delete.set_sensitive(index is not None)
        self.profile.set_selected(index if index is not None else (Gtk.INVALID_LIST_POSITION if profiles else 0))
        self.profile_name.set_text(profiles[index]['name'] if index is not None else '')
        self._profiles_updating = False
        self.ui.render_profiles()

    def identity_changed(self, *_):
        self._password_generation += 1
        self.password.set_text('')

    def lookup_password(self):
        self._password_generation += 1
        generation = self._password_generation
        server, user = self.server.get_text().strip(), self.user.get_text().strip()
        if not self.remember.get_active():
            return
        def lookup():
            value = secret(server, user, 'lookup')
            def fill():
                if value and generation == self._password_generation and not self._closing \
                        and not self.password.get_text() and not self.proc \
                        and (self.server.get_text().strip(), self.user.get_text().strip()) == (server, user):
                    self.password.set_text(value)
            GLib.idle_add(fill)
        threading.Thread(target=lookup, daemon=True).start()

    def apply_profile(self, refresh_profiles=True):
        self.identity_changed()
        self.server.set_text(self.cfg['server'])
        self.user.set_text(self.cfg['user'])
        self.fullscreen.set_active(self.cfg['fullscreen'])
        self.clipboard.set_active(self.cfg['clipboard'])
        self.remember.set_active(self.cfg['remember'])
        self.quality.set_selected(self.cfg['quality'])
        self.keyboard_mode.set_selected(('fullscreen', 'always', 'local').index(self.cfg['keyboard_mode']))
        for key, row in self.keyboard_rows.items():
            row.set_active(self.cfg[key])
        try:
            self.set_shortcut(self.cfg['fullscreen_shortcut'], persist=False)
        except ValueError:
            self.set_shortcut(DEFAULT['fullscreen_shortcut'], persist=False)
        self.refresh_monitors()
        self.render_shares()
        if refresh_profiles:
            self.refresh_profiles()
        else:
            profile = next(p for p in self.cfg['profiles'] if p['id'] == self.cfg['active_profile'])
            self.profile_name.set_text(profile['name'])
            self.profile_delete.set_sensitive(True)
        self.ui.render_profiles()
        self.show_error('')
        self.lookup_password()
        self.schedule_status()

    def profile_changed(self, *_):
        if self._profiles_updating:
            return
        index = self.profile.get_selected()
        if index >= len(self.cfg['profiles']):
            return
        profile_id = self.cfg['profiles'][index]['id']
        if profile_id == self.cfg['active_profile']:
            return
        self.persist()
        select_profile(self.cfg, profile_id)
        save_cfg(self.cfg)
        # Keep the selector model stable while handling notify::selected.
        self.apply_profile(refresh_profiles=False)

    def save_profile(self, *_):
        self.show_error('')
        self.persist()
        if not self.cfg['server'] or not self.cfg['user']:
            self.show_error('Preencha servidor e usuário antes de salvar a conexão.')
            return
        store_profile(self.cfg, self.profile_name.get_text())
        save_cfg(self.cfg)
        self.refresh_profiles()
        cfg, password = copy.deepcopy(self.cfg), self.password.get_text()
        def save_password():
            if cfg['remember'] and password:
                if not secret(cfg['server'], cfg['user'], 'store', password):
                    GLib.idle_add(lambda: self.toast.add_toast(Adw.Toast(title='Conexão salva. Não foi possível salvar a senha no chaveiro.')))
            elif not cfg['remember']:
                secret(cfg['server'], cfg['user'], 'clear')
        threading.Thread(target=save_password, daemon=True).start()
        self.toast.add_toast(Adw.Toast(title='Conexão salva.'))

    def new_profile(self, *_):
        self.persist()
        self.cfg.update(copy.deepcopy({key: DEFAULT[key] for key in PROFILE_KEYS}))
        self.cfg['active_profile'] = ''
        save_cfg(self.cfg)
        self.apply_profile()
        self.ui.show_page('connection')
        if self.ui.split.get_collapsed():
            self.ui.split.set_show_sidebar(False)
        self.profile_name.grab_focus()

    def delete_profile(self, *_):
        profile = next((p for p in self.cfg['profiles'] if p['id'] == self.cfg['active_profile']), None)
        if profile is None:
            self.show_error('Selecione uma conexão salva para excluir.')
            return
        dialog = Adw.MessageDialog(transient_for=self, modal=True,
            heading='Excluir conexão?', body=f'A conexão “{profile["name"]}” será removida deste aplicativo.')
        dialog.add_response('cancel', 'Cancelar')
        dialog.add_response('delete', 'Excluir')
        dialog.set_response_appearance('delete', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        def response(_dialog, result):
            if result != 'delete':
                return
            self.cfg['profiles'] = [p for p in self.cfg['profiles'] if p['id'] != profile['id']]
            # Keyring entries belong to server/user pairs and can be shared by profiles.
            if not any((p['server'], p['user']) == (profile['server'], profile['user'])
                       for p in self.cfg['profiles']):
                threading.Thread(target=secret,
                    args=(profile['server'], profile['user'], 'clear'), daemon=True).start()
            self.cfg['active_profile'] = ''
            if self.cfg['profiles']:
                select_profile(self.cfg, self.cfg['profiles'][0]['id'])
            else:
                self.cfg.update(copy.deepcopy({key: DEFAULT[key] for key in PROFILE_KEYS}))
            save_cfg(self.cfg)
            self.apply_profile()
        dialog.connect('response', response)
        dialog.present()

    def set_shortcut(self, value, persist=True):
        key, modifiers = shortcut_parts(value)
        self.cfg['fullscreen_shortcut'] = Gtk.accelerator_name(key, modifiers)
        self.shortcut.set_subtitle(Gtk.accelerator_get_label(key, modifiers))
        if persist:
            self.persist()

    def update_keyboard_options(self):
        active = self.keyboard_mode.get_selected() != 2
        for row in self.keyboard_rows.values():
            row.set_sensitive(active)
        self.keyboard_note.set_subtitle(
            'Prioridade individual disponível com a AJR Bar atualizada e ativa. As demais combinações seguem a captura do teclado.'
            if self._integration_ready else
            'Para misturar atalhos locais e remotos, ative a AJR Bar atualizada no GNOME. Sem ela, escolha todos no Windows ou todos locais.')

    def render_shares(self):
        while (child := self.share_list.get_first_child()) is not None:
            self.share_list.remove(child)
        if not self.cfg['shares']:
            self.share_list.append(self.ui.empty_shares())
        for i, share in enumerate(self.cfg['shares']):
            row = Adw.ActionRow(title=share['name'], subtitle=share['path'], subtitle_lines=1)
            row.add_prefix(Gtk.Image(icon_name='folder-symbolic'))
            for icon, tooltip, callback in [
                ('document-edit-symbolic', 'Editar pasta', lambda _b, index=i: self.edit_share(index)),
                ('user-trash-symbolic', 'Remover pasta', lambda _b, index=i: self.remove_share(index))]:
                button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
                button.add_css_class('flat')
                button.connect('clicked', callback)
                row.add_suffix(button)
            self.share_list.append(row)
        if hasattr(self, 'ui'):
            self.ui.update_summary()

    def edit_share(self, index=None):
        original = self.cfg['shares'][index] if index is not None else {}
        def saved(share):
            others = [s for i, s in enumerate(self.cfg['shares']) if i != index]
            share['name'] = unique_name(share['name'], others)
            if index is None:
                self.cfg['shares'].append(share)
            else:
                self.cfg['shares'][index] = share
            self.persist()
            self.render_shares()
        ShareEditor(self, original, saved).present()

    def remove_share(self, index):
        self.cfg['shares'].pop(index)
        self.persist()
        self.render_shares()

    def show_error(self, text):
        self.error.set_text(text)
        self.error.set_visible(bool(text))
        if text:
            self.error.grab_focus()

    def set_status(self, title, subtitle, icon='network-server-symbolic'):
        self.status.set_title(title)
        self.status.set_subtitle(subtitle)
        self.status_icon.set_from_icon_name(icon)
        self.ui.update_status(title, icon)

    def schedule_status(self):
        self._status_generation += 1
        generation = self._status_generation
        if self._status_source:
            GLib.source_remove(self._status_source)
            self._status_source = 0
        server = self.server.get_text().strip()
        if hasattr(self, 'ui'):
            self.ui.update_summary()
        if not server:
            if not self.proc:
                self.set_status('Configure sua conexão', 'Informe o servidor para começar.')
            return
        if not self.proc:
            self.set_status('Verificando servidor', server)
        def check():
            try:
                with socket.create_connection(host_port(server), timeout=1):
                    pass
                online = True
            except (OSError, ValueError):
                online = False
            def done():
                if not self._closing and generation == self._status_generation and not self.proc:
                    self.set_status('Servidor disponível' if online else 'Servidor indisponível',
                        server if online else 'Confira o endereço e se o Windows está ligado.',
                        'network-transmit-receive-symbolic' if online else 'network-offline-symbolic')
            GLib.idle_add(done)
        def start_check():
            self._status_source = 0
            if not self._closing and generation == self._status_generation:
                threading.Thread(target=check, daemon=True).start()
            return GLib.SOURCE_REMOVE
        self._status_source = GLib.timeout_add(250, start_check)

    def do_connect(self):
        if self.proc:
            self.control('disconnect')
            return
        if not self.connect_btn.get_sensitive():
            return
        self.show_error('')
        try:
            self.persist()
            host_port(self.cfg['server'])
            if not self.cfg['user'] or not self.password.get_text():
                raise ValueError('Preencha o usuário e a senha para conectar.')
            if not NATIVE.is_file():
                raise ValueError('O cliente AJR não está instalado. Execute o instalador do pacote.')
            if not self.monitors:
                raise ValueError('Nenhum monitor disponível. Atualize a lista de telas.')
            monitor = resolve_monitor(self.cfg, detect_monitors())
            if monitor is None:
                raise ValueError('O monitor selecionado foi desconectado. Atualize a lista de telas.')
            for share in self.cfg['shares']:
                if not Path(share['path']).expanduser().is_dir():
                    raise ValueError(f"A pasta {share['name']} não existe: {share['path']}")
            command = build_command(self.cfg, monitor)
            shortcut_key, shortcut_mods = shortcut_parts(self.cfg['fullscreen_shortcut'])
            if self.cfg['keyboard_mode'] != 'local' and not all(
                    self.cfg[key] for key in self.keyboard_rows):
                try:
                    ready = Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync(
                        LOCAL_BUS, LOCAL_PATH, LOCAL_INTERFACE, 'Ping', None,
                        GLib.VariantType.new('(b)'), Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
                except GLib.Error:
                    ready = False
                if not ready:
                    raise ValueError('Ative a AJR Bar atualizada para usar prioridades individuais de teclado.')
        except (ValueError, OSError, subprocess.TimeoutExpired, GLib.Error) as exc:
            self.show_error(str(exc))
            return
        password = self.password.get_text()
        self.connect_btn.set_sensitive(False)
        self.form.set_sensitive(False)
        self.connect_btn.set_label('Conectando…')
        self.set_status('Conectando ao Windows', self.cfg['server'])
        # Run network/keyring work off the GTK thread.
        cfg = dict(self.cfg)
        def launch():
            try:
                with socket.create_connection(host_port(cfg['server']), timeout=3):
                    pass
                if cfg['remember']:
                    if not secret(cfg['server'], cfg['user'], 'store', password):
                        GLib.idle_add(lambda: self.toast.add_toast(Adw.Toast(title='Não foi possível salvar a senha no chaveiro.')))
                else:
                    secret(cfg['server'], cfg['user'], 'clear')
                token = secrets.token_hex(4)
                env = dict(os.environ, AJR_CONTROL_TOKEN=token,
                           AJR_MONITOR_CONNECTOR=monitor['connector'],
                           AJR_KEYBOARD_MODE=cfg['keyboard_mode'],
                           AJR_FULLSCREEN_KEY=str(shortcut_key),
                           AJR_FULLSCREEN_MODS=str(int(shortcut_mods) & 13 |
                               (64 if shortcut_mods & Gdk.ModifierType.SUPER_MASK else 0)),
                           AJR_REMOTE_KEYS=str(sum(bit for key, bit in
                               [('remote_alt_tab', 1), ('remote_super', 2), ('remote_alt_f4', 4)] if cfg[key])))
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                log_path = DATA_DIR / f"session-{time.strftime('%Y%m%d-%H%M%S')}-{token}.log"
                with log_path.open('w') as log:
                    os.chmod(log_path, 0o600)
                    log.write('AJR Connect 6 · perfil conservador\n' +
                              json.dumps(command, ensure_ascii=False) + '\n')
                    log.flush()
                    proc = subprocess.Popen(command, stdin=subprocess.PIPE,
                        stdout=log, stderr=subprocess.STDOUT, text=True, env=env)
                session = dict(pid=proc.pid, token=token, connector=monitor['connector'],
                               log=str(log_path), start_fullscreen=cfg['fullscreen'])
                atomic_json(RUNTIME_DIR / f'session-{proc.pid}.json', session)
                proc.stdin.write(password + '\n')
                proc.stdin.close()
                GLib.idle_add(self.launched, proc, session)
            except Exception as exc:
                if 'proc' in locals() and proc.poll() is None:
                    proc.terminate()
                if 'proc' in locals():
                    (RUNTIME_DIR / f'session-{proc.pid}.json').unlink(missing_ok=True)
                GLib.idle_add(self.launch_failed, str(exc))
        threading.Thread(target=launch, daemon=True).start()

    def launched(self, proc, session):
        self.proc, self.session = proc, session
        self._started = False
        self._launch_time = time.monotonic()
        try:
            self.x11 = X11()
        except RuntimeError as exc:
            proc.terminate()
            proc.wait(timeout=5)
            (RUNTIME_DIR / f'session-{proc.pid}.json').unlink(missing_ok=True)
            self.proc, self.session = None, None
            self.launch_failed(str(exc))
            return
        if not self.cfg['remember']:
            self.password.set_text('')
        self.controls.set_visible(True)
        self.connect_btn.set_sensitive(True)
        self.connect_btn.set_label('Cancelar conexão')

    def launch_failed(self, message):
        self.form.set_sensitive(True)
        self.connect_btn.set_sensitive(True)
        self.connect_btn.set_label('Conectar ao Windows')
        self.show_error('Não foi possível conectar. ' + message)
        self.schedule_status()

    def control(self, command):
        if not self.proc:
            return
        if not self._started and command == 'disconnect':
            self.proc.terminate()
            return
        try:
            self.x11.control(self.proc.pid, self.session['token'],
                {'fullscreen': 1, 'restore': 2, 'minimize': 3, 'disconnect': 4}[command])
        except RuntimeError as exc:
            self.show_error(str(exc))

    def poll_session(self):
        if not self.proc:
            return GLib.SOURCE_CONTINUE
        code = self.proc.poll()
        if code is not None:
            started, session = self._started, self.session
            (RUNTIME_DIR / f'session-{self.proc.pid}.json').unlink(missing_ok=True)
            self.x11.close()
            self.proc, self.session, self.x11 = None, None, None
            self._started = False
            self.controls.set_visible(False)
            self.form.set_sensitive(True)
            self.connect_btn.set_label('Conectar ao Windows')
            self.connect_btn.add_css_class('suggested-action')
            self.set_status('Sessão encerrada', 'Você pode conectar novamente.')
            if not started or code not in (0, 11, 131):
                self.show_error(f"A conexão terminou (código {code}). Abra os registros para verificar o motivo.")
            self.present()
            return GLib.SOURCE_CONTINUE
        state = self.x11.state(self.proc.pid)
        self.dispatch_local_shortcuts()
        if state and not self._started:
            self._started = True
            self.connect_btn.set_label('Desconectar')
            self.connect_btn.remove_css_class('suggested-action')
            if self.session['start_fullscreen']:
                self.control('fullscreen')
        if state:
            self.set_status('Conectado · ' + ('Tela cheia' if state[1] else 'Modo janela'),
                f"{self.cfg['user']} em {self.cfg['server']} · {self.session['connector']}",
                'network-transmit-receive-symbolic')
        elif time.monotonic() - self._launch_time > 10:
            self.set_status('Aguardando a sessão', 'A autenticação está em andamento. Você pode cancelar.')
        return GLib.SOURCE_CONTINUE

    def dispatch_local_shortcuts(self):
        window = self.x11.find_window(self.proc.pid)
        if not window:
            return
        requests = self.x11.property(window, '_AJR_LOCAL_KEYS_V1', delete=True) or []
        if len(requests) % 2:
            return
        for action, reverse in zip(requests[::2], requests[1::2]):
            pid, token = self.proc.pid, self.session['token']
            def done(connection, result, pid=pid, token=token):
                try:
                    accepted = connection.call_finish(result).unpack()[0]
                    if not accepted:
                        raise RuntimeError('A integração local recusou o atalho.')
                except (GLib.Error, RuntimeError) as exc:
                    self.toast.add_toast(Adw.Toast(title='Não foi possível executar o atalho local: ' + str(exc)))
                finally:
                    if self.proc and self.proc.pid == pid:
                        self.x11.control(pid, token, 6)
            try:
                Gio.bus_get_sync(Gio.BusType.SESSION, None).call(
                    LOCAL_BUS, LOCAL_PATH, LOCAL_INTERFACE, 'LocalShortcut',
                    GLib.Variant('(usub)', (pid, token, action, bool(reverse))),
                    GLib.VariantType.new('(b)'), Gio.DBusCallFlags.NONE, 1500, None, done)
            except GLib.Error as exc:
                self.toast.add_toast(Adw.Toast(title='Integração de teclado indisponível: ' + exc.message))
                self.x11.control(pid, token, 6)

    def open_logs(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = Path(self.session['log']) if self.session else DATA_DIR
        Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)

    def close_requested(self, *_):
        # Keep the session and its controller available; closing the GUI hides it.
        if self.proc or not self.form.get_sensitive():
            self.set_visible(False)
            return True
        self.persist()
        self._closing = True
        if self._status_source:
            GLib.source_remove(self._status_source)
            self._status_source = 0
        GLib.source_remove(self._poll)
        return False


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        win = next(iter(self.get_windows()), None) or MainWindow(self)
        win.present()


if __name__ == '__main__':
    raise SystemExit(App().run())
