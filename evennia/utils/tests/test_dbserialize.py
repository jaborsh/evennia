"""
Tests for dbserialize module
"""

import json
from collections import OrderedDict, defaultdict, deque
from datetime import date, datetime, time, timedelta, timezone
from enum import IntFlag, auto

from django.db.models import Q
from django.test import SimpleTestCase, TestCase
from django.utils.safestring import SafeString
from parameterized import parameterized

from evennia.objects.objects import DefaultObject
from evennia.utils import dbserialize


class TestDbSerialize(TestCase):
    """
    Database serialization operations.
    """

    def setUp(self):
        self.obj = DefaultObject(db_key="Tester")
        self.obj.save()

    def test_intflag(self):
        class TestFlag(IntFlag):
            foo = auto()

        self.obj.db.test = TestFlag.foo
        self.assertEqual(self.obj.db.test, TestFlag.foo)
        self.obj.save()

    def test_constants(self):
        self.obj.db.test = 1
        self.obj.db.test += 1
        self.assertEqual(self.obj.db.test, 2)
        self.obj.db.test -= 3
        self.assertEqual(self.obj.db.test, -1)
        self.obj.db.test *= -2
        self.assertEqual(self.obj.db.test, 2)
        self.obj.db.test /= 2
        self.assertEqual(self.obj.db.test, 1)

    def test_saverlist(self):
        self.obj.db.test = [1, 2, 3]
        self.assertEqual(self.obj.db.test, [1, 2, 3])
        self.obj.db.test.append("4")
        self.assertEqual(self.obj.db.test, [1, 2, 3, "4"])
        self.obj.db.test.insert(1, 1.5)
        self.assertEqual(self.obj.db.test, [1, 1.5, 2, 3, "4"])
        self.obj.db.test.pop()
        self.assertEqual(self.obj.db.test, [1, 1.5, 2, 3])
        self.obj.db.test.pop(0)
        self.assertEqual(self.obj.db.test, [1.5, 2, 3])
        self.obj.db.test.reverse()
        self.assertEqual(self.obj.db.test, [3, 2, 1.5])

    def test_saverlist__sort(self):
        self.obj.db.test = [3, 2, 1.5]
        self.obj.db.test.sort()
        self.assertEqual(self.obj.db.test, [1.5, 2, 3])
        self.obj.db.test.extend([0, 4, 5])
        self.assertEqual(self.obj.db.test, [1.5, 2, 3, 0, 4, 5])
        self.obj.db.test.sort()
        self.assertEqual(self.obj.db.test, [0, 1.5, 2, 3, 4, 5])
        self.obj.db.test = [[4, 5, 6], [1, 2, 3]]
        self.assertEqual(self.obj.db.test, [[4, 5, 6], [1, 2, 3]])
        self.obj.db.test.sort()
        self.assertEqual(self.obj.db.test, [[1, 2, 3], [4, 5, 6]])
        self.obj.db.test = [{1: 0}, {0: 1}]
        self.assertEqual(self.obj.db.test, [{1: 0}, {0: 1}])
        self.obj.db.test.sort(key=lambda d: str(d))
        self.assertEqual(self.obj.db.test, [{0: 1}, {1: 0}])

    def test_saverdict(self):
        self.obj.db.test = {"a": True}
        self.obj.db.test.update({"b": False})
        self.assertEqual(self.obj.db.test, {"a": True, "b": False})
        self.obj.db.test |= {"c": 5}
        self.assertEqual(self.obj.db.test, {"a": True, "b": False, "c": 5})

    @parameterized.expand(
        [
            ("list", list, dbserialize._SaverList, [1, 2, 3]),
            ("dict", dict, dbserialize._SaverDict, {"key": "value"}),
            ("set", set, dbserialize._SaverSet, {1, 2, 3}),
            ("deque", deque, dbserialize._SaverDeque, deque(("a", "b", "c"))),
            (
                "OrderedDict",
                dbserialize.OrderedDict,
                dbserialize._SaverOrderedDict,
                dbserialize.OrderedDict([("a", 1), ("b", 2), ("c", 3)]),
            ),
        ]
    )
    def test_deserialize(self, _, base_type, saver_type, default_value):
        self.assertIsInstance(default_value, base_type)
        self.obj.db.test = default_value
        for value in (dbserialize.deserialize(self.obj.db.test), self.obj.db.test.deserialize()):
            self.assertIsInstance(value, base_type)
            self.assertNotIsInstance(value, saver_type)
            self.assertEqual(value, default_value)
        self.obj.db.test = {"a": True}
        self.obj.db.test.update({"b": False})
        self.assertEqual(self.obj.db.test, {"a": True, "b": False})

    def test_defaultdict(self):
        # baseline behavior for a defaultdict
        _dd = defaultdict(list)
        _dd["a"]
        self.assertEqual(_dd, {"a": []})

        # behavior after defaultdict is set as attribute

        dd = defaultdict(list)
        self.obj.db.test = dd
        self.obj.db.test["a"]
        self.assertEqual(self.obj.db.test, {"a": []})

        self.obj.db.test["a"].append(1)
        self.assertEqual(self.obj.db.test, {"a": [1]})
        self.obj.db.test["a"].append(2)
        self.assertEqual(self.obj.db.test, {"a": [1, 2]})
        self.obj.db.test["a"].append(3)
        self.assertEqual(self.obj.db.test, {"a": [1, 2, 3]})
        self.obj.db.test |= {"b": [5, 6]}
        self.assertEqual(self.obj.db.test, {"a": [1, 2, 3], "b": [5, 6]})

    def test_deque_with_maxlen(self):
        _dd = deque((), maxlen=1)
        _dd.append(1)
        _dd.append(2)
        self.assertEqual(list(_dd), [2])

        dd = deque((), maxlen=1)
        self.obj.db.test = dd
        self.obj.db.test.append(1)
        self.obj.db.test.append(2)
        self.assertEqual(list(self.obj.db.test), [2])


