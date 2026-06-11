# Command Sets


Command Sets are intimately linked with [Commands](./Commands.md) and you should be familiar with
Commands before reading this page. The two pages were split for ease of reading.

A *Command Set* (often referred to as a CmdSet or cmdset) is the basic unit for storing one or more
*Commands*. A given Command can go into any number of different command sets. Storing Command
classes in a command set is the way to make commands available to use in your game.

When storing a CmdSet on an object, you will make the commands in that command set available to the
object. An example is the default command set stored on new Characters. This command set contains
all the useful commands, from `look` and `inventory` to `@dig` and `@reload`
([permissions](./Permissions.md) then limit which players may use them, but that's a separate
topic).

When an account enters a command, cmdsets from the Account, Character, its location, and elsewhere
are pulled together into a stack of *layers*. This stack is resolved top-down by priority into a
single resolved cmdset, representing the pool of commands available at that very moment.

An example would be a `Window` object that has a cmdset with two commands in it: `look through
window` and `open window`. The command set would be visible to players in the room with the window,
allowing them to use those commands only there. You could imagine all sorts of clever uses of this,
like a `Television` object which had multiple commands for looking at it, switching channels and so
on. The tutorial world included with Evennia showcases a dark room that replaces certain critical
commands with its own versions because the Character cannot see.

If you want a quick start into defining your first commands and using them with command sets, you
can head over to the [Adding Command Tutorial](../Howtos/Beginner-Tutorial/Part1/Beginner-Tutorial-Adding-Commands.md) which steps through things
without the explanations.

## Defining Command Sets

