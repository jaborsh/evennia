"""
Fallback resolvers for the command handler.

When the command parser finds no match for the input, the cmdhandler tries
the resolvers listed in `settings.COMMAND_FALLBACK_RESOLVERS`, in order,
before giving up with the no-match error. Exits and channels are resolved
this way (neither contributes commands to the merged cmdset), as are
nick/alias replacements - so commands shadow exits, exits shadow channels,
and channels shadow nicks.

The resolvers only run when the merged cmdset defines no custom CMD_NOMATCH
system command. Free-form input capture (EvMenu, EvEditor, EvMore,
`get_input`) works by installing such a command, and typing an exit name
into an editor must not move the caller. A game-wide custom CMD_NOMATCH
therefore disables fallback resolution entirely.

A resolver is a callable

    resolver(caller, raw_string, cmdset, session=None, **kwargs)

where `raw_string` is the stripped input and `cmdset` the merged cmdset. It
may return a Deferred. The cmdhandler acts on the result:

- `None`: not handled; the next resolver is tried.
- `True`: the input was consumed (e.g. an exit was traversed); stop.
- `str`: a rewritten input line; the parse/resolve pipeline runs once more
  with the new string. A second rewrite is not honored.

"""

from django.conf import settings


def get_exit_candidates(caller):
    """
    Map matchable names to exits at the caller's location.

    Args:
        caller (Object, Account or Session): The entity executing the command.

    Returns:
        dict: Lowercased exit keys and aliases mapped to their exit objects,
        in contents order - on a name collision the first exit wins. Empty
        if the caller has no location (accounts, sessions).

    """
    location = getattr(caller, "location", None)
    if not location:
        return {}
    candidates = {}
    for exit_obj in location.contents_get(content_type="exit"):
        for name in (exit_obj.key, *exit_obj.aliases.all()):
            name = name.strip().lower() if name else ""
            if name:
                candidates.setdefault(name, exit_obj)
    return candidates


def resolve_exits(caller, raw_string, cmdset, session=None, **kwargs):
    """
    Fallback resolver: traverse the exit whose key or alias matches the input.

    The match is exact (after stripping and lowercasing) - exits take no
    arguments, mirroring the `arg_regex=r"^$"` of the old exit commands. A
    merged cmdset with `no_exits=True` (set e.g. by EvMenu and blinding
    cmdsets) suppresses exit matching.

    A name match consumes the input even when the traverse lock fails;
    messaging the failure is `exit_obj.traverse`'s job and the input must
    not leak on to nick replacement or the no-match error.

    Returns:
        True if an exit name matched, None otherwise.

    """
    if cmdset.no_exits:
        return None
    exit_obj = get_exit_candidates(caller).get(raw_string.strip().lower())
    if exit_obj is None:
        return None
    exit_obj.traverse(caller)
    return True


def get_channel_candidates(caller):
    """
    Map matchable channel names for the caller.

    Gathers, in precedence order (first writer wins on name collisions):
    the caller's personal "channel"-category nicks (alias -> channel key),
    the account's channel-nicks (when the caller is a puppet), then keys and
    global aliases of the channels the caller subscribes to, then the same
    for the account's subscriptions.

    Returns:
        dict: Lowercased name mapped to a Channel (for subscriptions) or a
        str channel-key (for nicks; resolved to a channel only on an actual
        match, sparing a query per input). Empty for sessions and other
        entities that cannot subscribe.

    """
    from evennia.comms.models import ChannelDB  # avoids import cycle at startup

    account = getattr(caller, "account", None)
    entities = [entity for entity in (caller, account) if entity is not None]
    candidates = {}
    for entity in entities:
        nicks = getattr(entity, "nicks", None)
        if not nicks:
            continue
        for nick in nicks.get(category="channel", return_obj=True, return_list=True) or []:
            if not nick:
                continue
            # nick value layout: (regex, template, alias, channel_key)
            _, _, alias, chan_key = nick.value
            if alias:
                candidates.setdefault(alias.strip().lower(), chan_key)
    for entity in entities:
        if not getattr(entity, "__dbclass__", None):
            # sessions etc. cannot subscribe to channels
            continue
        for channel in ChannelDB.objects.get_subscriptions(entity):
            for name in (channel.key, *channel.aliases.all()):
                name = name.strip().lower() if name else ""
                if name:
                    candidates.setdefault(name, channel)
    return candidates


def resolve_channels(caller, raw_string, cmdset, session=None, **kwargs):
    """
    Fallback resolver: send to the channel whose name prefixes the input.

    The first whitespace-bounded, case-insensitive match against the
    caller's subscribed channel keys/aliases and personal channel-nicks
    wins; on overlapping names the longest one is used. The rest of the
    line is the message. A bare channel name is rewritten to the command
    named by `settings.COMMAND_FALLBACK_CHANNEL_COMMAND` (the channel
    command's info display by default). A merged cmdset with
    `no_channels=True` suppresses channel matching.

    To preserve the sender identity of the account-level channel command,
    the send is attributed to the caller's account unless the caller is
    itself subscribed. A name match consumes the input even when the send
    lock fails; messaging the failure is `channel.send`'s job.

    Returns:
        True if handled, str for the bare-name rewrite, None to pass on.

    """
    if cmdset.no_channels:
        return None
    candidates = get_channel_candidates(caller)
    if not candidates:
        return None
    lowered = raw_string.strip().lower()
    names = [name for name in candidates if lowered == name or lowered.startswith(name + " ")]
    if not names:
        return None
    name = max(names, key=len)
    channel = candidates[name]
    if isinstance(channel, str):
        from evennia.comms.models import ChannelDB

        channel = ChannelDB.objects.get_channel(channel)
        if channel is None:
            # stale personal nick pointing at a deleted channel
            return None
    if not (channel.access(caller, "listen") or channel.access(caller, "control")):
        return None
    message = raw_string.strip()[len(name) :].strip()
    if not message:
        # bare channel name: defer to the configured channel command
        # (the dbref form is safe for multi-word channel keys)
        return f"{settings.COMMAND_FALLBACK_CHANNEL_COMMAND} #{channel.id}"
    account = getattr(caller, "account", None)
    # subscriptions.has is a strict per-entity check (unlike has_connection,
    # which falls back to the puppet's account)
    sender = account if account and not channel.subscriptions.has(caller) else caller
    channel.send(sender, message, session=session)
    return True


def resolve_nicks(caller, raw_string, cmdset, session=None, **kwargs):
    """
    Fallback resolver: apply inputline/channel nick replacement.

    Account-level nicks are included when the caller is an object (a puppet);
    accounts and sessions use only their own nicks.

    Returns:
        str: The rewritten input, if a nick matched - the cmdhandler
        re-parses with it. None if nothing changed.

    """
    nicks = getattr(caller, "nicks", None)
    if not nicks:
        return None
    rewritten = nicks.nickreplace(
        raw_string,
        categories=("inputline", "channel"),
        include_account=hasattr(caller, "has_account"),
    )
    return rewritten if rewritten != raw_string else None
