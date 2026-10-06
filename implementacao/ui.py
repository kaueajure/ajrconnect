"""AJR desktop presentation. Session, profile and keyring logic live in ajr_app."""
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Pango, Gio, GObject
from dialogs import ShortcutEditor
from keyboard import shortcut_parts

ASSETS = Path(__file__).resolve().parent / 'assets'

PALETTES = {
    'dark': dict(window='#111216', surface='#1b1c21', sidebar='#15161a',
                 raised='#222329', text='#f4f4f5', muted='#a2a4ac', border='#2b2d34',
                 accent='#a697ff', button='#7561d7', on_button='#ffffff',
                 selection='#2a2638', success='#60c995', danger='#ee777d', control='#686b76'),
    'light': dict(window='#f6f6f7', surface='#ffffff', sidebar='#f1f1f3',
                  raised='#f4f4f5', text='#222226', muted='#686870', border='#dedee3',
                  accent='#6854d9', button='#6854d9', on_button='#ffffff',
                  selection='#eeeafe', success='#27875a', danger='#c63b4c', control='#85858e'),
}


def label(text, css=None, wrap=False):
    widget = Gtk.Label(label=text, xalign=0, wrap=wrap)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if css:
        widget.add_css_class(css)
    return widget


def button(text, callback, icon=None, css=None):
    widget = Gtk.Button()
    content = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
    if icon:
        content.append(Gtk.Image(icon_name=icon))
    content.append(Gtk.Label(label=text))
    widget.set_child(content)
    if css:
        widget.add_css_class(css)
    widget.connect('clicked', callback)
    return widget


