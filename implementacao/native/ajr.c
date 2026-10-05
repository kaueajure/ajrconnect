/* AJR Connect integration for the FreeRDP 2.11.5 X11 frontend.
 * Uses public X11 window-manager protocols; RDP libraries stay unmodified.
 * SPDX-License-Identifier: Apache-2.0 */
#include <stdlib.h>
#include <string.h>
#include <X11/Xatom.h>
#include <X11/keysym.h>
#include <X11/XKBlib.h>
#include <X11/extensions/Xrandr.h>
#include <freerdp/event.h>
#include <winpr/sysinfo.h>
#include "ajr.h"
#include "xf_keyboard.h"
#include "xf_client.h"

static BOOL actual_fullscreen(xfContext* xfc)
{
    Atom type; int format; unsigned long count, remaining; unsigned char* bytes = NULL;
    BOOL result = FALSE;
    if (XGetWindowProperty(xfc->display, xfc->window->handle, xfc->_NET_WM_STATE,
                          0, 64, False, XA_ATOM, &type, &format, &count,
                          &remaining, &bytes) == Success && bytes && format == 32)
        for (unsigned long i = 0; i < count; i++)
            if (((Atom*)bytes)[i] == xfc->_NET_WM_STATE_FULLSCREEN) result = TRUE;
    if (bytes) XFree(bytes);
    return result;
}

static void publish(xfContext* xfc)
{
    unsigned long state[] = { xfc->fullscreen, actual_fullscreen(xfc),
        xfc->ajr_pending, xfc->ajr_grabbed, xfc->window->width, xfc->window->height,
        xfc->context.settings->DesktopWidth, xfc->context.settings->DesktopHeight };
    if (memcmp(state, xfc->ajr_state, sizeof(state)) != 0)
    {
        memcpy(xfc->ajr_state, state, sizeof(state));
        XChangeProperty(xfc->display, xfc->window->handle,
            XInternAtom(xfc->display, "_AJR_STATE_V1", False), XA_CARDINAL, 32,
            PropModeReplace, (unsigned char*)state, 8);
        XFlush(xfc->display);
    }
}

void xf_ajr_release_keyboard(xfContext* xfc)
{
    xfc->ajr_super_key = 0;
    XUngrabKeyboard(xfc->display, CurrentTime);
    if (xfc->ajr_grabbed && xfc->context.input)
        xf_keyboard_release_all_keypress(xfc);
    xfc->ajr_grabbed = FALSE;
}

void xf_ajr_update_keyboard(xfContext* xfc)
{
    if (!xfc->window) return;
    BOOL capture = xfc->grab_keyboard && xfc->focused &&
                   !xfc->ajr_pending && !xfc->ajr_local_pending &&
                   (xfc->ajr_capture_window || actual_fullscreen(xfc));
    if (capture)
    {
        XWindowAttributes attrs;
        capture = XGetWindowAttributes(xfc->display, xfc->window->handle, &attrs) &&
                  attrs.map_state == IsViewable;
    }
    if (capture)
    {
        if (!xfc->ajr_grabbed)
        {
            int result = XGrabKeyboard(xfc->display, xfc->window->handle, False,
                                      GrabModeAsync, GrabModeAsync, CurrentTime);
            xfc->ajr_grabbed = result == GrabSuccess;
            if (!xfc->ajr_grabbed)
                fprintf(stderr, "AJR keyboard grab failed: %d\n", result);
        }
    }
    else if (xfc->ajr_grabbed) xf_ajr_release_keyboard(xfc);
    publish(xfc);
}

