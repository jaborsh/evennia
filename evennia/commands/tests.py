"""
Unit testing for the Command system itself.

"""

from unittest.mock import MagicMock, patch

from django.test import override_settings

from evennia.commands import cmdparser, cmdsetcache
from evennia.commands.cmdset import CmdSet
from evennia.commands.command import Command
from evennia.utils.test_resources import BaseEvenniaTest, TestCase

# Testing-command sets


class _BaseCmd(Command):
    def __init__(self, cmdset, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.from_cmdset = cmdset


class _CmdA(_BaseCmd):
    key = "A"


class _CmdB(_BaseCmd):
    key = "B"


class _CmdC(_BaseCmd):
    key = "C"


class _CmdD(_BaseCmd):
    key = "D"


class _CmdEe(_BaseCmd):
    key = "E"
    aliases = ["ee"]


class _CmdEf(_BaseCmd):
    key = "E"
    aliases = ["ff"]


class _CmdSetA(CmdSet):
    key = "A"

    def at_cmdset_creation(self):
        self.add(_CmdA("A"))
        self.add(_CmdB("A"))
        self.add(_CmdC("A"))
        self.add(_CmdD("A"))


class _CmdSetB(CmdSet):
    key = "B"

    def at_cmdset_creation(self):
        self.add(_CmdA("B"))
        self.add(_CmdB("B"))
        self.add(_CmdC("B"))


class _CmdSetC(CmdSet):
    key = "C"

    def at_cmdset_creation(self):
        self.add(_CmdA("C"))
        self.add(_CmdB("C"))


class _CmdSetD(CmdSet):
    key = "D"

    def at_cmdset_creation(self):
        self.add(_CmdA("D"))
        self.add(_CmdB("D"))
        self.add(_CmdC("D"))
        self.add(_CmdD("D"))


class _CmdSetEe_Ef(CmdSet):
    key = "Ee_Ef"

    def at_cmdset_creation(self):
        self.add(_CmdEe("Ee"))
        self.add(_CmdEf("Ee"))


# testing Command Sets


import sys

from twisted.trial.unittest import TestCase as TwistedTestCase

import evennia
from evennia.commands import cmdhandler, fallbacks
from evennia.comms.comms import DefaultChannel
from evennia.server.sessionhandler import ServerSessionHandler
from evennia.utils.idmapper.models import flush_cache as idmapper_flush_cache


def _mockdelay(time, func, *args, **kwargs):
    return func(*args, **kwargs)


class TestGetAndMergeCmdSets(TwistedTestCase, BaseEvenniaTest):
    "Test the cmdhandler.get_and_merge_cmdsets function."

    def setUp(self):
        self.patch(sys.modules["evennia.server.sessionhandler"], "delay", _mockdelay)
        super().setUp()
        self.cmdset_a = _CmdSetA()
        self.cmdset_b = _CmdSetB()
        self.cmdset_c = _CmdSetC()
        self.cmdset_d = _CmdSetD()

    def set_cmdsets(self, obj, *args):
        "Set cmdets on obj in the order given in *args"
        for cmdset in args:
            obj.cmdset.add(cmdset)

    def test_from_session(self):
        a = self.cmdset_a
        a.no_channels = True
        self.set_cmdsets(self.session, a)
        (
            command_objects,
            command_objects_list,
            command_objects_list_error,
            caller,
            error_to,
        ) = cmdhandler.generate_cmdset_providers(self.session)

        deferred = cmdhandler.get_and_merge_cmdsets(
            self.session, [self.session], "session", "", error_to
        )

        def _callback(cmdset):
            self.assertEqual(cmdset.key, "A")

        deferred.addCallback(_callback)
        return deferred

    def test_from_account(self):
        from evennia.commands.default.cmdset_account import AccountCmdSet

        a = self.cmdset_a
        a.no_channels = True
        self.set_cmdsets(self.account, a)
        (
            command_objects,
            command_objects_list,
            command_objects_list_error,
            caller,
            error_to,
        ) = cmdhandler.generate_cmdset_providers(self.account)

        deferred = cmdhandler.get_and_merge_cmdsets(
            self.account, command_objects_list, "account", "", error_to
        )
        # get_and_merge_cmdsets converts  to lower-case internally.

        def _callback(cmdset):
            pcmdset = AccountCmdSet()
            pcmdset.at_cmdset_creation()
            pcmds = [cmd.key for cmd in pcmdset.commands] + ["a", "b", "c", "d"]
            self.assertEqual(set(cmd.key for cmd in cmdset.commands), set(pcmds))

        # _callback = lambda cmdset: self.assertEqual(sum(1 for cmd in cmdset.commands if cmd.key in ("a", "b", "c", "d")), 4)
        deferred.addCallback(_callback)
        return deferred

    def test_from_object(self):
        self.set_cmdsets(self.obj1, self.cmdset_a)
        (
            command_objects,
            command_objects_list,
            command_objects_list_error,
            caller,
            error_to,
        ) = cmdhandler.generate_cmdset_providers(self.obj1)

        deferred = cmdhandler.get_and_merge_cmdsets(
            self.obj1, command_objects_list, "object", "", error_to
        )
        # get_and_merge_cmdsets converts  to lower-case internally.

        def _callback(cmdset):
            return self.assertEqual(
                sum(1 for cmd in cmdset.commands if cmd.key in ("a", "b", "c", "d")), 4
            )

        deferred.addCallback(_callback)
        return deferred

    def test_multimerge(self):
        a, b, c, d = self.cmdset_a, self.cmdset_b, self.cmdset_c, self.cmdset_d
        a.no_exits = True
        a.no_channels = True
        self.set_cmdsets(self.obj1, a, b, c, d)
        (
            command_objects,
            command_objects_list,
            command_objects_list_error,
            caller,
            error_to,
        ) = cmdhandler.generate_cmdset_providers(self.obj1)
        deferred = cmdhandler.get_and_merge_cmdsets(
            self.obj1, command_objects_list, "object", "", error_to
        )

        def _callback(cmdset):
            self.assertTrue(cmdset.no_exits)
            self.assertTrue(cmdset.no_channels)
            self.assertEqual(cmdset.key, "D")

        deferred.addCallback(_callback)
        return deferred

    def test_same_source_dedupe(self):
        a, b, c, d = self.cmdset_a, self.cmdset_b, self.cmdset_c, self.cmdset_d
        a.no_exits = True
        a.no_channels = True
        self.set_cmdsets(self.obj1, a, b, c, d)
        (
            command_objects,
            command_objects_list,
            command_objects_list_error,
            caller,
            error_to,
        ) = cmdhandler.generate_cmdset_providers(self.obj1, session=None)

        deferred = cmdhandler.get_and_merge_cmdsets(
            self.obj1, command_objects_list, "object", "", error_to
        )

        def _callback(cmdset):
            # all stacked sets share obj1 as source: same-key commands dedupe
            # with the later-added set winning every key
            self.assertEqual(len(cmdset.commands), 4)
            self.assertTrue(all(cmd.from_cmdset == "D" for cmd in cmdset.commands))

        deferred.addCallback(_callback)
        return deferred

    def test_command_replace_different_aliases(self):
        cmdset_ee = _CmdSetEe_Ef()
        self.assertEqual(len(cmdset_ee.commands), 1)
        self.assertEqual(cmdset_ee.commands[0].key, "e")


class AccessableCommand(Command):
    def access(*args, **kwargs):
        return True


class _CmdTest1(AccessableCommand):
    key = "test1"
    arg_regex = None


class _CmdTest2(AccessableCommand):
    key = "another command"
    arg_regex = None


class _CmdTest3(AccessableCommand):
    key = "&the third command"
    arg_regex = None


class _CmdTest4(AccessableCommand):
    key = "test2"
    arg_regex = None


class _CmdSetTest(CmdSet):
    key = "test_cmdset"

    def at_cmdset_creation(self):
        self.add(_CmdTest1)
        self.add(_CmdTest2)
        self.add(_CmdTest3)


class TestCmdParser(TestCase):
    def test_create_match(self):
        class DummyCmd:
            pass

        dummy = DummyCmd()

        self.assertEqual(
            cmdparser.create_match("look at", "look at target", dummy, "look"),
            ("look at", " target", dummy, 7, 0.5, "look"),
        )

    @patch("evennia.commands.cmdparser.log_trace")
    def test_build_matches_masks_sensitive_input_on_error(self, mock_log_trace):
        class _BrokenCmdSet:
            def __iter__(self):
                raise RuntimeError("forced parser failure")

        cmdparser.build_matches("connect johnny password123", _BrokenCmdSet())
        self.assertTrue(mock_log_trace.called)

        logged = mock_log_trace.call_args[0][0]
        self.assertIn("connect johnny ***********", logged)
        self.assertNotIn("password123", logged)

    @override_settings(CMD_IGNORE_PREFIXES="@&/+")
    def test_build_matches(self):
        a_cmdset = _CmdSetTest()
        bcmd = [cmd for cmd in a_cmdset.commands if cmd.key == "test1"][0]

        # normal parsing
        self.assertEqual(
            cmdparser.build_matches("test1 rock", a_cmdset, include_prefixes=False),
            [("test1", " rock", bcmd, 5, 0.5, "test1")],
        )

        # test prefix exclusion
        bcmd = [cmd for cmd in a_cmdset.commands if cmd.key == "another command"][0]
        self.assertEqual(
            cmdparser.build_matches(
                "@another command smiles to me  ", a_cmdset, include_prefixes=False
            ),
            [("another command", " smiles to me  ", bcmd, 15, 0.5, "another command")],
        )
        # test prefix exclusion on the cmd class
        bcmd = [cmd for cmd in a_cmdset.commands if cmd.key == "&the third command"][0]
        self.assertEqual(
            cmdparser.build_matches("the third command", a_cmdset, include_prefixes=False),
            [("the third command", "", bcmd, 17, 1.0, "&the third command")],
        )

    @override_settings(SEARCH_MULTIMATCH_REGEX=r"(?P<number>[0-9]+)-(?P<name>.*)")
    def test_num_differentiators(self):
        self.assertEqual(cmdparser.try_num_differentiators("look me"), (None, None))
        self.assertEqual(cmdparser.try_num_differentiators("look me-3"), (3, "look me"))
        self.assertEqual(cmdparser.try_num_differentiators("look me-567"), (567, "look me"))

    def test_num_differentiators_hyphenated_names(self):
        """Test that hyphenated object names like 't-shirt-1' are parsed correctly.

        This tests the default SEARCH_MULTIMATCH_REGEX which uses the format 'name-number'.
        Objects with hyphens in their names (e.g., 't-shirt') should be correctly parsed
        when disambiguated (e.g., 't-shirt-1' should return (1, 't-shirt')).

        See: https://github.com/evennia/evennia/issues/3691
        """
        # Simple name without hyphen - should work
        self.assertEqual(cmdparser.try_num_differentiators("ball-1"), (1, "ball"))
        self.assertEqual(cmdparser.try_num_differentiators("ball-23"), (23, "ball"))

        # Hyphenated name - this is the bug case
        self.assertEqual(cmdparser.try_num_differentiators("t-shirt-1"), (1, "t-shirt"))
        self.assertEqual(cmdparser.try_num_differentiators("t-shirt-2"), (2, "t-shirt"))

        # Multiple hyphens in name
        self.assertEqual(
            cmdparser.try_num_differentiators("some-long-name-3"), (3, "some-long-name")
        )

        # No number suffix - should return (None, None)
        self.assertEqual(cmdparser.try_num_differentiators("t-shirt"), (None, None))
        self.assertEqual(cmdparser.try_num_differentiators("ball"), (None, None))

        # With trailing args (space after the number)
        self.assertEqual(cmdparser.try_num_differentiators("t-shirt-1 arg"), (1, "t-shirt arg"))
        self.assertEqual(
            cmdparser.try_num_differentiators("ball-2 some args"), (2, "ball some args")
        )

    @override_settings(
        SEARCH_MULTIMATCH_REGEX=r"(?P<number>[0-9]+)-(?P<name>.*)", CMD_IGNORE_PREFIXES="@&/+"
    )
    def test_cmdparser(self):
        a_cmdset = _CmdSetTest()
        bcmd = [cmd for cmd in a_cmdset.commands if cmd.key == "test1"][0]

        self.assertEqual(
            cmdparser.cmdparser("test1hello", a_cmdset, None),
            [("test1", "hello", bcmd, 5, 0.5, "test1")],
        )


class TestCmdSetNesting(BaseEvenniaTest):
    """
    Test 'nesting' of cmdsets by adding
    """

    def test_nest(self):
        class CmdA(Command):
            key = "a"

            def func(self):
                self.msg(str(self.obj))

        class CmdSetA(CmdSet):
            def at_cmdset_creation(self):
                self.add(CmdA)

        class CmdSetB(CmdSet):
            def at_cmdset_creation(self):
                self.add(CmdSetA)

        cmd = self.char1.cmdset.cmdset_stack[-1].commands[0]
        self.assertEqual(cmd.obj, self.char1)


class TestCmdSet(BaseEvenniaTest):
    """
    General tests for cmdsets
    """

    def test_cmdset_remove_by_key(self):
        test_cmd_set = _CmdSetTest()
        test_cmd_set.remove("another command")

        self.assertNotIn(_CmdTest2, test_cmd_set.commands)

    def test_cmdset_gets_by_key(self):
        test_cmd_set = _CmdSetTest()
        result = test_cmd_set.get("another command")

        self.assertIsInstance(result, _CmdTest2)

    def test_cmdset_add_same_key_replaces(self):
        class _CmdDuplicateA(Command):
            key = "duplicate"

        class _CmdDuplicateB(Command):
            key = "duplicate"

        cmdset = CmdSet()
        cmdset.add(_CmdDuplicateA)
        cmdset.add(_CmdDuplicateB)

        duplicate_cmds = [cmd for cmd in cmdset.commands if cmd.key == "duplicate"]
        self.assertEqual(len(duplicate_cmds), 1)
        self.assertIsInstance(duplicate_cmds[0], _CmdDuplicateB)


class _CmdG(Command):
    key = "smile"
    aliases = ["smile at", "grin", "grin at"]


class _CmdSetG(CmdSet):
    def at_cmdset_creation(self):
        self.add(_CmdG())


class TestIssue3090(BaseEvenniaTest):
    """
    Command aliases should be prioritized longest-match to shortest-match.
    https://github.com/evennia/evennia/issues/3090

    """

    def test_long_aliases(self):
        cmdset_g = _CmdSetG()

        # print(cmdset_g.commands[0]._keyaliases)

        result = cmdparser.cmdparser("smile at", cmdset_g, None)[0]
        self.assertEqual(result[0], "smile at")
        self.assertEqual(result[1], "")
        self.assertEqual(result[2].__class__, _CmdG)
        self.assertEqual(result[3], 8)
        self.assertEqual(result[4], 1.0)
        self.assertEqual(result[5], "smile at")


class _TestCmd1(Command):
    key = "testcmd"
    locks = "usecmd:false()"

    def func():
        pass


class TestIssue3643(BaseEvenniaTest):
    """
    Commands with a 'cmd:' anywhere in its string, even `funccmd:` is assumed to
    be a cmd: type lock, meaning it will not auto-insert `cmd:all()` into the
    lockstring as intended.

    """

    def test_issue_3643(self):
        cmd = _TestCmd1()
        self.assertEqual(cmd.locks, "cmd:all();usecmd:false()")


class _CmdCrash(Command):
    key = "connect"

    def func(self):
        raise RuntimeError("forced failure")


class TestIssue2627(TwistedTestCase, BaseEvenniaTest):
    """
    Prevent logging plaintext credentials in command-error reporting.
    https://github.com/evennia/evennia/issues/2627
    """

    def setUp(self):
        self.patch(sys.modules["evennia.server.sessionhandler"], "delay", _mockdelay)
        super().setUp()

    @patch("evennia.commands.cmdhandler.logger.log_err")
    def test_cmdhandler_masks_sensitive_input_in_error_log(self, mock_log_err):
        d = cmdhandler.cmdhandler(
            self.session, " johnny password123", cmdobj=_CmdCrash(), cmdobj_key="connect"
        )

        def _callback(_):
            logged = [call.args[0] for call in mock_log_err.call_args_list if call.args]
            self.assertIn("User input was: 'connect johnny ***********'.", logged)
            self.assertNotIn(
                "User input was: 'connect johnny password123'.",
                logged,
            )

        d.addCallback(_callback)
        return d


class TestCmdSetMergeObjBindings(TestCase):
    """Test that cmdset resolution preserves correct cmd.obj bindings."""

    def test_merge_preserves_obj_from_different_cmdsets(self):
        """Commands from different objects retain their obj after merge."""
        from unittest.mock import Mock

        obj1 = Mock(name="Sword")
        obj2 = Mock(name="Shield")

        cmdset1 = CmdSet(obj1)
        cmdset1.key = "SwordCmds"
        cmd_slash = _CmdA("sword")
        cmd_slash.obj = obj1
        cmdset1.add(cmd_slash)

        cmdset2 = CmdSet(obj2)
        cmdset2.key = "ShieldCmds"
        cmd_block = _CmdB("shield")
        cmd_block.obj = obj2
        cmdset2.add(cmd_block)

        merged = resolve_cmdsets([(cmdset1, obj1), (cmdset2, obj2)])
        cmds = {cmd.key: cmd for cmd in merged.commands}

        self.assertIs(cmds["a"].obj, obj1)
        self.assertIs(cmds["b"].obj, obj2)

    def test_same_key_different_obj_resolved_by_priority(self):
        """When two cmdsets share a command key, priority determines which obj wins."""
        from unittest.mock import Mock

        obj_low = Mock(name="LowPrio")
        obj_high = Mock(name="HighPrio")

        cmdset_low = CmdSet(obj_low)
        cmdset_low.key = "LowSet"
        cmdset_low.priority = 0
        cmd_low = _CmdA("low")
        cmd_low.obj = obj_low
        cmdset_low.add(cmd_low)

        cmdset_high = CmdSet(obj_high)
        cmdset_high.key = "HighSet"
        cmdset_high.priority = 1
        cmd_high = _CmdA("high")
        cmd_high.obj = obj_high
        cmdset_high.add(cmd_high)

        merged = resolve_cmdsets([(cmdset_low, obj_low), (cmdset_high, obj_high)])
        result_cmd = [cmd for cmd in merged.commands if cmd.key == "a"][0]

        self.assertIs(result_cmd.obj, obj_high)

    def test_merge_after_add_reflects_new_command(self):
        """Adding a command to a cmdset and re-merging includes it with correct obj."""
        from unittest.mock import Mock

        obj1 = Mock(name="Obj1")
        obj2 = Mock(name="Obj2")

        cmdset1 = CmdSet(obj1)
        cmdset1.key = "Set1"
        cmd_a = _CmdA("set1")
        cmd_a.obj = obj1
        cmdset1.add(cmd_a)

        cmdset2 = CmdSet(obj2)
        cmdset2.key = "Set2"
        cmd_b = _CmdB("set2")
        cmd_b.obj = obj2
        cmdset2.add(cmd_b)

        merged1 = resolve_cmdsets([(cmdset1, obj1), (cmdset2, obj2)])
        self.assertEqual(len(merged1.commands), 2)

        # add a new command and re-resolve
        cmd_c = _CmdC("set1")
        cmd_c.obj = obj1
        cmdset1.add(cmd_c)

        merged2 = resolve_cmdsets([(cmdset1, obj1), (cmdset2, obj2)])
        self.assertEqual(len(merged2.commands), 3)
        cmds = {cmd.key: cmd for cmd in merged2.commands}
        self.assertIn("c", cmds)
        self.assertIs(cmds["c"].obj, obj1)

    def test_merge_after_remove_excludes_command(self):
        """Removing a command from a cmdset and re-merging excludes it."""
        from unittest.mock import Mock

        obj1 = Mock(name="Obj1")
        obj2 = Mock(name="Obj2")

        cmdset1 = CmdSet(obj1)
        cmdset1.key = "Set1"
        cmd_a = _CmdA("set1")
        cmd_a.obj = obj1
        cmd_b = _CmdB("set1")
        cmd_b.obj = obj1
        cmdset1.add(cmd_a)
        cmdset1.add(cmd_b)

        cmdset2 = CmdSet(obj2)
        cmdset2.key = "Set2"
        cmd_c = _CmdC("set2")
        cmd_c.obj = obj2
        cmdset2.add(cmd_c)

        merged1 = resolve_cmdsets([(cmdset1, obj1), (cmdset2, obj2)])
        self.assertEqual(len(merged1.commands), 3)

        # remove a command and re-resolve
        cmdset1.remove(cmd_b)

        merged2 = resolve_cmdsets([(cmdset1, obj1), (cmdset2, obj2)])
        self.assertEqual(len(merged2.commands), 2)
        keys = {cmd.key for cmd in merged2.commands}
        self.assertNotIn("b", keys)


class _CacheEntity:
    """Bare stand-in for a session/account/object in gather-cache tests."""

    cmdset_provider_type = "session"
    cmdset_dynamic = False

    def __init__(self, provider_type=None, location=None):
        if provider_type:
            self.cmdset_provider_type = provider_type
        self.location = location


class TestCmdsetCachePrimitives(TestCase):
    """Test the version-counter cache primitives in cmdsetcache."""

    def _chain(self):
        """Build a session/account/object provider chain with a location."""
        room = _CacheEntity(provider_type="room")
        session = _CacheEntity()
        account = _CacheEntity(provider_type="account")
        puppet = _CacheEntity(provider_type="object", location=room)
        return [session, account, puppet], room

    def _build_cached(self, providers, location):
        vector = cmdsetcache.snapshot_vector(providers, location)
        return cmdsetcache.CachedGather(
            cmdsetcache.get_epoch(), tuple(providers), location, vector, ()
        )

    def test_version_bumps(self):
        entity = _CacheEntity()
        self.assertEqual(cmdsetcache.get_version(entity), 0)
        cmdsetcache.invalidate(entity)
        cmdsetcache.invalidate(entity)
        self.assertEqual(cmdsetcache.get_version(entity), 2)

    def test_invalidate_neighborhood(self):
        room = _CacheEntity()
        obj = _CacheEntity(location=room)
        cmdsetcache.invalidate_neighborhood(obj)
        self.assertEqual(cmdsetcache.get_version(obj), 1)
        self.assertEqual(cmdsetcache.get_version(room), 1)
        # without a location (location=None routes through invalidate(None))
        lone = _CacheEntity()
        cmdsetcache.invalidate_neighborhood(lone)
        self.assertEqual(cmdsetcache.get_version(lone), 1)

    def test_is_dynamic(self):
        entity = _CacheEntity()
        self.assertFalse(cmdsetcache.is_dynamic(entity))
        entity.cmdset_dynamic = True
        self.assertTrue(cmdsetcache.is_dynamic(entity))

    def test_vectors_equal(self):
        providers, room = self._chain()
        vector_a = cmdsetcache.snapshot_vector(providers, room)
        vector_b = cmdsetcache.snapshot_vector(providers, room)
        self.assertTrue(cmdsetcache.vectors_equal(vector_a, vector_b))
        cmdsetcache.invalidate(room)
        vector_c = cmdsetcache.snapshot_vector(providers, room)
        self.assertFalse(cmdsetcache.vectors_equal(vector_a, vector_c))

    def test_store_and_get_roundtrip(self):
        providers, room = self._chain()
        holder = providers[-1]
        cached = self._build_cached(providers, room)
        cmdsetcache.store_cached(holder, providers, cached)
        self.assertIs(cmdsetcache.get_cached(holder, providers), cached)

    def test_get_rejects_epoch_change(self):
        providers, room = self._chain()
        holder = providers[-1]
        cmdsetcache.store_cached(holder, providers, self._build_cached(providers, room))
        cmdsetcache.invalidate_all()
        self.assertIsNone(cmdsetcache.get_cached(holder, providers))

    def test_get_rejects_provider_replacement(self):
        providers, room = self._chain()
        holder = providers[-1]
        cmdsetcache.store_cached(holder, providers, self._build_cached(providers, room))
        replaced = [_CacheEntity(), providers[1], providers[2]]
        self.assertIsNone(cmdsetcache.get_cached(holder, replaced))

    def test_get_rejects_location_change(self):
        providers, room = self._chain()
        holder = providers[-1]
        cmdsetcache.store_cached(holder, providers, self._build_cached(providers, room))
        holder.location = _CacheEntity()
        self.assertIsNone(cmdsetcache.get_cached(holder, providers))

    def test_get_rejects_version_bumps(self):
        for bump_target in ("provider", "location"):
            providers, room = self._chain()
            holder = providers[-1]
            cmdsetcache.store_cached(holder, providers, self._build_cached(providers, room))
            cmdsetcache.invalidate(providers[1] if bump_target == "provider" else room)
            self.assertIsNone(
                cmdsetcache.get_cached(holder, providers), f"stale hit after {bump_target} bump"
            )

    def test_store_eviction_cap(self):
        providers, room = self._chain()
        holder = providers[-1]
        first = providers
        cmdsetcache.store_cached(holder, first, self._build_cached(first, room))
        for _ in range(cmdsetcache._MAX_CACHE_ENTRIES):
            extra = [_CacheEntity(), providers[1], providers[2]]
            cmdsetcache.store_cached(holder, extra, self._build_cached(extra, room))
        self.assertEqual(len(holder._cmdset_gather_cache), cmdsetcache._MAX_CACHE_ENTRIES)
        # the oldest entry (the first chain) was evicted
        self.assertIsNone(cmdsetcache.get_cached(holder, first))


class _GatherCacheTestMixin:
    """Helpers shared by the gather-cache test classes."""

    def setUp(self):
        self.patch(sys.modules["evennia.server.sessionhandler"], "delay", _mockdelay)
        super().setUp()

    def _gather(self, caller, providers=None):
        """Run get_and_merge_cmdsets; everything fires synchronously here."""
        result = []
        cmdhandler.get_and_merge_cmdsets(
            caller,
            [caller] if providers is None else providers,
            caller.cmdset_provider_type,
            "",
        ).addCallback(result.append)
        self.assertTrue(result, "gather did not complete synchronously")
        return result[0]

    def _spy_hook(self, obj):
        """Replace obj.at_cmdset_get with a recording wrapper."""
        calls = []
        original = obj.at_cmdset_get

        def _spy(**kwargs):
            calls.append(kwargs)
            return original(**kwargs)

        obj.at_cmdset_get = _spy
        return calls

    def _prime(self, caller, providers=None):
        """Gather twice; the second pass is free of lazy-init bumps and stores."""
        self._gather(caller, providers)
        return self._gather(caller, providers)

    def _keys(self, merged):
        """Get the command keys of a merged cmdset (empty when the gather
        found no cmdsets at all, which merges to None)."""
        return [cmd.key for cmd in merged.commands] if merged else []


class TestCmdsetGatherCache(_GatherCacheTestMixin, TwistedTestCase, BaseEvenniaTest):
    """
    Test the event-invalidated gather cache through get_and_merge_cmdsets.

    """

    def test_cache_hit_skips_local_walk(self):
        self._prime(self.obj1)
        self.assertIsNotNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))
        calls = self._spy_hook(self.room1)
        self._gather(self.obj1)
        self.assertEqual(len(calls), 0, "cache hit still ran the local-object walk")

    @override_settings(CMDSET_GATHER_CACHE=False)
    def test_flag_off_walks_every_time(self):
        calls = self._spy_hook(self.room1)
        self._gather(self.obj1)
        self._gather(self.obj1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(hasattr(self.obj1, "_cmdset_gather_cache"))

    def test_own_cmdset_change_immediately_visible(self):
        self._prime(self.obj1)
        self.obj1.cmdset.add(_CmdSetA())
        self.assertIn("a", self._keys(self._gather(self.obj1)))
        self.obj1.cmdset.remove(_CmdSetA)
        self.assertNotIn("a", self._keys(self._gather(self.obj1)))

    def test_neighbor_cmdset_change_invalidates(self):
        self._prime(self.obj1)
        self.obj2.cmdset.add(_CmdSetB())
        self.assertIn("b", self._keys(self._gather(self.obj1)))
        self.obj2.cmdset.remove(_CmdSetB)
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))

    def test_neighbor_move_invalidates(self):
        self.obj2.cmdset.add(_CmdSetB())
        self._prime(self.obj1)
        self.assertIn("b", self._keys(self._gather(self.obj1)))
        self.obj2.location = self.room2
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))

    def test_live_cmdset_mutation_needs_no_event(self):
        # mutating a stacked CmdSet directly fires no engine event; it must
        # still be picked up via the per-input fingerprint recomputation
        self.obj2.cmdset.add(_CmdSetC())
        self._prime(self.obj1)
        merged = self._gather(self.obj1)
        self.assertNotIn("d", [cmd.key for cmd in merged.commands])
        stacked = self.obj2.cmdset.cmdset_stack[-1]
        stacked.add(_CmdD("live"))
        merged = self._gather(self.obj1)
        self.assertIn("d", [cmd.key for cmd in merged.commands])

    def test_cross_source_coexistence(self):
        # same-key commands on two different room objects must stay separate
        # (source-identity multimatch) on both the build and the cached path
        self.obj2.cmdset.add(_CmdSetB())
        self.room1.cmdset.add(_CmdSetB())
        built = self._prime(self.obj1)
        self.assertEqual(sum(1 for cmd in built.commands if cmd.key == "b"), 2)
        cached = self._gather(self.obj1)
        self.assertEqual(sum(1 for cmd in cached.commands if cmd.key == "b"), 2)


