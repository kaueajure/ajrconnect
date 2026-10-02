#!/usr/bin/env python3
"""AJR Connect: native GNOME connection manager and session controls."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk
from pathlib import Path
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from core import (APP_DIR, DATA_DIR, NATIVE, RUNTIME_DIR, atomic_json, build_command,
                  detect_monitors, host_port, load_cfg, resolve_monitor, save_cfg)
from x11 import X11

APP_ID = 'com.ajure.AJRConnect'
EXTENSION_ID = 'ajr-connect@ajure.local'


def normalize_share_name(value):
    return re.sub(r'[^A-Za-z0-9_-]+', '_', value.strip()).strip('_')[:24] or 'Pasta'


def unique_name(value, shares):
    base = normalize_share_name(value)
    used = {s['name'].lower() for s in shares}
    name, i = base, 2
    while name.lower() in used:
        name, i = f'{base}{i}', i + 1
    return name


def secret(server, user, operation, password=None):
    if not shutil.which('secret-tool'):
        return ''
    cmd = ['secret-tool', operation]
    if operation == 'store':
        cmd.append('--label=AJR Connect')
    cmd += ['app', 'ajr-connect', 'server', server, 'user', user]
    try:
        result = subprocess.run(cmd, input=password, text=True, capture_output=True, timeout=5)
        return result.stdout.strip() if operation == 'lookup' and result.returncode == 0 \
            else result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return ''


class ShareEditor(Adw.Window):
    def __init__(self, parent, share, on_save):
        super().__init__(transient_for=parent, modal=True, title='Pasta compartilhada')
        self.callback = on_save
        self.set_default_size(480, 280)
        view = Adw.ToolbarView()
        self.set_content(view)
        header = Adw.HeaderBar()
        view.add_top_bar(header)
        button = Gtk.Button(label='Salvar')
        button.add_css_class('suggested-action')
        button.connect('clicked', self.save)
        header.pack_end(button)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{side}')(24)
        view.set_content(box)
        group = Adw.PreferencesGroup(description='A pasta ficará disponível no Explorador do Windows.')
        box.append(group)
        self.name = Adw.EntryRow(title='Nome no Windows', text=share.get('name', ''))
        self.path = Adw.EntryRow(title='Pasta no Linux', text=share.get('path', ''))
        group.add(self.name)
        group.add(self.path)
        choose = Gtk.Button(icon_name='folder-open-symbolic', tooltip_text='Escolher pasta')
        choose.add_css_class('flat')
        choose.set_valign(Gtk.Align.CENTER)
        choose.connect('clicked', self.choose)
        self.path.add_suffix(choose)
        self.error = Gtk.Label(wrap=True, xalign=0)
        self.error.add_css_class('error')
        box.append(self.error)

    def choose(self, *_):
        chooser = Gtk.FileChooserNative.new('Escolher pasta', self,
            Gtk.FileChooserAction.SELECT_FOLDER, 'Selecionar', 'Cancelar')
        def response(dialog, result):
            if result == Gtk.ResponseType.ACCEPT:
                chosen = dialog.get_file()
                if chosen and chosen.get_path():
                    self.path.set_text(chosen.get_path())
                    if not self.name.get_text().strip():
                        self.name.set_text(normalize_share_name(Path(chosen.get_path()).name))
            dialog.destroy()
        chooser.connect('response', response)
        chooser.show()

    def save(self, *_):
        path = Path(self.path.get_text().strip()).expanduser()
        if not self.path.get_text().strip() or not path.is_dir():
            self.error.set_text('Escolha uma pasta existente no Linux.')
            self.path.grab_focus()
            return
        if ',' in str(path):
            self.error.set_text('O caminho da pasta não pode conter vírgulas.')
            return
        self.callback(dict(name=normalize_share_name(self.name.get_text()), path=str(path.resolve())))
        self.close()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='AJR Connect')
        self.cfg = load_cfg()
        self.cfg["capture_keyboard"] = True
        self.proc, self.session, self.x11 = None, None, None
        self._status_generation = 0
        self._closing = False
        self._started = False
        self.set_default_size(620, 780)
        self.set_size_request(420, 400)
        self.connect('close-request', self.close_requested)
        view = Adw.ToolbarView()
        self.set_content(view)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title='AJR Connect', subtitle='Seu Windows, no seu monitor'))
        view.add_top_bar(header)
        self.integration_banner = Adw.Banner(title='')
        view.add_top_bar(self.integration_banner)
        def integration_status():
            try:
                result = Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync('org.gnome.Shell', '/org/gnome/Shell',
                    'org.gnome.Shell.Extensions', 'GetExtensionInfo',
                    GLib.Variant('(s)', (EXTENSION_ID,)), None,
                    Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
                ready = result.get('version', 0) >= 6 and result.get('state') == 1
                message = ('Saia da sessão e entre novamente para ativar a nova AJR Bar.'
                           if result.get('version', 0) < 6 else
                           'A AJR Bar está desativada. Ative AJR Connect no aplicativo Extensões.')
            except GLib.Error:
                ready, message = False, 'Não foi possível verificar a AJR Bar no GNOME.'
            def done():
                self.integration_banner.set_title(message)
                self.integration_banner.set_revealed(not ready)
            GLib.idle_add(done)
        threading.Thread(target=integration_status, daemon=True).start()
        logs = Gtk.Button(icon_name='text-x-generic-symbolic', tooltip_text='Abrir registros da conexão')
        logs.add_css_class('flat')
        logs.connect('clicked', lambda *_: self.open_logs())
        header.pack_end(logs)
        self.toast = Adw.ToastOverlay()
        view.set_content(self.toast)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.toast.set_child(scroll)
        clamp = Adw.Clamp(maximum_size=640, tightening_threshold=480)
        scroll.set_child(clamp)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{side}')(24)
        clamp.set_child(box)
        brand = Gtk.Box(spacing=16)
        icon = Gtk.Image(icon_name='computer-symbolic', pixel_size=40)
        icon.add_css_class('accent')
        brand.append(icon)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label(label='Seu espaço de trabalho Windows', xalign=0, wrap=True)
        title.add_css_class('title-2')
        title_box.append(title)
        subtitle = Gtk.Label(label='Conecte à VM com suas pastas sempre à mão.', xalign=0, wrap=True)
        subtitle.add_css_class('dim-label')
        title_box.append(subtitle)
        brand.append(title_box)
        box.append(brand)
        self.status = Adw.ActionRow(title='Verificando conexão', subtitle=self.cfg['server'])
        self.status_icon = Gtk.Image(icon_name='network-server-symbolic')
        self.status.add_prefix(self.status_icon)
        status_group = Adw.PreferencesGroup()
        status_group.add(self.status)
        box.append(status_group)
        self.controls = Gtk.Box(spacing=8, homogeneous=True)
        for label, command in [('Tela cheia', 'fullscreen'), ('Modo janela', 'restore'),
                               ('Minimizar', 'minimize')]:
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda _b, cmd=command: self.control(cmd))
            self.controls.append(button)
        self.controls.set_visible(False)
        box.append(self.controls)
        self.form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.append(self.form)
        group = Adw.PreferencesGroup(title='Conexão')
        self.form.append(group)
        self.server = Adw.EntryRow(title='Servidor', text=str(self.cfg['server']))
        self.user = Adw.EntryRow(title='Usuário', text=str(self.cfg['user']))
        self.password = Adw.PasswordEntryRow(title='Senha')
        for row in (self.server, self.user, self.password):
            group.add(row)
        self.password.connect('entry-activated', lambda *_: self.do_connect())
        self.server.connect('changed', lambda *_: self.schedule_status())
        self.share_group = Adw.PreferencesGroup(title='Pastas no Windows',
            description='Disponíveis em Este Computador durante a conexão.')
        self.form.append(self.share_group)
        self.share_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.share_list.add_css_class('boxed-list')
        self.share_group.add(self.share_list)
        add = Gtk.Button(halign=Gtk.Align.START)
        add_content = Gtk.Box(spacing=6)
        add_content.append(Gtk.Image(icon_name='list-add-symbolic'))
        add_content.append(Gtk.Label(label='Adicionar pasta'))
        add.set_child(add_content)
        add.set_margin_top(12)
        add.connect('clicked', lambda *_: self.edit_share())
        self.share_group.add(add)
        self.render_shares()
        display = Adw.PreferencesGroup(title='Tela e teclado')
        self.form.append(display)
        self.monitor = Adw.ComboRow(title='Monitor', subtitle='A janela e a tela cheia usam esta tela.')
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Atualizar monitores')
        refresh.add_css_class('flat')
        refresh.connect('clicked', lambda *_: self.refresh_monitors())
        refresh.set_valign(Gtk.Align.CENTER)
        self.monitor.add_suffix(refresh)
        display.add(self.monitor)
        self.fullscreen = Adw.SwitchRow(title='Iniciar em tela cheia',
            subtitle='Ctrl + Alt + Enter alterna entre janela e tela cheia.', active=self.cfg['fullscreen'])
        keyboard_policy = Adw.ActionRow(title='Teclado automático',
            subtitle='Tela cheia: atalhos no Windows. Janela: atalhos globais no Linux.')
        display.add(self.fullscreen)
        display.add(keyboard_policy)
        self.quality = Adw.ComboRow(title='Qualidade',
            model=Gtk.StringList.new(['Equilibrada', 'Mais qualidade', 'Mais leve']),
            selected=self.cfg['quality'])
        display.add(self.quality)
        options = Adw.PreferencesGroup(title='Preferências')
        self.form.append(options)
        self.clipboard = Adw.SwitchRow(title='Compartilhar área de transferência', active=self.cfg['clipboard'])
        self.remember = Adw.SwitchRow(title='Lembrar senha', subtitle='Armazenada no chaveiro do GNOME.',
                                     active=self.cfg['remember'])
        options.add(self.clipboard)
        options.add(self.remember)
        self.error = Gtk.Label(xalign=0, wrap=True)
        self.error.add_css_class('error')
        self.error.set_visible(False)
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(footer, f'set_margin_{side}')(16)
        footer.append(self.error)
        view.add_bottom_bar(footer)
        self.connect_btn = Gtk.Button(label='Conectar à VM', height_request=48)
        self.connect_btn.add_css_class('suggested-action')
        self.connect_btn.connect('clicked', lambda *_: self.do_connect())
        footer.append(self.connect_btn)
        hint = Gtk.Label(label='Em tela cheia, passe o mouse no topo central para abrir a AJR Bar.', wrap=True)
        hint.add_css_class('dim-label')
        hint.add_css_class('caption')
        footer.append(hint)
        self.refresh_monitors()
        self.schedule_status()
        # Keyring access stays in the application; no password is logged or exported.
        if self.cfg['remember']:
            def lookup():
                value = secret(self.cfg['server'], self.cfg['user'], 'lookup')
                if value:
                    def fill():
                        if not self.password.get_text() and not self._closing:
                            self.password.set_text(value)
                    GLib.idle_add(fill)
            threading.Thread(target=lookup, daemon=True).start()
        self._poll = GLib.timeout_add(250, self.poll_session)

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

    def persist(self):
        self.cfg.update(server=self.server.get_text().strip(), user=self.user.get_text().strip(),
            quality=int(self.quality.get_selected()), fullscreen=self.fullscreen.get_active(),
            capture_keyboard=True, clipboard=self.clipboard.get_active(),
            remember=self.remember.get_active())
        i = int(self.monitor.get_selected())
        if 0 <= i < len(self.monitors):
            self.cfg.update(monitor=self.monitors[i]['id'], monitor_connector=self.monitors[i]['connector'])
        save_cfg(self.cfg)

    def render_shares(self):
        while (child := self.share_list.get_first_child()) is not None:
            self.share_list.remove(child)
        if not self.cfg['shares']:
            self.share_list.append(Adw.ActionRow(title='Nenhuma pasta compartilhada',
                subtitle='Adicione uma pasta para acessá-la no Windows.'))
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

    def set_status(self, title, subtitle, icon='network-server-symbolic'):
        self.status.set_title(title)
        self.status.set_subtitle(subtitle)
        self.status_icon.set_from_icon_name(icon)

    def schedule_status(self):
        self._status_generation += 1
        generation = self._status_generation
        server = self.server.get_text()
        def check():
            try:
                with socket.create_connection(host_port(server), timeout=1):
                    pass
                online = True
            except (OSError, ValueError):
                online = False
            def done():
                if not self._closing and generation == self._status_generation and not self.proc:
                    self.set_status('VM disponível' if online else 'VM indisponível',
                        server if online else 'Confira o servidor e se a VM está ligada.',
                        'network-transmit-receive-symbolic' if online else 'network-offline-symbolic')
            GLib.idle_add(done)
        threading.Thread(target=check, daemon=True).start()

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
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            self.show_error(str(exc))
            return
        password = self.password.get_text()
        self.connect_btn.set_sensitive(False)
        self.form.set_sensitive(False)
        self.connect_btn.set_label('Conectando…')
        self.set_status('Conectando à VM', self.cfg['server'])
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
                           AJR_MONITOR_CONNECTOR=monitor['connector'])
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
        self.connect_btn.set_label('Conectar à VM')
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
            self.connect_btn.set_label('Conectar à VM')
            self.connect_btn.add_css_class('suggested-action')
            self.set_status('Sessão encerrada', 'Você pode conectar novamente.')
            if not started or code not in (0, 11, 131):
                self.show_error(f"A conexão terminou (código {code}). Abra os registros para verificar o motivo.")
            self.present()
            return GLib.SOURCE_CONTINUE
        state = self.x11.state(self.proc.pid)
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
