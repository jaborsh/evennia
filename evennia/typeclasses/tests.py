"""
Unit tests for typeclass base system

"""

import re
from io import StringIO

from django.core.management import call_command
from django.test import override_settings
from mock import patch
from parameterized import parameterized

from evennia.objects.objects import DefaultObject
from evennia.typeclasses.attributes import Attribute
from evennia.utils.dbserialize import to_pickle
from evennia.utils.test_resources import BaseEvenniaTest, EvenniaTestCase

# ------------------------------------------------------------
# Manager tests
# ------------------------------------------------------------


class DictSubclass(dict):
    pass


class TestAttributes(BaseEvenniaTest):
    def test_attrhandler(self):
        key = "testattr"
        value = "test attr value "
        self.obj1.attributes.add(key, value)
        self.assertEqual(self.obj1.attributes.get(key), value)
        self.obj1.db.testattr = value
        self.assertEqual(self.obj1.db.testattr, value)

        # "plain" subclasses
        value = DictSubclass({"fo": "foo", "bar": "bar"})
        self.obj1.db.testattr = value
        self.assertEqual(self.obj1.db.testattr, value)

        self.obj1.db.testattr["fo"] = "foo2"
        value.update({"fo": "foo2"})
        self.assertEqual(self.obj1.db.testattr, value)
        self.assertEqual(self.obj1.attributes.get("testattr"), value)

        # nested subclasses
        value = DictSubclass({"nested": True, "deep": DictSubclass({"fo": "foo", "bar": "bar"})})
        self.obj1.db.testattr = value

        self.obj1.db.testattr["deep"]["fo"] = "nemo"
        value["deep"].update({"fo": "nemo"})
        self.assertEqual(self.obj1.db.testattr, value)
        self.assertEqual(self.obj1.attributes.get("testattr"), value)

    @override_settings(TYPECLASS_AGGRESSIVE_CACHE=False)
    @patch("evennia.typeclasses.attributes._TYPECLASS_AGGRESSIVE_CACHE", False)
    def test_attrhandler_nocache(self):
        key = "testattr"
        value = "test attr value "
        self.obj1.attributes.add(key, value)
        self.assertFalse(self.obj1.attributes.backend._cache)

        self.assertEqual(self.obj1.attributes.get(key), value)
        self.obj1.db.testattr = value
        self.assertEqual(self.obj1.db.testattr, value)
        self.assertFalse(self.obj1.attributes.backend._cache)

        # "plain" subclasses
        value = DictSubclass({"fo": "foo", "bar": "bar"})
        self.obj1.db.testattr = value
        self.assertEqual(self.obj1.db.testattr, value)

        self.obj1.db.testattr["fo"] = "foo2"
        value.update({"fo": "foo2"})
        self.assertEqual(self.obj1.db.testattr, value)
        self.assertEqual(self.obj1.attributes.get("testattr"), value)
        self.assertFalse(self.obj1.attributes.backend._cache)

        # nested subclasses
        value = DictSubclass({"nested": True, "deep": DictSubclass({"fo": "foo", "bar": "bar"})})
        self.obj1.db.testattr = value

        self.obj1.db.testattr["deep"]["fo"] = "nemo"
        value["deep"].update({"fo": "nemo"})
        self.assertEqual(self.obj1.db.testattr, value)
        self.assertEqual(self.obj1.attributes.get("testattr"), value)
        self.assertFalse(self.obj1.attributes.backend._cache)

    def test_weird_text_save(self):
        "test 'weird' text type (different in py2 vs py3)"
        from django.utils.safestring import SafeText

        key = "test attr 2"
        value = SafeText("test attr value 2")
        self.obj1.attributes.add(key, value)
        self.assertEqual(self.obj1.attributes.get(key), value)

    def test_batch_add(self):
        attrs = [
            ("key1", "value1"),
            ("key2", "value2", "category2"),
            ("key3", "value3"),
            ("key4", "value4", "category4", "attrread:id(1)", False),
        ]
        new_attrs = self.obj1.attributes.batch_add(*attrs)
        attrobj = self.obj1.attributes.get(key="key4", category="category4", return_obj=True)
        self.assertEqual(attrobj.value, "value4")
        self.assertEqual(attrobj.category, "category4")
        self.assertEqual(attrobj.locks.all(), ["attrread:id(1)"])

    def test_value_vs_strvalue(self):
        self.obj1.attributes.add("test", "one")
        self.assertEqual(self.obj1.attributes.get("test"), "one")
        self.assertEqual(self.obj1.attributes.get("test", strattr=True), None)
        # switch to strattr
        self.obj1.attributes.add("test", "two", strattr=True)
        self.assertEqual(self.obj1.attributes.get("test"), None)
        self.assertEqual(self.obj1.attributes.get("test", strattr=True), "two")