class TestCmdsetGatherCacheInvalidation(_GatherCacheTestMixin, TwistedTestCase, BaseEvenniaTest):
    """
    Test that engine events beyond cmdset mutations and movement invalidate
    cached gathers: lock and permission changes, quelling, puppeting,
    login/disconnect, idmapper flushes, renames and typeclass swaps.

    """

    def _puppet_chain(self):
        """Puppet char1 through the test session and return its provider chain."""
        self.account.puppet_object(self.session, self.char1)
        _, providers, _, _, _ = cmdhandler.generate_cmdset_providers(
            self.char1, session=self.session
        )
        return providers

    def test_lock_edit_flips_call_inclusion(self):
        self.obj2.cmdset.add(_CmdSetB())
        self._prime(self.obj1)
        self.assertIn("b", self._keys(self._gather(self.obj1)))
        self.obj2.locks.add("call:false()")
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))
        self.obj2.locks.add("call:true()")
        self.assertIn("b", self._keys(self._gather(self.obj1)))

    def test_permission_change_invalidates(self):
        self.obj2.cmdset.add(_CmdSetB())
        self.obj2.locks.add("call:perm(Builder)")
        self._prime(self.obj1)
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))
        self.obj1.permissions.add("Builder")
        self.assertIn("b", self._keys(self._gather(self.obj1)))
        self.obj1.permissions.remove("Builder")
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))

    def test_quell_invalidates(self):
        # CmdQuell's mechanics: toggle the _quell attribute, then
        # locks.reset() on puppet and account (CmdQuell._recache_locks)
        providers = self._puppet_chain()
        self.char1.permissions.remove("Developer")
        self.obj2.cmdset.add(_CmdSetB())
        self.obj2.locks.add("call:perm(Developer)")
        self._prime(self.char1, providers)
        # unquelled, the account's Developer perm applies
        self.assertIn("b", self._keys(self._gather(self.char1, providers)))
        self.account.attributes.add("_quell", True)
        self.char1.locks.reset()
        self.account.locks.reset()
        # quelled, the puppet's own (lower) perms apply
        self.assertNotIn("b", self._keys(self._gather(self.char1, providers)))
        self.account.attributes.remove("_quell")
        self.char1.locks.reset()
        self.account.locks.reset()
        self.assertIn("b", self._keys(self._gather(self.char1, providers)))

    def test_puppet_and_unpuppet_invalidate(self):
        providers = self._puppet_chain()
        self._prime(self.char1, providers)
        self.assertIsNotNone(cmdsetcache.get_cached(self.char1, providers))
        self.account.unpuppet_object(self.session)
        self.assertIsNone(cmdsetcache.get_cached(self.char1, providers))

    def test_distinct_provider_chains_get_distinct_entries(self):
        # multisession safety: the same holder caches one gather per chain
        providers = self._puppet_chain()
        self._prime(self.char1)
        self._prime(self.char1, providers)
        self.assertEqual(len(self.char1._cmdset_gather_cache), 2)
        cmdsetcache.invalidate(self.room1)
        self.assertIsNone(cmdsetcache.get_cached(self.char1, [self.char1]))
        self.assertIsNone(cmdsetcache.get_cached(self.char1, providers))

    def test_deletion_invalidates(self):
        self.obj2.cmdset.add(_CmdSetB())
        self._prime(self.obj1)
        self.assertIn("b", self._keys(self._gather(self.obj1)))
        self.obj2.delete()
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))

    def test_idmapper_flush_invalidates(self):
        self._prime(self.obj1)
        self.assertIsNotNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))
        self.obj2.flush_from_cache(force=True)
        self.assertIsNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))

    def test_exits_contribute_no_commands(self):
        # exits are not commands; neither the build pass nor the cached
        # path may include them in the merged cmdset
        merged = self._prime(self.char1)
        self.assertNotIn("out", self._keys(merged))
        self.assertNotIn("out", self._keys(self._gather(self.char1)))

    def test_flush_cache_bumps_epoch(self):
        self._prime(self.obj1)
        self.assertIsNotNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))
        epoch = cmdsetcache.get_epoch()
        idmapper_flush_cache()
        self.assertEqual(cmdsetcache.get_epoch(), epoch + 1)
        self.assertIsNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))

    def test_swap_typeclass_invalidates(self):
        self._prime(self.obj1)
        self.assertIsNotNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))
        self.obj2.swap_typeclass("evennia.objects.objects.DefaultObject", run_start_hooks=None)
        self.assertIsNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))

    def test_login_and_disconnect_invalidate_session(self):
        version = cmdsetcache.get_version(self.session)
        evennia.SESSION_HANDLER.login(self.session, self.account, force=True, testmode=True)
        self.assertGreater(cmdsetcache.get_version(self.session), version)
        version = cmdsetcache.get_version(self.session)
        # the fixture mocks out SESSION_HANDLER.disconnect; call the real one
        ServerSessionHandler.disconnect(evennia.SESSION_HANDLER, self.session, sync_portal=False)
        self.assertGreater(cmdsetcache.get_version(self.session), version)
        # put the session back so the fixture teardown finds it
        evennia.SESSION_HANDLER[self.session.sessid] = self.session


