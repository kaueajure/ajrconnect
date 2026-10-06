/* Exercise the actual frontend keyboard handlers on an isolated X server. */
#include <assert.h>
#include <cairo/cairo-xlib.h>
#include <stdio.h>
#include <string.h>
#include <X11/Xatom.h>
#include <X11/keysym.h>
#include <freerdp/locale/keyboard.h>
#include <freerdp/event.h>
#include "ajr.h"
#include "xf_event.h"
#include "xf_keyboard.h"

static unsigned sent;
static UINT16 last_code;
static BOOL keyboard_event(rdpInput* input, UINT16 flags, UINT16 code)
{
    (void)input; (void)flags;
    sent++; last_code = code;
    return TRUE;
}
static BOOL sync_event(rdpInput* input, UINT32 flags)
{
    (void)input; (void)flags;
    return TRUE;
}
static void event_state(xfContext* xfc, int type, KeySym sym, unsigned int state)
{
    XEvent e = {0};
    e.xkey.type = type;
    e.xkey.display = xfc->display;
    e.xkey.window = xfc->window->handle;
    e.xkey.keycode = XKeysymToKeycode(xfc->display, sym);
    e.xkey.state = state;
    assert(xf_event_process(xfc->context.instance, &e));
}
static void event(xfContext* xfc, int type, KeySym sym)
{
    event_state(xfc, type, sym, 0);
}
static void local_request(xfContext* xfc, unsigned long action, BOOL reverse)
{
    Atom type; int format;
    unsigned long count, remaining;
    unsigned char* bytes = NULL;
    assert(XGetWindowProperty(xfc->display, xfc->window->handle,
        XInternAtom(xfc->display, "_AJR_LOCAL_KEYS_V1", False), 0, 10,
        True, XA_CARDINAL, &type, &format, &count, &remaining, &bytes) == Success);
    assert(bytes && format == 32 && count == 2);
    assert(((unsigned long*)bytes)[0] == action);
    assert(((unsigned long*)bytes)[1] == (unsigned long)reverse);
    XFree(bytes);
    assert(xfc->ajr_local_pending && !xfc->ajr_grabbed);
}
static void resume(xfContext* xfc)
{
    XClientMessageEvent command = {0};
    command.window = xfc->window->handle;
    command.message_type = XInternAtom(xfc->display, "_AJR_CONTROL_V1", False);
    command.format = 32;
    command.data.l[0] = 6;
    command.data.l[1] = xfc->ajr_token;
    assert(xf_ajr_control(xfc, &command));
    assert(!xfc->ajr_local_pending && xfc->ajr_grabbed);
}
static void fullscreen_property(xfContext* xfc, BOOL fullscreen)
{
    Atom atom = xfc->_NET_WM_STATE_FULLSCREEN;
    XChangeProperty(xfc->display, xfc->window->handle, xfc->_NET_WM_STATE,
        XA_ATOM, 32, PropModeReplace, (unsigned char*)&atom, fullscreen ? 1 : 0);
    XSync(xfc->display, False);
    xf_ajr_sync(xfc);
}
static void probe(xfContext* xfc, Display* other, BOOL captured)
{
    int result = XGrabKeyboard(other, xfc->window->handle, False,
                              GrabModeAsync, GrabModeAsync, CurrentTime);
    assert(result == (captured ? AlreadyGrabbed : GrabSuccess));
    if (!captured) XUngrabKeyboard(other, CurrentTime);
    XSync(other, False);
}
int main(void)
{
    xfContext xfc = {0};
    xfWindow window = {0};
    freerdp instance = {0};
    rdpInput input = {0};
    xfc.display = XOpenDisplay(NULL);
    Display* other = XOpenDisplay(NULL);
    assert(xfc.display && other);
    xfc.context.settings = freerdp_settings_new(0);
    assert(xfc.context.settings);
    xfc.context.settings->DesktopWidth = 800;
    xfc.context.settings->DesktopHeight = 600;
    xfc.context.settings->DesktopPosX = 0;
    xfc.context.settings->DesktopPosY = 0;
    xfc.context.input = &input;
    xfc.context.pubSub = PubSub_New(FALSE);
    assert(xfc.context.pubSub);
    xfc.context.instance = &instance;
    instance.context = &xfc.context;
    input.context = &xfc.context;
    input.KeyboardEvent = keyboard_event;
    input.SynchronizeEvent = sync_event;
    xfc.screen = DefaultScreenOfDisplay(xfc.display);
    xfc.modifierMap = XGetModifierMapping(xfc.display);
    xfc.window = &window;
    window.width = 400; window.height = 300;
    window.handle = XCreateSimpleWindow(xfc.display, DefaultRootWindow(xfc.display),
                                       0, 0, 400, 300, 0, 0, 0);
    XMapWindow(xfc.display, window.handle);
    XSetInputFocus(xfc.display, window.handle, RevertToPointerRoot, CurrentTime);
    XSync(xfc.display, False);
    xfc._NET_WM_STATE = XInternAtom(xfc.display, "_NET_WM_STATE", False);
    xfc._NET_WM_STATE_FULLSCREEN = XInternAtom(xfc.display, "_NET_WM_STATE_FULLSCREEN", False);
    freerdp_keyboard_init(0);
    xfc.grab_keyboard = xfc.focused = TRUE;
    setenv("AJR_CONTROL_TOKEN", "1234abcd", 1);
    setenv("AJR_KEYBOARD_RULES", "65361:12:0;65363:12:1;65289:9:1;100:64:0", 1);
    xf_ajr_init(&xfc);
    assert(xfc.ajr_rule_count == 4);
    xfc.ajr_rule_count = 0; /* Preserve the original built-in routing tests. */
    fullscreen_property(&xfc, FALSE);
    assert(!xfc.ajr_grabbed);
    probe(&xfc, other, FALSE);
    fullscreen_property(&xfc, TRUE);
    assert(xfc.ajr_grabbed);  /* Pointer need not be inside on entry. */
    probe(&xfc, other, TRUE);
    /* A compositor grab notification must never change logical focus or
     * release the grab. Previously these edges formed an endless feedback loop. */
    for (unsigned iteration = 0; iteration < 100; iteration++)
    {
        int modes[] = { NotifyGrab, NotifyUngrab };
        for (unsigned m = 0; m < 2; m++)
        {
            XEvent focus = {0};
            focus.xfocus.window = window.handle;
            focus.xfocus.mode = modes[m];
            focus.xfocus.type = FocusOut;
            assert(xf_event_process(&instance, &focus));
            assert(xfc.focused && xfc.ajr_grabbed);
            focus.xfocus.type = FocusIn;
            assert(xf_event_process(&instance, &focus));
            assert(xfc.focused && xfc.ajr_grabbed);
        }
    }
    probe(&xfc, other, TRUE);
    XEvent leave = {0};
    leave.xcrossing.type = LeaveNotify;
    leave.xcrossing.window = window.handle;
    assert(xf_event_process(&instance, &leave));
    assert(!xfc.mouse_active && xfc.ajr_grabbed);
    probe(&xfc, other, TRUE);
    for (unsigned i = 0; i < 3; i++)
    {
        event(&xfc, KeyPress, XK_Control_R);
        assert(last_code == 0x1d);
        event(&xfc, KeyRelease, XK_Control_R);
        assert(xfc.ajr_grabbed);
        probe(&xfc, other, TRUE);
    }
    unsigned before = sent;
    event(&xfc, KeyPress, XK_Super_L);
    assert(last_code == 0x5b);
    event(&xfc, KeyPress, XK_r);
    assert(last_code == 0x13);
    event(&xfc, KeyRelease, XK_r);
    event(&xfc, KeyRelease, XK_Super_L);
    event(&xfc, KeyPress, XK_Alt_L);
    event(&xfc, KeyPress, XK_Tab);
    assert(last_code == 0x0f);
    event(&xfc, KeyRelease, XK_Tab);
    event(&xfc, KeyRelease, XK_Alt_L);
    assert(sent == before + 8);
    assert(xfc.ajr_grabbed);
    /* Individual local shortcuts must never send their triggering key to RDP. */
    xfc.ajr_remote_keys = 0;
    event(&xfc, KeyPress, XK_Alt_L);
    before = sent;
    event_state(&xfc, KeyPress, XK_Tab, Mod1Mask | ShiftMask);
    local_request(&xfc, 1, TRUE);
    assert(sent == before + 1); /* Release the remote Alt modifier. */
    before = sent;
    event_state(&xfc, KeyPress, XK_Tab, Mod1Mask | ShiftMask);
    event_state(&xfc, KeyRelease, XK_Tab, Mod1Mask | ShiftMask);
    assert(sent == before); /* Swallow repeat and matching release. */
    event(&xfc, KeyPress, XK_Alt_L);
    event_state(&xfc, KeyPress, XK_Tab, Mod1Mask);
    event_state(&xfc, KeyRelease, XK_Tab, Mod1Mask);
    event(&xfc, KeyRelease, XK_Alt_L);
    assert(sent == before); /* No portal replay modifier leaks to Windows. */
    event(&xfc, KeyRelease, XK_Alt_L);
    probe(&xfc, other, FALSE);
    resume(&xfc);
    before = sent;
    event(&xfc, KeyPress, XK_Super_L);
    event(&xfc, KeyRelease, XK_Super_L);
    assert(sent == before);
    local_request(&xfc, 2, FALSE);
    resume(&xfc);
    /* Super by itself is local; Super+R still reaches the Windows desktop. */
    before = sent;
    event(&xfc, KeyPress, XK_Super_L);
    event_state(&xfc, KeyPress, XK_r, Mod4Mask);
    assert(sent == before + 2 && last_code == 0x13);
    event_state(&xfc, KeyRelease, XK_r, Mod4Mask);
    event(&xfc, KeyRelease, XK_Super_L);
    assert(sent == before + 4);
    event(&xfc, KeyPress, XK_Alt_L);
    before = sent;
    event_state(&xfc, KeyPress, XK_F4, Mod1Mask);
    local_request(&xfc, 3, FALSE);
    assert(sent == before + 1);
    before = sent;
    event_state(&xfc, KeyRelease, XK_F4, Mod1Mask);
    assert(sent == before);
    event(&xfc, KeyRelease, XK_Alt_L);
    resume(&xfc);
    /* Recover capture even if the GUI never acknowledges a local action. */
    xfc.ajr_local_pending = TRUE;
    xfc.ajr_local_deadline = 0;
    xf_ajr_sync(&xfc);
    assert(!xfc.ajr_local_pending && xfc.ajr_grabbed);

    /* Custom shortcut: exact modifiers, no auto-repeat, no remote key leakage. */
    /* An arbitrary local combination waits for all physical keys to be up. */
    xfc.ajr_rule_count = 4;
    event(&xfc, KeyPress, XK_Control_L);
    event(&xfc, KeyPress, XK_Alt_L);
    before = sent;
    event_state(&xfc, KeyPress, XK_Left, ControlMask | Mod1Mask | LockMask | Mod2Mask);
    assert(xfc.ajr_wait_keys && xfc.ajr_local_pending && xfc.ajr_grabbed);
    assert(sent == before + 2); /* Only release the remote modifiers. */
    before = sent;
    xf_ajr_sync(&xfc);
    assert(xfc.ajr_grabbed);
    event_state(&xfc, KeyPress, XK_Left, ControlMask | Mod1Mask);
    event_state(&xfc, KeyRelease, XK_Left, ControlMask | Mod1Mask);
    event(&xfc, KeyRelease, XK_Alt_L);
    assert(xfc.ajr_wait_keys && xfc.ajr_grabbed);
    event(&xfc, KeyRelease, XK_Control_L);
    assert(!xfc.ajr_wait_keys && !xfc.ajr_grabbed && xfc.ajr_local_pending);
    Atom type; int format; unsigned long count, remaining; unsigned char* bytes = NULL;
    assert(XGetWindowProperty(xfc.display, window.handle,
        XInternAtom(xfc.display, "_AJR_LOCAL_ACCELERATORS_V2", False), 0, 10,
        True, XA_CARDINAL, &type, &format, &count, &remaining, &bytes) == Success);
    assert(bytes && format == 32 && count == 3);
    assert(((unsigned long*)bytes)[0] == XK_Left);
    assert(((unsigned long*)bytes)[1] == (ControlMask | Mod1Mask));
    assert(((unsigned long*)bytes)[2] == XKeysymToKeycode(xfc.display, XK_Left));
    XFree(bytes);
    /* Compositor replay and repeats never leak into the remote session. */
    event(&xfc, KeyPress, XK_Control_L);
    event_state(&xfc, KeyPress, XK_Left, ControlMask | Mod1Mask);
    event_state(&xfc, KeyRelease, XK_Left, ControlMask | Mod1Mask);
    event(&xfc, KeyRelease, XK_Control_L);
    assert(sent == before);
    resume(&xfc);
    before = sent;
    event(&xfc, KeyPress, XK_Control_L);
    event(&xfc, KeyPress, XK_Alt_L);
    event_state(&xfc, KeyPress, XK_Right, ControlMask | Mod1Mask);
    event_state(&xfc, KeyRelease, XK_Right, ControlMask | Mod1Mask);
    event(&xfc, KeyRelease, XK_Alt_L);
    event(&xfc, KeyRelease, XK_Control_L);
    assert(sent == before + 6 && !xfc.ajr_local_pending);
    /* Shift+Alt+Tab overrides the broader built-in local Alt+Tab rule. */
    before = sent;
    event(&xfc, KeyPress, XK_Alt_L);
    event_state(&xfc, KeyPress, XK_Tab, Mod1Mask | ShiftMask);
    event_state(&xfc, KeyRelease, XK_Tab, Mod1Mask | ShiftMask);
    event(&xfc, KeyRelease, XK_Alt_L);
    assert(sent == before + 4 && !xfc.ajr_local_pending);
    /* Extra modifiers do not accidentally match a local rule. */
    before = sent;
    event_state(&xfc, KeyPress, XK_Left, ControlMask | Mod1Mask | ShiftMask);
    event_state(&xfc, KeyRelease, XK_Left, ControlMask | Mod1Mask | ShiftMask);
    assert(sent == before + 2 && !xfc.ajr_local_pending);

    /* A custom Super combination takes precedence over Super alone. */
    before = sent;
    event(&xfc, KeyPress, XK_Super_L);
    event_state(&xfc, KeyPress, XK_d, Mod4Mask);
    assert(xfc.ajr_wait_keys && sent == before);
    event_state(&xfc, KeyRelease, XK_d, Mod4Mask);
    event(&xfc, KeyRelease, XK_Super_L);
    assert(!xfc.ajr_wait_keys && xfc.ajr_local_pending && sent == before);
    bytes = NULL;
    assert(XGetWindowProperty(xfc.display, window.handle,
        XInternAtom(xfc.display, "_AJR_LOCAL_ACCELERATORS_V2", False), 0, 10,
        True, XA_CARDINAL, &type, &format, &count, &remaining, &bytes) == Success);
    assert(bytes && count == 3 && ((unsigned long*)bytes)[0] == XK_d &&
           ((unsigned long*)bytes)[1] == Mod4Mask);
    XFree(bytes);
    resume(&xfc);

    /* Losing focus cancels an unfinished chord instead of leaving a grab. */
    event(&xfc, KeyPress, XK_Control_L);
    event(&xfc, KeyPress, XK_Alt_L);
    event_state(&xfc, KeyPress, XK_Left, ControlMask | Mod1Mask);
    assert(xfc.ajr_wait_keys);
    XEvent focus = {0};
    focus.xfocus.window = window.handle;
    focus.xfocus.mode = NotifyNormal;
    focus.xfocus.type = FocusOut;
    assert(xf_event_process(&instance, &focus));
    assert(!xfc.ajr_wait_keys && !xfc.ajr_local_pending && !xfc.ajr_grabbed);
    focus.xfocus.type = FocusIn;
    assert(xf_event_process(&instance, &focus));
    assert(xfc.ajr_grabbed);

    xfc.fullscreen_toggle = TRUE;
    xfc.ajr_fullscreen_key = XK_F12;
    xfc.ajr_fullscreen_mods = ControlMask | ShiftMask;
    before = sent;
    event_state(&xfc, KeyPress, XK_F12, ControlMask | ShiftMask | LockMask);
    assert(xfc.ajr_shortcut_down && !xfc.fullscreen);
    assert(sent == before);
    event_state(&xfc, KeyPress, XK_F12, ControlMask | ShiftMask);
    assert(!xfc.fullscreen && sent == before);
    event_state(&xfc, KeyRelease, XK_F12, 0);
    assert(!xfc.ajr_shortcut_down && sent == before);
    fullscreen_property(&xfc, FALSE);
    assert(!xfc.ajr_grabbed);
    xfc.ajr_capture_window = TRUE;
    xf_ajr_update_keyboard(&xfc);
    assert(xfc.ajr_grabbed);
    probe(&xfc, other, TRUE);
    xfc.ajr_capture_window = FALSE;
    fullscreen_property(&xfc, TRUE);
    XUnmapWindow(xfc.display, window.handle);
    XSync(xfc.display, False);
    xf_ajr_update_keyboard(&xfc);
    assert(!xfc.ajr_grabbed);
    XMapWindow(xfc.display, window.handle);
    XSync(xfc.display, False);
    xf_ajr_update_keyboard(&xfc);
    assert(xfc.ajr_grabbed);
    xfc.focused = FALSE;
    xf_ajr_update_keyboard(&xfc);
    assert(!xfc.ajr_grabbed);
    probe(&xfc, other, FALSE);
    xfc.focused = TRUE;
    xf_ajr_update_keyboard(&xfc);
    assert(xfc.ajr_grabbed);
    fullscreen_property(&xfc, FALSE);
    assert(!xfc.ajr_grabbed);
    probe(&xfc, other, FALSE);
    /* Native toolbar: a child of the session, no desktop extension or RDP. */
    setenv("AJR_NATIVE_BAR", "1", 1);
    const char* bar_width = getenv("AJR_BAR_TEST_WIDTH");
    if (bar_width) {
        window.width = atoi(bar_width);
        XResizeWindow(xfc.display, window.handle, window.width, window.height);
    }
    xf_ajr_bar_init(&xfc);
    assert(xfc.ajr_bar);
    fullscreen_property(&xfc, TRUE);
    xf_ajr_bar_sync(&xfc);
    assert(xfc.ajr_bar_mapped && !xfc.ajr_bar_expanded);
    XEvent bar_event = {0};
    bar_event.xcrossing.type = EnterNotify;
    bar_event.xcrossing.window = xfc.ajr_bar;
    bar_event.xcrossing.x = 150;
    before = sent;
    assert(xf_event_process(&instance, &bar_event));
    assert(xfc.ajr_bar_expanded && sent == before && xfc.ajr_grabbed);
    XSync(xfc.display, False);
    const char* preview = getenv("AJR_BAR_PREVIEW");
    if (preview) {
        cairo_surface_t* screen = cairo_xlib_surface_create(xfc.display, xfc.ajr_bar,
            DefaultVisual(xfc.display, DefaultScreen(xfc.display)), xfc.ajr_bar_width, xfc.ajr_bar_height);
        cairo_surface_t* copy = cairo_image_surface_create(CAIRO_FORMAT_RGB24, xfc.ajr_bar_width, xfc.ajr_bar_height);
        cairo_t* cr = cairo_create(copy);
        cairo_set_source_surface(cr, screen, 0, 0); cairo_paint(cr);
        assert(cairo_surface_write_to_png(copy, preview) == CAIRO_STATUS_SUCCESS);
        cairo_destroy(cr); cairo_surface_destroy(copy); cairo_surface_destroy(screen);
    }
    /* No press, right click and release on a different button do nothing. */
    bar_event.xbutton.type = ButtonRelease; bar_event.xbutton.button = Button1;
    bar_event.xbutton.x = xfc.ajr_bar_width - 20;
    assert(xf_event_process(&instance, &bar_event));
    bar_event.xbutton.type = ButtonPress; bar_event.xbutton.button = Button3;
    assert(xf_event_process(&instance, &bar_event));
    bar_event.xbutton.type = ButtonRelease;
    assert(xf_event_process(&instance, &bar_event));
    bar_event.xbutton.type = ButtonPress; bar_event.xbutton.button = Button1;
    assert(xf_event_process(&instance, &bar_event));
    bar_event.xbutton.type = ButtonRelease; bar_event.xbutton.x = 10;
    assert(xf_event_process(&instance, &bar_event));
    /* Restore and disconnect never reach the remote input callbacks. */
    bar_event.xbutton.type = ButtonPress; bar_event.xbutton.x = xfc.ajr_bar_width / 2;
    assert(xf_event_process(&instance, &bar_event));
    bar_event.xbutton.type = ButtonRelease;
    assert(xf_event_process(&instance, &bar_event));
    assert(!xfc.fullscreen && sent == before);
    fullscreen_property(&xfc, TRUE);
    xfc.ajr_pending = FALSE; /* Xvfb has no WM to acknowledge the restore geometry. */
    xf_ajr_sync(&xfc);
    bar_event.xcrossing.type = EnterNotify;
    assert(xf_event_process(&instance, &bar_event));
    bar_event.xbutton.type = ButtonPress; bar_event.xbutton.x = xfc.ajr_bar_width - 20;
    assert(xf_event_process(&instance, &bar_event));
    bar_event.xbutton.type = ButtonRelease;
    assert(!xf_event_process(&instance, &bar_event));
    assert(sent == before);
    xfc.focused = FALSE; xf_ajr_bar_sync(&xfc);
    assert(!xfc.ajr_bar_mapped);
    XDestroyWindow(xfc.display, xfc.ajr_bar); xfc.ajr_bar = 0;
    XDestroyWindow(xfc.display, window.handle);
    XFreeModifiermap(xfc.modifierMap);
    PubSub_Free(xfc.context.pubSub);
    freerdp_settings_free(xfc.context.settings);
    XCloseDisplay(other);
    XCloseDisplay(xfc.display);
    puts("PASS native keyboard: built-in/custom local and remote rules, modifier/replay isolation, focus/timeout recovery and fullscreen shortcut");
    return 0;
}