class TestAttributeJsonStorage(BaseEvenniaTest):
    """
    Test the dual JSON/pickle Attribute storage columns.

    """

    def _columns(self, key, obj=None):
        """Fetch the raw storage columns for an attribute from the database."""
        attr = (obj or self.obj1).attributes.get(key, return_obj=True)
        return Attribute.objects.filter(id=attr.id).values(
            "db_value", "db_json", "db_storage_type"
        )[0]

    def _make_legacy_attr(self, key, value, obj=None):
        """Create a pre-migration-style row writing the pickle column directly."""
        obj = obj or self.obj1
        attr = Attribute(db_key=key, db_value=to_pickle(value), db_model="objectdb")
        attr.save()
        obj.db_attributes.add(attr)
        obj.attributes.reset_cache()
        return attr

    def test_json_storage_columns(self):
        self.obj1.db.jsonval = [1, "a", (2, 3)]
        cols = self._columns("jsonval")
        self.assertEqual(cols["db_storage_type"], "json")
        self.assertIsNone(cols["db_value"])
        self.assertEqual(cols["db_json"], [1, "a", {"__tuple__": [2, 3]}])
        self.assertEqual(self.obj1.db.jsonval, [1, "a", (2, 3)])

    def test_pickle_fallback_columns(self):
        self.obj1.db.binval = b"bytes"
        cols = self._columns("binval")
        self.assertEqual(cols["db_storage_type"], "pickle")
        self.assertIsNone(cols["db_json"])
        self.assertEqual(self.obj1.db.binval, b"bytes")

    def test_none_value(self):
        self.obj1.db.noneval = None
        cols = self._columns("noneval")
        self.assertEqual(cols["db_storage_type"], "pickle")
        self.assertIsNone(cols["db_value"])
        self.assertIsNone(cols["db_json"])
        self.assertIsNone(self.obj1.db.noneval)

    def test_saver_mutation_stays_json(self):
        self.obj1.db.lst = [1, 2]
        self.obj1.db.lst.append(3)
        self.obj1.attributes.reset_cache()
        self.assertEqual(self.obj1.db.lst, [1, 2, 3])
        self.assertEqual(self._columns("lst")["db_storage_type"], "json")

    def test_saver_mutation_flips_to_pickle(self):
        self.obj1.db.lst = [1]
        self.obj1.db.lst.append(b"x")
        self.obj1.attributes.reset_cache()
        self.assertEqual(self.obj1.db.lst, [1, b"x"])
        self.assertEqual(self._columns("lst")["db_storage_type"], "pickle")

    def test_dbobj_value(self):
        self.obj1.db.ref = self.obj2
        cols = self._columns("ref")
        self.assertEqual(cols["db_storage_type"], "json")
        self.assertIn("__dbobj__", cols["db_json"])
        self.assertEqual(cols["db_json"]["__dbobj__"][2], self.obj2.id)
        self.assertEqual(self.obj1.db.ref, self.obj2)

    def test_dbobj_value_deleted(self):
        self.obj1.db.ref = self.obj2
        self.obj2.delete()
        self.assertIsNone(self.obj1.db.ref)

    def test_legacy_pickle_row(self):
        self._make_legacy_attr("legacy", {"a": (1,)})
        cols = self._columns("legacy")
        self.assertEqual(cols["db_storage_type"], "pickle")
        self.assertEqual(self.obj1.db.legacy, {"a": (1,)})

    def test_strvalue_columns(self):
        self.obj1.attributes.add("strval", "two", strattr=True)
        cols = self._columns("strval")
        self.assertEqual(cols["db_storage_type"], "pickle")
        self.assertIsNone(cols["db_value"])
        self.assertIsNone(cols["db_json"])
        self.assertEqual(self.obj1.attributes.get("strval", strattr=True), "two")

    def test_batch_create_columns(self):
        self.obj1.attributes.batch_add(("bkey1", [1, (2,)]), ("bkey2", b"x"))
        self.assertEqual(self._columns("bkey1")["db_storage_type"], "json")
        self.assertEqual(self._columns("bkey2")["db_storage_type"], "pickle")
        self.assertEqual(self.obj1.db.bkey1, [1, (2,)])
        self.assertEqual(self.obj1.db.bkey2, b"x")

    def test_serialized_value(self):
        self.obj1.db.jval = {"a": (1,)}
        attr = self.obj1.attributes.get("jval", return_obj=True)
        self.assertEqual(attr.serialized_value(), {"a": (1,)})
        self.obj1.db.pval = b"x"
        attr = self.obj1.attributes.get("pval", return_obj=True)
        self.assertEqual(attr.serialized_value(), b"x")

    def test_query_finds_json_rows(self):
        self.obj1.db.qval = {"a": 1}
        found = self.obj1.__class__.objects.get_by_attribute(key="qval", value={"a": 1})
        self.assertIn(self.obj1, found)

    def test_query_finds_pickle_rows(self):
        self.obj1.db.qbin = b"z"
        found = self.obj1.__class__.objects.get_by_attribute(key="qbin", value=b"z")
        self.assertIn(self.obj1, found)

    def test_query_finds_mixed_storage(self):
        # same value in a legacy pickle row and a new json row
        self.obj1.db.qmixed = "samevalue"
        self._make_legacy_attr("qmixed", "samevalue", obj=self.obj2)
        found = self.obj1.__class__.objects.get_by_attribute(key="qmixed", value="samevalue")
        self.assertIn(self.obj1, found)
        self.assertIn(self.obj2, found)

    def test_get_objs_with_attr_value(self):
        self.obj1.db.qobj = self.obj2
        found = self.obj1.__class__.objects.get_objs_with_attr_value("qobj", self.obj2)
        self.assertIn(self.obj1, found)

    def test_monitor_fires_on_json_save(self):
        from evennia.scripts.monitorhandler import MONITOR_HANDLER

        with patch.object(MONITOR_HANDLER, "at_update") as mock_update:
            self.obj1.db.monval = {"a": 1}
            fieldnames = [call.args[1] for call in mock_update.call_args_list]
            self.assertIn("db_value", fieldnames)


