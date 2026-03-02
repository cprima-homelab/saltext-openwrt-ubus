# rpcd Session-Staging Internals

> Source: [rpcd](https://git.openwrt.org/?p=project/rpcd.git) git
> repository, files `uci.c`, `session.c`, `include/rpcd/uci.h`.
> Line numbers are approximate and may drift between releases.

rpcd intercepts the `ubus_rpc_session` field from every UCI ubus call
and redirects libuci's save directory to a per-session path. This is
the mechanism that isolates staged UCI changes between JSON-RPC
sessions and makes autoverified mode possible in the Salt proxy.

## Path constants

`include/rpcd/uci.h`:

```c
#define RPC_UCI_DIR_PREFIX       "/var/run/rpcd"
#define RPC_UCI_SAVEDIR_PREFIX   RPC_UCI_DIR_PREFIX "/uci-"
```

Every session's staging directory becomes `/var/run/rpcd/uci-<32_hex_chars>/`.

## How the session ID arrives

Every UCI method's blobmsg policy includes a `ubus_rpc_session` field.
For example, the `set` policy (`uci.c`):

```c
static const struct blobmsg_policy rpc_uci_set_policy[__RPC_S_MAX] = {
    [RPC_S_CONFIG]  = { .name = "config",  .type = BLOBMSG_TYPE_STRING },
    [RPC_S_SECTION] = { .name = "section", .type = BLOBMSG_TYPE_STRING },
    /* ... */
    [RPC_S_SESSION] = { .name = "ubus_rpc_session",
                                           .type = BLOBMSG_TYPE_STRING },
};
```

The same pattern repeats for `get`, `add`, `delete`, `rename`, `order`,
`commit`, `revert`, and `apply`. When a call arrives through rpcd's
JSON-RPC gateway, ubusd injects the authenticated session ID into the
blob message automatically.

## The savedir redirect

`uci.c`, `rpc_uci_set_savedir()`:

```c
/*
 * Setup per-session delta save directory. If the passed "sid" blob
 * attribute pointer is NULL then the procedure was not invoked through
 * the ubus-rpc so we do not perform session isolation and use the
 * default save directory.
 */
static void
rpc_uci_set_savedir(struct blob_attr *sid)
{
    char path[PATH_MAX];

    if (!sid)
    {
        rpc_uci_replace_savedir("/tmp/.uci");   // <-- local socket fallback
        return;
    }

    snprintf(path, sizeof(path) - 1,
             RPC_UCI_SAVEDIR_PREFIX "%s", blobmsg_get_string(sid));

    rpc_uci_replace_savedir(path);              // <-- per-session path
}
```

`rpc_uci_replace_savedir()` clears the libuci cursor's delta path
list and calls `uci_set_savedir(cursor, path)`. After this, any
`uci_save()` on that cursor writes delta files to the session
directory instead of `/tmp/.uci/`.

## Access-check chaining

The savedir redirect is a side effect of the access-check functions
that every handler calls before doing any work:

```c
static bool
rpc_uci_write_access(struct blob_attr *sid, struct blob_attr *config)
{
    rpc_uci_set_savedir(sid);   // <-- always called first

    if (!sid)
        return true;

    return rpc_session_access(blobmsg_data(sid), "uci",
                              blobmsg_data(config), "write");
}
```

In `rpc_uci_set()`:

```c
    if (!rpc_uci_write_access(tb[RPC_S_SESSION], tb[RPC_S_CONFIG]))
        return UBUS_STATUS_PERMISSION_DENIED;

    /* ... modify UCI options ... */

    if (!err)
        uci_save(cursor, p);   // writes to /var/run/rpcd/uci-<sid>/
```

Because `rpc_uci_write_access` already redirected the savedir, the
`uci_save()` call writes deltas to the per-session directory. The same
pattern applies to `rpc_uci_read_access` (which also calls
`rpc_uci_set_savedir` so that `uci_load` merges the correct session's
pending deltas when reading).

## Apply reads from the session directory

When `uci.apply` is called, it globs the per-session delta directory
to find which configs have staged changes:

```c
    snprintf(tmp, sizeof(tmp),
             RPC_UCI_SAVEDIR_PREFIX "%s/*", sid);

    if (glob(tmp, GLOB_PERIOD, NULL, &gl) < 0)
        return UBUS_STATUS_NOT_FOUND;
```

Each matching file is committed via `rpc_uci_apply_config()`, which
snapshots the current `/etc/config/<name>` to
`/var/run/rpcd/snapshot-files/`, then commits the delta.

## Session expiry cleanup

`uci.c` registers a destroy callback at init:

```c
int rpc_uci_api_init(struct ubus_context *ctx)
{
    static struct rpc_session_cb cb = {
        .cb = rpc_uci_purge_savedir_cb
    };

    cursor = uci_alloc_context();
    rpc_session_destroy_cb(&cb);
    return ubus_add_object(ctx, &obj);
}
```

When a session expires, `session.c` fires the callback chain:

```c
static void rpc_session_timeout(struct uloop_timeout *t)
{
    struct rpc_session *ses;
    ses = container_of(t, struct rpc_session, t);
    rpc_session_destroy(ses);
}

static void rpc_session_destroy(struct rpc_session *ses)
{
    struct rpc_session_cb *cb;

    list_for_each_entry(cb, &destroy_callbacks, list)
        cb->cb(ses, cb->priv);          // <-- fires purge callback

    uloop_timeout_cancel(&ses->t);
    /* ... free ACLs, data, remove from AVL tree ... */
}
```

The purge callback removes the per-session directory and all delta
files inside it:

```c
static void
rpc_uci_purge_savedir_cb(struct rpc_session *ses, void *priv)
{
    char path[PATH_MAX];
    snprintf(path, sizeof(path) - 1,
             RPC_UCI_SAVEDIR_PREFIX "%s", ses->id);
    rpc_uci_purge_dir(path);           // unlink files, rmdir
}
```

All uncommitted changes for that session are silently discarded.

## Startup cleanup

rpcd also cleans up stale directories at startup (e.g. after a crash):

```c
void rpc_uci_purge_savedirs(void)
{
    int i;
    glob_t gl;

    if (!glob(RPC_UCI_SAVEDIR_PREFIX "*", 0, NULL, &gl))
    {
        for (i = 0; i < gl.gl_pathc; i++)
            rpc_uci_purge_dir(gl.gl_pathv[i]);
        globfree(&gl);
    }
}
```

This globs `/var/run/rpcd/uci-*` and removes all matching directories.

## Why SSH + `ubus call` does not use session staging

The `ubus` CLI on the device talks to ubusd via the local Unix socket.
rpcd is not in the call path:

```
JSON-RPC:  curl -> uhttpd -> rpcd -> ubusd -> handler
                              ^
                     session interception here

SSH CLI:   ssh -> ubus -> ubusd -> handler
                          ^
                   no rpcd, sid is NULL
```

When the UCI handler receives a call with `sid=NULL`, it falls back to
`/tmp/.uci/` (see the `if (!sid)` branch in `rpc_uci_set_savedir`
above). This happens regardless of whether you previously called
`ubus call session login` over SSH -- the session token obtained that
way lives in rpcd's memory, but the `ubus` CLI does not inject it into
the blob message the way rpcd's JSON-RPC gateway does.

Even if you manually pass `ubus_rpc_session` as a parameter in the
JSON argument to `ubus call uci set`, the local socket dispatch path
does not go through rpcd's session interception layer. The parameter
is simply ignored by the handler's policy parsing because `sid` in
the blob message is set by ubusd's authentication layer (which is
rpcd for HTTP calls, but absent for local socket calls).

**Bottom line**: over SSH you always stage to `/tmp/.uci/`, visible to
all processes on the device. Per-session isolation is exclusively a
JSON-RPC-over-HTTPS feature provided by rpcd's interception of the
session token.
