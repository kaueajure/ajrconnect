"""Local machine selection and power controls, with automatic system authorization."""
import threading
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk, GLib
import vm_control


class MachineWindow(Adw.Window):
    def __init__(self, owner):
        super().__init__(transient_for=owner, modal=True, title='Máquinas deste computador',
                         default_width=560, default_height=520)
        self.owner = owner
        self.machines, self.restricted, self.authorized = [], [], set()
        self.elevate_attempted = set()
        self.busy = self.closed = False
        self.add_css_class('ajr-dialog')
        self.connect('close-request', self.close_requested)
        shell = Adw.ToolbarView()
        shell.add_top_bar(Adw.HeaderBar())
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                       margin_top=20, margin_bottom=20, margin_start=20, margin_end=20)
        scroll.set_child(body)
        shell.set_content(scroll)
        self.set_content(shell)
        description = Gtk.Label(label='Encontre a VM ou o contêiner que hospeda o Windows neste computador '
            'e vincule à conexão atual. A busca só consulta gerenciadores locais (Docker, Podman, '
            'libvirt, VirtualBox), incluindo máquinas paradas — não encontra VMs hospedadas em outro PC. '
            'Se faltar permissão, o próprio AJR pede autorização ao Linux.',
            wrap=True, xalign=0)
        body.append(description)
        self.selection = Adw.ComboRow(title='Máquina encontrada',
                                      model=Gtk.StringList.new([]), use_subtitle=True)
        self.selection.connect('notify::selected', lambda *_: self.update_controls())
        group = Adw.PreferencesGroup()
        group.add(self.selection)
        body.append(group)
        self.binding = Gtk.Label(wrap=True, xalign=0)
        body.append(self.binding)
        self.link = Gtk.Button(label='Usar nesta conexão')
        self.link.connect('clicked', self.bind)
        body.append(self.link)
        row = Gtk.Box(spacing=12, homogeneous=True)
        self.start = Gtk.Button(label='Ligar Windows', height_request=44)
        self.start.add_css_class('suggested-action')
        self.start.connect('clicked', lambda *_: self.request_power('start'))
        self.stop = Gtk.Button(label='Desligar Windows', height_request=44)
        self.stop.add_css_class('destructive-action')
        self.stop.connect('clicked', lambda *_: self.request_power('stop'))
        row.append(self.start)
        row.append(self.stop)
        body.append(row)
        self.spinner = Gtk.Spinner()
        body.append(self.spinner)
        self.message = Gtk.Label(wrap=True, xalign=0, selectable=True)
        body.append(self.message)
        self.refresh = Gtk.Button(label='Buscar máquinas')
        self.refresh.connect('clicked', lambda *_: self.scan())
        body.append(self.refresh)
        self.authorize = Gtk.Button(label='Tentar autorização novamente')
        self.authorize.connect('clicked', self.authorize_scan)
        body.append(self.authorize)
        self.unlink = Gtk.Button(label='Remover vínculo desta conexão')
        self.unlink.connect('clicked', self.remove_binding)
        body.append(self.unlink)
        self.update_controls()
        self.scan()

    def selected_machine(self):
        index = self.selection.get_selected()
        return self.machines[index] if index < len(self.machines) else None

    def is_bound(self, machine):
        return machine is not None and (machine.backend, machine.identifier) == \
            (self.owner.cfg['vm_backend'], self.owner.cfg['vm_id'])

    def update_controls(self):
        machine = self.selected_machine()
        bound = self.is_bound(machine)
        self.selection.set_sensitive(not self.busy and bool(self.machines))
        self.link.set_sensitive(not self.busy and machine is not None and not bound)
        self.start.set_sensitive(not self.busy and bound and machine.state in ('exited', 'created', 'stopped', 'shut off'))
        self.stop.set_sensitive(not self.busy and bound and machine.state == 'running')
        self.refresh.set_sensitive(not self.busy)
        failed = set(self.restricted) & self.elevate_attempted
        self.authorize.set_visible(bool(failed) and not self.machines)
        self.authorize.set_sensitive(not self.busy)
        self.unlink.set_sensitive(not self.busy and bool(self.owner.cfg['vm_id']))
        self.binding.set_text('Vinculada: ' + self.owner.cfg['vm_name'] if self.owner.cfg['vm_id'] else
                              'Nenhuma máquina vinculada. Selecione e escolha “Usar nesta conexão”.')
        if machine:
            states = {'running': 'Ligada', 'exited': 'Parada', 'created': 'Parada',
                      'stopped': 'Parada', 'shut off': 'Desligada'}
            state = states.get(machine.state, machine.state or 'Estado desconhecido')
            self.selection.set_subtitle(machine.label + ' · ' + state)
        else:
            self.selection.set_subtitle('Nenhuma seleção')
        self.spinner.set_visible(self.busy)
        self.spinner.set_spinning(self.busy)

    def work(self, callback, complete, message):
        if self.busy:
            return
        self.busy = True
        self.message.set_text(message)
        self.update_controls()
        def worker():
            try:
                result, error = callback(), None
            except Exception as exc:
                result, error = None, exc
            def finish():
                if self.closed:
                    return GLib.SOURCE_REMOVE
                self.busy = False
                complete(result, error)
                self.update_controls()
                return GLib.SOURCE_REMOVE
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=True).start()

    def scan(self, result_message=''):
        def complete(result, error):
            if error:
                self.message.set_text(str(error))
                return
            self.machines, notices, self.restricted = result
            self.selection.set_model(Gtk.StringList.new([machine.label for machine in self.machines]))
            index = next((i for i, machine in enumerate(self.machines) if self.is_bound(machine)),
                         Gtk.INVALID_LIST_POSITION)
            self.selection.set_selected(index)
            pending = [backend for backend in self.restricted if backend not in self.elevate_attempted]
            if pending:
                self.elevate_attempted.update(pending)
                self.authorized.update(pending)
                self.scan('O Linux pedirá sua senha para o AJR acessar o Docker/VM. A senha não é salva.')
                return
            text = f'{len(self.machines)} máquina(s) encontrada(s) neste computador. Selecione a que hospeda o Windows.' if self.machines else \
                   'Nenhuma máquina encontrada neste computador.'
            if self.restricted and not self.machines:
                text += '\n\nA autorização foi cancelada ou negada. Use “Tentar autorização novamente”.'
            self.message.set_text('\n\n'.join(part for part in [result_message, text, *notices] if part))
            if self.machines and any(machine.backend.startswith('docker') for machine in self.machines):
                self.finish_docker_access()
        self.work(lambda: vm_control.discover(self.authorized), complete, 'Buscando máquinas neste computador…')

    def finish_docker_access(self):
        if getattr(self, '_docker_access_done', False) or vm_control.docker_group_configured():
            return
        self._docker_access_done = True

        def complete(changed, error):
            if self.closed:
                return
            if error:
                self._docker_access_done = False
                return
            if changed:
                current = self.message.get_text()
                note = 'Acesso permanente ao Docker configurado. Após reiniciar a sessão do Linux, ' \
                       'o AJR não precisará pedir senha de novo.'
                self.message.set_text((current + '\n\n' + note).strip())

        self.work(vm_control.ensure_docker_group, complete,
                  'Configurando acesso permanente ao Docker…')

    def authorize_scan(self, *_):
        self.elevate_attempted.clear()
        self.authorized.update(self.restricted)
        self.elevate_attempted.update(self.restricted)
        self.scan('O Linux pedirá sua senha para o AJR acessar o Docker/VM. A senha não é salva.')

    def bind(self, *_):
        machine = self.selected_machine()
        if self.busy or not machine:
            return
        self.owner.cfg.update(vm_backend=machine.backend, vm_id=machine.identifier, vm_name=machine.name)
        self.owner.persist()
        self.update_controls()

    def remove_binding(self, *_):
        if self.busy:
            return
        self.owner.cfg.update(vm_backend='', vm_id='', vm_name='')
        self.owner.persist()
        self.update_controls()

    def request_power(self, action):
        machine = self.selected_machine()
        if self.busy or not self.is_bound(machine) or self.owner._updating:
            return
        if action == 'start':
            self.execute(machine, action)
            return
        container = machine.backend.startswith('docker') or machine.backend == 'podman'
        body = (f'O contêiner “{machine.name}” será parado. Salve seus arquivos. '
                'O gerenciador aguardará até 120 segundos antes de forçar a parada.') if container else \
               (f'Será solicitado o desligamento de “{machine.name}” ao sistema convidado. Salve seus arquivos.')
        body += ' A sessão AJR será desconectada e a reconexão automática será cancelada.'
        dialog = Adw.MessageDialog(transient_for=self, modal=True,
                                  heading='Desligar esta máquina?', body=body)
        dialog.add_response('cancel', 'Cancelar')
        dialog.add_response('stop', 'Desligar Windows')
        dialog.set_response_appearance('stop', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response', lambda _dialog, response:
                       self.execute(machine, action) if response == 'stop' else None)
        dialog.present()

    def execute(self, machine, action, *, elevated=None):
        if self.busy or self.closed or not self.is_bound(machine) or self.owner._updating:
            return
        if elevated is None:
            elevated = machine.backend in self.authorized
        if action == 'stop' and self.owner.connection_busy():
            self.owner.cancel_connection()
        self.owner._machine_action = True

        def complete(_result, error):
            self.owner._machine_action = False
            if isinstance(error, vm_control.VMError) and error.permission \
                    and machine.backend in vm_control.ELEVATABLE and not elevated:
                self.authorized.add(machine.backend)
                self.message.set_text('O Linux pedirá sua senha para controlar a máquina.')
                self.execute(machine, action, elevated=True)
            elif error:
                self.message.set_text(str(error))
            else:
                self.scan('Inicialização solicitada. Aguarde o Windows iniciar antes de conectar.' if action == 'start' else
                          'Desligamento solicitado. Atualize a busca para conferir o estado da máquina.')

        self.work(lambda: vm_control.power(machine, action, elevated=elevated), complete,
                  'Ligando a máquina…' if action == 'start' else 'Desligando a máquina…')

    def close_requested(self, *_):
        if self.owner._machine_action:
            return True
        self.closed = True
        if self.owner._machine_window is self:
            self.owner._machine_window = None
        return False