class _CmdSetNoExits(CmdSet):
    key = "NoExits"
    no_exits = True


class _CmdSetNoChannels(CmdSet):
    key = "NoChannels"
    no_channels = True


class _CmdSetNoObjs(CmdSet):
    key = "NoObjs"
    no_objs = True


class TestCmdsetGatherCacheDynamic(_GatherCacheTestMixin, TwistedTestCase, BaseEvenniaTest):
    """
    Test the cmdset_dynamic opt-in: a dynamic local object's contribution
    (call lock, at_cmdset_get hook and stack) is re-evaluated on every input
    while the rest of the gather stays cached, whereas a dynamic provider
    disables gather caching entirely.

    """

    def test_dynamic_object_reevaluated_per_input(self):
        self.obj2.cmdset_dynamic = True
        self.obj2.cmdset.add(_CmdSetB())
        self._prime(self.obj1)
        # a dynamic local object must not prevent caching the gather
        self.assertIsNotNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))
        dynamic_calls = self._spy_hook(self.obj2)
        static_calls = self._spy_hook(self.room1)
        self.assertIn("b", self._keys(self._gather(self.obj1)))
        self.assertIn("b", self._keys(self._gather(self.obj1)))
        self.assertEqual(len(dynamic_calls), 2, "dynamic object's hook did not run per input")
        self.assertEqual(len(static_calls), 0, "static object's hook ran on a cache hit")

    def test_dynamic_call_lock_tracks_attribute(self):
        # the dynamic object is recorded in the cached gather even while its
        # call lock fails, so the lock can start passing without any event
        self.obj2.cmdset_dynamic = True
        self.obj2.cmdset.add(_CmdSetB())
        self.obj2.locks.add("call:attr(clearance, yes)")
        self._prime(self.obj1)
        static_calls = self._spy_hook(self.room1)
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))
        # plain Attribute writes fire no engine event; the dynamic object's
        # call lock must pick them up per input all the same
        self.obj1.attributes.add("clearance", "yes")
        self.assertIn("b", self._keys(self._gather(self.obj1)))
        self.obj1.attributes.remove("clearance")
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))
        self.assertEqual(len(static_calls), 0, "attribute write triggered a full rebuild")

    def test_exit_excluded_even_if_dynamic(self):
        # exits never contribute cmdsets, even when marked cmdset_dynamic
        self.exit.cmdset_dynamic = True
        merged = self._prime(self.obj1)
        self.assertIsNotNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))
        self.assertNotIn("out", self._keys(merged))
        self.assertNotIn("out", self._keys(self._gather(self.obj1)))

    def test_dynamic_provider_falls_back_to_legacy(self):
        self.obj1.cmdset_dynamic = True
        self.obj2.cmdset.add(_CmdSetB())
        calls = self._spy_hook(self.room1)
        merged = self._gather(self.obj1)
        self._gather(self.obj1)
        self.assertEqual(len(calls), 2, "dynamic provider still cached the gather")
        self.assertIsNone(cmdsetcache.get_cached(self.obj1, [self.obj1]))
        with override_settings(CMDSET_GATHER_CACHE=False):
            legacy = self._gather(self.obj1)
        self.assertEqual(self._keys(merged), self._keys(legacy))

    def test_cross_source_coexistence_with_dynamic(self):
        # same-key commands on a dynamic and a static object must stay
        # separate on both paths
        self.obj2.cmdset_dynamic = True
        self.obj2.cmdset.add(_CmdSetB())
        self.room1.cmdset.add(_CmdSetB())
        built = self._prime(self.obj1)
        self.assertEqual(sum(1 for cmd in built.commands if cmd.key == "b"), 2)
        cached = self._gather(self.obj1)
        self.assertEqual(sum(1 for cmd in cached.commands if cmd.key == "b"), 2)

    def test_invalidate_caches_escape_hatch(self):
        # a static object's call lock freezes between engine events; the
        # public CmdSetHandler.invalidate_caches() forces a re-gather
        self.obj2.cmdset.add(_CmdSetB())
        self.obj2.locks.add("call:attr(clearance, yes)")
        self._prime(self.obj1)
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))
        self.obj1.attributes.add("clearance", "yes")
        self.assertNotIn("b", self._keys(self._gather(self.obj1)))
        self.obj2.cmdset.invalidate_caches()
        self.assertIn("b", self._keys(self._gather(self.obj1)))


