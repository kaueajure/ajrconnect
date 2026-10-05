"""Folder and shortcut editors, independent from the session controller."""
import re
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, Gio, GLib
from core import DEFAULT


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
        self.add_css_class('ajr-dialog')
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
        self.preview.add_css_class('ajr-shortcut-preview')
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


class ShareEditor(Adw.Window):
    def __init__(self, parent, share, on_save):
        super().__init__(transient_for=parent, modal=True, title='Pasta compartilhada')
        self.add_css_class('ajr-dialog')
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


