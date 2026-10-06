"""AJR desktop presentation. Session, profile and keyring logic live in ajr_app."""
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Pango
from dialogs import ShortcutEditor

ASSETS = Path(__file__).resolve().parent / 'assets'

PALETTES = {
    'dark': dict(window='#111219', surface='#191a24', sidebar='#15161e',
                 raised='#222330', text='#f3f2fa', muted='#aaaabd', border='#353648',
                 accent='#a99aff', button='#8974ed', on_button='#11101c',
                 selection='#302941', success='#85dbb4', danger='#ffabae', control='#666276'),
    'light': dict(window='#f4f3f8', surface='#ffffff', sidebar='#ebe9f2',
                  raised='#f0eef7', text='#242236', muted='#656178', border='#d3cedf',
                  accent='#5d43bf', button='#694acb', on_button='#ffffff',
                  selection='#e1d9fa', success='#217248', danger='#b22c41', control='#847e94'),
}


def label(text, css=None, wrap=False):
    widget = Gtk.Label(label=text, xalign=0, wrap=wrap)
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
    box.add_css_class('ajr-section')
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
        self.title = label('Configure sua conexão', 'ajr-status-title')
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
        logs = Gtk.Button(icon_name='text-x-generic-symbolic', tooltip_text='Abrir registros da conexão')
        logs.connect('clicked', lambda *_: w.open_logs())
        header.pack_end(logs)
        self.updates_button = Gtk.Button(icon_name='software-update-available-symbolic',
                                         tooltip_text='Atualizações do aplicativo')
        self.updates_button.connect('clicked', lambda *_: w.open_updates())
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
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 860px'))
        breakpoint.add_setter(self.split, 'collapsed', True)
        breakpoint.add_setter(self.sidebar_toggle, 'visible', True)
        breakpoint.add_setter(self.compact_profiles, 'visible', True)
        self.sidebar_toggle.set_visible(False)
        self.compact_profiles.set_visible(False)
        w.add_breakpoint(breakpoint)
        self.update_theme()
        w.form.connect('notify::sensitive', lambda *_:
                       self.profile_area.set_sensitive(w.form.get_sensitive()))
        w.form.connect('notify::sensitive', lambda *_:
                       self.compact_profiles.set_sensitive(w.form.get_sensitive()))
        for field in (w.profile_name, w.server, w.user):
            field.connect('changed', lambda *_: self.update_summary())
        w.monitor.connect('notify::selected', lambda *_: self.update_summary())
        w.fullscreen.connect('notify::active', lambda *_: self.update_summary())

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
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        sidebar.add_css_class('ajr-sidebar')
        brand = Gtk.Box(spacing=12)
        mark = Gtk.Image.new_from_file(str(ASSETS / 'ajr-connect.svg'))
        mark.set_pixel_size(42)
        brand.append(mark)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, valign=Gtk.Align.CENTER)
        words.append(label('AJR', 'ajr-brand-title'))
        words.append(label('C O N N E C T', 'ajr-brand-subtitle'))
        brand.append(words)
        sidebar.append(brand)
        self.profile_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, vexpand=True)
        sidebar.append(self.profile_area)
        self.profile_area.append(button('Nova conexão', w.new_profile, 'list-add-symbolic', 'ajr-new'))
        caption = Gtk.Box(spacing=8)
        caption.append(label('SUAS CONEXÕES', 'ajr-eyebrow'))
        self.profile_count = Gtk.Label(label='0', css_classes=['ajr-count'])
        caption.append(self.profile_count)
        self.profile_area.append(caption)
        self.search = Gtk.SearchEntry(placeholder_text='Buscar conexão')
        self.search.add_css_class('ajr-search')
        self.search.connect('search-changed', lambda *_: self.render_profiles())
        self.profile_area.append(self.search)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                   min_content_height=120)
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
        navigation.add_css_class('ajr-navigation')
        navigation_clamp.set_child(navigation)
        view.add_top_bar(navigation_clamp)

        hero = Gtk.Box(spacing=24)
        self.hero = hero
        hero.add_css_class('ajr-hero')
        visual = Gtk.Image.new_from_file(str(ASSETS / 'workspace.svg'))
        visual.set_pixel_size(96)
        hero.append(visual)
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9, hexpand=True,
                          valign=Gtk.Align.CENTER)
        self.connection_title = label('Nova conexão', 'ajr-hero-title', wrap=True)
        details.append(self.connection_title)
        self.connection_meta = label('Servidor não informado.', 'ajr-muted', wrap=True)
        details.append(self.connection_meta)
        self.share_summary = label('Nenhuma pasta compartilhada', 'ajr-field-hint', wrap=True)
        details.append(self.share_summary)
        hero.append(details)

        self.compact_profiles = Gtk.Box(spacing=12)
        self.compact_profiles.append(label('Conexão salva', 'ajr-field-label'))
        w.profile = Gtk.DropDown(hexpand=True)
        w.profile.update_property([Gtk.AccessibleProperty.LABEL], ['Conexões salvas'])
        self.compact_profiles.append(w.profile)
        self.compact_profiles.append(button('Nova', w.new_profile, 'list-add-symbolic'))
        navigation.append(self.compact_profiles)

        tabs = Gtk.Box(spacing=4, homogeneous=True)
        tabs.add_css_class('ajr-tabs')
        w.form = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                           transition_duration=140, vhomogeneous=False, vexpand=True)
        self.tab_buttons = {}
        for key, title, icon in [('connection', 'Conexão', 'network-server-symbolic'),
                                  ('display', 'Tela e teclado', 'video-display-symbolic'),
                                  ('sharing', 'Compartilhamento', 'folder-symbolic')]:
            tab = Gtk.ToggleButton()
            tab_box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            tab_box.append(Gtk.Image(icon_name=icon))
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
        pages = [('connection', self.build_connection()),
                 ('display', self.build_display()),
                 ('sharing', self.build_sharing())]
        for name, body in pages:
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            clamp = Adw.Clamp(maximum_size=840, tightening_threshold=720)
            scroll.set_child(clamp)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
            content.add_css_class('ajr-workspace')
            clamp.set_child(content)
            if name == 'connection':
                content.append(hero)
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
        footer.append(w.controls)
        w.error = label('', 'ajr-error', wrap=True)
        w.error.set_focusable(True)
        w.error.set_visible(False)
        footer.append(w.error)
        w.status = StatusCard()
        w.status_icon = w.status.icon
        footer.append(w.status)
        row = Gtk.Box(spacing=16)
        self.monitor_summary = label('Selecione um monitor em Tela e teclado.', 'ajr-field-hint', wrap=True)
        self.monitor_summary.set_hexpand(True)
        row.append(self.monitor_summary)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        row.append(self.spinner)
        w.connect_btn = Gtk.Button(label='Conectar ao Windows', height_request=46, width_request=210)
        w.connect_btn.add_css_class('suggested-action')
        w.connect_btn.add_css_class('ajr-connect')
        w.connect_btn.connect('clicked', lambda *_: w.do_connect())
        row.append(w.connect_btn)
        footer.append(row)
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
        box = section('Dados de acesso')
        headings = box.get_first_child()
        box.remove(headings)
        top = Gtk.Box(spacing=12)
        headings.set_hexpand(True)
        top.append(headings)
        w.profile_delete = Gtk.Button(icon_name='user-trash-symbolic', tooltip_text='Excluir conexão',
                                      valign=Gtk.Align.CENTER)
        w.profile_delete.add_css_class('ajr-delete')
        w.profile_delete.connect('clicked', w.delete_profile)
        top.append(w.profile_delete)
        top.append(button('Salvar conexão', w.save_profile, 'document-save-symbolic', 'ajr-secondary'))
        box.append(top)
        identity = Gtk.Box(spacing=16, homogeneous=True)
        field, w.profile_name = entry_field('Nome da conexão')
        w.profile_name.set_placeholder_text('Ex.: Meu escritório')
        identity.append(field)
        field, w.server = entry_field('Servidor', w.cfg['server'])
        w.server.set_placeholder_text('IP ou domínio:porta')
        identity.append(field)
        box.append(identity)
        credentials = Gtk.Box(spacing=16, homogeneous=True)
        field, w.user = entry_field('Usuário', w.cfg['user'])
        credentials.append(field)
        field, w.password = entry_field('Senha', password=True)
        credentials.append(field)
        box.append(credentials)
        w.remember = Adw.SwitchRow(title='Lembrar senha', subtitle='Guardada no chaveiro deste computador.',
                                   active=w.cfg['remember'])
        remember = Adw.PreferencesGroup()
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
        keyboard = Adw.PreferencesGroup(title='Prioridade dos atalhos')
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
        w.keyboard_note = Adw.ActionRow(title='Ativado: Windows · Desativado: este computador', subtitle_lines=0)
        keyboard.add(w.keyboard_note)
        rules = Adw.PreferencesGroup(title='Outras combinações',
            description='Defina a prioridade de áreas de trabalho, atalhos do sistema e combinações personalizadas.')
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

    def build_sharing(self):
        w = self.owner
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        w.share_group = Adw.PreferencesGroup(title='Pastas compartilhadas',
            description='As pastas aparecem em Este Computador no Windows durante a sessão.')
        box.append(w.share_group)
        w.share_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        w.share_list.add_css_class('boxed-list')
        w.share_group.add(w.share_list)
        add = button('Adicionar pasta', lambda *_: w.edit_share(), 'list-add-symbolic', 'ajr-secondary')
        add.set_margin_top(12)
        w.share_group.add(add)
        options = Adw.PreferencesGroup()
        w.clipboard = Adw.SwitchRow(title='Compartilhar área de transferência',
                                  subtitle='Copie e cole entre este computador e o Windows.', active=w.cfg['clipboard'])
        options.add(w.clipboard)
        box.append(options)
        note = label('Pastas de rede precisam estar montadas neste computador antes de serem compartilhadas.',
                     'ajr-muted', wrap=True)
        box.append(note)
        return box

    def empty_shares(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(box, f'set_margin_{side}')(28)
        icon = Gtk.Image(icon_name='folder-open-symbolic', pixel_size=40)
        icon.add_css_class('accent')
        box.append(icon)
        title = Gtk.Label(label='Nenhuma pasta compartilhada', css_classes=['ajr-section-title'])
        box.append(title)
        return box

    def update_summary(self):
        w = self.owner
        if not hasattr(self, 'connection_title'):
            return
        profile = next((p for p in w.cfg['profiles'] if p['id'] == w.cfg['active_profile']), None)
        self.connection_title.set_text(w.profile_name.get_text().strip() or
                                      (profile['name'] if profile else 'Nova conexão'))
        server, user = w.server.get_text().strip(), w.user.get_text().strip()
        self.connection_meta.set_text(f'{user} em {server}' if server and user else
                                      server or 'Servidor não informado.')
        count = len(w.cfg['shares'])
        self.share_summary.set_text(f'{count} pasta' + ('s compartilhadas' if count != 1 else ' compartilhada')
                                    if count else 'Nenhuma pasta compartilhada')
        index = w.monitor.get_selected()
        if index < len(getattr(w, 'monitors', [])):
            monitor = w.monitors[index]
            mode = 'Tela cheia' if w.fullscreen.get_active() else 'Modo janela'
            self.monitor_summary.set_text(f"{monitor['connector']} · {monitor['width']} × {monitor['height']}\n{mode}")
        else:
            self.monitor_summary.set_text('Selecione um monitor em Tela e teclado.')

    def update_status(self, title, icon):
        busy = title.startswith(('Conectando', 'Aguardando', 'Reconectando'))
        self.spinner.set_visible(busy)
        self.spinner.set_spinning(busy)
        online = icon == 'network-transmit-receive-symbolic'
        for css in ('ajr-online', 'ajr-offline'):
            self.owner.status.remove_css_class(css)
        self.owner.status.add_css_class('ajr-online' if online else 'ajr-offline')

    def integration_changed(self, ready):
        self.integration_label.set_text('AJR Bar conectada' if ready else 'Controles no aplicativo')