class TestCmdsetGatherCacheParity(_GatherCacheTestMixin, TwistedTestCase, BaseEvenniaTest):
    """
    Sweep one busy scene through repeated gathers, asserting after every
    scene change that the cached path (build pass and cache hits alike)
    merges to exactly the same result as the legacy per-input path.

    """

    def _signature(self, merged):
        """Reduce a merged cmdset to a sortable, binding-aware form."""
        return sorted(
            (
                cmd.key,
                tuple(sorted(cmd.aliases)),
                type(cmd).__name__,
                str(getattr(cmd, "from_cmdset", "")),
                getattr(getattr(cmd, "obj", None), "dbref", None) or "",
            )
            for cmd in merged.commands
        )

    def _assert_parity(self, caller, providers, scenario):
        """Compare a legacy gather against a build pass and two cache hits."""
        with override_settings(CMDSET_GATHER_CACHE=False):
            legacy = self._gather(caller, providers)
        reference = self._signature(legacy)
        for repeat in range(3):
            merged = self._gather(caller, providers)
            self.assertEqual(
                self._signature(merged),
                reference,
                f"{scenario}: cached gather {repeat} diverged from the legacy merge",
            )
            # identical gather order and duplicates handling give both paths
            # the same mergehash, so they must share one merge-cache entry
            self.assertIs(merged, legacy, f"{scenario}: gather {repeat} missed the merge cache")
        self.assertIsNotNone(
            cmdsetcache.get_cached(caller, providers),
            f"{scenario}: gather never stored, cache hits were not exercised",
        )

    def test_parity_across_scene_changes(self):
        self.account.puppet_object(self.session, self.char1)
        _, providers, _, _, _ = cmdhandler.generate_cmdset_providers(
            self.char1, session=self.session
        )
        # a busy scene: an inventory object, same-key cmdsets on a room object
        # and the room itself (duplicates handling), alias-carrying commands on
        # the caller, a call-locked bystander and a dynamic object
        self.obj1.location = self.char1
        self.obj1.cmdset.add(_CmdSetA())
        self.obj2.cmdset.add(_CmdSetB())
        self.room1.cmdset.add(_CmdSetB())
        self.char1.cmdset.add(_CmdSetEe_Ef())
        self.char2.cmdset.add(_CmdSetC())
        self.char2.locks.add("call:false()")
        self.obj2.cmdset_dynamic = True
        self._assert_parity(self.char1, providers, "initial scene")
        self.char2.locks.add("call:true()")
        self._assert_parity(self.char1, providers, "bystander call lock opened")
        self.obj1.location = self.room1
        self._assert_parity(self.char1, providers, "inventory object dropped")
        self.obj2.locks.add("call:attr(clearance, yes)")
        self._assert_parity(self.char1, providers, "dynamic object attr-locked")
        # plain Attribute writes fire no engine event; the per-input dynamic
        # splice and the legacy walk must agree all the same
        self.char1.attributes.add("clearance", "yes")
        self._assert_parity(self.char1, providers, "attr flips dynamic lock without event")
        self.char1.cmdset.add(_CmdSetNoObjs())
        self._assert_parity(self.char1, providers, "no_objs gate raised")
        self.char1.cmdset.remove(_CmdSetNoObjs)
        self._assert_parity(self.char1, providers, "gates lowered")