def section(title, description=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    headings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    headings.append(label(title, 'ajr-section-title'))
    if description:
        headings.append(label(description, 'ajr-muted', wrap=True))
    box.append(headings)
    return box


def entry_field(title, value='', password=False, hint=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7, hexpand=True)
    widget = Gtk.PasswordEntry(show_peek_icon=True) if password else Gtk.Entry()
    widget.set_text(value)
    widget.set_hexpand(True)
    widget.add_css_class('ajr-entry')
    widget.update_property([Gtk.AccessibleProperty.LABEL], [title])
    box.append(label(title, 'ajr-field-label'))
    box.append(widget)
    if hint:
        box.append(label(hint, 'ajr-field-hint', wrap=True))
    return box, widget


class StatusCard(Gtk.Box):
    def __init__(self):
        super().__init__(spacing=10, valign=Gtk.Align.CENTER)
        self.add_css_class('ajr-status')
        self.icon = Gtk.Image(icon_name='network-server-symbolic')
        self.append(self.icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        self.title = label('Configure sua conexão', 'ajr-status-title', wrap=True)
        self.subtitle = label('Informe o servidor para começar.', 'ajr-muted', wrap=True)
        text.append(self.title)
        text.append(self.subtitle)
        self.append(text)

    def set_title(self, value):
        self.title.set_text(value)

    def set_subtitle(self, value):
        self.subtitle.set_text(value)


class DesktopView:
    """Build a responsive workspace and expose the controller's existing fields."""
    def __init__(self, owner):
        self.owner = w = owner
        w.add_css_class('ajr-window')
        self.styles = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(w.get_display(), self.styles,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.manager = Adw.StyleManager.get_default()
        self.theme_signal = self.manager.connect('notify::dark', lambda *_: self.update_theme())
        self.set_theme(w.cfg.get('appearance', 'dark'))
        w.connect('destroy', self.dispose)

        shell = Adw.ToolbarView()
        w.set_content(shell)
        header = Adw.HeaderBar()
        header.add_css_class('ajr-header')
        header.set_title_widget(Gtk.Label(label='AJR Connect', css_classes=['ajr-header-title']))
        shell.add_top_bar(header)
        self.sidebar_toggle = Gtk.ToggleButton(icon_name='sidebar-show-symbolic',
                                               tooltip_text='Mostrar conexões salvas')
        header.pack_start(self.sidebar_toggle)
        self.theme_button = Gtk.Button(tooltip_text='Alternar tema claro e escuro')
        self.theme_button.connect('clicked', self.toggle_theme)
        header.pack_end(self.theme_button)
        menu = Gio.Menu()
        for name, title, callback in [('logs', 'Registros da conexão', w.open_logs),
                                       ('updates', 'Atualizações', w.open_updates)]:
            action = Gio.SimpleAction.new('ui-' + name, None)
            action.connect('activate', lambda _a, _p, cb=callback: cb())
            w.add_action(action)
            menu.append(title, 'win.ui-' + name)
        header.pack_end(Gtk.MenuButton(icon_name='view-more-symbolic', menu_model=menu,
                                       tooltip_text='Mais opções'))
        self.updates_button = Gtk.Button(icon_name='software-update-available-symbolic',
                                         tooltip_text='Atualizações do aplicativo')
        self.updates_button.connect('clicked', lambda *_: w.open_updates())
        self.updates_button.set_visible(False)
        header.pack_end(self.updates_button)
        w.integration_banner = Adw.Banner(title='')
        shell.add_top_bar(w.integration_banner)
        w.toast = Adw.ToastOverlay()
        shell.set_content(w.toast)

        self.split = Adw.OverlaySplitView(min_sidebar_width=230, max_sidebar_width=260,
                                         sidebar_width_fraction=.23)
        w.toast.set_child(self.split)
        self.sidebar_toggle.connect('toggled', lambda btn: self.split.set_show_sidebar(btn.get_active()))
        self.split.connect('notify::show-sidebar', lambda *_:
                           self.sidebar_toggle.set_active(self.split.get_show_sidebar()))
        self.split.set_sidebar(self.build_sidebar())
        self.split.set_content(self.build_workspace())
        fields_breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 1040px'))
        for row in self.field_rows:
            fields_breakpoint.add_setter(row, 'orientation', Gtk.Orientation.VERTICAL)
        w.add_breakpoint(fields_breakpoint)
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 860px'))
        # Only the last matching window breakpoint applies, so compact mode
        # must include the field layout as well as the sidebar setters.
        for row in self.field_rows:
            breakpoint.add_setter(row, 'orientation', Gtk.Orientation.VERTICAL)
        breakpoint.add_setter(self.split, 'collapsed', True)
        breakpoint.add_setter(self.sidebar_toggle, 'visible', True)
        breakpoint.add_setter(self.compact_profiles, 'visible', True)
        self.sidebar_toggle.set_visible(False)
        self.compact_profiles.set_visible(False)
        w.add_breakpoint(breakpoint)
        short = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(
            'max-width: 860px and max-height: 560px'))
        for row in self.field_rows:
            short.add_setter(row, 'orientation', Gtk.Orientation.VERTICAL)
        short.add_setter(self.split, 'collapsed', True)
        short.add_setter(self.sidebar_toggle, 'visible', True)
        # The sidebar remains the profile picker in short windows. Avoid
        # repeating its dropdown above the selected connection's heading.
        short.add_setter(self.compact_profiles, 'visible', False)
        short.add_setter(self.navigation, 'css-classes', GObject.Value(
            GObject.TYPE_STRV, ['ajr-navigation', 'ajr-short-navigation']))
        short.add_setter(self.navigation, 'spacing', 8)
        for content in self.page_contents:
            short.add_setter(content, 'css-classes', GObject.Value(
                GObject.TYPE_STRV, ['ajr-workspace', 'ajr-short-workspace']))
        short.add_setter(self.empty_share_icon, 'visible', False)
        short.add_setter(self.sharing_box, 'spacing', 16)
        w.add_breakpoint(short)
        self.update_theme()
        w.form.connect('notify::sensitive', lambda *_:
                       self.profile_area.set_sensitive(w.form.get_sensitive()))
        w.form.connect('notify::sensitive', lambda *_:
                       self.compact_profiles.set_sensitive(w.form.get_sensitive()))
        for field in (w.profile_name, w.server, w.user):
            field.connect('changed', lambda *_: self.update_summary())

    def dispose(self, *_):
        self.manager.disconnect(self.theme_signal)
        Gtk.StyleContext.remove_provider_for_display(self.owner.get_display(), self.styles)

    def set_theme(self, value):
        self.manager.set_color_scheme({'light': Adw.ColorScheme.FORCE_LIGHT,
                                       'dark': Adw.ColorScheme.FORCE_DARK,
                                       'system': Adw.ColorScheme.DEFAULT}.get(value, Adw.ColorScheme.FORCE_DARK))

    def toggle_theme(self, *_):
        self.owner.cfg['appearance'] = 'light' if self.manager.get_dark() else 'dark'
        self.set_theme(self.owner.cfg['appearance'])
        self.owner.persist()

    def update_available(self, available):
        self.updates_button.set_visible(available)
        if available:
            self.updates_button.add_css_class('suggested-action')
        else:
            self.updates_button.remove_css_class('suggested-action')
        self.updates_button.set_tooltip_text('Nova versão disponível' if available else 'Atualizações do aplicativo')

    def update_theme(self):
        dark = self.manager.get_dark()
        colors = PALETTES['dark' if dark else 'light']
        tokens = '\n'.join(f'@define-color ajr_{name} {value};' for name, value in colors.items())
        aliases = dict(window_bg_color='window', window_fg_color='text', view_bg_color='surface',
                       view_fg_color='text', headerbar_bg_color='window', headerbar_fg_color='text',
                       headerbar_backdrop_color='window', card_bg_color='surface', card_fg_color='text',
                       popover_bg_color='surface', popover_fg_color='text', dialog_bg_color='surface',
                       dialog_fg_color='text', accent_color='accent', accent_bg_color='button',
                       accent_fg_color='on_button', destructive_color='danger')
        tokens += '\n' + '\n'.join(f'@define-color {name} @ajr_{value};' for name, value in aliases.items())
        self.styles.load_from_data((tokens + '\n' + (ASSETS / 'style.css').read_text()).encode())
        if hasattr(self, 'theme_button'):
            self.theme_button.set_icon_name('weather-clear-symbolic' if dark else 'weather-clear-night-symbolic')
            self.theme_button.set_tooltip_text('Usar tema claro' if dark else 'Usar tema escuro')

    def build_sidebar(self):
        w = self.owner
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        sidebar.add_css_class('ajr-sidebar')
        sidebar.append(label('Conexões', 'ajr-section-title'))
        self.profile_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, vexpand=True)
        sidebar.append(self.profile_area)
        caption = Gtk.Box(spacing=8)
        caption.append(label('Conexões salvas', 'ajr-field-hint'))
        self.profile_count = Gtk.Label(label='0', css_classes=['ajr-count'])
        caption.append(self.profile_count)
        self.search = Gtk.SearchEntry(placeholder_text='Buscar conexão')
        self.search.add_css_class('ajr-search')
        self.search.connect('search-changed', lambda *_: self.render_profiles())
        self.profile_area.append(self.search)
        self.profile_area.append(button('Nova conexão', w.new_profile, 'list-add-symbolic', 'ajr-secondary'))
        self.profile_area.append(caption)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.profile_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.profile_list.add_css_class('ajr-profiles')
        self.profile_list.connect('row-selected', self.profile_selected)
        scroll.set_child(self.profile_list)
        self.profile_area.append(scroll)
        self.empty_profiles = label('Nenhuma conexão salva.', 'ajr-muted', wrap=True)
        self.profile_area.append(self.empty_profiles)
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        bottom.add_css_class('ajr-sidebar-footer')
        self.integration_label = label('Controles no aplicativo', 'ajr-field-hint', wrap=True)
        bottom.append(self.integration_label)
        sidebar.append(bottom)
        return sidebar

    def render_profiles(self):
        w = self.owner
        self.rendering_profiles = True
        while (child := self.profile_list.get_first_child()) is not None:
            self.profile_list.remove(child)
        query = self.search.get_text().casefold().strip()
        profiles = w.cfg['profiles']
        self.profile_count.set_text(str(len(profiles)))
        count = 0
        for index, profile in enumerate(profiles):
            if query and query not in (profile['name'] + ' ' + profile['server'] + ' ' + profile['user']).casefold():
                continue
            row = Gtk.ListBoxRow()
            row.profile_index = index
            content = Gtk.Box(spacing=10)
            icon = Gtk.Image(icon_name='computer-symbolic', pixel_size=20)
            icon.add_css_class('ajr-profile-icon')
            content.append(icon)
            names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
            title = label(profile['name'], 'ajr-profile-name')
            title.set_ellipsize(Pango.EllipsizeMode.END)
            subtitle = label(profile['server'], 'ajr-profile-host')
            subtitle.set_ellipsize(Pango.EllipsizeMode.END)
            names.append(title)
            names.append(subtitle)
            content.append(names)
            row.set_child(content)
            self.profile_list.append(row)
            if profile['id'] == w.cfg['active_profile']:
                self.profile_list.select_row(row)
            count += 1
        self.empty_profiles.set_label('Nenhuma conexão encontrada.' if query else
                                      'Nenhuma conexão salva.')
        self.empty_profiles.set_visible(not count)
        self.rendering_profiles = False
        self.update_summary()

    def profile_selected(self, _list, row):
        if row and not getattr(self, 'rendering_profiles', False):
            self.owner.profile.set_selected(row.profile_index)
            if self.split.get_collapsed():
                self.split.set_show_sidebar(False)

    def build_workspace(self):
        w = self.owner
        view = Adw.ToolbarView()
        # ToolbarView allocates space for navigation instead of overlaying the
        # scrolling page. Changing page content never changes this bar's height.
        navigation_clamp = Adw.Clamp(maximum_size=840, tightening_threshold=720)
        navigation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.navigation = navigation
        navigation.add_css_class('ajr-navigation')
        navigation_clamp.set_child(navigation)
        view.add_top_bar(navigation_clamp)

        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.connection_title = label('Nova conexão', 'ajr-connection-title')
        self.connection_title.set_ellipsize(Pango.EllipsizeMode.END)
        details.append(self.connection_title)
        self.connection_meta = label('Servidor não informado.', 'ajr-muted')
        self.connection_meta.set_ellipsize(Pango.EllipsizeMode.END)
        details.append(self.connection_meta)

        self.compact_profiles = Gtk.Box(spacing=12)
        self.compact_profiles.append(label('Conexão salva', 'ajr-field-label'))
        w.profile = Gtk.DropDown(hexpand=True)
        w.profile.update_property([Gtk.AccessibleProperty.LABEL], ['Conexões salvas'])
        self.compact_profiles.append(w.profile)
        self.compact_profiles.append(button('Nova', w.new_profile, 'list-add-symbolic'))
        navigation.append(self.compact_profiles)
        navigation.append(details)

        tabs = Gtk.Box(spacing=16)
        tabs.add_css_class('ajr-tabs')
        w.form = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                           transition_duration=140, vhomogeneous=False, vexpand=True)
        self.tab_buttons = {}
        for key, title in [('connection', 'Conexão'), ('display', 'Tela e teclado'),
                            ('sharing', 'Compartilhamento')]:
            tab = Gtk.ToggleButton()
            tab_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            tab_box.append(Gtk.Label(label=title))
            tab.set_child(tab_box)
            tab.add_css_class('ajr-tab')
            tab.update_property([Gtk.AccessibleProperty.LABEL], [title])
            tab.connect('clicked', lambda _b, page=key: self.show_page(page))
            self.tab_buttons[key] = tab
            tabs.append(tab)
        navigation.append(tabs)
        view.set_content(w.form)
        self.page_scrolls = {}
        self.page_contents = []
        pages = [('connection', self.build_connection()),
                 ('display', self.build_display()),
                 ('sharing', self.build_sharing())]
        for name, body in pages:
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            clamp = Adw.Clamp(maximum_size=840, tightening_threshold=720)
            scroll.set_child(clamp)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
            content.add_css_class('ajr-workspace')
            self.page_contents.append(content)
            clamp.set_child(content)
            content.append(body)
            self.page_scrolls[name] = scroll
            w.form.add_named(scroll, name)
        self.show_page('connection')

        w.controls = Gtk.Box(spacing=8, homogeneous=True)
        for title, command, icon in [('Tela cheia', 'fullscreen', 'view-fullscreen-symbolic'),
                                      ('Modo janela', 'restore', 'view-restore-symbolic'),
                                      ('Minimizar', 'minimize', 'window-minimize-symbolic')]:
            w.controls.append(button(title, lambda _b, cmd=command: w.control(cmd), icon))
        w.controls.set_visible(False)

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        footer.add_css_class('ajr-footer')
        w.error = label('', 'ajr-error', wrap=True)
        # Gtk.Label's focus implementation requires selection (or links),
        # even when focusable is set. Allow copying errors and focus them.
        w.error.set_selectable(True)
        w.error.set_focusable(True)
        w.error.set_visible(False)
        footer.append(w.error)
        w.status = StatusCard()
        w.status.set_hexpand(True)
        w.status_icon = w.status.icon
        row = Gtk.Box(spacing=12)
        row.append(w.status)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        row.append(self.spinner)
        self.save_button = button('Salvar', w.save_profile, css='ajr-secondary')
        row.append(self.save_button)
        w.form.connect('notify::sensitive', lambda *_:
                       self.save_button.set_sensitive(w.form.get_sensitive()))
        w.form.connect('notify::sensitive', lambda *_:
                       self.save_button.set_visible(w.form.get_sensitive()))
        w.connect_btn = Gtk.Button(label='Conectar ao Windows', height_request=44,
                                   valign=Gtk.Align.CENTER)
        w.connect_btn.add_css_class('suggested-action')
        w.connect_btn.add_css_class('ajr-connect')
        w.connect_btn.connect('clicked', lambda *_: w.do_connect())
        row.append(w.connect_btn)
        footer.append(row)
        footer.append(w.controls)
        view.add_bottom_bar(footer)
        return view

    def show_page(self, name):
        if self.owner.form.get_visible_child_name() != name:
            # Keep focus on navigation while switching. Otherwise Gtk.Stack
            # can focus a field in the new page and scroll it away from the
            # position the user left it at.
            self.tab_buttons[name].grab_focus()
        self.owner.form.set_visible_child_name(name)
        for page, tab in self.tab_buttons.items():
            tab.set_active(page == name)

    def build_connection(self):
        w = self.owner
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        access = section('Dados de acesso')
        box.append(access)
        headings = access.get_first_child()
        access.remove(headings)
        top = Gtk.Box(spacing=12)
        headings.set_hexpand(True)
        top.append(headings)
        w.profile_delete = Gtk.Button(icon_name='user-trash-symbolic', tooltip_text='Excluir conexão',
                                      valign=Gtk.Align.CENTER)
        w.profile_delete.add_css_class('ajr-delete')
        w.profile_delete.connect('clicked', w.delete_profile)
        top.append(w.profile_delete)
        access.append(top)
        identity = Gtk.Box(spacing=16, homogeneous=True)
        field, w.profile_name = entry_field('Nome da conexão')
        w.profile_name.set_placeholder_text('Ex.: Meu escritório')
        identity.append(field)
        field, w.server = entry_field('Servidor', w.cfg['server'])
        w.server.set_placeholder_text('IP ou domínio:porta')
        identity.append(field)
        access.append(identity)
        credentials = Gtk.Box(spacing=16, homogeneous=True)
        field, w.user = entry_field('Usuário', w.cfg['user'])
        credentials.append(field)
        field, w.password = entry_field('Senha', password=True)
        credentials.append(field)
        access.append(credentials)
        self.field_rows = [identity, credentials]
        w.remember = Adw.SwitchRow(title='Lembrar senha', subtitle='Guardada no chaveiro deste computador.',
                                   active=w.cfg['remember'])
        remember = Adw.PreferencesGroup(title='Preferências')
        remember.add(w.remember)
        w.auto_reconnect = Adw.SwitchRow(title='Reconectar automaticamente',
            subtitle='Em quedas de rede, tenta recuperar a conexão até 5 vezes.', active=w.cfg['auto_reconnect'])
        remember.add(w.auto_reconnect)
        box.append(remember)
        w.password.connect('activate', lambda *_: w.do_connect())
        w.server.connect('changed', lambda *_: w.schedule_status())
        for field in (w.server, w.user):
            field.connect('changed', w.identity_changed)
        return box

    def build_display(self):
        w = self.owner
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        display = Adw.PreferencesGroup(title='Tela')
        box.append(display)
        w.monitor = Adw.ComboRow(title='Monitor', subtitle='Usado nos modos janela e tela cheia.')
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Atualizar monitores', valign=Gtk.Align.CENTER)
        refresh.add_css_class('flat')
        refresh.connect('clicked', lambda *_: w.refresh_monitors())
        w.monitor.add_suffix(refresh)
        display.add(w.monitor)
        w.fullscreen = Adw.SwitchRow(title='Iniciar em tela cheia', active=w.cfg['fullscreen'])
        display.add(w.fullscreen)
        w.shortcut = Adw.ActionRow(title='Atalho de tela cheia')
        change = Gtk.Button(label='Alterar', valign=Gtk.Align.CENTER)
        change.connect('clicked', lambda *_: ShortcutEditor(w, w.cfg['fullscreen_shortcut'], w.set_shortcut).present())
        w.shortcut.add_suffix(change)
        display.add(w.shortcut)
        w.quality = Adw.ComboRow(title='Qualidade da imagem',
            model=Gtk.StringList.new(['Equilibrada', 'Mais qualidade', 'Mais leve']), selected=w.cfg['quality'])
        display.add(w.quality)
        keyboard = Adw.PreferencesGroup(title='Atalhos',
            description='Ativado: Windows · Desativado: este computador')
        box.append(keyboard)
        w.keyboard_mode = Adw.ComboRow(title='Encaminhar atalhos ao Windows',
            model=Gtk.StringList.new(['Somente em tela cheia', 'Também em modo janela', 'Manter atalhos neste computador']),
            selected=('fullscreen', 'always', 'local').index(w.cfg['keyboard_mode']))
        keyboard.add(w.keyboard_mode)
        w.keyboard_rows = {}
        for key, title, subtitle in [('remote_alt_tab', 'Alt + Tab', 'Alternar entre aplicativos.'),
                                     ('remote_super', 'Windows / Super', 'Tecla sozinha: menu Iniciar ou atividades locais.'),
                                     ('remote_alt_f4', 'Alt + F4', 'Fechar a janela ativa.')]:
            row = Adw.SwitchRow(title=title, subtitle=subtitle, active=w.cfg[key])
            keyboard.add(row)
            w.keyboard_rows[key] = row
        w.keyboard_note = label('', 'ajr-field-hint', wrap=True)
        box.append(w.keyboard_note)
        rules = Adw.PreferencesGroup(title='Atalhos personalizados',
            description='Escolha onde executar cada combinação.')
        box.append(rules)
        w.keyboard_rules = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        w.keyboard_rules.add_css_class('boxed-list')
        rules.add(w.keyboard_rules)
        w.add_keyboard_rule = button('Adicionar atalho', lambda *_: w.edit_keyboard_rule(),
                                     'list-add-symbolic', 'ajr-secondary')
        w.add_keyboard_rule.set_margin_top(12)
        rules.add(w.add_keyboard_rule)
        w.keyboard_mode.connect('notify::selected', lambda *_: w.update_keyboard_options())
        return box

    def keyboard_rule_row(self, rule, on_target, on_edit, on_remove):
        row = Adw.SwitchRow(title=Gtk.accelerator_get_label(
            *shortcut_parts(rule['accelerator'], routing=True)), active=rule['remote'])
        row.set_use_markup(False)
        def update_target(widget, *_):
            destination = 'Windows' if widget.get_active() else 'Este computador'
            widget.set_subtitle('Destino: ' + destination)
            widget.update_property([Gtk.AccessibleProperty.LABEL],
                                   [widget.get_title() + ': ' + destination])
        update_target(row)
        row.connect('notify::active', update_target)
        row.connect('notify::active', lambda widget, *_: on_target(widget.get_active()))
        for icon, tooltip, callback in [('document-edit-symbolic', 'Editar atalho', on_edit),
                                         ('user-trash-symbolic', 'Remover atalho', on_remove)]:
            control = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
            control.add_css_class('flat')
            control.connect('clicked', lambda _b, cb=callback: cb())
            row.add_suffix(control)
        return row

    def build_sharing(self):
        w = self.owner
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.sharing_box = box
        w.share_group = Adw.PreferencesGroup(title='Pastas compartilhadas',
            description='As pastas aparecem em Este Computador no Windows durante a sessão.')
        box.append(w.share_group)
        w.share_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        w.share_list.add_css_class('boxed-list')
        w.share_group.add(w.share_list)
        self.empty_share_state = self.empty_shares()
        w.share_group.add(self.empty_share_state)
        self.add_share_button = button('Adicionar pasta', lambda *_: w.edit_share(),
                                       'list-add-symbolic', 'ajr-secondary')
        self.add_share_button.set_margin_top(12)
        self.add_share_button.set_halign(Gtk.Align.START)
        w.share_group.add(self.add_share_button)
        options = Adw.PreferencesGroup(title='Área de transferência')
        w.clipboard = Adw.SwitchRow(title='Compartilhar área de transferência',
                                  subtitle='Copie e cole entre este computador e o Windows.', active=w.cfg['clipboard'])
        options.add(w.clipboard)
        box.append(options)
        note = label('Pastas de rede precisam estar montadas neste computador antes de serem compartilhadas.',
                     'ajr-muted', wrap=True)
        box.append(note)
        return box

    def empty_shares(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{side}')(16)
        icon = Gtk.Image(icon_name='folder-open-symbolic', pixel_size=40)
        self.empty_share_icon = icon
        icon.add_css_class('ajr-muted')
        box.append(icon)
        title = Gtk.Label(label='Nenhuma pasta compartilhada', css_classes=['ajr-section-title'])
        box.append(title)
        box.append(Gtk.Label(label='Compartilhe uma pasta do Linux para acessá-la\ndurante a sessão Windows.',
                             wrap=True, justify=Gtk.Justification.CENTER, css_classes=['ajr-muted']))
        add = button('Adicionar pasta', lambda *_: self.owner.edit_share(),
                      'list-add-symbolic', 'ajr-secondary')
        add.set_halign(Gtk.Align.CENTER)
        add.set_margin_top(8)
        box.append(add)
        return box

    def share_row(self, share, on_edit, on_remove):
        path = Path(share['path'])
        row = Adw.ActionRow(title=path.name or share['name'],
                            subtitle=share['path'] + '\nWindows: ' + share['name'],
                            title_lines=1, subtitle_lines=0, use_markup=False)
        row.set_tooltip_text(share['path'])
        row.add_prefix(Gtk.Image(icon_name='folder-symbolic'))
        popover = Gtk.Popover()
        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        popover.set_child(actions)
        for title, icon, callback in [('Editar pasta', 'document-edit-symbolic', on_edit),
                                      ('Remover pasta', 'user-trash-symbolic', on_remove)]:
            def activate(_button, cb=callback):
                popover.popdown()
                cb()
            action = button(title, activate, icon, 'flat')
            if title == 'Remover pasta':
                action.add_css_class('ajr-delete')
            actions.append(action)
        row.add_suffix(Gtk.MenuButton(icon_name='view-more-symbolic', popover=popover,
                                       tooltip_text='Opções da pasta ' + share['name'],
                                       valign=Gtk.Align.CENTER))
        return row

    def update_summary(self):
        w = self.owner
        if not hasattr(self, 'connection_title'):
            return
        profile = next((p for p in w.cfg['profiles'] if p['id'] == w.cfg['active_profile']), None)
        self.connection_title.set_text(w.profile_name.get_text().strip() or
                                      (profile['name'] if profile else 'Nova conexão'))
        self.connection_title.set_tooltip_text(self.connection_title.get_text())
        server, user = w.server.get_text().strip(), w.user.get_text().strip()
        self.connection_meta.set_text(f'{server} · {user}' if server and user else
                                      server or 'Servidor não informado.')
        self.connection_meta.set_tooltip_text(self.connection_meta.get_text())

    def update_status(self, title, icon):
        busy = title.startswith(('Conectando', 'Aguardando', 'Reconectando'))
        if busy:
            self.owner.connect_btn.remove_css_class('suggested-action')
        self.spinner.set_visible(busy)
        self.spinner.set_spinning(busy)
        online = icon == 'network-transmit-receive-symbolic'
        for css in ('ajr-online', 'ajr-offline'):
            self.owner.status.remove_css_class(css)
        self.owner.status.add_css_class('ajr-online' if online else 'ajr-offline')
        if title.startswith('Conectado'):
            name = self.owner.profile_name.get_text().strip() or self.owner.cfg['server']
            self.owner.status.set_title('Conectado a ' + name)

    def integration_changed(self, ready):
        self.integration_label.set_text('AJR Bar conectada' if ready else 'Controles no aplicativo')
