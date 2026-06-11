"""

A Command Set (CmdSet) holds a set of commands. All cmdsets available to an
entity form a stack of layers that is resolved top-down by priority into the
final set of available commands (see `evennia.commands.cmdresolver`). This
makes them powerful for implementing custom game states where different
commands (or different variations of commands) are available to the accounts
depending on circumstance.

A cmdset declares how it layers:

* priority - higher-priority cmdsets shadow same-key commands in lower
    layers. On ties, commands from different source objects coexist (the
    player gets a multimatch), while later-added cmdsets on the same object
    win.
* exclusive - this cmdset blocks all lower layers entirely while it is
    active (menus, editors). Layers with higher priority still resolve on
    top of it.
* removes - a list of command keys to filter out of all lower layers,
    without replacing them with anything.

"""

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext as _

from evennia.utils.utils import inherits_from, is_iter

__all__ = ("CmdSet",)


class _CmdSetMeta(type):
    """
    This metaclass makes some minor on-the-fly convenience fixes to
    the cmdset class.

    """

    def __init__(cls, *args, **kwargs):
        """
        Fixes some things in the cmdclass

        """
        # by default we key the cmdset the same as the
        # name of its class.
        if not hasattr(cls, "key") or not cls.key:
            cls.key = cls.__name__
        cls.path = "%s.%s" % (cls.__module__, cls.__name__)

        # --- LEGACY MERGETYPE SHIM ---
        # Translate old set-theory declarations to the layer-stack model so
        # out-of-tree cmdsets keep working. Remove once nothing declares
        # `mergetype` anymore.
        legacy_mergetype = vars(cls).get("mergetype")
        if legacy_mergetype == "Replace":
            cls.exclusive = True
        elif legacy_mergetype == "Remove":
            cls._legacy_remove = True
        elif legacy_mergetype == "Intersect":
            raise ImproperlyConfigured(
                f"CmdSet {cls.path}: mergetype='Intersect' is no longer supported. "
                "Cmdsets resolve as a layer stack; see evennia.commands.cmdresolver."
            )
        if legacy_mergetype or vars(cls).get("key_mergetypes") or vars(cls).get("duplicates"):
            from evennia.utils import logger

            logger.log_dep(
                f"CmdSet {cls.path} declares legacy merge attributes "
                "(mergetype/key_mergetypes/duplicates). Cmdsets resolve as a layer "
                "stack; use `exclusive`/`removes` (key_mergetypes and duplicates "
                "are ignored). See evennia.commands.cmdresolver."
            )
        # --- END LEGACY MERGETYPE SHIM ---

        super().__init__(*args, **kwargs)