# layer-stack resolver tests

import re

from evennia.commands.cmdresolver import (
    BindingTable,
    ResolvedCmdSet,
    make_bindings,
    resolve_cmdsets,
)

_ARG_REGEX = re.compile(r"^[ /]|\n|$", re.I + re.UNICODE)


def _rcmd(key, aliases=None, arg_regex=None, obj=None):
    """Build a bare command instance for resolver tests."""
    cmd = Command()
    cmd.set_key(key)
    if aliases:
        cmd.set_aliases(aliases)
    cmd.arg_regex = arg_regex
    cmd.obj = obj
    return cmd


def _rset(
    key,
    commands=(),
    priority=0,
    exclusive=False,
    removes=(),
    no_exits=None,
    no_objs=None,
    no_channels=None,
):
    """Build a cmdset instance for resolver tests."""
    cmdset = CmdSet(key=key)
    cmdset.priority = priority
    cmdset.exclusive = exclusive
    cmdset.removes = removes
    cmdset.no_exits = no_exits
    cmdset.no_objs = no_objs
    cmdset.no_channels = no_channels
    for cmd in commands:
        cmdset.add(cmd)
    return cmdset


class TestResolverShadowing(TestCase):
    def test_key_shadows_whole_command(self):
        # higher-prio same key removes the lower command including its aliases
        low_look = _rcmd("look", aliases=["l"])
        high_look = _rcmd("look")
        resolved = resolve_cmdsets(
            [
                (_rset("low", [low_look]), None),
                (_rset("high", [high_look], priority=1), None),
            ]
        )
        self.assertEqual(resolved.commands, [high_look])
        self.assertEqual(resolved.bindings.names["look"], (high_look,))
        self.assertNotIn("l", resolved.bindings.names)

    def test_alias_rebinds_lower_command_survives(self):
        # different keys sharing an alias: the name rebinds to the higher
        # command, the lower one stays reachable via its other names
        look = _rcmd("look", aliases=["l"])
        lock = _rcmd("lock", aliases=["l"])
        resolved = resolve_cmdsets(
            [
                (_rset("low", [look]), None),
                (_rset("high", [lock], priority=1), None),
            ]
        )
        self.assertCountEqual(resolved.commands, [look, lock])
        self.assertEqual(resolved.bindings.names["l"], (lock,))
        self.assertEqual(resolved.bindings.names["look"], (look,))
        self.assertEqual(resolved.bindings.names["lock"], (lock,))

    def test_same_priority_later_gather_wins(self):
        early = _rcmd("jump")
        late = _rcmd("jump")
        source = object()
        resolved = resolve_cmdsets(
            [
                (_rset("early", [early]), source),
                (_rset("late", [late]), source),
            ]
        )
        self.assertEqual(resolved.commands, [late])


