/* Exercise the actual frontend keyboard handlers on an isolated X server. */
#include <assert.h>
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
    xf_ajr_init(&xfc);
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
    XDestroyWindow(xfc.display, window.handle);
    XFreeModifiermap(xfc.modifierMap);
    PubSub_Free(xfc.context.pubSub);
    freerdp_settings_free(xfc.context.settings);
    XCloseDisplay(other);
    XCloseDisplay(xfc.display);
    puts("PASS native grab lifecycle, local Alt+Tab/Super/Alt+F4 routing, remote Super+R, custom shortcut/repeat, window capture and timeout recovery");
    return 0;
}