/* Resolve the saved connector at each entry, instead of trusting an old index. */
static BOOL refresh_monitor(xfContext* xfc)
{
    const char* connector = getenv("AJR_MONITOR_CONNECTOR");
    int count = 0;
    XRRMonitorInfo* monitors = XRRGetMonitors(xfc->display,
        DefaultRootWindow(xfc->display), True, &count);
    if (!monitors) return FALSE;
    int selected = -1;
    for (int i = 0; i < count; i++)
    {
        char* name = XGetAtomName(xfc->display, monitors[i].name);
        if (name && connector && strcmp(name, connector) == 0) selected = i;
        if (name) XFree(name);
    }
    if (selected < 0)
    {
        fprintf(stderr, "AJR selected monitor unavailable; fullscreen cancelled\n");
        XRRFreeMonitors(monitors);
        return FALSE;
    }
    rdpSettings* settings = xfc->context.settings;
    settings->MonitorCount = 1;
    settings->MonitorDefArray[0].x = 0;
    settings->MonitorDefArray[0].y = 0;
    settings->MonitorDefArray[0].width = monitors[selected].width;
    settings->MonitorDefArray[0].height = monitors[selected].height;
    settings->MonitorLocalShiftX = monitors[selected].x;
    settings->MonitorLocalShiftY = monitors[selected].y;
    XRRFreeMonitors(monitors);
    return TRUE;
}

void xf_ajr_init(xfContext* xfc)
{
    const char* token = getenv("AJR_CONTROL_TOKEN");
    xfc->ajr_token = token ? (UINT32)strtoul(token, NULL, 16) : 0;
    const char* mode = getenv("AJR_KEYBOARD_MODE");
    const char* key = getenv("AJR_FULLSCREEN_KEY");
    const char* mods = getenv("AJR_FULLSCREEN_MODS");
    const char* remote = getenv("AJR_REMOTE_KEYS");
    xfc->ajr_capture_window = mode && strcmp(mode, "always") == 0;
    if (mode && strcmp(mode, "local") == 0) xfc->grab_keyboard = FALSE;
    xfc->ajr_fullscreen_key = key ? strtoul(key, NULL, 10) : XK_Return;
    xfc->ajr_fullscreen_mods = mods ? strtoul(mods, NULL, 10) : ControlMask | Mod1Mask;
    xfc->ajr_remote_keys = remote ? strtoul(remote, NULL, 10) : 7;
    xfc->savedWidth = xfc->window->width;
    xfc->savedHeight = xfc->window->height;
    xfc->savedPosX = xfc->context.settings->DesktopPosX;
    xfc->savedPosY = xfc->context.settings->DesktopPosY;
    memset(xfc->ajr_state, 0xff, sizeof(xfc->ajr_state));
    unsigned long version = 1;
    XChangeProperty(xfc->display, xfc->window->handle,
        XInternAtom(xfc->display, "_AJR_CONTROL_VERSION", False), XA_CARDINAL,
        32, PropModeReplace, (unsigned char*)&version, 1);
    publish(xfc);
}

static void local_shortcut(xfContext* xfc, unsigned long action, BOOL reverse)
{
    unsigned long request[] = { action, reverse };
    /* Suppress recapture until the GUI has handed the action to GNOME Shell.
     * A bounded timeout recovers if the GUI/integration has disappeared. */
    xfc->ajr_local_pending = TRUE;
    xfc->ajr_local_deadline = GetTickCount64() + 2000;
    xf_keyboard_release_all_keypress(xfc);
    xf_ajr_release_keyboard(xfc);
    XChangeProperty(xfc->display, xfc->window->handle,
        XInternAtom(xfc->display, "_AJR_LOCAL_KEYS_V1", False), XA_CARDINAL, 32,
        PropModeAppend, (unsigned char*)request, 2);
    XFlush(xfc->display);
}

