/* Input-only idle observer. No input contents are available to this client. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>
#include "idle-protocol.h"

static struct wl_seat *seat;
static struct ext_idle_notifier_v1 *notifier;
static void global(void *data, struct wl_registry *r, uint32_t name,
                   const char *interface, uint32_t version) {
    (void)data;
    if (!strcmp(interface, "wl_seat") && !seat)
        seat = wl_registry_bind(r, name, &wl_seat_interface, 1);
    if (!strcmp(interface, "ext_idle_notifier_v1") && version >= 2)
        notifier = wl_registry_bind(r, name, &ext_idle_notifier_v1_interface, 2);
}
static void removed(void *data, struct wl_registry *r, uint32_t name) {
    (void)data; (void)r; (void)name;
}
static void idled(void *data, struct ext_idle_notification_v1 *n) {
    (void)n; puts((const char *)data);
}
static void resumed(void *data, struct ext_idle_notification_v1 *n) {
    (void)n;
    if (!strcmp(data, "idle")) puts("active");
}
int main(int argc, char **argv) {
    unsigned timeout = argc == 2 ? (unsigned)strtoul(argv[1], NULL, 10) : 180;
    if (timeout < 30 || timeout > 900) return 2;
    setvbuf(stdout, NULL, _IOLBF, 0);
    struct wl_display *d = wl_display_connect(NULL);
    if (!d) return 3;
    struct wl_registry *r = wl_display_get_registry(d);
    const struct wl_registry_listener registry = {global, removed};
    wl_registry_add_listener(r, &registry, NULL);
    if (wl_display_roundtrip(d) < 0 || !seat || !notifier) return 4;
    const struct ext_idle_notification_v1_listener listener = {idled, resumed};
    struct ext_idle_notification_v1 *short_idle =
        ext_idle_notifier_v1_get_input_idle_notification(notifier, timeout * 1000, seat);
    struct ext_idle_notification_v1 *long_idle =
        ext_idle_notifier_v1_get_input_idle_notification(notifier, 900000, seat); /* = AWAY in hydration.py */
    ext_idle_notification_v1_add_listener(short_idle, &listener, "idle");
    ext_idle_notification_v1_add_listener(long_idle, &listener, "away");
    if (wl_display_roundtrip(d) < 0) return 5;
    puts("ready");
    while (wl_display_dispatch(d) >= 0) {}
    wl_display_disconnect(d);
    return 6;
}
