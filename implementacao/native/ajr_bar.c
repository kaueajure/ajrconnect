/* AJR session controls are children of the RDP window, so they work above the
 * framebuffer on X11 and XWayland without a GNOME extension. Apache-2.0. */
#include <stdlib.h>
#include <string.h>
#include <cairo/cairo-xlib.h>
#include <pango/pangocairo.h>
#include <X11/cursorfont.h>
#include <X11/Xatom.h>
#include <winpr/sysinfo.h>
#include "ajr.h"

static int scale(xfContext* xfc) { return xfc->ajr_bar_scale; }
static int height(xfContext* xfc) { return 48 * scale(xfc); }
static int width(xfContext* xfc)
{
    int available = (int)xfc->window->width - 24 * scale(xfc);
    int maximum = 640 * scale(xfc);
    return available < maximum ? (available > 0 ? available : 1) : maximum;
}
static int brand_width(xfContext* xfc)
{
    return width(xfc) >= 560 * scale(xfc) ? 128 * scale(xfc) : 0;
}
static int target(xfContext* xfc, int x)
{
    int brand = brand_width(xfc), content = width(xfc) - brand;
    if (x < brand || x >= width(xfc)) return -1;
    return (x - brand) * 3 / content;
}
static void color(cairo_t* cr, double r, double g, double b)
{
    cairo_set_source_rgb(cr, r / 255, g / 255, b / 255);
}
static void text(cairo_t* cr, const char* value, int x, int w, int h, int ui_scale)
{
    PangoLayout* layout = pango_cairo_create_layout(cr);
    PangoFontDescription* font = pango_font_description_from_string("Sans 10");
    pango_font_description_set_absolute_size(font, 14 * ui_scale * PANGO_SCALE);
    pango_layout_set_font_description(layout, font);
    pango_layout_set_text(layout, value, -1);
    pango_layout_set_width(layout, w * PANGO_SCALE);
    pango_layout_set_alignment(layout, PANGO_ALIGN_CENTER);
    pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);
    int th;
    pango_layout_get_pixel_size(layout, NULL, &th);
    cairo_move_to(cr, x, (h - th) / 2);
    pango_cairo_show_layout(cr, layout);
    pango_font_description_free(font);
    g_object_unref(layout);
}
static void paint(xfContext* xfc)
{
    int w = width(xfc), h = height(xfc), s = scale(xfc);
    cairo_surface_t* surface = cairo_xlib_surface_create(xfc->display, xfc->ajr_bar,
        DefaultVisual(xfc->display, xfc->screen_number), w, h);
    cairo_t* cr = cairo_create(surface);
    if (xfc->ajr_bar_dark) color(cr, 27, 28, 33); else color(cr, 255, 255, 255);
    cairo_paint(cr);
    if (xfc->ajr_bar_dark) color(cr, 117, 97, 215); else color(cr, 101, 80, 196);
    cairo_rectangle(cr, 0, h - 2 * s, w, 2 * s);
    cairo_fill(cr);
    if (!xfc->ajr_bar_expanded) {
        cairo_destroy(cr); cairo_surface_destroy(surface); return;
    }
    int brand = brand_width(xfc);
    if (brand) {
        if (xfc->ajr_bar_dark) color(cr, 241, 241, 244); else color(cr, 32, 33, 39);
        text(cr, "AJR Connect", 0, brand, h, s);
    }
    const char* labels[] = {w >= 360 * s ? "Minimizar" : "Min.",
        w >= 560 * s ? "Sair de tela cheia" : (w >= 360 * s ? "Restaurar" : "Janela"),
        w >= 360 * s ? "Desconectar" : "Sair"};
    for (int i = 0; i < 3; i++) {
        int left = brand + (w - brand) * i / 3;
        int right = brand + (w - brand) * (i + 1) / 3;
        if (xfc->ajr_bar_hover == i) {
            if (xfc->ajr_bar_pressed == i) {
                if (xfc->ajr_bar_dark) color(cr, 73, 65, 102); else color(cr, 218, 211, 242);
            } else {
                if (xfc->ajr_bar_dark) color(cr, 45, 46, 54); else color(cr, 238, 238, 243);
            }
            cairo_rectangle(cr, left + 4 * s, 4 * s, right - left - 8 * s, h - 8 * s);
            cairo_fill(cr);
        }
        if (i == 2) {
            if (xfc->ajr_bar_dark) color(cr, 255, 153, 157); else color(cr, 169, 40, 50);
        } else {
            if (xfc->ajr_bar_dark) color(cr, 241, 241, 244); else color(cr, 32, 33, 39);
        }
        text(cr, labels[i], left + 8 * s, right - left - 16 * s, h, s);
    }
    cairo_destroy(cr); cairo_surface_destroy(surface);
}
void xf_ajr_bar_init(xfContext* xfc)
{
    if (!getenv("AJR_NATIVE_BAR") || xfc->remote_app) return;
    const char* factor = getenv("AJR_UI_SCALE");
    xfc->ajr_bar_scale = factor ? atoi(factor) : 1;
    if (xfc->ajr_bar_scale < 1 || xfc->ajr_bar_scale > 4) xfc->ajr_bar_scale = 1;
    xfc->ajr_bar_dark = !getenv("AJR_BAR_THEME") || strcmp(getenv("AJR_BAR_THEME"), "light");
    xfc->ajr_bar_hover = xfc->ajr_bar_pressed = -1;
    xfc->ajr_bar = XCreateSimpleWindow(xfc->display, xfc->window->handle, 0, 0,
        1, 1, 0, 0, xfc->ajr_bar_dark ? 0x1b1c21 : 0xffffff);
    XStoreName(xfc->display, xfc->ajr_bar, "AJR Bar: Minimizar, Sair de tela cheia, Desconectar");
    XSelectInput(xfc->display, xfc->ajr_bar, ExposureMask | EnterWindowMask |
        LeaveWindowMask | PointerMotionMask | ButtonPressMask | ButtonReleaseMask);
    Cursor cursor = XCreateFontCursor(xfc->display, XC_left_ptr);
    XDefineCursor(xfc->display, xfc->ajr_bar, cursor);
    XFreeCursor(xfc->display, cursor);
    unsigned long bar = xfc->ajr_bar;
    XChangeProperty(xfc->display, xfc->window->handle,
        XInternAtom(xfc->display, "_AJR_NATIVE_BAR_V1", False), XA_WINDOW,
        32, PropModeReplace, (unsigned char*)&bar, 1);
}
void xf_ajr_bar_sync(xfContext* xfc)
{
    if (!xfc->ajr_bar) return;
    BOOL show = xfc->fullscreen && xfc->focused && !xfc->ajr_pending;
    if (!show) {
        if (xfc->ajr_bar_mapped) XUnmapWindow(xfc->display, xfc->ajr_bar);
        xfc->ajr_bar_mapped = xfc->ajr_bar_expanded = FALSE;
        xfc->ajr_bar_hide_due = 0;
        xfc->ajr_bar_hover = xfc->ajr_bar_pressed = -1;
        return;
    }
    if (xfc->ajr_bar_hide_due && GetTickCount64() >= xfc->ajr_bar_hide_due) {
        Window root, child; int rx, ry, x, y; unsigned int mask;
        XQueryPointer(xfc->display, xfc->ajr_bar, &root, &child, &rx, &ry, &x, &y, &mask);
        if (x < 0 || x >= width(xfc) || y < 0 || y >= height(xfc)) {
            xfc->ajr_bar_expanded = FALSE;
            xfc->ajr_bar_hover = xfc->ajr_bar_pressed = -1;
        }
        xfc->ajr_bar_hide_due = 0;
    }
    int w = width(xfc), h = xfc->ajr_bar_expanded ? height(xfc) : 6 * scale(xfc);
    if (w != xfc->ajr_bar_width || h != xfc->ajr_bar_height) {
        XMoveResizeWindow(xfc->display, xfc->ajr_bar,
            ((int)xfc->window->width - w) / 2, 0, w, h);
        xfc->ajr_bar_width = w; xfc->ajr_bar_height = h;
    }
    if (!xfc->ajr_bar_mapped) {
        XMapRaised(xfc->display, xfc->ajr_bar);
        xfc->ajr_bar_mapped = TRUE;
    }
}
BOOL xf_ajr_bar_event(xfContext* xfc, const XEvent* event, BOOL* result)
{
    if (!xfc->ajr_bar || event->xany.window != xfc->ajr_bar) return FALSE;
    *result = TRUE;
    switch (event->type) {
        case EnterNotify:
            xfc->ajr_bar_expanded = TRUE;
            xfc->ajr_bar_hide_due = 0;
            xfc->ajr_bar_hover = target(xfc, event->xcrossing.x);
            xf_ajr_bar_sync(xfc); paint(xfc); break;
        case LeaveNotify:
            xfc->ajr_bar_hide_due = GetTickCount64() + 600;
            xfc->ajr_bar_hover = -1;
            paint(xfc); break;
        case MotionNotify:
            xfc->ajr_bar_hover = target(xfc, event->xmotion.x);
            paint(xfc); break;
        case Expose: paint(xfc); break;
        case ButtonPress:
            if (event->xbutton.button == Button1 && xfc->ajr_bar_expanded)
                xfc->ajr_bar_pressed = target(xfc, event->xbutton.x);
            paint(xfc); break;
        case ButtonRelease:
            if (event->xbutton.button == Button1 && xfc->ajr_bar_expanded &&
                xfc->ajr_bar_pressed >= 0 && xfc->ajr_bar_pressed == target(xfc, event->xbutton.x)) {
                int action = xfc->ajr_bar_pressed;
                xfc->ajr_bar_pressed = -1;
                xf_ajr_release_keyboard(xfc);
                if (action == 0) XIconifyWindow(xfc->display, xfc->window->handle, xfc->screen_number);
                else if (action == 1) xf_ajr_set_fullscreen(xfc, FALSE);
                else *result = FALSE;
            }
            xfc->ajr_bar_pressed = -1;
            paint(xfc); break;
    }
    return TRUE;
}