class TestResolverExclusive(TestCase):
    def test_exclusive_blocks_lower_layers(self):
        default = _rcmd("look")
        menuopt = _rcmd("menuopt")
        resolved = resolve_cmdsets(
            [
                (_rset("default", [default]), None),
                (_rset("menu", [menuopt], priority=1, exclusive=True), None),
            ]
        )
        self.assertEqual(resolved.commands, [menuopt])

    def test_layers_above_exclusive_still_resolve(self):
        default = _rcmd("look")
        menuopt = _rcmd("menuopt")
        editline = _rcmd("editline")
        resolved = resolve_cmdsets(
            [
                (_rset("default", [default]), None),
                (_rset("menu", [menuopt], priority=1, exclusive=True), None),
                (_rset("editor", [editline], priority=150, exclusive=True), None),
            ]
        )
        self.assertEqual(resolved.commands, [editline])

    def test_non_exclusive_layer_above_exclusive_unions(self):
        default = _rcmd("look")
        menuopt = _rcmd("menuopt")
        helper = _rcmd("helper")
        resolved = resolve_cmdsets(
            [
                (_rset("default", [default]), None),
                (_rset("menu", [menuopt], priority=1, exclusive=True), None),
                (_rset("extra", [helper], priority=2), None),
            ]
        )
        self.assertCountEqual(resolved.commands, [helper, menuopt])

    def test_system_commands_bypass_exclusive(self):
        default = _rcmd("look")
        noinput = _rcmd("__noinput_command")
        menuopt = _rcmd("menuopt")
        resolved = resolve_cmdsets(
            [
                (_rset("default", [default, noinput]), None),
                (_rset("menu", [menuopt], priority=1, exclusive=True), None),
            ]
        )
        self.assertIs(resolved.get("__noinput_command"), noinput)
        self.assertIn(noinput, resolved.commands)
        self.assertEqual(resolved.get_system_cmds(), [noinput])

    def test_system_commands_stay_parser_matchable(self):
        # CMD_LOGINSTART arrives as raw input on connect and the unloggedin
        # look is reachable as look/l - syscommands must be in the bindings
        unlook = _rcmd("__unloggedin_look_command", aliases=["look", "l"])
        resolved = resolve_cmdsets([(_rset("unloggedin", [unlook]), None)])
        for name in ("__unloggedin_look_command", "look", "l"):
            self.assertEqual(resolved.bindings.names.get(name), (unlook,))
        self.assertEqual(
            resolved.bindings.candidates("__unloggedin_look_command"),
            [("__unloggedin_look_command", "__unloggedin_look_command", unlook)],
        )

    def test_normal_command_keeps_name_contested_by_system_alias(self):
        look = _rcmd("look")
        syslook = _rcmd("__unloggedin_look_command", aliases=["look"])
        resolved = resolve_cmdsets([(_rset("default", [look, syslook]), None)])
        self.assertEqual(resolved.bindings.names.get("look"), (look,))
        self.assertEqual(resolved.bindings.names.get("__unloggedin_look_command"), (syslook,))

    def test_flags_pass_through_exclusive(self):
        resolved = resolve_cmdsets(
            [
                (_rset("default", no_channels=True), None),
                (_rset("menu", priority=1, exclusive=True, no_objs=True), None),
            ]
        )
        self.assertTrue(resolved.no_channels)
        self.assertTrue(resolved.no_objs)
        self.assertIsNone(resolved.no_exits)


class TestResolverRemoves(TestCase):
    def test_removes_filters_lower_layers_by_key(self):
        look = _rcmd("look", aliases=["l"])
        jump = _rcmd("jump")
        resolved = resolve_cmdsets(
            [
                (_rset("default", [look, jump]), None),
                (_rset("filter", priority=1, removes=("look",)), None),
            ]
        )
        self.assertEqual(resolved.commands, [jump])
        self.assertNotIn("l", resolved.bindings.names)

    def test_removes_does_not_affect_higher_layers(self):
        attack = _rcmd("attack")
        resolved = resolve_cmdsets(
            [
                (_rset("filter", removes=("attack",)), None),
                (_rset("combat", [attack], priority=1), None),
            ]
        )
        self.assertEqual(resolved.commands, [attack])

    def test_removes_spares_system_commands(self):
        noinput = _rcmd("__noinput_command")
        resolved = resolve_cmdsets(
            [
                (_rset("default", [noinput]), None),
                (_rset("filter", priority=1, removes=("__noinput_command",)), None),
            ]
        )
        self.assertIs(resolved.get("__noinput_command"), noinput)


class TestSourceIdentityMultimatch(TestCase):
    def test_different_sources_coexist(self):
        north1 = _rcmd("north")
        north2 = _rcmd("north")
        resolved = resolve_cmdsets(
            [
                (_rset("exit1", [north1]), object()),
                (_rset("exit2", [north2]), object()),
            ]
        )
        self.assertCountEqual(resolved.commands, [north1, north2])
        self.assertCountEqual(resolved.bindings.names["north"], (north1, north2))

    def test_same_source_dedupes(self):
        north1 = _rcmd("north")
        north2 = _rcmd("north")
        source = object()
        resolved = resolve_cmdsets(
            [
                (_rset("exit1", [north1]), source),
                (_rset("exit2", [north2]), source),
            ]
        )
        self.assertEqual(resolved.commands, [north2])

    def test_mixed_sources(self):
        press1 = _rcmd("press")
        press2 = _rcmd("press")
        press3 = _rcmd("press")
        source_a, source_b = object(), object()
        resolved = resolve_cmdsets(
            [
                (_rset("one", [press1]), source_a),
                (_rset("two", [press2]), source_a),
                (_rset("three", [press3]), source_b),
            ]
        )
        self.assertCountEqual(resolved.commands, [press2, press3])

    def test_higher_priority_shadows_across_sources(self):
        low = _rcmd("press")
        high = _rcmd("press")
        resolved = resolve_cmdsets(
            [
                (_rset("low", [low]), object()),
                (_rset("high", [high], priority=1), object()),
            ]
        )
        self.assertEqual(resolved.commands, [high])