BOOL xf_ajr_key(xfContext* xfc, const XKeyEvent* event, KeySym keysym, BOOL down)
{
    if (xfc->remote_app || event->keycode >= 256) return FALSE;
    BYTE code = event->keycode;
    if (!down)
    {
        if (code == xfc->ajr_shortcut_down)
        {
            xfc->ajr_shortcut_down = 0;
            return TRUE;
        }
        if (xfc->ajr_swallowed[code])
        {
            xfc->ajr_swallowed[code] = FALSE;
            return TRUE;
        }
        if (code == xfc->ajr_super_key)
        {
            xfc->ajr_super_key = 0;
            local_shortcut(xfc, 2, FALSE);
            return TRUE;
        }
        return FALSE;
    }
    if (code == xfc->ajr_shortcut_down || xfc->ajr_swallowed[code]) return TRUE;
    /* Match exactly, ignoring Caps/Num Lock. Normalize letter case/layout Shift. */
    unsigned int modifiers = event->state & (ShiftMask | ControlMask | Mod1Mask | Mod4Mask);
    KeySym lower, upper;
    XConvertCase(keysym == XK_ISO_Left_Tab ? XK_Tab : keysym, &lower, &upper);
    if (xfc->fullscreen_toggle && lower == xfc->ajr_fullscreen_key &&
        modifiers == xfc->ajr_fullscreen_mods)
    {
        xfc->ajr_shortcut_down = code;
        xfc->ajr_super_key = 0;
        xf_toggle_fullscreen(xfc);
        return TRUE;
    }
    if (!xfc->ajr_grabbed) return FALSE;
    if (!(xfc->ajr_remote_keys & 2) && (keysym == XK_Super_L || keysym == XK_Super_R))
    {
        xfc->ajr_super_key = code;
        return TRUE;
    }
    if (xfc->ajr_super_key)
    {
        BYTE super = xfc->ajr_super_key;
        xfc->ajr_super_key = 0;
        xf_keyboard_key_press(xfc, super, XkbKeycodeToKeysym(xfc->display, super, 0, 0));
    }
    if (!(modifiers & (ControlMask | Mod4Mask)) && (modifiers & Mod1Mask))
    {
        if (!(xfc->ajr_remote_keys & 1) && (keysym == XK_Tab || keysym == XK_ISO_Left_Tab))
        {
            xfc->ajr_swallowed[code] = TRUE;
            local_shortcut(xfc, 1, (modifiers & ShiftMask) != 0);
            return TRUE;
        }
        if (!(xfc->ajr_remote_keys & 4) && keysym == XK_F4 && !(modifiers & ShiftMask))
        {
            xfc->ajr_swallowed[code] = TRUE;
            local_shortcut(xfc, 3, FALSE);
            return TRUE;
        }
    }
    return FALSE;
}

void xf_ajr_set_fullscreen(xfContext* xfc, BOOL fullscreen)
{
    if (!xfc->window || xfc->remote_app) return;
    xf_ajr_sync(xfc);
    if (xfc->ajr_pending || xfc->fullscreen == fullscreen) return;
    if (fullscreen && !refresh_monitor(xfc)) return;
    xf_ajr_release_keyboard(xfc);
    xf_keyboard_release_all_keypress(xfc);
    xfc->ajr_pending = TRUE;
    xfc->ajr_deadline = GetTickCount64() + 2000;
    fprintf(stderr, "AJR geometry before toggle: window=%dx%d saved=%dx%d pos=%d,%d\n", xfc->window->width, xfc->window->height, xfc->savedWidth, xfc->savedHeight, xfc->savedPosX, xfc->savedPosY);
    /* Request EWMH state first. Resizing while the window is still fullscreen
     * lets Mutter's legacy-fullscreen heuristic re-enter fullscreen on exit. */
    if (fullscreen)
    {
        Window child;
        int x, y;
        XTranslateCoordinates(xfc->display, xfc->window->handle,
            DefaultRootWindow(xfc->display), 0, 0, &x, &y, &child);
        xfc->savedPosX = x; xfc->savedPosY = y;
        xfc->savedWidth = xfc->window->width;
        xfc->savedHeight = xfc->window->height;
        /* Leave Mutter's normal restore rectangle untouched on this monitor. */
        int mx = xfc->context.settings->MonitorLocalShiftX;
        int my = xfc->context.settings->MonitorLocalShiftY;
        int mw = xfc->context.settings->MonitorDefArray[0].width;
        int mh = xfc->context.settings->MonitorDefArray[0].height;
        if (x + xfc->savedWidth / 2 < mx || x + xfc->savedWidth / 2 >= mx + mw ||
            y + xfc->savedHeight / 2 < my || y + xfc->savedHeight / 2 >= my + mh)
            XMoveWindow(xfc->display, xfc->window->handle, mx + 32, my + 64);
    }
    xfc->fullscreen = fullscreen;
    xfc->decorations = fullscreen ? FALSE : xfc->context.settings->Decorations;
    xf_SendClientEvent(xfc, xfc->window->handle, xfc->_NET_WM_STATE, 4,
        fullscreen ? _NET_WM_STATE_ADD : _NET_WM_STATE_REMOVE,
        xfc->_NET_WM_STATE_FULLSCREEN, 0, 1);
    if (fullscreen)
    {
        /* A GUI/helper entry can start from another focused application.
         * Ask Mutter to activate the RDP window once for this user command. */
        xf_SendClientEvent(xfc, xfc->window->handle,
            XInternAtom(xfc->display, "_NET_ACTIVE_WINDOW", False), 3,
            2, CurrentTime, 0);
    }
    WindowStateChangeEventArgs change;
    EventArgsInit(&change, "AJR Connect");
    change.state = fullscreen ? FREERDP_WINDOW_STATE_FULLSCREEN : 0;
    PubSub_OnWindowStateChange(xfc->context.pubSub, &xfc->context, &change);
    fprintf(stderr, "AJR fullscreen requested=%d monitor=%s\n", fullscreen,
            getenv("AJR_MONITOR_CONNECTOR") ? getenv("AJR_MONITOR_CONNECTOR") : "unknown");
    publish(xfc);
}

