"""
Cmdset gather cache.

This module implements the in-memory cache used by
`evennia.commands.cmdhandler.get_and_merge_cmdsets` to avoid re-gathering
cmdsets from the caller's surroundings on every command input (controlled by
`settings.CMDSET_GATHER_CACHE`).

Without the cache, every command input walks the caller's location contents
and inventory, checks the 'call' lock on each object, calls their
`at_cmdset_get` hooks and collects their cmdset stacks. With the cache, the
result of that gather (an ordered sequence of cmdset 'segments') is stored on
the calling entity and reused until an engine event invalidates it.

Invalidation is lazy, via monotonic version counters: engine events (cmdset
changes, movement, lock/permission changes, puppeting etc) bump an in-memory
counter on the affected entity and/or its location. A cached gather records a
'version vector' - the counter values of every entity it depends on (the
cmdset providers plus the puppet's location) - and is discarded when any of
them has changed. Events are thereby O(1); no audience bookkeeping is needed,
since every local contributor to a gather is located either in the caller's
location or in the caller's inventory, both of which are part of the vector.

A module-global epoch counter handles bulk invalidation (e.g. idmapper cache
flushes) - bumping it via `invalidate_all` discards every cached gather at
once.

All state is plain in-memory attributes (`_cmdset_cache_version` and
`_cmdset_gather_cache`); nothing is persisted, so caches naturally die with
the entity or on server reload.

"""

# global epoch; bumping it invalidates all cached gathers at once
_EPOCH = 0

# max cached gathers stored per calling entity; oldest evicted first
_MAX_CACHE_ENTRIES = 8


def get_epoch():
    """
    Get the current global cache epoch.

    Returns:
        int: The current epoch. Cached gathers built under an older epoch are
            invalid.

    """
    return _EPOCH


def invalidate_all():
    """
    Invalidate every cached gather globally by bumping the epoch.

    Used for bulk operations where per-entity invalidation is impractical,
    such as flushing the idmapper cache.

    """
    global _EPOCH
    _EPOCH += 1


def get_version(entity):
    """
    Get an entity's current cache-version counter.

    Args:
        entity (any): Session, Account or Object. May be `None`.

    Returns:
        int: The entity's version counter (0 if never bumped or `None`).

    """
    return getattr(entity, "_cmdset_cache_version", 0)


def invalidate(entity):
    """
    Invalidate cached gathers depending on this entity by bumping its
    version counter.

    Args:
        entity (any): Session, Account or Object. `None` is a no-op.

    Notes:
        This is called from engine internals (movement, cmdset/lock changes
        etc) and must never raise; entities that cannot hold plain attributes
        are silently skipped (such entities cannot hold caches either).

    """
    if entity is None:
        return
    try:
        entity._cmdset_cache_version = getattr(entity, "_cmdset_cache_version", 0) + 1
    except Exception:
        pass


def invalidate_neighborhood(obj):
    """
    Invalidate cached gathers depending on this object or on its location.

    This is the standard event hook: a change to `obj` can affect the gathers
    of `obj` itself, of whoever holds it, and of everyone sharing its
    location - all of which have either `obj` or `obj.location` in their
    version vector.

    Args:
        obj (any): The changed entity. `None` is a no-op.

    """
    invalidate(obj)
    try:
        location = obj.location
    except Exception:
        location = None
    invalidate(location)


def is_dynamic(obj):
    """
    Check if an entity opts out of gather caching.

    Args:
        obj (any): Session, Account or Object.

    Returns:
        bool: `True` if the entity's class sets `cmdset_dynamic = True`,
            marking its cmdset contribution ('call' lock, `at_cmdset_get`
            hook and stack) as needing re-evaluation on every command input.

    """
    return bool(getattr(obj, "cmdset_dynamic", False))


def snapshot_vector(providers, location):
    """
    Snapshot the version vector for a gather.

    Args:
        providers (list): The sorted cmdset providers (session/account/object).
        location (Object or None): The object-provider's location, if any.

    Returns:
        tuple: Pairs of `(entity, version)` for each provider plus the
            location.

    """
    entities = list(providers)
    if location is not None:
        entities.append(location)
    return tuple((entity, get_version(entity)) for entity in entities)