class _AccessDenyCmd(Command):
    def access(self, srcobj, access_type="cmd", default=False, session=None):
        return False


class _AccessAllowCmd(Command):
    def access(self, srcobj, access_type="cmd", default=False, session=None):
        return True


class TestResolverResultSurface(TestCase):
    def test_empty_gather_resolves_to_none(self):
        self.assertIsNone(resolve_cmdsets([]))

    def test_top_layer_names_result(self):
        resolved = resolve_cmdsets(
            [
                (_rset("low", [_rcmd("look")]), None),
                (_rset("high", [_rcmd("menuopt")], priority=2), None),
            ]
        )
        self.assertEqual(resolved.key, "high")
        self.assertEqual(resolved.priority, 2)

    def test_merged_from_keeps_gather_order(self):
        low = _rset("low", priority=5)
        high = _rset("high")
        resolved = resolve_cmdsets([(low, None), (high, None)])
        self.assertEqual(resolved.merged_from, [low, high])

    def test_iteration_count_and_membership(self):
        look = _rcmd("look", aliases=["l"])
        resolved = resolve_cmdsets([(_rset("set", [look]), None)])
        self.assertEqual(list(resolved), [look])
        self.assertEqual(resolved.count(), 1)
        self.assertIn(look, resolved)
        self.assertIn("l", resolved)
        self.assertNotIn("missing", resolved)

    def test_get_by_key_alias_and_instance(self):
        look = _rcmd("look", aliases=["l"])
        resolved = resolve_cmdsets([(_rset("set", [look]), None)])
        self.assertIs(resolved.get("look"), look)
        self.assertIs(resolved.get("l"), look)
        self.assertIs(resolved.get(look), look)
        self.assertIsNone(resolved.get("missing"))
        self.assertIsNone(resolved.get(_rcmd("other")))

    def test_make_unique_prefers_caller(self):
        caller = object()
        mine = _rcmd("press", obj=caller)
        other = _rcmd("press", obj=object())
        resolved = resolve_cmdsets(
            [
                (_rset("other", [other]), object()),
                (_rset("mine", [mine]), object()),
            ]
        )
        self.assertEqual(resolved.count(), 2)
        resolved.make_unique(caller)
        self.assertEqual(resolved.commands, [mine])

    def test_get_all_cmd_keys_and_aliases(self):
        allowed = _AccessAllowCmd()
        allowed.set_key("look")
        allowed.set_aliases(["l"])
        allowed.arg_regex = None
        denied = _AccessDenyCmd()
        denied.set_key("deny")
        denied.arg_regex = None
        resolved = resolve_cmdsets([(_rset("set", [allowed, denied]), None)])
        self.assertCountEqual(resolved.get_all_cmd_keys_and_aliases(), ["look", "l", "deny"])
        self.assertCountEqual(resolved.get_all_cmd_keys_and_aliases(caller=object()), ["look", "l"])

    def test_flag_resolution_first_non_none_top_down(self):
        resolved = resolve_cmdsets(
            [
                (_rset("low", no_exits=True, no_objs=True), None),
                (_rset("high", priority=1, no_exits=False), None),
            ]
        )
        self.assertFalse(resolved.no_exits)
        self.assertTrue(resolved.no_objs)
        self.assertIsNone(resolved.no_channels)


class TestBindingTableMatching(TestCase):
    def test_longest_passing_name_wins(self):
        smile = _rcmd("smile", aliases=["smile at"], arg_regex=_ARG_REGEX)
        table = make_bindings([smile])
        matches = table.candidates("smile at bob")
        self.assertEqual(matches, [("smile at", "smile at", smile)])

    def test_arg_regex_failure_falls_through_to_shorter_name(self):
        smile = _rcmd("smile", aliases=["smile at"], arg_regex=_ARG_REGEX)
        table = make_bindings([smile])
        matches = table.candidates("smile atx")
        self.assertEqual(matches, [("smile", "smile", smile)])

    def test_multimatch_candidates_all_returned(self):
        north1 = _rcmd("north")
        north2 = _rcmd("north")
        table = BindingTable({"north": [north1, north2]})
        matches = table.candidates("north")
        self.assertEqual(matches, [("north", "north", north1), ("north", "north", north2)])

    def test_noprefix_matching(self):
        desc = _rcmd("@desc", arg_regex=_ARG_REGEX)
        table = make_bindings([desc])
        self.assertEqual(table.candidates("desc here"), [])
        matches = table.candidates("desc here", include_prefixes=False)
        self.assertEqual(matches, [("desc", "@desc", desc)])

    def test_make_bindings_does_not_shadow(self):
        # the plain-list fallback must behave like polling each command's
        # match(): every command reachable on every one of its names
        look = _rcmd("look", aliases=["l"])
        lock = _rcmd("lock", aliases=["l"])
        table = make_bindings([look, lock])
        matched = {cmd for _, _, cmd in table.candidates("l")}
        self.assertEqual(matched, {look, lock})

    def test_no_match_returns_empty(self):
        look = _rcmd("look")
        table = make_bindings([look])
        self.assertEqual(table.candidates("dance"), [])

class _CmdMarker(Command):
    key = "marker"

    def func(self):
        self.caller.msg("marker ran")


class _CmdOut(Command):
    key = "out"

    def func(self):
        self.caller.msg("out-command ran")


class _CmdNoMatchCapture(Command):
    key = cmdhandler.CMD_NOMATCH

    def func(self):
        self.caller.msg(f"captured {self.args}")


class _CmdSetMarker(CmdSet):
    key = "MarkerSet"

    def at_cmdset_creation(self):
        self.add(_CmdMarker())


class _CmdSetOut(CmdSet):
    key = "OutSet"

    def at_cmdset_creation(self):
        self.add(_CmdOut())


class _CmdSetNoMatchCapture(CmdSet):
    key = "NoMatchCaptureSet"

    def at_cmdset_creation(self):
        self.add(_CmdNoMatchCapture())


