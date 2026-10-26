"""Background session presence via desktop notifications (GTK4-safe).

A classic AppIndicator menu needs GTK3 widgets and conflicts with this GTK4
process, so hide-to-background uses Gio.Notification with Show/Quit actions.
"""
from gi.repository import Gio


class TrayController:
    def __init__(self, owner):
        self.owner = owner
        self._notified = False
        self._connected = False

    @property
    def available(self):
        return False

    def set_connected(self, connected):
        self._connected = bool(connected)

    def show_window(self):
        window = self.owner
        window.set_visible(True)
        window.present()
        app = window.get_application()
        if app:
            app.withdraw_notification('ajr-background')
        self._notified = False

    def disconnect(self):
        if self.owner.connection_busy():
            self.owner.cancel_connection()
        self.show_window()

    def hide_to_background(self):
        if self.owner._closing:
            return
        app = self.owner.get_application()
        if not app:
            return
        self._notified = True
        title = 'AJR Connect continua em execução'
        body = ('A sessão Windows permanece aberta. Abra a notificação para mostrar a janela '
                'ou sair do aplicativo.') if self._connected else \
               ('O AJR continua em segundo plano. Abra a notificação para mostrar a janela '
                'ou sair.')
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_default_action('app.show-window')
        notification.add_button('Mostrar janela', 'app.show-window')
        if self._connected:
            notification.add_button('Desconectar', 'app.disconnect-session')
        notification.add_button('Sair', 'app.quit')
        app.send_notification('ajr-background', notification)

    def dispose(self):
        getter = getattr(self.owner, 'get_application', None)
        app = getter() if callable(getter) else None
        if app:
            app.withdraw_notification('ajr-background')
        self._notified = False
