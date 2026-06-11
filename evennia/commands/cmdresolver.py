"""
Layer-stack resolution of command sets.

This replaces the old set-theory merge algebra (Union/Intersect/Replace/Remove
mergetypes, `key_mergetypes` and the `duplicates` tri-state). All cmdsets
gathered for an entity form a stack of layers, sorted by `priority` and
resolved top-down into a name -> command binding table:

- A command whose key is already claimed by a higher layer is fully shadowed
  (none of its names remain reachable).
- Commands with *different* keys that share an alias each stay live; the
  contested name binds to the higher-layer command while the lower command
  remains reachable via its other names.
- Same-key commands at equal priority coexist when they come from *different
  source objects* (two exits named "north", a room object's and an inventory
  object's `press`) and produce a multimatch. Within one source's stack the
  later-added entry wins.
- A layer with `exclusive = True` blocks all layers below it (the old
  `mergetype = "Replace"`). Layers above it still resolve on top.
- A layer's `removes` lists command keys to filter from all layers below it
  (the old `mergetype = "Remove"`).
- System commands (keys starting with `__`) bypass shadowing, `exclusive` and
  `removes` entirely; per key the highest layer wins. They stay parser-matchable
  through all their names (`CMD_LOGINSTART` arrives as raw input on connect, and
  the unloggedin look command is reachable as `look`/`l` through its aliases),
  though a normal command keeps any contested name.
- The `no_exits`/`no_objs`/`no_channels` flags resolve to the first non-None
  value top-down, independently of `exclusive` (matching how flags always
  passed through Replace merges).

The result is a `ResolvedCmdSet`, a read-only artifact exposing the parts of
the old merged-CmdSet surface that downstream code uses, plus `bindings` - a
`BindingTable` the command parser matches input against.

"""

from django.conf import settings

__all__ = ("BindingTable", "ResolvedCmdSet", "make_bindings", "resolve_cmdsets")

_CMD_IGNORE_PREFIXES = settings.CMD_IGNORE_PREFIXES


class BindingTable:
    """
    Name -> candidate-command lookup for parsing.

    Args:
        bound (dict): `{name (str): [Command, ...]}` with candidates in
            precedence order (highest first). Multiple candidates for one
            name mean a multimatch.

    """

    def __init__(self, bound):
        self.names = {name: tuple(cmds) for name, cmds in bound.items()}
        self._lengths = sorted({len(name) for name in self.names}, reverse=True)
        noprefix = {}
        for name, cmds in bound.items():
            stripped = name.lstrip(_CMD_IGNORE_PREFIXES) if len(name) > 1 else name
            entries = noprefix.setdefault(stripped, [])
            entries.extend((name, cmd) for cmd in cmds)
        self._noprefix = {name: tuple(entries) for name, entries in noprefix.items()}
        self._noprefix_lengths = sorted({len(name) for name in self._noprefix}, reverse=True)

    def candidates(self, search_string, include_prefixes=True):
        """
        Find all commands one of whose bound names prefixes `search_string`.

        Args:
            search_string (str): Lowercase input string; the command name must
                be first in it.
            include_prefixes (bool): If unset, match against names with
                CMD_IGNORE_PREFIXES stripped, like `Command.match`.

        Returns:
            list: `(cmdname, raw_cmdname, command)` tuples. Per command only
            its longest name that both prefixes the input and passes the
            command's `arg_regex` is returned, mirroring `Command.match`.

        """
        if include_prefixes:
            index, lengths = self.names, self._lengths
            entries_for = lambda chunk: tuple((chunk, cmd) for cmd in index.get(chunk, ()))
        else:
            index, lengths = self._noprefix, self._noprefix_lengths
            entries_for = lambda chunk: index.get(chunk, ())

        matched = set()
        results = []
        for length in lengths:
            if length > len(search_string):
                continue
            chunk = search_string[:length]
            remainder = search_string[length:]
            for raw_cmdname, cmd in entries_for(chunk):
                if id(cmd) in matched:
                    continue
                if not cmd.arg_regex or cmd.arg_regex.match(remainder):
                    matched.add(id(cmd))
                    results.append((chunk, raw_cmdname, cmd))
        return results


def make_bindings(commands):
    """
    Build a BindingTable from a plain command iterable, without any shadowing:
    every command is reachable on every one of its names, exactly as when the
    parser polled each command's `match()` directly. This is the fallback used
    when the parser is handed a plain CmdSet instead of a ResolvedCmdSet.

    Args:
        commands (iterable): Command instances.

    Returns:
        BindingTable: The lookup table.

    """
    bound = {}
    for cmd in commands:
        for name in cmd._keyaliases:
            bound.setdefault(name, []).append(cmd)
    return BindingTable(bound)