class TestConvertAttributeStorage(BaseEvenniaTest):
    """
    Test the convert_attribute_storage management command.

    """

    def _convert(self, *args):
        out = StringIO()
        call_command("convert_attribute_storage", *args, stdout=out)
        return int(re.search(r"(?:Converted|Would convert) (\d+)", out.getvalue()).group(1))

    def _make_legacy_attr(self, key, value):
        attr = Attribute(db_key=key, db_value=to_pickle(value), db_model="objectdb")
        attr.save()
        self.obj1.db_attributes.add(attr)
        return attr

    def test_convert(self):
        legacy_keys = ("conv1", "conv2", "conv3")
        for key in legacy_keys:
            self._make_legacy_attr(key, {key: (1, 2)})
        self.obj1.db.binval = b"unconvertible"

        converted = self._convert()
        self.assertGreaterEqual(converted, 3)

        self.obj1.attributes.reset_cache()
        for key in legacy_keys:
            cols = Attribute.objects.filter(db_key=key).values(
                "db_value", "db_json", "db_storage_type"
            )[0]
            self.assertEqual(cols["db_storage_type"], "json")
            self.assertIsNone(cols["db_value"])
            self.assertEqual(self.obj1.attributes.get(key), {key: (1, 2)})
        # the unconvertible row stays as pickle and still round-trips
        cols = Attribute.objects.filter(db_key="binval").values("db_storage_type")[0]
        self.assertEqual(cols["db_storage_type"], "pickle")
        self.assertEqual(self.obj1.db.binval, b"unconvertible")

        # idempotency: a second run converts nothing
        self.assertEqual(self._convert(), 0)

    def test_dry_run(self):
        self._make_legacy_attr("dryval", [1, 2])
        would_convert = self._convert("--dry-run")
        self.assertGreaterEqual(would_convert, 1)
        cols = Attribute.objects.filter(db_key="dryval").values("db_storage_type")[0]
        self.assertEqual(cols["db_storage_type"], "pickle")