A CmdSet is, as most things in Evennia, defined as a Python class inheriting from the correct parent
(`evennia.CmdSet`, which is a shortcut to `evennia.commands.cmdset.CmdSet`). The CmdSet class only
needs to define one method, called `at_cmdset_creation()`. All other class parameters are optional,
but are used for more advanced set manipulation and coding (see the [merge rules](Command-
Sets#merge-rules) section).

```python
# file mygame/commands/mycmdset.py

from evennia import CmdSet

# this is a theoretical custom module with commands we
# created previously: mygame/commands/mycommands.py
from commands import mycommands

class MyCmdSet(CmdSet):
    def at_cmdset_creation(self):
        """
        The only thing this method should need
        to do is to add commands to the set.
        """
        self.add(mycommands.MyCommand1())
        self.add(mycommands.MyCommand2())
        self.add(mycommands.MyCommand3())
```

The CmdSet's `add()` method can also take another CmdSet as input. In this case all the commands
from that CmdSet will be appended to this one as if you added them line by line:

```python
    def at_cmdset_creation():
        ...
        self.add(AdditionalCmdSet) # adds all command from this set
        ...
```

If you added your command to an existing cmdset (like to the default cmdset), that set is already
loaded into memory. You need to make the server aware of the code changes:

```
@reload
```

You should now be able to use the command.

If you created a new, fresh cmdset, this must be added to an object in order to make the commands
within available. A simple way to temporarily test a cmdset on yourself is use the `@py` command to
execute a python snippet:

```python
@py self.cmdset.add('commands.mycmdset.MyCmdSet')
```

This will stay with you until you `@reset` or `@shutdown` the server, or you run

```python
@py self.cmdset.delete('commands.mycmdset.MyCmdSet')
```

In the example above, a specific Cmdset class is removed. Calling `delete` without arguments will
remove the latest added cmdset.

> Note: Command sets added using `cmdset.add` are, by default, *not* persistent in the database.

If you want the cmdset to survive a reload, you can do:

```
@py self.cmdset.add(commands.mycmdset.MyCmdSet, persistent=True)
```

Or you could add the cmdset as the *default* cmdset:

```
@py self.cmdset.add_default(commands.mycmdset.MyCmdSet)
```

An object can only have one "default" cmdset (but can also have none). This is meant as a safe fall-
back even if all other cmdsets fail or are removed. It is always persistent and will not be affected
by `cmdset.delete()`. To remove a default cmdset you must explicitly call `cmdset.remove_default()`.

Command sets are often added to an object in its `at_object_creation` method. For more examples of
adding commands, read the [Step by step tutorial](../Howtos/Beginner-Tutorial/Part1/Beginner-Tutorial-Adding-Commands.md). Generally you can
customize which command sets are added to your objects by using `self.cmdset.add()` or
`self.cmdset.add_default()`.

> Important: Within a command set, commands are identified by their `key`. Adding a Command to a
command set that already has a command with the same key will *replace* the previous command. This
is how you overload default Evennia commands with your own: add a command with the same key to a
higher-priority (or the same) cmdset. Aliases don't destroy commands - if two commands with
different keys share an alias, the contested alias simply goes to the command in the higher layer
while both commands stay reachable through their other names.

### Properties on Command Sets

There are several extra flags that you can set on CmdSets in order to modify how they work. All are
optional and will be set to defaults otherwise.  Since many of these relate to *layering* cmdsets,
you might want to read the [Adding and Layering Command Sets](./Command-Sets.md#adding-and-layering-
command-sets) section for some of these to make sense.

- `key` (string) - an identifier for the cmdset. This is optional, but should be unique. It is used
for display in lists and to selectively remove cmdsets.
- `priority` (int) - This defines the layer order of the stack - the resolved cmdset is built
top-down with the highest-priority set on top. A command whose key is claimed by a higher layer is
shadowed entirely. On identical priorities, same-key commands from *different source objects*
coexist (the player gets a multimatch), while for cmdsets on the same object the one added later
wins. The priority value must be greater or equal to `-100`. Most in-game sets should usually have
priorities between `0` and `100`. Evennia default sets have priorities as follows (these can be
changed if you want a different distribution):
    - EmptySet: `-101` (should be lower than all other sets)
    - SessionCmdSet: `-20`
    - AccountCmdSet: `-10`
    - CharacterCmdSet: `0`
    - ExitCmdSet: ` 101` (generally should always be available)
    - ChannelCmdSet: `101` (should usually always be available) - since exits never accept
arguments, there is no collision between exits named the same as a channel even though the commands
"collide".
- `exclusive` (bool, default `False`) - while this cmdset is active, all lower layers are blocked
entirely. This is what menus ([EvMenu](./EvMenu.md)) and editors use to take over the input. Layers
with *higher* priority still resolve on top of an exclusive layer.
- `removes` (iterable of strings, default empty) - command keys to filter out of all lower layers,
without replacing them with anything. Use this to selectively disable commands while a state is
active.
- `no_objs` this is a flag for the cmdhandler that builds the set of commands available at every
moment. It tells the handler not to include cmdsets from objects around the account (nor from rooms
or inventory) when building the merged set. Exit commands will still be included. This option can
have three values:
    - `None` (default): Passthrough of any value set explicitly earlier in the merge stack. If never
set explicitly, this acts as `False`.
    - `True`/`False`: Explicitly turn on/off. If two sets with explicit `no_objs` are merged,
priority determines what is used.
- `no_exits` - this is a flag for the cmdhandler that builds the set of commands available at every
moment. It tells the handler not to include cmdsets from exits. This flag can have three values:
    - `None` (default):  Passthrough of any value set explicitly earlier in the merge stack. If
never set explicitly, this acts as `False`.
    - `True`/`False`: Explicitly turn on/off. If two sets with explicit `no_exits` are merged,
priority determines what is used.
- `no_channels` (bool) - this is a flag for the cmdhandler that builds the set of commands available
at every moment. It tells the handler not to include cmdsets from available in-game channels. This
flag can have three values:
    - `None` (default):  Passthrough of any value set explicitly earlier in the merge stack. If
never set explicitly, this acts as `False`.
    - `True`/`False`: Explicitly turn on/off. If two sets with explicit `no_channels` are merged,
priority determines what is used.

## Command Sets Searched

When a user issues a command, it is matched against the [merged](./Command-Sets.md#adding-and-merging-
command-sets) command sets available to the player at the moment. Which those are may change at any
time (such as when the player walks into the room with the `Window` object described earlier).

The currently valid command sets are collected from the following sources:

- The cmdsets stored on the currently active [Session](./Sessions.md). Default is the empty
`SessionCmdSet` with merge priority `-20`.
- The cmdsets defined on the [Account](./Accounts.md). Default is the AccountCmdSet with merge priority
`-10`.
- All cmdsets on the Character/Object (assuming the Account is currently puppeting such a
Character/Object). Merge priority `0`.
- The cmdsets of all objects carried by the puppeted Character (checks the `call` lock). Will not be
included if `no_objs` option is active in the merge stack.
- The cmdsets of the Character's current location (checks the `call` lock). Will not be included if
`no_objs` option is active in the merge stack.
- The cmdsets of objects in the current location (checks the `call` lock). Will not be included if
`no_objs` option is active in the merge stack.
- The cmdsets of Exits in the location. Merge priority `+101`. Will not be included if `no_exits`
*or* `no_objs` option is active in the merge stack.
- The [channel](./Channels.md) cmdset containing commands for posting to all channels the account
or character is currently connected to. Merge priority `+101`. Will not be included if `no_channels`
option is active in the merge stack.

Note that an object does not *have* to share its commands with its surroundings. A Character's
cmdsets should not be shared for example, or all other Characters would get multi-match errors just
by being in the same room. The ability of an object to share its cmdsets is managed by its `call`
[lock](./Locks.md). For example, [Character objects](./Objects.md) defaults to `call:false()` so that any
cmdsets on them can only be accessed by themselves, not by other objects around them. Another
example might be to lock an object with `call:inside()` to only make their commands available to
objects inside them, or `cmd:holds()` to make their commands available only if they are held.

### The cmdset gather cache

Collecting the cmdsets above is expensive - it means checking the `call` lock and calling the
`at_cmdset_get` hook of every object in the room and inventory, for every command input. Since the
result rarely changes between inputs, Evennia caches the gathered cmdsets per calling
session/account/object and reuses them until an engine event invalidates the cache (controlled by
the `CMDSET_GATHER_CACHE` setting, default `True`). The cache is invalidated automatically by
everything that normally changes which cmdsets apply:

- cmdset changes through the cmdset handler (`obj.cmdset.add/remove/clear/...`), including those made
  by [EvMenu](./EvMenu.md) and EvEditor
- objects moving in or out of the location or inventory
- [lock](./Locks.md) and permission changes
- puppeting/unpuppeting, login/logout and `quell`/`unquell`
- object deletion, typeclass swaps and renames
- server `reload` (the cache is memory-only and never survives a restart)

Adding commands directly to a live `CmdSet` instance (like `cmdset.add(cmd)` on a stacked set) also
shows up on the next input without any of the events above - the merge step re-reads each cmdset's
content fingerprint every time.

Two things change meaning when the cache is active:

- The `at_cmdset_get` hook of surrounding objects runs when the cache is (re)built, not on every
  command input. If your hook mutates the object's cmdsets per input, set `cmdset_dynamic = True` on
  its typeclass - such objects get their `call` lock, hook and cmdsets re-evaluated on every input
  while the rest of the gather stays cached. Setting `cmdset_dynamic = True` on a Session, Account or
  puppeted Object instead disables gather-caching entirely for every caller it serves.
- The `call` lock of surrounding objects is likewise checked at rebuild time. Lock *edits* are picked
  up automatically (see above), but a lock whose *outcome* depends on un-tracked state - like
  `attr()`, `holds()` or time-based locks - will not flip until some other event triggers a rebuild.
  Either set `cmdset_dynamic = True` on the locked object, or call `obj.cmdset.invalidate_caches()`
  yourself when the relevant state changes.

Setting `CMDSET_GATHER_CACHE = False` restores the previous behavior of re-gathering everything on
every input.

## Adding and Layering Command Sets

*Note: This is an advanced topic. It's very useful to know about, but you might want to skip it if
this is your first time learning about commands.*

CmdSets *layer* on top of each other. Which of the ingoing commands end up available is defined by
the relative *priorities* of the sets and their `exclusive`/`removes` declarations. Removing the
latest added set will restore things back to the way it was before the addition.

CmdSets are non-destructively stored in a stack inside the cmdset handler on the object. This stack
is resolved to create the "combined" cmdset active at the moment. CmdSets from other sources are
also included in the resolution, such as those on objects in the same room (like buttons to press)
or those introduced by state changes (such as when entering a menu). The cmdsets are ordered by
priority and resolved *top-down* - think of it like a layered cake with the highest priority on
top. By defining a cmdset with a priority between that of two other sets, you slot it in between
them.
The very first cmdset in this stack is called the *Default cmdset* and is protected from accidental
deletion. Running `obj.cmdset.delete()` will never delete the default set. Instead one should add
new cmdsets on top of the default to "hide" it, as described below.  Use the special
`obj.cmdset.delete_default()` only if you really know what you are doing.

CmdSet layering is an advanced feature useful for implementing powerful game effects. Imagine for
example a player entering a dark room. You don't want the player to be able to find everything in
the room at a glance - maybe you even want them to have a hard time to find stuff in their backpack!
You can then define a different CmdSet with commands that override the normal ones. While they are
in the dark room, maybe the `look` and `inv` commands now just tell the player they cannot see
anything! Another example would be to offer special combat commands only when the player is in
combat. Or when being on a boat. Or when having taken the super power-up. All this can be done on
the fly by layering command sets.

### Layer Rules

The resolution walks the stack from the highest-priority layer downwards and decides, per command,
whether it is available:

- **Key shadowing** - a command whose `key` is already claimed by a higher layer is shadowed
entirely; none of its aliases remain reachable. This is how a higher-priority `look` replaces the
default `look`.

         # the high-prio set wins keys 1 and 2; B's unique commands survive
         A1,A2 (prio 1)  over  B1,B2,B3,B4 (prio 0)  =  A1,A2,B3,B4

- **Alias binding** - commands with *different* keys that share an alias all stay live. The
contested name binds to the command in the higher layer; the lower command stays reachable via its
key and other aliases. (A command with key `lock` and alias `l` above a `look` with alias `l` takes
over `l`, but `look` still works as `look`.)

- **Priority ties** - same-key commands from *different source objects* coexist and produce a
multimatch (the player gets a list to choose from). This is what makes two same-named exits, or a
`red button` and a `green button` that both define `press button`, disambiguate with `1-press
button`/`2-press button`. Same-key commands from cmdsets on the *same* object dedupe instead - the
set added later wins.

- **`exclusive`** - an exclusive layer blocks all layers below it, no matter their content. Menus
and editors use this to take over input completely. Layers with higher priority still resolve on
top of an exclusive layer (this is why the editor, at priority 150, works inside a menu at
priority 1).

         # exclusive replaces everything below
         A1,A3 (prio 1, exclusive)  over  B1,B2,B4,B5 (prio 0)  =  A1,A3

- **`removes`** - the listed command keys are filtered from all lower layers, without replacement.
This is a filter that prunes lower layers; the removing set may itself be empty.

         # removes=["1", "3"] filters the lower set
         A(removes=1,3) (prio 1)  over  B1,B2,B3,B4,B5 (prio 0)  =  B2,B4,B5

- **System commands** - commands with keys starting with `__` (like `__noinput_command`) bypass
shadowing, `exclusive` and `removes` entirely; per key, the highest layer's version applies.

A cmdset example using these declarations:

```python
from commands import mycommands

class DarkRoomCmdSet(CmdSet):

    key = "DarkRoomCmdSet"
    priority = 4
    # while in the dark, "search" from lower layers is unavailable
    removes = ["search"]

    def at_cmdset_creation(self):
        """
        The only thing this method should need
        to do is to add commands to the set.
        """
        self.add(mycommands.DarkLook())
        self.add(mycommands.DarkInventory())
```

### Assorted Notes

Within a single cmdset, `add()`ing a command whose `key` matches an existing command *replaces* the
old one. Aliases never destroy commands - across layers, a shared alias just rebinds to the higher
layer. So for these two Commands:

 - A Command with key "kick" and alias "fight"
 - A Command with key "punch" also with an alias "fight"

both remain available if they end up in different layers; "fight" triggers whichever sits in the
higher layer (on a priority tie, the one added later), while "kick" and "punch" always reach their
respective commands. Shared aliases are thus no longer destructive - but they can still surprise
players, so use them deliberately.