class _InvalidContainer:
    """Container not saveable in Attribute (if obj is dbobj, it 'hides' it)"""

    def __init__(self, obj):
        self.hidden_obj = obj


class _ValidContainer(_InvalidContainer):
    """Container possible to save in Attribute (handles hidden dbobj explicitly)"""

    def __serialize_dbobjs__(self):
        self.hidden_obj = dbserialize.dbserialize(self.hidden_obj)

    def __deserialize_dbobjs__(self):
        self.hidden_obj = dbserialize.dbunserialize(self.hidden_obj)


class DbObjWrappers(TestCase):
    """
    Test the `__serialize_dbobjs__` and `__deserialize_dbobjs__` methods.

    """

    def setUp(self):
        super().setUp()
        self.dbobj1 = DefaultObject(db_key="Tester1")
        self.dbobj1.save()
        self.dbobj2 = DefaultObject(db_key="Tester2")
        self.dbobj2.save()

    def test_dbobj_hidden_obj__fail(self):
        with self.assertRaises(TypeError):
            self.dbobj1.db.testarg = _InvalidContainer(self.dbobj1)

    def test_consecutive_fetch(self):
        con = _ValidContainer(self.dbobj2)
        self.dbobj1.db.testarg = con
        attrobj = self.dbobj1.attributes.get("testarg", return_obj=True)

        self.assertEqual(attrobj.value, con)
        self.assertEqual(attrobj.value, con)
        self.assertEqual(attrobj.value.hidden_obj, self.dbobj2)

    def test_dbobj_hidden_obj__success(self):
        con = _ValidContainer(self.dbobj2)
        self.dbobj1.db.testarg = con

        # accessing the same data multiple times
        res1 = self.dbobj1.db.testarg
        res2 = self.dbobj1.db.testarg
        res3 = self.dbobj1.db.testarg

        self.assertEqual(res1, res2)
        self.assertEqual(res1, res3)
        self.assertEqual(res1, con)
        self.assertEqual(res2, con)
        self.assertEqual(res1.hidden_obj, self.dbobj2)
        self.assertEqual(res2.hidden_obj, self.dbobj2)
        self.assertEqual(res3.hidden_obj, self.dbobj2)

    def test_dbobj_hidden_dict(self):
        con1 = _ValidContainer(self.dbobj2)
        con2 = _ValidContainer(self.dbobj2)

        self.dbobj1.db.dict = {}

        self.dbobj1.db.dict["key1"] = con1
        self.dbobj1.db.dict["key2"] = con2

        self.assertEqual(self.dbobj1.db.dict["key1"].hidden_obj, self.dbobj2)
        self.assertEqual(self.dbobj1.db.dict["key1"].hidden_obj, self.dbobj2)
        self.assertEqual(self.dbobj1.db.dict["key2"].hidden_obj, self.dbobj2)
        self.assertEqual(self.dbobj1.db.dict["key2"].hidden_obj, self.dbobj2)

    def test_dbobj_hidden_defaultdict(self):
        con1 = _ValidContainer(self.dbobj2)
        con2 = _ValidContainer(self.dbobj2)

        self.dbobj1.db.dfdict = defaultdict(dict)

        self.dbobj1.db.dfdict["key"]["con1"] = con1
        self.dbobj1.db.dfdict["key"]["con2"] = con2

        self.assertEqual(self.dbobj1.db.dfdict["key"]["con1"].hidden_obj, self.dbobj2)

        self.assertEqual(self.dbobj1.db.dfdict["key"]["con1"].hidden_obj, self.dbobj2)
        self.assertEqual(self.dbobj1.db.dfdict["key"]["con2"].hidden_obj, self.dbobj2)
        self.assertEqual(self.dbobj1.db.dfdict["key"]["con2"].hidden_obj, self.dbobj2)