class TestTypedObjectManager(BaseEvenniaTest):
    def _manager(self, methodname, *args, **kwargs):
        return list(getattr(self.obj1.__class__.objects, methodname)(*args, **kwargs))

    def test_get_by_tag_no_category(self):
        self.obj1.tags.add("tag1")
        self.obj1.tags.add("tag2")
        self.obj1.tags.add("tag2c")
        self.obj2.tags.add("tag2")
        self.obj2.tags.add("tag2a")
        self.obj2.tags.add("tag2b")
        self.obj2.tags.add("tag3 with spaces")
        self.obj2.tags.add("tag4")
        self.obj2.tags.add("tag2c")
        self.assertEqual(self._manager("get_by_tag", "tag1"), [self.obj1])
        self.assertEqual(set(self._manager("get_by_tag", "tag2")), set([self.obj1, self.obj2]))
        self.assertEqual(self._manager("get_by_tag", "tag2a"), [self.obj2])
        self.assertEqual(self._manager("get_by_tag", "tag3 with spaces"), [self.obj2])
        self.assertEqual(self._manager("get_by_tag", ["tag2a", "tag2b"]), [self.obj2])
        self.assertEqual(self._manager("get_by_tag", ["tag2a", "tag1"]), [])
        self.assertEqual(self._manager("get_by_tag", ["tag2a", "tag4", "tag2c"]), [self.obj2])

    def test_get_by_tag_and_category(self):
        self.obj1.tags.add("tag5", "category1")
        self.obj1.tags.add("tag6")
        self.obj1.tags.add("tag7", "category1")
        self.obj1.tags.add("tag6", "category3")
        self.obj1.tags.add("tag7", "category4")
        self.obj2.tags.add("tag5", "category1")
        self.obj2.tags.add("tag5", "category2")
        self.obj2.tags.add("tag6", "category3")
        self.obj2.tags.add("tag7", "category1")
        self.obj2.tags.add("tag7", "category5")
        self.obj1.tags.add("tag8", "category6")
        self.obj2.tags.add("tag9", "category6")

        self.assertEqual(self._manager("get_by_tag", "tag5", "category1"), [self.obj1, self.obj2])
        self.assertEqual(self._manager("get_by_tag", "tag6", "category1"), [])
        self.assertEqual(self._manager("get_by_tag", "tag6", "category3"), [self.obj1, self.obj2])
        self.assertEqual(
            self._manager("get_by_tag", ["tag5", "tag6"], ["category1", "category3"]),
            [self.obj1, self.obj2],
        )
        self.assertEqual(
            self._manager("get_by_tag", ["tag5", "tag7"], "category1"),
            [self.obj1, self.obj2],
        )
        self.assertEqual(self._manager("get_by_tag", category="category1"), [self.obj1, self.obj2])
        self.assertEqual(self._manager("get_by_tag", category="category2"), [self.obj2])
        self.assertEqual(
            self._manager("get_by_tag", category=["category1", "category3"]),
            [self.obj1, self.obj2],
        )
        self.assertEqual(
            self._manager("get_by_tag", category=["category1", "category2"]),
            [self.obj1, self.obj2],
        )
        self.assertEqual(self._manager("get_by_tag", category=["category5", "category4"]), [])
        self.assertEqual(self._manager("get_by_tag", category="category1"), [self.obj1, self.obj2])
        self.assertEqual(self._manager("get_by_tag", category="category6"), [self.obj1, self.obj2])

    def test_get_tag_with_all(self):
        self.obj1.tags.add("tagA", "categoryA")
        self.assertEqual(
            self._manager("get_by_tag", ["tagA", "tagB"], ["categoryA", "categoryB"], match="all"),
            [],
        )

    def test_get_tag_with_any(self):
        self.obj1.tags.add("tagA", "categoryA")
        self.assertEqual(
            self._manager("get_by_tag", ["tagA", "tagB"], ["categoryA", "categoryB"], match="any"),
            [self.obj1],
        )

    def test_get_tag_with_any_including_nones(self):
        self.obj1.tags.add("tagA", "categoryA")
        self.assertEqual(
            self._manager(
                "get_by_tag", ["tagA", "tagB"], ["categoryA", "categoryB", None], match="any"
            ),
            [self.obj1],
        )

    def test_get_tag_withnomatch(self):
        self.obj1.tags.add("tagC", "categoryC")
        self.assertEqual(
            self._manager("get_by_tag", ["tagA", "tagB"], ["categoryA", "categoryB"], match="any"),
            [],
        )

    def test_get_by_tag_with_integer_key_and_category(self):
        self.obj1.tags.add(123, 456)
        self.assertEqual(self._manager("get_by_tag", 123, 456), [self.obj1])
        self.assertEqual(self._manager("get_by_tag", "123", "456"), [self.obj1])

    def test_batch_add(self):
        tags = ["tag1", ("tag2", "category2"), "tag3", ("tag4", "category4", "data4")]
        self.obj1.tags.batch_add(*tags)
        self.assertEqual(self.obj1.tags.get("tag1"), "tag1")
        tagobj = self.obj1.tags.get("tag4", category="category4", return_tagobj=True)
        self.assertEqual(tagobj.db_key, "tag4")
        self.assertEqual(tagobj.db_category, "category4")
        self.assertEqual(tagobj.db_data, "data4")