# the channel command's lookups are filtered on the game's channel typeclass;
# the test channels are plain DefaultChannels
@patch("evennia.commands.default.comms.CHANNEL_DEFAULT_TYPECLASS", DefaultChannel)
class TestCommandFallbackResolvers(TwistedTestCase, BaseEvenniaTest):
    """
    Test the COMMAND_FALLBACK_RESOLVERS pipeline: exits, channels and nicks
    resolve on parser no-match, commands shadow exits shadow channels shadow
    nicks, and a custom CMD_NOMATCH command suppresses the resolvers
    entirely.

    """

    def setUp(self):
        self.patch(sys.modules["evennia.server.sessionhandler"], "delay", _mockdelay)
        super().setUp()
        self.char1.msg = MagicMock()
        self.channel, _ = DefaultChannel.create("testchan")

    def tearDown(self):
        if self.channel.pk:
            self.channel.delete()
        super().tearDown()

    def _msgs(self):
        """All text sent to char1, flattened to one string."""
        return " ".join(
            str(call.args[0] if call.args else call.kwargs.get("text", ""))
            for call in self.char1.msg.call_args_list
        )

    def test_exit_traversal_via_fallback(self):
        self.char1.execute_cmd("out")
        self.assertEqual(self.char1.location, self.room2)

    def test_exit_alias_traversal(self):
        # direction shorthands are plain aliases on the exit object
        self.exit.aliases.add("o")
        self.char1.execute_cmd("o")
        self.assertEqual(self.char1.location, self.room2)

    def test_exit_match_is_case_insensitive(self):
        self.char1.execute_cmd("OUT")
        self.assertEqual(self.char1.location, self.room2)

    def test_exit_match_is_exact(self):
        # exits take no arguments; trailing input defeats the match
        self.char1.execute_cmd("out now")
        self.assertEqual(self.char1.location, self.room1)
        self.assertIn("Command 'out now' is not available", self._msgs())

    def test_locked_exit_consumes_input(self):
        self.exit.locks.add("traverse:false()")
        self.exit.db.err_traverse = "The door is barred."
        self.char1.execute_cmd("out")
        self.assertEqual(self.char1.location, self.room1)
        self.assertIn("The door is barred.", self._msgs())
        self.assertNotIn("is not available", self._msgs())

    def test_command_shadows_exit(self):
        self.char1.cmdset.add(_CmdSetOut())
        self.char1.execute_cmd("out")
        self.assertEqual(self.char1.location, self.room1)
        self.assertIn("out-command ran", self._msgs())

    def test_exit_shadows_nick(self):
        self.char1.cmdset.add(_CmdSetMarker())
        self.char1.nicks.add("out", "marker", category="inputline")
        self.char1.execute_cmd("out")
        self.assertEqual(self.char1.location, self.room2)
        self.assertNotIn("marker ran", self._msgs())

    def test_nick_resolves_as_fallback(self):
        self.char1.cmdset.add(_CmdSetMarker())
        self.char1.nicks.add("zap", "marker", category="inputline")
        self.char1.execute_cmd("zap")
        self.assertIn("marker ran", self._msgs())

    def test_command_shadows_nick(self):
        self.char1.cmdset.add(_CmdSetMarker())
        self.char1.cmdset.add(_CmdSetOut())
        self.char1.nicks.add("out", "marker", category="inputline")
        self.char1.execute_cmd("out")
        self.assertIn("out-command ran", self._msgs())
        self.assertNotIn("marker ran", self._msgs())

    def test_single_rewrite_guard(self):
        # only one nick rewrite is honored per input; the no-match error
        # reports the original string
        self.char1.cmdset.add(_CmdSetMarker())
        self.char1.nicks.add("x", "y", category="inputline")
        self.char1.nicks.add("y", "marker", category="inputline")
        self.char1.execute_cmd("x")
        self.assertNotIn("marker ran", self._msgs())
        self.assertIn("Command 'x' is not available", self._msgs())

    def test_custom_nomatch_suppresses_resolvers(self):
        # free-input capture (EvMenu/EvEditor style) takes precedence over
        # both exit and nick resolution
        self.char1.cmdset.add(_CmdSetNoMatchCapture())
        self.char1.nicks.add("zap", "look", category="inputline")
        self.char1.execute_cmd("out")
        self.assertEqual(self.char1.location, self.room1)
        self.assertIn("captured out", self._msgs())
        self.char1.execute_cmd("zap")
        self.assertIn("captured zap", self._msgs())

    def test_no_exits_cmdset_suppresses_exit_matching(self):
        # the no_exits merge option gates the exit resolver but not nicks
        self.char1.cmdset.add(_CmdSetNoExits())
        self.char1.cmdset.add(_CmdSetMarker())
        self.char1.nicks.add("out", "marker", category="inputline")
        self.char1.execute_cmd("out")
        self.assertEqual(self.char1.location, self.room1)
        self.assertIn("marker ran", self._msgs())

    def test_suggestions_include_exit_names(self):
        self.char1.execute_cmd("ou")
        self.assertIn("Maybe you meant", self._msgs())
        self.assertIn("out", self._msgs())

    def test_account_caller_without_location(self):
        # account/session callers have no location; the exit resolver must
        # fall through without error
        self.assertEqual(fallbacks.get_exit_candidates(self.account), {})
        self.assertIsNone(fallbacks.resolve_exits(self.account, "out", CmdSet()))
        # smoke: the full pipeline must complete without an untrapped error
        with patch("evennia.commands.cmdhandler._msg_err") as mock_err:
            self.account.execute_cmd("xyzzy_unknown")
            mock_err.assert_not_called()

    # channel resolution

    def test_channel_send_via_key(self):
        self.channel.connect(self.char1)
        self.channel.msg = MagicMock()
        self.char1.execute_cmd("testchan hello")
        self.channel.msg.assert_called_with("hello", senders=self.char1)

    def test_channel_send_via_global_alias(self):
        # global channel aliases match directly, with no per-user nick
        self.channel.aliases.add("tc")
        self.channel.connect(self.char1)
        self.channel.msg = MagicMock()
        self.char1.execute_cmd("tc hi")
        self.channel.msg.assert_called_with("hi", senders=self.char1)

    def test_channel_send_via_personal_nick(self):
        # a personal channel-nick works without a subscription; the send is
        # attributed to the account since the caller is not subscribed
        self.char1.nicks.add("tcc", "testchan", category="channel")
        self.channel.msg = MagicMock()
        self.char1.execute_cmd("tcc hi")
        self.channel.msg.assert_called_with("hi", senders=self.account)

    def test_channel_send_is_case_insensitive(self):
        self.channel.connect(self.char1)
        self.channel.msg = MagicMock()
        self.char1.execute_cmd("TESTCHAN hi")
        self.channel.msg.assert_called_with("hi", senders=self.char1)

    def test_channel_remainder_verbatim(self):
        # the message is the raw remainder, only stripped at the ends
        self.channel.connect(self.char1)
        self.channel.msg = MagicMock()
        self.char1.execute_cmd("testchan   hello there = x ; y ")
        self.channel.msg.assert_called_with("hello there = x ; y", senders=self.char1)

    def test_unsubscribed_channel_falls_through(self):
        self.channel.msg = MagicMock()
        self.char1.execute_cmd("testchan hi")
        self.channel.msg.assert_not_called()
        self.assertIn("is not available", self._msgs())

    def test_channel_send_lock_failure_consumes(self):
        self.channel.connect(self.char1)
        self.channel.locks.add("send:false()")
        self.channel.msg = MagicMock()
        self.char1.execute_cmd("testchan hi")
        self.channel.msg.assert_not_called()
        self.assertIn("not allowed to send", self._msgs())
        self.assertNotIn("is not available", self._msgs())

    def test_command_shadows_channel(self):
        marker_channel, _ = DefaultChannel.create("marker")
        try:
            marker_channel.connect(self.char1)
            marker_channel.msg = MagicMock()
            self.char1.cmdset.add(_CmdSetMarker())
            self.char1.execute_cmd("marker")
            self.assertIn("marker ran", self._msgs())
            marker_channel.msg.assert_not_called()
        finally:
            marker_channel.delete()

    def test_exit_shadows_channel(self):
        out_channel, _ = DefaultChannel.create("out")
        try:
            out_channel.connect(self.char1)
            out_channel.msg = MagicMock()
            self.char1.execute_cmd("out")
            # the exact-match exit wins on the bare name...
            self.assertEqual(self.char1.location, self.room2)
            out_channel.msg.assert_not_called()
            # ...but with a message the exit cannot match, so the channel gets it
            self.char1.execute_cmd("out hi")
            out_channel.msg.assert_called_with("hi", senders=self.char1)
        finally:
            out_channel.delete()

    def test_channel_shadows_inputline_nick(self):
        self.channel.connect(self.char1)
        self.channel.msg = MagicMock()
        self.char1.cmdset.add(_CmdSetMarker())
        self.char1.nicks.add("testchan hi", "marker", category="inputline")
        self.char1.execute_cmd("testchan hi")
        self.channel.msg.assert_called_with("hi", senders=self.char1)
        self.assertNotIn("marker ran", self._msgs())

    def test_no_channels_cmdset_suppresses_channel_matching(self):
        self.channel.connect(self.char1)
        self.channel.msg = MagicMock()
        self.char1.cmdset.add(_CmdSetNoChannels())
        self.char1.execute_cmd("testchan hi")
        self.channel.msg.assert_not_called()
        self.assertIn("is not available", self._msgs())

    def test_channel_bare_name_shows_info(self):
        # a bare channel name is rewritten to the channel command, which
        # displays the channel info (caller depends on account_caller, so
        # capture both sinks; the command sends its text as a kwarg)
        self.channel.connect(self.char1)
        self.channel.connect(self.account)
        self.account.msg = MagicMock()
        self.char1.execute_cmd("testchan")
        account_msgs = " ".join(
            str(call.args[0] if call.args else call.kwargs.get("text", ""))
            for call in self.account.msg.call_args_list
        )
        self.assertIn("testchan", self._msgs() + account_msgs)

    def test_puppet_with_account_level_subscription(self):
        # default channels subscribe the account; sends from the puppet must
        # resolve and be attributed to the account
        self.channel.connect(self.account)
        self.channel.msg = MagicMock()
        self.char1.execute_cmd("testchan hi")
        self.channel.msg.assert_called_with("hi", senders=self.account)

    def test_account_caller_channel_send(self):
        self.channel.connect(self.account)
        self.channel.msg = MagicMock()
        self.account.execute_cmd("testchan hi")
        self.channel.msg.assert_called_with("hi", senders=self.account)