class ResolvedCmdSet:
    """
    The read-only result of resolving a stack of cmdset layers. This replaces
    the merged CmdSet produced by the old `__add__` folds and duck-types the
    parts of that surface that downstream code uses (help system iteration,
    `get` for system commands, `merged_from` introspection).

    """

    # layer-compatible class attrs so a resolved set can itself be fed back
    # into resolve_cmdsets() as one layer (the cmdhandler does this when
    # building the merged-so-far context for at_cmdset_get hooks)
    exclusive = False
    removes = ()
    cmdsetobj = None
    errmessage = ""
    persistent = False
    path = "evennia.commands.cmdresolver.ResolvedCmdSet"

    def __init__(
        self,
        key,
        priority,
        commands,
        system_commands,
        bindings,
        no_exits=None,
        no_objs=None,
        no_channels=None,
        merged_from=None,
    ):
        self.key = key
        self.priority = priority
        self.commands = commands
        self.system_commands = system_commands
        self.bindings = bindings
        self.no_exits = no_exits
        self.no_objs = no_objs
        self.no_channels = no_channels
        self.merged_from = merged_from or []

    def __str__(self):
        return "ResolvedCmdSet(%s, prio %s, %i commands)" % (
            self.key,
            self.priority,
            len(self.commands),
        )

    def __iter__(self):
        return iter(self.commands)

    def __contains__(self, other):
        if isinstance(other, str):
            return other in self.bindings.names
        return any(cmd is other for cmd in self.commands)

    def get(self, cmd):
        """
        Get a command from the resolved set by key, alias or instance.

        Args:
            cmd (Command or str): The command or command key/alias to look for.

        Returns:
            Command or None: The first match, with key matches preferred
            over alias matches.

        """
        if isinstance(cmd, str):
            for command in self.commands:
                if command.key == cmd:
                    return command
            for command in self.commands:
                if cmd in command._matchset:
                    return command
            return None
        return cmd if any(command is cmd for command in self.commands) else None

    def count(self):
        """
        Number of commands in the resolved set.

        Returns:
            int: The number of commands.

        """
        return len(self.commands)

    def get_system_cmds(self):
        """
        Get system commands in the resolved set.

        Returns:
            list: The system (`__`-prefixed) commands.

        """
        return self.system_commands

    def make_unique(self, caller):
        """
        Remove duplicate command-keys, with preference to commands defined on
        `caller`. Same contract as the old merged-CmdSet method; used by the
        help system to collapse cross-source multimatches.

        Args:
            caller (object): Commands on this object get preference.

        """
        unique = {}
        for cmd in self.commands:
            if cmd.key in unique:
                ocmd = unique[cmd.key]
                if (hasattr(cmd, "obj") and cmd.obj == caller) and not (
                    hasattr(ocmd, "obj") and ocmd.obj == caller
                ):
                    unique[cmd.key] = cmd
            else:
                unique[cmd.key] = cmd
        self.commands = list(unique.values())

    def get_all_cmd_keys_and_aliases(self, caller=None):
        """
        Collect keys and aliases from all commands in the resolved set.

        Args:
            caller (Object, optional): If given, only commands `caller`
                passes the 'call' locktype check for are included.

        Returns:
            list: All command keys and aliases.

        """
        names = []
        for cmd in self.commands:
            if caller is None or cmd.access(caller):
                names.extend(cmd._keyaliases)
        return names


def resolve_cmdsets(entries):
    """
    Resolve a gather of cmdsets into a ResolvedCmdSet.

    Args:
        entries (iterable): `(cmdset, source)` pairs in gather order (least
            precedence first on priority ties). `source` is the entity whose
            cmdset stack contributed the set (Session, Account or Object) or
            None; it defines coexistence identity at equal priority.

    Returns:
        ResolvedCmdSet or None: The resolved artifact, or None for an
        empty gather.

    """
    entries = list(entries)
    if not entries:
        return None

    # stable sort, then reverse: top-down by priority, later-gathered above
    # on ties (matching the runtime gather's tie direction)
    layers = sorted(entries, key=lambda entry: entry[0].priority)
    layers.reverse()

    top = layers[0][0]
    no_exits = no_objs = no_channels = None
    removed_keys = set()
    barrier = False
    key_claims = {}
    selected = []
    sys_claims = {}

    for cmdset, source in layers:
        if no_exits is None:
            no_exits = cmdset.no_exits
        if no_objs is None:
            no_objs = cmdset.no_objs
        if no_channels is None:
            no_channels = cmdset.no_channels

        for cmd in reversed(cmdset.system_commands):
            sys_claims.setdefault(cmd.key, cmd)

        if barrier:
            continue

        # later-added stack entries take precedence within one layer
        for cmd in reversed(cmdset.commands):
            key = cmd.key
            if key.startswith("__") or key in removed_keys:
                continue
            claim = key_claims.get(key)
            if claim is None:
                key_claims[key] = (cmdset.priority, {source})
                selected.append(cmd)
            else:
                claim_priority, claim_sources = claim
                if claim_priority > cmdset.priority or source in claim_sources:
                    continue
                claim_sources.add(source)
                selected.append(cmd)

        removed_keys.update(str(key).lower() for key in cmdset.removes)
        if cmdset.exclusive:
            barrier = True

    system_commands = list(sys_claims.values())

    bound = {}
    for cmd in selected + system_commands:
        for name in cmd._keyaliases:
            candidates = bound.get(name)
            if candidates is None:
                bound[name] = [cmd]
            elif candidates[0].key == cmd.key:
                # same-key coexistence group -> multimatch candidates
                candidates.append(cmd)
            # different key: the name stays bound to the higher command

    return ResolvedCmdSet(
        top.key,
        top.priority,
        selected + system_commands,
        system_commands,
        BindingTable(bound),
        no_exits=no_exits,
        no_objs=no_objs,
        no_channels=no_channels,
        merged_from=[cmdset for cmdset, _ in entries],
    )
