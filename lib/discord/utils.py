import inspect
import random
from datetime import datetime, timedelta
import zlib
import re
import secrets


__all__ = (
    "base36_dumps",
    "base36_loads",
    "unique_id",
    "timestamp_from_id",
    "iterable_get",
    "datetime_to_string",
    "timedelta_to_string",
    "string_to_timedelta",
    "time_units",
    "secure_id",
    "single_async_yield"
)


base36 = '0123456789abcdefghijklmnopqrstuvwxyz'


def base36_dumps(number: int):
    if number < 0:
        return '-' + base36_dumps(-number)

    value = ''

    while number != 0:
        number, index = divmod(number, len(base36))
        value = base36[index] + value

    return value or '0'


def base36_loads(value):
    return int(value, len(base36))


def unique_id():
    """
    Generates a unique id consisting of the the unix timestamp and 8 random bits
    """
    unix_t = int(datetime.utcnow().timestamp() * 1000)
    result = (unix_t << 8) | random.getrandbits(8)
    return base36_dumps(result)


def timestamp_from_id(uid):
    return datetime.utcfromtimestamp((base36_loads(uid) >> 8) / 1000)


def secure_id():
    return secrets.token_urlsafe(64)


def chunk_blob(blob: bytes, size_limit=7000000):
    """
    Chunk bytes into up to 256 chunks with size of up to 'size_limit' bytes
    """
    compressed = bytearray(zlib.compress(blob))
    chunks = []

    chunk_number = 0
    while len(compressed) > size_limit:
        chunk = compressed[:size_limit]
        compressed = compressed[size_limit:]

        chunk.insert(0, chunk_number)
        chunks.append(bytes(chunk))

        chunk_number += 1

    if len(compressed) > 0:
        compressed.insert(0, chunk_number)
        chunks.append(bytes(compressed))

    return chunks


def combine_chunks(chunks):
    sorted_chunks = sorted([bytearray(c) for c in chunks], key=lambda c: c[0])
    result = bytearray()
    for chunk in sorted_chunks:
        result.extend(chunk[1:])

    return zlib.decompress(bytes(result))


def iterable_get(iterable, **kwargs):
    for item in iterable:
        for key, value in kwargs.items():
            if getattr(item, key) != value:
                break

        else:
            return item

    return None


def datetime_to_string(dt: datetime):
    return dt.strftime("%d. %b %Y - %H:%M")


time_units = (
    (("w", "week", "weeks"), 7 * 24 * 60 * 60),
    (("d", "day", "days"), 24 * 60 * 60),
    (("h", "hour", "hours"), 60 * 60),
    (("m", "min", "minute", "minutes"), 60),
    (("s", "second", "seconds"), 1)
)


def timedelta_to_string(td: timedelta, precision="s"):
    seconds = td.total_seconds()
    if seconds == 0:
        return "0 seconds"

    result = ""
    for names, mp in time_units:
        count, seconds = divmod(seconds, mp)
        count = int(count)
        if count > 0:
            result += f", {count} {names[-2] if count == 1 else names[-1]}"

        if precision in names:
            break

    return result.strip(" ,")


def string_to_timedelta(string):
    def get_multiplier(name):
        for names, mp in time_units:
            if name in names:
                return mp

        raise ValueError

    parts = string.split(" ")
    seconds = 0
    i = 0
    while i < len(parts):
        part = parts[i]
        if re.match(r"^[0-9]+$", part):
            try:
                count = max(int(part), 0)
                unit = parts[i + 1]
                mp = get_multiplier(unit)
                seconds += count * mp
            except (ValueError, IndexError):
                i += 1
            else:
                i += 2

        else:
            try:
                count, unit = int(part[:-1]), part[-1]
                mp = get_multiplier(unit)
                seconds += count * mp
            except (ValueError, IndexError):
                pass
            finally:
                i += 1

    return timedelta(seconds=seconds)


async def single_async_yield(item):
    if inspect.isawaitable(item):
        yield await item
    else:
        yield item