_PACKED_DBOBJ = ("__packed_dbobj__", ("objects", "objectdb"), "2025:01:01-12:00:00:000000", 5)
_PACKED_SESSION = ("__packed_session__", "sessid1", 1718029445.12345)


class _CustomClass:
    pass


class _StrSubclass(str):
    pass


class _ListSubclass(list):
    pass


class _DictSubclass(dict):
    pass


class TestJsonCodec(SimpleTestCase):
    """
    Test the to_jsonable/from_jsonable codec converting between the
    pickle-intermediate form and pure-JSON structures with sentinel keys.

    """

    def _roundtrip(self, value):
        encoded = dbserialize.to_jsonable(value)
        # must be strict JSON (no NaN, no non-JSON types)
        json.dumps(encoded, allow_nan=False)
        decoded = dbserialize.from_jsonable(encoded)
        self.assertEqual(decoded, value)
        return decoded

    @parameterized.expand(
        [
            ("none", None),
            ("true", True),
            ("false", False),
            ("int", 42),
            ("negative_int", -5),
            ("big_int", 2**70),
            ("float", 1.5),
            ("str", "text"),
            ("unicode", "snölik ✓"),
            ("empty_str", ""),
            ("list", [1, "a", [2, 3]]),
            ("dict", {"a": 1, "b": {"c": [1]}}),
            ("empty_list", []),
            ("empty_dict", {}),
        ]
    )
    def test_roundtrip_plain_json_types(self, _, value):
        self.assertEqual(dbserialize.to_jsonable(value), value)
        self._roundtrip(value)

    @parameterized.expand(
        [
            ("tuple", (1, 2)),
            ("empty_tuple", ()),
            ("nested_tuple_in_dict", {"pos": (1, 2)}),
            ("tuple_in_list", [(1, "a"), (2, "b")]),
            ("set", {1, 2, 3}),
            ("empty_set", set()),
            ("frozenset", frozenset((1, 2))),
            ("set_of_tuples", {(1, 2), (3, 4)}),
            ("deque", deque(("a", "b"))),
            ("deque_maxlen", deque((1, 2), maxlen=5)),
            ("datetime_naive", datetime(2025, 6, 10, 12, 30, 45, 123456)),
            ("datetime_aware", datetime(2025, 6, 10, 12, 30, tzinfo=timezone.utc)),
            ("datetime_offset", datetime(2025, 6, 10, tzinfo=timezone(timedelta(hours=5)))),
            ("date", date(2025, 6, 10)),
            ("time", time(12, 30, 45, 1)),
            ("odict", OrderedDict([("b", 2), ("a", 1)])),
        ]
    )
    def test_roundtrip_sentinel_types(self, _, value):
        decoded = self._roundtrip(value)
        self.assertIs(type(decoded), type(value))

    def test_roundtrip_preserves_container_details(self):
        decoded = self._roundtrip(deque((1, 2), maxlen=5))
        self.assertEqual(decoded.maxlen, 5)
        decoded = self._roundtrip(deque((1, 2)))
        self.assertIsNone(decoded.maxlen)
        decoded = self._roundtrip(OrderedDict([("b", 2), ("a", 1)]))
        self.assertEqual(list(decoded.items()), [("b", 2), ("a", 1)])

    def test_roundtrip_packed_dbobj(self):
        decoded = self._roundtrip(_PACKED_DBOBJ)
        self.assertTrue(dbserialize._IS_PACKED_DBOBJ(decoded))
        # the ContentType natural key must come back as a tuple (model-map key)
        self.assertIs(type(decoded[1]), tuple)

    def test_roundtrip_packed_session(self):
        decoded = self._roundtrip(_PACKED_SESSION)
        self.assertTrue(dbserialize._IS_PACKED_SESSION(decoded))

    def test_roundtrip_deeply_nested(self):
        value = {
            "chars": [_PACKED_DBOBJ],
            "pos": (1, 2),
            "tags": {("a", "b")},
            "when": datetime(2025, 6, 10),
            "meta": {"flat": [1.5, None, True]},
        }
        self._roundtrip(value)

    @parameterized.expand(
        [
            ("bytes", b"bytes"),
            ("nan", float("nan")),
            ("inf", float("inf")),
            ("neg_inf", float("-inf")),
            ("nul_in_str", "with\x00nul"),
            ("nul_in_key", {"k\x00ey": 1}),
            ("int_key", {1: "a"}),
            ("bool_key", {True: "a"}),
            ("tuple_key", {(1, 2): "a"}),
            ("sentinel_collision", {"__tuple__": [1]}),
            ("sentinel_collision_dbobj", {"__dbobj__": 1}),
            ("defaultdict", defaultdict(list)),
            ("custom_class", _CustomClass()),
            ("safestring", SafeString("marked")),
            ("str_subclass", _StrSubclass("sub")),
            ("list_subclass", _ListSubclass([1])),
            ("dict_subclass", _DictSubclass(a=1)),
        ]
    )
    def test_not_jsonable(self, _, value):
        with self.assertRaises(dbserialize.NotJSONSerializable):
            dbserialize.to_jsonable(value)
        # the same trigger nested deep inside a structure
        with self.assertRaises(dbserialize.NotJSONSerializable):
            dbserialize.to_jsonable([1, {"a": [value]}])

    def test_multi_key_dict_with_sentinel_key_rejected(self):
        # a sentinel key among others must also trigger fallback
        with self.assertRaises(dbserialize.NotJSONSerializable):
            dbserialize.to_jsonable({"__set__": [1], "other": 2})