class CmdSet(object, metaclass=_CmdSetMeta):
    """
    This class describes a unique cmdset that understands priorities.
    All cmdsets available to an entity form a stack of layers, resolved
    top-down into the final set of available commands (see
    `evennia.commands.cmdresolver`).

    key - the name of the cmdset. This can be used on its own for game
    operations.

    priority - higher-priority cmdsets shadow same-key commands in lower
              layers (an overridden command disappears entirely, aliases
              included). Commands with different keys that share an alias
              all stay live; the contested name goes to the higher layer.
              On priority ties, same-key commands from different source
              objects coexist (the player gets a multimatch - e.g. two
              exits named the same, or two objects in a room defining the
              same command), while later-added cmdsets on the same object
              win. Default commands have priority 0; priorities can be
              negative to give default commands preference.

    exclusive - while this cmdset is active, all lower layers are blocked
              entirely (used by menus and editors). Layers with higher
              priority still resolve on top of it.

    removes - an iterable of command keys to filter out of all lower
              layers, without replacing them with anything.

              Note: Commands with keys starting with double underscores,
              like '__noinput_command', are considered 'system commands'
              and bypass shadowing, `exclusive` and `removes` entirely -
              per key, the highest layer's version applies.

    no_objs - don't include any commands from nearby objects
                  when searching for suitable commands
    no_exits - ignore the names of exits when matching against
                        commands
    no_channels - ignore the name of channels when matching against
                        commands (WARNING- this is dangerous since the
                        account can then not even ask staff for help if
                        something goes wrong)

    """

    key = "Unnamed CmdSet"
    priority = 0

    # an exclusive cmdset blocks all lower layers entirely; `removes` lists
    # command keys to filter from all lower layers.
    exclusive = False
    removes = ()
    # legacy-shim marker: set by the metaclass for mergetype="Remove" classes
    _legacy_remove = False

    # These flags, if set to None should be interpreted as 'I don't care' and,
    # will allow "pass-through" even of lower-prio cmdsets' explicitly True/False
    # options. If this is set to True/False however, priority matters.
    no_exits = None
    no_objs = None
    no_channels = None

    persistent = False
    errmessage = ""

    def __init__(self, cmdsetobj=None, key=None):
        """
        Creates a new CmdSet instance.

        Args:
            cmdsetobj (Session, Account, Object, optional): This is the database object
                to which this particular instance of cmdset is related. It
                is often a character but may also be a regular object, Account
                or Session.
            key (str, optional): The idenfier for this cmdset. This
                helps if wanting to selectively remov cmdsets.

        """

        if key:
            self.key = key
        self.commands = []
        self.system_commands = []
        self.cmdsetobj = cmdsetobj

        # initialize system
        self.at_cmdset_creation()
        self._cached_fingerprint = None

        # --- LEGACY MERGETYPE SHIM ---
        # a legacy mergetype="Remove" cmdset contributes no commands of its
        # own; its command keys become the filter for lower layers.
        if self._legacy_remove and not self.removes:
            self.removes = tuple(cmd.key for cmd in self.commands if not cmd.key.startswith("__"))
            self.commands = [cmd for cmd in self.commands if cmd.key.startswith("__")]
        # --- END LEGACY MERGETYPE SHIM ---

    @property
    def fingerprint(self):
        """
        A hashable, content-based fingerprint of this cmdset. Two cmdsets with
        identical commands and merge properties produce the same fingerprint.
        Lazily computed and cached; invalidated when commands are added/removed
        or when `make_unique` deduplicates the command list.

        The fingerprint includes `cmd.obj` and `self.cmdsetobj` (the object this
        cmdset sits on) so that two structurally identical cmdsets on different
        game objects (e.g. ExitCmdSets with north/south in different rooms) are
        correctly distinguished. These must be hashable — Evennia's TypedObject
        (Django model with integer PK) satisfies this; an unhashable obj here
        would indicate a deeper problem.

        Note: Including live object references means the cache holds strong refs
        to those objects, preventing garbage collection while the entry exists.
        """
        if self._cached_fingerprint is None:
            # the command collections are order-sensitive tuples: stack order
            # decides ties and alias binding in the layer resolution
            cmd_ids = tuple((frozenset(cmd._matchset), cmd.obj) for cmd in self.commands)
            sys_cmd_ids = tuple((frozenset(cmd._matchset), cmd.obj) for cmd in self.system_commands)
            self._cached_fingerprint = (
                self.key,
                self.priority,
                bool(self.exclusive),
                tuple(sorted(str(key).lower() for key in self.removes)),
                self.no_exits,
                self.no_objs,
                self.no_channels,
                self.cmdsetobj,
                cmd_ids,
                sys_cmd_ids,
            )
        return self._cached_fingerprint

    def _instantiate(self, cmd):
        """
        checks so that object is an instantiated command and not, say
        a cmdclass. If it is, instantiate it.  Other types, like
        strings, are passed through.

        Args:
            cmd (any): Entity to analyze.

        Returns:
            result (any): An instantiated Command or the input unmodified.

        """
        if callable(cmd):
            return cmd()
        else:
            return cmd

    def __str__(self):
        """
        Show all commands in cmdset when printing it.

        Returns:
            commands (str): Representation of commands in Cmdset.

        """
        perm = "perm" if self.persistent else "non-perm"
        options = ", ".join(
            [
                "{}:{}".format(opt, "T" if getattr(self, opt) else "F")
                for opt in ("no_exits", "no_objs", "no_channels")
                if getattr(self, opt) is not None
            ]
        )
        options = (", " + options) if options else ""
        exclusive = ", exclusive" if self.exclusive else ""
        removes = f", removes:{sorted(self.removes)}" if self.removes else ""
        return (
            f"<CmdSet {self.key}, {perm}, prio {self.priority}{exclusive}{removes}{options}>: "
            + ", ".join([str(cmd) for cmd in sorted(self.commands, key=lambda o: o.key)])
        )

    def __iter__(self):
        """
        Allows for things like 'for cmd in cmdset':

        Returns:
            iterable (iter): Commands in Cmdset.

        """
        return iter(self.commands)

    def __contains__(self, othercmd):
        """
        Returns True if this cmdset contains the given command instance.
        This allows for things like 'if cmd in cmdset'.

        """
        return any(cmd is othercmd for cmd in self.commands)

    def add(self, cmd):
        """
        Add a new command or commands to this CmdSet, a list of
        commands or a cmdset to this cmdset.

        Args:
            cmd (Command, list, Cmdset): This allows for adding one or
                more commands to this Cmdset in one go. If another Cmdset
                is given, all its commands will be added.

        Notes:
            If a command with the same key already exists in the set, it
            will be replaced by the new one (no priority checking etc
            happens here). This is very useful when overloading default
            commands.

            If cmd is another cmdset class or -instance, the commands of
            that command set is added to this one, as if they were part of
            the original cmdset definition. No layering or priority checks
            are made, rather later added commands will simply replace
            existing ones to make a unique set.

        """
        if inherits_from(cmd, "evennia.commands.cmdset.CmdSet"):
            # cmd is a command set so merge all commands in that set
            # to this one. We raise a visible error if we created
            # an infinite loop (adding cmdset to itself somehow)
            cmdset = cmd
            try:
                cmdset = self._instantiate(cmdset)
            except RuntimeError:
                err = (
                    "Adding cmdset {cmdset} to {cls} lead to an "
                    "infinite loop. When adding a cmdset to another, "
                    "make sure they are not themself cyclically added to "
                    "the new cmdset somewhere in the chain."
                )
                raise RuntimeError(_(err.format(cmdset=cmdset, cls=self.__class__)))
            cmds = cmdset.commands
        elif is_iter(cmd):
            cmds = [self._instantiate(c) for c in cmd]
        else:
            cmds = [self._instantiate(cmd)]

        for cmd in cmds:
            # Ensure commands know their source cmdset.
            cmd.cmdset_source = self
            # add all commands
            if not hasattr(cmd, "obj") or cmd.obj is None:
                cmd.obj = self.cmdsetobj

            # same-key commands are replaced by the newcomer
            self.commands = [oldcmd for oldcmd in self.commands if oldcmd.key != cmd.key]
            self.commands.append(cmd)

            # add system_command to separate list as well, for quick look-up
            if cmd.key.startswith("__"):
                self.system_commands = [
                    oldcmd for oldcmd in self.system_commands if oldcmd.key != cmd.key
                ]
                self.system_commands.append(cmd)

        self._cached_fingerprint = None

    def remove(self, cmd):
        """
        Remove a command from the cmdset, by instance or key.

        Args:
            cmd (Command or str): Either the Command object to remove
                or the key of such a command.

        """
        cmd = self._instantiate(cmd)
        key = cmd if isinstance(cmd, str) else cmd.key
        self.commands = [oldcmd for oldcmd in self.commands if oldcmd.key != key]
        if key.startswith("__"):
            self.system_commands = [oldcmd for oldcmd in self.system_commands if oldcmd.key != key]
        self._cached_fingerprint = None

    def get(self, cmd):
        """
        Get a command from the cmdset. This is mostly useful to
        check if the command is part of this cmdset or not.

        Args:
            cmd (Command or str): Either the Command object or its
                key or alias.

        Returns:
            cmd (Command): The first matching Command in the set, with
                key matches preferred over alias matches.

        """
        cmd = self._instantiate(cmd)
        key = cmd if isinstance(cmd, str) else cmd.key
        for thiscmd in self.commands:
            if thiscmd.key == key:
                return thiscmd
        for thiscmd in self.commands:
            if key in thiscmd._matchset:
                return thiscmd
        return None

    def count(self):
        """
        Number of commands in set.

        Returns:
            N (int): Number of commands in this Cmdset.

        """
        return len(self.commands)

    def get_system_cmds(self):
        """
        Get system commands in cmdset

        Returns:
            sys_cmds (list): The system commands in the set.

        Notes:
            As far as the Cmdset is concerned, system commands are any
            commands with a key starting with double underscore __.
            These are excempt from merge operations.

        """
        return self.system_commands

    def make_unique(self, caller):
        """
        Remove duplicate command-keys (unsafe)

        Args:
            caller (object): Commands on this object will
                get preference in the duplicate removal.

        Notes:
            This is an unsafe command meant to clean out a cmdset of
            doublet commands after it has been created. It is useful
            for commands inheriting cmdsets from the cmdhandler where
            obj-based cmdsets always are added double. Doublets will
            be weeded out with preference to commands defined on
            caller, otherwise just by first-come-first-served.

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
        self._cached_fingerprint = None

    def get_all_cmd_keys_and_aliases(self, caller=None):
        """
        Collects keys/aliases from commands

        Args:
            caller (Object, optional): If set, this is used to check access permissions
                on each command. Only commands that pass are returned.

        Returns:
            names (list): A list of all command keys and aliases in this cmdset. If `caller`
                was given, this list will only contain commands to which `caller` passed
                the `call` locktype check.

        """
        names = []
        if caller:
            [names.extend(cmd._keyaliases) for cmd in self.commands if cmd.access(caller)]
        else:
            [names.extend(cmd._keyaliases) for cmd in self.commands]
        return names

    def at_cmdset_creation(self):
        """
        Hook method - this should be overloaded in the inheriting
        class, and should take care of populating the cmdset by use of
        self.add().

        """
        pass