# setting up testing typeclass with child- and parent class
class TestSearchManagerTypeclassParent(DefaultObject):
    pass


class TestSearchManagerTypeclass(TestSearchManagerTypeclassParent):
    pass


class TestSearchManagerTypeclassChild(TestSearchManagerTypeclass):
    pass


class TestSearchTypeclassFamily(EvenniaTestCase):
    """
    Test the manager method for searching for inheriting typeclasses.

    """

    def setUp(self):
        self.obj_parent, _ = TestSearchManagerTypeclassParent.create(key="obj_parent")
        self.obj1, _ = TestSearchManagerTypeclass.create(key="obj1")
        self.obj2, _ = TestSearchManagerTypeclass.create(key="obj2")
        self.obj_child, _ = TestSearchManagerTypeclassChild.create(key="obj_child")

    def test_typeclass_search__inputs(self):
        """Test basic functionality"""

        res1 = self.obj1.__class__.objects.typeclass_search(self.obj1.__class__)
        res2 = self.obj1.__class__.objects.typeclass_search(
            "evennia.typeclasses.tests.TestSearchManagerTypeclass"
        )
        self.assertEqual(set(res1), {self.obj1, self.obj2})
        self.assertEqual(set(res2), {self.obj1, self.obj2})

    def test_typeclass_search__children_and_parents(self):
        """Test getting parents/child classes"""

        # just the objects of this typeclass
        res1 = self.obj1.__class__.objects.typeclass_search(self.obj1.__class__)
        res2 = self.obj2.__class__.objects.typeclass_search(self.obj2.__class__)

        # these objects + children
        res3 = self.obj1.__class__.objects.typeclass_search(
            self.obj1.__class__, include_children=True
        )
        # these objects + parents
        res4 = self.obj1.__class__.objects.typeclass_search(
            self.obj1.__class__, include_parents=True
        )
        # these objects + parents + children
        res5 = self.obj1.__class__.objects.typeclass_search(
            self.obj1.__class__, include_children=True, include_parents=True
        )

        self.assertEqual(set(res1), {self.obj1, self.obj2})
        self.assertEqual(set(res2), {self.obj1, self.obj2})
        self.assertEqual(set(res3), {self.obj1, self.obj2, self.obj_child})
        self.assertEqual(set(res4), {self.obj1, self.obj2, self.obj_parent})
        self.assertEqual(set(res5), {self.obj1, self.obj2, self.obj_child, self.obj_parent})

    def test_typeclass_search__nested(self):
        """Test several levels deep searches"""
        # check all children of the parent
        res1 = self.obj1.__class__.objects.typeclass_search(
            self.obj_parent.__class__, include_children=True
        )
        # check all parents of the child
        res2 = self.obj1.__class__.objects.typeclass_search(
            self.obj_child.__class__, include_parents=True
        )

        self.assertEqual(set(res1), {self.obj_parent, self.obj1, self.obj2, self.obj_child})
        self.assertEqual(set(res2), {self.obj_parent, self.obj1, self.obj2, self.obj_child})


class TestTags(BaseEvenniaTest):
    def test_has_tag_key_only(self):
        self.obj1.tags.add("tagC")
        self.assertTrue(self.obj1.tags.has("tagC"))

    def test_has_tag_key_with_category(self):
        self.obj1.tags.add("tagC", "categoryC")
        self.assertTrue(self.obj1.tags.has("tagC", "categoryC"))

    def test_does_not_have_tag_key_only(self):
        self.obj1.tags.add("tagC")
        self.assertFalse(self.obj1.tags.has("tagD"))

    def test_does_not_have_tag_key_with_category(self):
        self.obj1.tags.add("tagC", "categoryC")
        self.assertFalse(self.obj1.tags.has("tagD", "categoryD"))

    def test_has_tag_category_only(self):
        self.obj1.tags.add("tagC", "categoryC")
        self.assertTrue(self.obj1.tags.has(category="categoryC"))

    def test_does_not_have_tag_category_only(self):
        self.obj1.tags.add("tagC", "categoryC")
        self.assertFalse(self.obj1.tags.has(category="categoryD"))

    def test_integer_tag(self):
        self.obj1.tags.add(1)
        self.assertTrue(self.obj1.tags.has(1))
        self.assertTrue(self.obj1.tags.get(1))
        self.assertTrue(self.obj1.tags.has("1"))
        self.assertTrue(self.obj1.tags.get("1"))
        self.obj1.tags.remove(1)
        self.assertFalse(self.obj1.tags.has(1))
        self.assertFalse(self.obj1.tags.get(1))
        self.assertFalse(self.obj1.tags.has("1"))
        self.assertFalse(self.obj1.tags.get("1"))

    def test_tag_add_no_category__issue_2688(self):
        """
        Adding a tag without a category should create a new tag:None tag
        rather than trying to update an existing tag:category tag.
        """
        # adding tag+category, creates tag+category entry
        self.obj1.tags.add("testing", category="testing_category")
        self.assertEqual(
            self.obj1.tags.all(return_key_and_category=True), [("testing", "testing_category")]
        )
        # adding a new tag with no category should create a tag+None entry
        self.obj1.tags.add("testing")
        self.assertEqual(
            self.obj1.tags.all(return_key_and_category=True),
            [("testing", "testing_category"), ("testing", None)],
        )


