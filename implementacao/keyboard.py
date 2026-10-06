"""Canonical accelerators and the native keyboard-rule protocol."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk

MAX_RULES = 128
PRESETS = (
    ('Área de trabalho à esquerda', '<Control><Alt>Left'),
    ('Área de trabalho à direita', '<Control><Alt>Right'),
    ('Área de trabalho acima', '<Control><Alt>Up'),
    ('Área de trabalho abaixo', '<Control><Alt>Down'),
    ('Área de trabalho: Super + Ctrl + esquerda', '<Super><Control>Left'),
    ('Área de trabalho: Super + Ctrl + direita', '<Super><Control>Right'),
    ('Visão das áreas de trabalho', '<Super>Tab'),
    ('Mostrar área de trabalho', '<Super>d'),
    ('Bloquear sessão', '<Super>l'),
    ('Executar comando', '<Alt>F2'),
    ('Captura de tela', 'Print'),
)


def shortcut_parts(value, *, routing=False):
    valid, key, modifiers = Gtk.accelerator_parse(value)
    allowed = Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK | \
              Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK
    if not valid or not key or modifiers & ~allowed or Gdk.keyval_name(key) in (
            'Control_L', 'Control_R', 'Alt_L', 'Alt_R', 'Super_L', 'Super_R',
            'Shift_L', 'Shift_R', 'Meta_L', 'Meta_R'):
        raise ValueError('Informe uma tecla ou combinação válida.')
    if not routing and (not Gtk.accelerator_valid(key, modifiers) or not modifiers & (
            Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)):
        raise ValueError('Escolha uma combinação com Ctrl, Alt ou Super e uma tecla.')
    # ISO_Left_Tab is Shift+Tab on X11, not a separate routing key.
    if key == Gdk.KEY_ISO_Left_Tab:
        key, modifiers = Gdk.KEY_Tab, modifiers | Gdk.ModifierType.SHIFT_MASK
    return Gdk.keyval_to_lower(key), modifiers


def canonical(value, *, routing=True):
    return Gtk.accelerator_name(*shortcut_parts(value, routing=routing))


def shortcut_text(value):
    key, modifiers = shortcut_parts(value, routing=True)
    parts = [name for name, mask in (('Ctrl', Gdk.ModifierType.CONTROL_MASK),
             ('Alt', Gdk.ModifierType.ALT_MASK), ('Shift', Gdk.ModifierType.SHIFT_MASK),
             ('Super', Gdk.ModifierType.SUPER_MASK)) if modifiers & mask]
    parts.append(Gdk.keyval_name(key))
    return ' + '.join(parts)


def parse_shortcut_text(value, *, routing=False):
    value = value.strip()
    if value.startswith('<'):
        return canonical(value, routing=routing)
    parts = [part.strip() for part in value.split('+')]
    aliases = {'ctrl': 'Control', 'control': 'Control', 'alt': 'Alt',
               'shift': 'Shift', 'super': 'Super', 'win': 'Super', 'windows': 'Super'}
    modifiers = []
    for part in parts[:-1]:
        name = aliases.get(part.casefold())
        if name is None or name in modifiers:
            raise ValueError('Use Ctrl, Alt, Shift ou Super antes da tecla.')
        modifiers.append(name)
    names = {'esquerda': 'Left', 'direita': 'Right', 'cima': 'Up', 'baixo': 'Down',
             'enter': 'Return', 'esc': 'Escape', 'espaço': 'space', 'space': 'space',
             'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
             'tab': 'Tab', 'delete': 'Delete', 'backspace': 'BackSpace',
             'print': 'Print', 'home': 'Home', 'end': 'End', 'pageup': 'Page_Up',
             'pagedown': 'Page_Down', 'plus': 'plus'}
    key = names.get(parts[-1].casefold(), parts[-1])
    if key.lower().startswith('f') and key[1:].isdigit():
        key = key.upper()
    return canonical(''.join(f'<{name}>' for name in modifiers) + key, routing=routing)


def x11_modifiers(modifiers):
    return int(modifiers) & 13 | (64 if modifiers & Gdk.ModifierType.SUPER_MASK else 0)


def validate_rules(rules, fullscreen_shortcut):
    if len(rules) > MAX_RULES:
        raise ValueError(f'Use no máximo {MAX_RULES} regras de teclado.')
    seen = set()
    reserved = canonical(fullscreen_shortcut)
    # These already have dedicated controls; Shift+Alt+Tab may be overridden.
    builtins = {canonical('<Alt>Tab'), canonical('<Alt>F4')}
    result = []
    for rule in rules:
        value = canonical(rule['accelerator'])
        if value in seen:
            raise ValueError('Já existe uma regra para ' + shortcut_text(value) + '.')
        if value == reserved:
            raise ValueError('Essa combinação já é o atalho de tela cheia.')
        if value in builtins:
            raise ValueError('Use a opção de ' + shortcut_text(value) + ' na lista de atalhos.')
        seen.add(value)
        result.append(dict(accelerator=value, remote=rule['remote']))
    return result


def native_rules(rules, fullscreen_shortcut):
    return ';'.join(f'{key}:{x11_modifiers(modifiers)}:{int(rule["remote"])}'
        for rule in validate_rules(rules, fullscreen_shortcut)
        for key, modifiers in [shortcut_parts(rule['accelerator'], routing=True)])
