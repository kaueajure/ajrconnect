#!/usr/bin/env python3
"""AJR Connect: native GNOME connection manager and session controls."""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk
from pathlib import Path
import copy
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
                  DEFAULT, PROFILE_KEYS, detect_monitors, host_port, load_cfg,
                  resolve_monitor, save_cfg, select_profile, store_profile)
from x11 import X11
from integration import installed_revision

APP_ID = 'com.ajure.AJRConnect'
EXTENSION_ID = 'ajr-connect@ajure.local'
LOCAL_BUS = 'org.gnome.Shell'
LOCAL_PATH = '/com/ajure/AJRConnect'
LOCAL_INTERFACE = 'com.ajure.AJRConnect.Keyboard'


def shortcut_parts(value):
    valid, key, modifiers = Gtk.accelerator_parse(value)
    allowed = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK | \
              Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK
    if not valid or not key or not Gtk.accelerator_valid(key, modifiers) or modifiers & ~allowed or not modifiers & (
            Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
        raise ValueError('Escolha uma combinação com Ctrl, Alt ou Super e uma tecla.')
    return Gdk.keyval_to_lower(key), modifiers


class ShortcutEditor(Adw.Window):
    def __init__(self, parent, current, callback):
        super().__init__(transient_for=parent, modal=True, title='Atalho de tela cheia')
        self.callback, self.value = callback, current
        self.set_default_size(420, 240)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        self.set_content(view)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{side}')(24)
        view.set_content(box)
        box.append(Gtk.Label(label='Pressione a combinação desejada com Ctrl, Alt ou Super.', wrap=True))
        self.preview = Gtk.Label(label=Gtk.accelerator_get_label(*shortcut_parts(current)), wrap=True)
        self.preview.add_css_class('title-2')
        box.append(self.preview)
        self.error = Gtk.Label(wrap=True)
        self.error.add_css_class('error')
        box.append(self.error)
        actions = Gtk.Box(spacing=8, homogeneous=True)
        box.append(actions)
        reset = Gtk.Button(label='Restaurar padrão')
        reset.connect('clicked', lambda *_: self.set_shortcut(DEFAULT['fullscreen_shortcut']))
        actions.append(reset)
        save = Gtk.Button(label='Salvar atalho')
        save.add_css_class('suggested-action')
        save.connect('clicked', lambda *_: self.save())
        actions.append(save)
        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect('key-pressed', self.key_pressed)
        self.add_controller(controller)

    def set_shortcut(self, value):
        self.value = value
        self.preview.set_text(Gtk.accelerator_get_label(*shortcut_parts(value)))
        self.error.set_text('')

    def key_pressed(self, _controller, key, _code, state):
        if Gdk.keyval_name(key) in ('Control_L', 'Control_R', 'Alt_L', 'Alt_R',
                'Super_L', 'Super_R', 'Shift_L', 'Shift_R', 'Meta_L', 'Meta_R'):
            return True
        modifiers = state & Gtk.accelerator_get_default_mod_mask()
        if not modifiers:
            if key == Gdk.KEY_Escape:
                self.close()
                return True
            return False  # Keep Tab navigation and keyboard activation of buttons.
        if key == Gdk.KEY_ISO_Left_Tab:
            key = Gdk.KEY_Tab
        value = Gtk.accelerator_name(Gdk.keyval_to_lower(key), modifiers)
        try:
            shortcut_parts(value)
        except ValueError as exc:
            self.error.set_text(str(exc))
        else:
            self.set_shortcut(value)
        return True

    def save(self):
        self.callback(self.value)
        self.close()


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
        return result.stdout.removesuffix('\n') if operation == 'lookup' and result.returncode == 0 \
            else result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return ''


class ShareEditor(Adw.Window):
    def __init__(self, parent, share, on_save):
        super().__init__(transient_for=parent, modal=True, title='Pasta compartilhada')
        self.callback = on_save
        self._chooser = None
        self.connect('close-request', self.close_requested)
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
        if self._chooser:
            self._chooser.present()
            return
        # A GTK dialog avoids broken desktop portals on some Zorin sessions.
        # Keep a strong reference until response/close, including with PyGObject.
        chooser = Gtk.FileChooserDialog(title='Escolher pasta no Linux',
            transient_for=self, modal=True, action=Gtk.FileChooserAction.SELECT_FOLDER)
        self._chooser = chooser
        chooser.add_buttons('Cancelar', Gtk.ResponseType.CANCEL,
                            'Selecionar pasta', Gtk.ResponseType.ACCEPT)
        chooser.set_default_response(Gtk.ResponseType.ACCEPT)
        current = Path(self.path.get_text().strip()).expanduser()
        if not self.path.get_text().strip() or not current.is_dir():
            current = Path.home()
        try:
            chooser.set_current_folder(Gio.File.new_for_path(str(current)))
        except GLib.Error as exc:
            self.error.set_text('Não foi possível abrir a pasta inicial: ' + exc.message)
        def response(dialog, result):
            if result == Gtk.ResponseType.ACCEPT:
                chosen = dialog.get_file()
                if chosen and chosen.get_path():
                    self.path.set_text(chosen.get_path())
                    if not self.name.get_text().strip():
                        self.name.set_text(normalize_share_name(Path(chosen.get_path()).name))
                    self.error.set_text('')
                else:
                    self.error.set_text('Selecione uma pasta local ou monte a pasta de rede no Linux primeiro.')
            self._chooser = None
            dialog.destroy()
        chooser.connect('response', response)
        chooser.present()

    def close_requested(self, *_):
        if self._chooser:
            self._chooser.destroy()
            self._chooser = None
        return False

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
        try:
            shortcut_parts(self.cfg['fullscreen_shortcut'])
        except ValueError:
            self.cfg['fullscreen_shortcut'] = DEFAULT['fullscreen_shortcut']
        self._profiles_updating = False
        self._password_generation = 0
        self._integration_ready = False
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
                self._integration_ready = ready
                self.integration_banner.set_title(message)
                self.integration_banner.set_revealed(not ready)
                self.update_keyboard_options()
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
        self.profile = Adw.ComboRow(title='Conexões salvas')
        group.add(self.profile)
        self.profile_name = Adw.EntryRow(title='Nome da conexão')
        group.add(self.profile_name)
        profile_actions = Gtk.Box(spacing=8, homogeneous=True)
        for label, callback in [('Nova', self.new_profile), ('Salvar', self.save_profile),
                                ('Excluir', self.delete_profile)]:
            button = Gtk.Button(label=label)
            button.connect('clicked', callback)
            profile_actions.append(button)
            if label == 'Excluir':
                self.profile_delete = button
        profile_actions.set_margin_top(12)
        group.add(profile_actions)
        self.server = Adw.EntryRow(title='Servidor', text=str(self.cfg['server']))
        self.user = Adw.EntryRow(title='Usuário', text=str(self.cfg['user']))
        self.password = Adw.PasswordEntryRow(title='Senha')
        for row in (self.server, self.user, self.password):
            group.add(row)
        self.remember = Adw.SwitchRow(title='Lembrar senha desta conexão',
            subtitle='Armazenada no chaveiro do GNOME.', active=self.cfg['remember'])
        group.add(self.remember)
        self.password.connect('entry-activated', lambda *_: self.do_connect())
        self.server.connect('changed', lambda *_: self.schedule_status())
        for row in (self.server, self.user):
            row.connect('changed', self.identity_changed)
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
            subtitle='Use o atalho abaixo para alternar entre janela e tela cheia.', active=self.cfg['fullscreen'])
        display.add(self.fullscreen)
        self.shortcut = Adw.ActionRow(title='Atalho de tela cheia')
        change = Gtk.Button(label='Alterar', valign=Gtk.Align.CENTER)
        change.connect('clicked', lambda *_: ShortcutEditor(self,
            self.cfg['fullscreen_shortcut'], self.set_shortcut).present())
        self.shortcut.add_suffix(change)
        display.add(self.shortcut)
        keyboard = Adw.PreferencesGroup(title='Prioridade dos atalhos',
            description='Ative para executar no Windows remoto. Desative para executar no computador local.')
        self.form.append(keyboard)
        self.keyboard_mode = Adw.ComboRow(title='Encaminhar atalhos ao Windows',
            model=Gtk.StringList.new(['Somente em tela cheia', 'Também em modo janela', 'Manter atalhos no computador local']),
            selected=('fullscreen', 'always', 'local').index(self.cfg['keyboard_mode']))
        keyboard.add(self.keyboard_mode)
        self.keyboard_rows = {}
        for key, title, subtitle in [
            ('remote_alt_tab', 'Alt + Tab', 'Alternar aplicativos; Shift inverte a ordem.'),
            ('remote_super', 'Tecla Windows / Super', 'Pressionada sozinha: menu Iniciar ou visão de atividades local.'),
            ('remote_alt_f4', 'Alt + F4', 'Fechar a janela remota ou a janela da conexão local.')]:
            row = Adw.SwitchRow(title=title, subtitle=subtitle, active=self.cfg[key])
            keyboard.add(row)
            self.keyboard_rows[key] = row
        self.keyboard_note = Adw.ActionRow(title='Integração com o desktop')
        keyboard.add(self.keyboard_note)
        self.keyboard_mode.connect('notify::selected', lambda *_: self.update_keyboard_options())
        self.quality = Adw.ComboRow(title='Qualidade',
            model=Gtk.StringList.new(['Equilibrada', 'Mais qualidade', 'Mais leve']),
            selected=self.cfg['quality'])
        display.add(self.quality)
        options = Adw.PreferencesGroup(title='Preferências')
        self.form.append(options)
        self.clipboard = Adw.SwitchRow(title='Compartilhar área de transferência', active=self.cfg['clipboard'])
        options.add(self.clipboard)
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
        self.refresh_profiles()
        self.profile.connect('notify::selected', self.profile_changed)
        self.set_shortcut(self.cfg['fullscreen_shortcut'], persist=False)
        self.lookup_password()
        self.update_keyboard_options()
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
        # Replacing a ComboRow model inside notify::selected can recurse/crash GTK.
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