class TestNickHandler(BaseEvenniaTest):
    """
    Test the nick handler replacement.

    """

    @parameterized.expand(
        [
            # shell syntax
            (
                "gr $1 $2 at $3",
                "emote with a $1 smile, $2 grins at $3.",
                False,
                "gr happy Foo at Bar",
                "emote with a happy smile, Foo grins at Bar.",
            ),
            # regex syntax
            (
                "gr (?P<arg1>.+?) (?P<arg2>.+?) at (?P<arg3>.+?)",
                "emote with a $1 smile, $2 grins at $3.",
                True,
                "gr happy Foo at Bar",
                "emote with a happy smile, Foo grins at Bar.",
            ),
            # channel-style syntax
            (
                "groo $1",
                "channel groo = $1",
                False,
                "groo Hello world",
                "channel groo = Hello world",
            ),
            (
                r"groo\s*?|groo\s+?(?P<arg1>.+?)",
                "channel groo = $1",
                True,
                "groo Hello world",
                "channel groo = Hello world",
            ),
            (
                r"groo\s*?|groo\s+?(?P<arg1>.+?)",
                "channel groo = $1",
                True,
                "groo ",
                "channel groo = ",
            ),
            (
                r"groo\s*?|groo\s*?(?P<arg1>.+?)",
                "channel groo = $1",
                True,
                "groo",
                "channel groo = ",
            ),
            (
                r"groo\s*?|groo\s+?(?P<arg1>.+?)",
                "channel groo = $1",
                True,
                "grooHello world",
                "grooHello world",
            ),  # not matched - this is correct!
            # optional, space-separated arguments
            (
                r"groo\s*?|groo\s+?(?P<arg1>.+?)(?:\s+?(?P<arg2>.+?)){0,1}",
                "channel groo = $1 and $2",
                True,
                "groo Hello World",
                "channel groo = Hello and World",
            ),
            (
                r"groo\s*?|groo\s+?(?P<arg1>.+?)(?:\s+?(?P<arg2>.+?)){0,1}",
                "channel groo = $1 and $2",
                True,
                "groo Hello",
                "channel groo = Hello and ",
            ),
            (
                r"groo\s*?|groo\s+?(?P<arg1>.+?)(?:\s+?(?P<arg2>.+?)){0,1}",
                "channel groo = $1 and $2",
                True,
                "groo",
                "channel groo =  and ",
            ),  # $1/$2 replaced by ''
        ]
    )
    def test_nick_parsing(
        self, pattern, replacement, pattern_is_regex, inp_string, expected_replaced
    ):
        """
        Setting up nick patterns and make sure they replace as expected.

        """
        # from evennia import set_trace;set_trace()
        self.char1.nicks.add(
            pattern, replacement, category="inputline", pattern_is_regex=pattern_is_regex
        )
        actual_replaced = self.char1.nicks.nickreplace(inp_string)

        self.assertEqual(expected_replaced, actual_replaced)
        self.char1.nicks.clear()

    def test_nick_with_parenthesis(self):
        """
        Test case where input has a special character

        """
        import re

        from evennia.typeclasses.attributes import initialize_nick_templates

        nick_regex, replacement_string = initialize_nick_templates(
            re.escape("OOC["), "ooc", pattern_is_regex=True
        )
        re.compile(nick_regex, re.I + re.DOTALL + re.U)
