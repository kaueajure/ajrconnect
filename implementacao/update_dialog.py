"""Update controls with cancellable download and explicit application restart."""
import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
import updates
from version import APP_VERSION


class UpdateWindow(Adw.Window):
    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=True, title='Atualizações')
        self.add_css_class('ajr-dialog')
        self.owner, self.release = parent, parent._available_release
        self.phase, self.closed = 'idle', False
        self.cancel = threading.Event()
        self.set_default_size(500, 460)
        self.set_size_request(360, 300)
        self.connect('close-request', self.close_requested)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        self.set_content(view)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        view.set_content(scroll)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{side}')(24)
        scroll.set_child(box)
        box.append(Gtk.Label(label='AJR Connect', xalign=0,
                             css_classes=['ajr-section-title']))
        box.append(Gtk.Label(label='Versão atual · ' + APP_VERSION, xalign=0,
                             css_classes=['ajr-muted']))
        group = Adw.PreferencesGroup(title='Preferências de atualização')
        self.auto = Adw.SwitchRow(title='Verificar ao abrir o aplicativo', active=parent.cfg['check_updates'])
        self.betas = Adw.SwitchRow(title='Incluir versões de teste', active=parent.cfg['update_prereleases'])
        group.add(self.auto)
        group.add(self.betas)
        self.auto.connect('notify::active', self.settings_changed)
        self.betas.connect('notify::active', self.settings_changed)
        box.append(group)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.set_selectable(True)
        self.status.set_focusable(True)
        self.status.add_css_class('ajr-update-status')
        box.append(self.status)
        self.progress = Gtk.ProgressBar(show_text=True, visible=False)
        box.append(self.progress)
        self.notes = Gtk.LinkButton(label='Notas da versão', visible=False)
        self.notes.set_halign(Gtk.Align.START)
        box.append(self.notes)
        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        actions.add_css_class('ajr-dialog-actions')
        view.add_bottom_bar(actions)
        self.action = Gtk.Button(label='Verificar atualizações', height_request=44)
        self.action.add_css_class('suggested-action')
        self.action.connect('clicked', self.activate)
        actions.append(self.action)
        self.cancel_button = Gtk.Button(label='Cancelar download', visible=False)
        self.cancel_button.connect('clicked', self.cancel_download)
        actions.append(self.cancel_button)
        self.show_release()
        if not self.release and not parent._update_ready:
            self.check()

    def settings_changed(self, widget, *_):
        self.owner.cfg.update(check_updates=self.auto.get_active(),
                              update_prereleases=self.betas.get_active())
        self.owner.persist()
        if widget == self.betas:
            self.release = None
            self.owner._available_release = None
            self.owner.ui.update_available(False)
            self.status.set_text('Verifique novamente para aplicar a escolha de versões de teste.')
        self.show_release()

    def show_release(self):
        self.action.set_sensitive(self.phase in ('idle', 'ready'))
        if self.owner._update_ready:
            self.phase = 'ready'
            self.status.set_text('Atualização instalada. Reinicie o aplicativo para usar a nova versão.')
            self.action.set_label('Reiniciar aplicativo')
        elif self.release:
            self.status.set_text('Nova versão disponível: ' + self.release.tag.removeprefix('v'))
            self.action.set_label('Baixar e atualizar')
            self.notes.set_uri(self.release.page)
            self.notes.set_visible(True)
            if not updates.installed_application():
                self.status.set_text('Nova versão disponível. Abra o aplicativo instalado para atualizar; '
                                     'esta execução usa os fontes de desenvolvimento.')
                self.action.set_sensitive(False)
        else:
            self.action.set_label('Verificar atualizações')
            self.notes.set_visible(False)
        self.auto.set_sensitive(self.phase == 'idle')
        self.betas.set_sensitive(self.phase == 'idle')

    def activate(self, *_):
        if self.phase == 'ready':
            self.owner.restart_application()
        elif self.release:
            self.install()
        else:
            self.check()

    def check(self):
        if self.phase != 'idle':
            return
        self.phase = 'check'
        self.cancel.clear()
        self.action.set_sensitive(False)
        self.auto.set_sensitive(False)
        self.betas.set_sensitive(False)
        self.status.set_text('Verificando atualizações…')
        include = self.betas.get_active()
        def worker():
            try:
                release = updates.check_updates(include_prereleases=include, cancel=self.cancel)
                message = '' if release else 'O aplicativo já está atualizado.'
            except Exception as exc:
                release, message = None, 'Não foi possível verificar atualizações. ' + str(exc)
            def done():
                if self.closed:
                    return
                self.phase, self.release = 'idle', release
                self.owner._available_release = release
                self.owner.ui.update_available(bool(release))
                self.action.set_sensitive(True)
                self.status.set_text(message)
                self.show_release()
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def install(self):
        if self.phase != 'idle' or self.owner._updating or self.owner._update_ready:
            return
        if self.owner.connection_busy():
            self.status.set_text('Desconecte do Windows ou cancele a reconexão antes de atualizar.')
            return
        self.owner.persist()
        self.owner._updating = True
        self.owner.form.set_sensitive(False)
        self.owner.connect_btn.set_sensitive(False)
        self.phase = 'download'
        self.cancel.clear()
        self.action.set_sensitive(False)
        self.auto.set_sensitive(False)
        self.betas.set_sensitive(False)
        self.progress.set_visible(True)
        self.cancel_button.set_visible(True)
        self.status.set_text('Baixando atualização…')
        def progress(phase, fraction):
            def render():
                if self.closed:
                    return
                self.phase = phase
                self.progress.set_fraction(fraction)
                self.progress.set_text(f'{fraction:.0%}' if phase == 'download' else '')
                self.status.set_text({'download': 'Baixando atualização…',
                    'verify': 'Verificando pacote…', 'install': 'Instalando atualização…'}[phase])
                self.cancel_button.set_sensitive(phase == 'download')
            GLib.idle_add(render)
        def worker():
            try:
                updates.apply_update(self.release, self.cancel, progress)
                error = None
            except Exception as exc:
                error = exc
            def done():
                self.owner._updating = False
                self.owner._update_ready = error is None
                self.owner.form.set_sensitive(error is not None)
                self.owner.connect_btn.set_sensitive(error is not None)
                if self.closed:
                    return
                self.phase = 'idle' if error else 'ready'
                self.cancel_button.set_visible(False)
                self.progress.set_visible(False)
                self.action.set_sensitive(True)
                self.status.set_text(str(error) if error else '')
                self.show_release()
                if error:
                    self.status.set_text('Download cancelado.' if isinstance(error, updates.UpdateCancelled)
                                         else 'Falha na atualização. ' + str(error))
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def cancel_download(self, *_):
        if self.phase == 'download':
            self.cancel.set()
            self.status.set_text('Cancelando download…')
            self.cancel_button.set_sensitive(False)

    def close_requested(self, *_):
        if self.owner._updating:
            self.cancel_download()
            return True
        self.closed = True
        self.cancel.set()
        self.owner._update_window = None
        return False