void xf_toggle_fullscreen(xfContext* xfc)
{
    xf_ajr_set_fullscreen(xfc, !xfc->fullscreen);
}

void xf_ajr_sync(xfContext* xfc)
{
    if (!xfc->window) return;
    if (xfc->ajr_local_pending && GetTickCount64() >= xfc->ajr_local_deadline)
        xfc->ajr_local_pending = FALSE;
    BOOL actual = actual_fullscreen(xfc);
    if (xfc->ajr_pending)
    {
        if (actual == xfc->fullscreen)
        {
            XWindowAttributes attrs;
            Window child; int x, y;
            XGetWindowAttributes(xfc->display, xfc->window->handle, &attrs);
            XTranslateCoordinates(xfc->display, xfc->window->handle,
                DefaultRootWindow(xfc->display), 0, 0, &x, &y, &child);
            int wantedWidth = actual ? xfc->context.settings->MonitorDefArray[0].width : xfc->savedWidth;
            int wantedHeight = actual ? xfc->context.settings->MonitorDefArray[0].height : xfc->savedHeight;
            int wantedX = actual ? xfc->context.settings->MonitorLocalShiftX : xfc->savedPosX;
            int wantedY = actual ? xfc->context.settings->MonitorLocalShiftY : xfc->savedPosY;
            if (attrs.width == wantedWidth && attrs.height == wantedHeight && x == wantedX && y == wantedY)
                xfc->ajr_pending = FALSE;
            else if (GetTickCount64() < xfc->ajr_deadline) return;
            else xfc->ajr_pending = FALSE;
        }
        else if (GetTickCount64() < xfc->ajr_deadline) return;
        else
        {
            fprintf(stderr, "AJR fullscreen acknowledgement timeout; reconciling\n");
            xfc->ajr_pending = FALSE;
        }
    }
    if (xfc->fullscreen != actual)
    {
        /* External WM change: keep client state/decorations consistent. */
        xfc->fullscreen = actual;
        xfc->decorations = actual ? FALSE : xfc->context.settings->Decorations;
        /* Mutter already handles decorations when changing EWMH state. */
        fprintf(stderr, "AJR external fullscreen reconciled=%d\n", actual);
    }
    xf_ajr_update_keyboard(xfc);
}

BOOL xf_ajr_control(xfContext* xfc, const XClientMessageEvent* event)
{
    if (event->message_type != XInternAtom(xfc->display, "_AJR_CONTROL_V1", False))
        return TRUE;
    if (event->format != 32 || event->window != xfc->window->handle ||
        !xfc->ajr_token || (UINT32)event->data.l[1] != xfc->ajr_token) return TRUE;
    switch (event->data.l[0])
    {
        case 1: xf_ajr_set_fullscreen(xfc, TRUE); break;
        case 2: xf_ajr_set_fullscreen(xfc, FALSE); break;
        case 3: xf_ajr_release_keyboard(xfc); XIconifyWindow(xfc->display,
                    xfc->window->handle, xfc->screen_number); break;
        case 4: xf_ajr_release_keyboard(xfc); return FALSE;
        case 5: xf_toggle_fullscreen(xfc); break;
        case 6: xfc->ajr_local_pending = FALSE; xf_ajr_update_keyboard(xfc); break;
    }
    return TRUE;
}