class TestAttributeStorageHelpers(SimpleTestCase):
    """
    Test the storage-field builder and the dual-column unpack/query helpers.

    """

    def test_storage_fields_json(self):
        fields = dbserialize.attribute_storage_fields([1, (2, 3)])
        self.assertEqual(
            fields,
            {
                "db_value": None,
                "db_json": [1, {"__tuple__": [2, 3]}],
                "db_storage_type": "json",
            },
        )

    def test_storage_fields_pickle_fallback(self):
        fields = dbserialize.attribute_storage_fields(b"raw")
        self.assertEqual(
            fields,
            {"db_value": b"raw", "db_json": None, "db_storage_type": "pickle"},
        )

    def test_storage_fields_none(self):
        fields = dbserialize.attribute_storage_fields(None)
        self.assertEqual(
            fields,
            {"db_value": None, "db_json": None, "db_storage_type": "pickle"},
        )

    def test_storage_to_intermediate(self):
        self.assertEqual(
            dbserialize.storage_to_intermediate("json", None, [1, {"__tuple__": [2, 3]}]),
            [1, (2, 3)],
        )
        self.assertEqual(
            dbserialize.storage_to_intermediate("pickle", b"raw", None),
            b"raw",
        )
        self.assertIsNone(dbserialize.storage_to_intermediate("pickle", None, None))

    def test_attr_value_q_jsonable(self):
        self.assertEqual(
            dbserialize.attr_value_q(5, prefix="db_attributes"),
            Q(db_attributes__db_value=5) | Q(db_attributes__db_json=5),
        )
        self.assertEqual(
            dbserialize.attr_value_q([1, (2, 3)]),
            Q(db_value=[1, (2, 3)]) | Q(db_json=[1, {"__tuple__": [2, 3]}]),
        )

    def test_attr_value_q_pickle_only(self):
        self.assertEqual(
            dbserialize.attr_value_q(b"raw", prefix="attribute"),
            Q(attribute__db_value=b"raw"),
        )
        self.assertEqual(dbserialize.attr_value_q(None), Q(db_value=None))