def vectors_equal(vector_a, vector_b):
    """
    Compare two version vectors for identity and version equality.

    Args:
        vector_a (tuple): Vector of `(entity, version)` pairs.
        vector_b (tuple): Vector of `(entity, version)` pairs.

    Returns:
        bool: `True` if both vectors reference the same entity instances with
            the same versions.

    """
    return len(vector_a) == len(vector_b) and all(
        entity_a is entity_b and version_a == version_b
        for (entity_a, version_a), (entity_b, version_b) in zip(vector_a, vector_b)
    )


class CachedGather:
    """
    A cached cmdset gather for one calling entity and provider chain.

    The gather is stored as ordered segments preserving the original gather
    order:

    - `("provider", (cmdset, ...))` - a provider's own cmdset stack.
    - `("local", (cmdset, ...))` - cmdsets from static local objects (room
      contents, inventory and the location itself), stored with their
      `duplicates` flags in their restored state.
    - `("dynamic", obj)` - a local object with `cmdset_dynamic = True`, whose
      contribution is re-evaluated on every input.

    Segments hold references to live cmdsets, never copies; merge-level
    changes are picked up via the per-cmdset fingerprints, which are
    recomputed from the segments on every input.

    """

    __slots__ = ("epoch", "providers", "location", "vector", "segments", "no_objs")

    def __init__(self, epoch, providers, location, vector, segments, no_objs=None):
        """
        Initialize the cached gather.

        Args:
            epoch (int): The global epoch at build start.
            providers (tuple): The provider instances, identity-compared on
                validation.
            location (Object or None): The object-provider's location at
                build time, identity-compared on validation.
            vector (tuple): `(entity, version)` pairs from `snapshot_vector`.
            segments (tuple): Ordered gather segments (see class docstring).
            no_objs (bool or None): The object-provider's `no_objs` gate value
                recorded at build time.

        """
        self.epoch = epoch
        self.providers = providers
        self.location = location
        self.vector = vector
        self.segments = segments
        self.no_objs = no_objs


def _cache_key(providers):
    """
    Build the cache key for a provider chain.

    Args:
        providers (list): The sorted cmdset providers.

    Returns:
        tuple: Identity-based key. Stale keys from replaced instances are
            evicted by the per-entity entry cap.

    """
    return tuple(id(provider) for provider in providers)


def _object_provider(providers):
    """
    Find the object-type provider in a provider chain.

    Args:
        providers (list): The sorted cmdset providers.

    Returns:
        Object or None: The provider with `cmdset_provider_type == "object"`.

    """
    for provider in providers:
        if getattr(provider, "cmdset_provider_type", None) == "object":
            return provider
    return None


def get_cached(holder, providers):
    """
    Fetch and validate a cached gather.

    Args:
        holder (Session, Account or Object): The calling entity holding the
            cache.
        providers (list): The current sorted cmdset providers.

    Returns:
        CachedGather or None: The cached gather if still valid, else `None`.
            Validation rejects on epoch change, any provider instance being
            replaced, the object-provider's location having changed, or any
            entity in the version vector having been bumped.

    """
    cache = getattr(holder, "_cmdset_gather_cache", None)
    if not cache:
        return None
    cached = cache.get(_cache_key(providers))
    if cached is None or cached.epoch != _EPOCH:
        return None
    if len(cached.providers) != len(providers) or any(
        stored is not current for stored, current in zip(cached.providers, providers)
    ):
        return None
    obj_provider = _object_provider(providers)
    try:
        location = obj_provider.location if obj_provider is not None else None
    except Exception:
        return None
    if location is not cached.location:
        return None
    if any(get_version(entity) != version for entity, version in cached.vector):
        return None
    return cached


def store_cached(holder, providers, cached):
    """
    Store a cached gather on the calling entity.

    Args:
        holder (Session, Account or Object): The calling entity to hold the
            cache.
        providers (list): The sorted cmdset providers (cache key source).
        cached (CachedGather): The gather to store.

    Notes:
        The per-holder cache is a plain dict capped at `_MAX_CACHE_ENTRIES`
        entries, evicting oldest-stored first. Entities that cannot hold
        plain attributes are silently skipped.

    """
    cache = getattr(holder, "_cmdset_gather_cache", None)
    if cache is None:
        cache = {}
        try:
            holder._cmdset_gather_cache = cache
        except Exception:
            return
    key = _cache_key(providers)
    cache.pop(key, None)
    cache[key] = cached
    while len(cache) > _MAX_CACHE_ENTRIES:
        del cache[next(iter(cache))]
