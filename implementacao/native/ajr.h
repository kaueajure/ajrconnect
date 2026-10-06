#ifndef AJR_NATIVE_H
#define AJR_NATIVE_H
#include "xfreerdp.h"
void xf_ajr_init(xfContext* xfc);
void xf_ajr_sync(xfContext* xfc);
void xf_ajr_set_fullscreen(xfContext* xfc, BOOL fullscreen);
void xf_ajr_update_keyboard(xfContext* xfc);
void xf_ajr_release_keyboard(xfContext* xfc);
BOOL xf_ajr_control(xfContext* xfc, const XClientMessageEvent* event);
BOOL xf_ajr_key(xfContext* xfc, const XKeyEvent* event, KeySym keysym, BOOL down);
void xf_ajr_bar_init(xfContext* xfc);
void xf_ajr_bar_sync(xfContext* xfc);
BOOL xf_ajr_bar_event(xfContext* xfc, const XEvent* event, BOOL* result);
#endif
