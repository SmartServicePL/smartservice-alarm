"""PIN hashes and lockouts of Smart Service Alarm.

A PIN is never stored or logged. Only a scrypt hash with a random salt per
user is kept in the integration's own storage file. Every code check hashes
the given code for every stored user and compares all results, so the work
does not depend on whose PIN it is, or whether it is anybody's.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta
import hashlib
import hmac
from itertools import pairwise
import re
import secrets
from typing import Any

from homeassistant.components.alarm_control_panel import DOMAIN as ALARM_DOMAIN
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import events
from .const import ACTION_LOCKOUT, ACTION_WRONG_CODE, DOMAIN, STORAGE_VERSION

# Production scrypt parameters for new PINs. Each stored PIN keeps the
# parameters it was hashed with, so raising them later does not break
# existing PINs. Tests lower them to stay fast.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16

PIN_PATTERN = re.compile(r"[0-9]{4,8}")

MAX_FAILURES = 5
LOCK_BASE_SECONDS = 60
LOCK_MAX_SECONDS = 900
_MAX_LEVEL = 16

NO_ACCOUNT = "_bez_konta"

KEY_PINS = "piny"
KEY_LOCKOUTS = "blokady"
KEY_STATE = "stan"


def alarm_error(key: str, **placeholders: str) -> ServiceValidationError:
    """Error shown 1:1 to the person who called the action."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


def bucket_for(user_id: str | None) -> str:
    """Lockout bucket of the calling account."""
    return user_id or NO_ACCOUNT


def pin_problem(pin: Any) -> str | None:
    """Return the translation key of a broken PIN rule, or None."""
    if not isinstance(pin, str) or PIN_PATTERN.fullmatch(pin) is None:
        return "pin_format"
    steps = {(int(b) - int(a)) % 10 for a, b in pairwise(pin)}
    if steps in ({0}, {1}, {9}):
        # Same digit repeated, or an ascending / descending run (also 7890).
        return "pin_trivial"
    return None


def scrypt_hash(pin: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    """Derive the scrypt hash of a PIN."""
    return hashlib.scrypt(
        pin.encode(),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=dklen,
        maxmem=128 * r * (n + p + 2) + 2**20,
    )


def new_record(pin: str, changed: datetime) -> dict[str, Any]:
    """Storage record of a PIN: salt, hash and the parameters used."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = scrypt_hash(pin, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
    return {
        "salt": base64.b64encode(salt).decode(),
        "hash": base64.b64encode(digest).decode(),
        "n": SCRYPT_N,
        "r": SCRYPT_R,
        "p": SCRYPT_P,
        "zmieniono": changed.isoformat(),
    }


def record_matches(record: dict[str, Any], pin: str) -> bool:
    """Hash the PIN with the record's salt and compare in constant time."""
    expected = base64.b64decode(record["hash"])
    actual = scrypt_hash(
        pin,
        base64.b64decode(record["salt"]),
        int(record["n"]),
        int(record["r"]),
        int(record["p"]),
        len(expected),
    )
    return hmac.compare_digest(actual, expected)


def lock_seconds(level: int) -> int:
    """Length of the n-th lockout: 60, 120, 240, 480, then 900 seconds."""
    level = max(1, min(level, _MAX_LEVEL))
    return min(LOCK_BASE_SECONDS * 2 ** (level - 1), LOCK_MAX_SECONDS)


class LockoutBook:
    """Wrong-code counters per calling account (plain dict, stored as is)."""

    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self.data = data

    def locked_until(self, bucket: str, now: datetime) -> datetime | None:
        """End of an active lockout of the account, or None."""
        until = (self.data.get(bucket) or {}).get("do")
        if until is None:
            return None
        end = dt_util.parse_datetime(until)
        if end is None or end <= now:
            return None
        return end

    def register_failure(
        self, bucket: str, now: datetime
    ) -> tuple[int, datetime | None]:
        """Count a wrong code; return the attempt number and a new lockout end."""
        entry = self.data.setdefault(bucket, {"nieudane": 0, "poziom": 0, "do": None})
        attempt = int(entry.get("nieudane", 0)) + 1
        if attempt < MAX_FAILURES:
            entry["nieudane"] = attempt
            return attempt, None
        level = int(entry.get("poziom", 0)) + 1
        until = now + timedelta(seconds=lock_seconds(level))
        entry.update({"nieudane": 0, "poziom": min(level, _MAX_LEVEL), "do": until.isoformat()})
        return attempt, until

    def reset(self, bucket: str) -> bool:
        """Correct code: forget the account's wrong codes and lockout level."""
        return self.data.pop(bucket, None) is not None

    def unlock(self, bucket: str) -> bool:
        """Administrator unlock: same as a reset."""
        return self.reset(bucket)


def lockout_error(until: datetime) -> ServiceValidationError:
    """Lockout message with the local time from which a new try is possible."""
    local = dt_util.as_local(until)
    if local.second or local.microsecond:
        # Round up so that a retry at the shown minute is never still locked.
        local = local.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return alarm_error("locked_out", godzina=local.strftime("%H:%M"))


class PinManager:
    """PINs, lockouts and the persisted panel state of one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}",
            private=True,
            atomic_writes=True,
        )
        self._data: dict[str, Any] = {KEY_PINS: {}, KEY_LOCKOUTS: {}, KEY_STATE: {}}
        self._lock = asyncio.Lock()

    @property
    def pins(self) -> dict[str, dict[str, Any]]:
        return self._data[KEY_PINS]

    @property
    def lockouts(self) -> dict[str, dict[str, Any]]:
        return self._data[KEY_LOCKOUTS]

    @property
    def state(self) -> dict[str, Any]:
        """Persisted alarm panel state (no PIN data)."""
        return self._data[KEY_STATE]

    @property
    def book(self) -> LockoutBook:
        return LockoutBook(self.lockouts)

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            for key in (KEY_PINS, KEY_LOCKOUTS, KEY_STATE):
                if isinstance(stored.get(key), dict):
                    self._data[key] = stored[key]

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    async def async_remove(self) -> None:
        await self._store.async_remove()

    def remove_unknown_users(self, known: set[str]) -> bool:
        """Drop PINs and lockouts of deleted users."""
        changed = False
        for user_id in list(self.pins):
            if user_id not in known:
                del self.pins[user_id]
                changed = True
        for bucket in list(self.lockouts):
            if bucket != NO_ACCOUNT and bucket not in known:
                del self.lockouts[bucket]
                changed = True
        return changed

    def has_pin(self, user_id: str) -> bool:
        return user_id in self.pins

    def locked_until(self, bucket: str) -> datetime | None:
        return self.book.locked_until(bucket, dt_util.utcnow())

    def _entity_id(self) -> str | None:
        return er.async_get(self.hass).async_get_entity_id(
            ALARM_DOMAIN, DOMAIN, self.entry_id
        )

    async def _async_owners(self, pin: str) -> list[str]:
        """Users whose PIN equals the given one; hashes every stored PIN."""
        records = list(self.pins.items())
        results = await asyncio.gather(
            *(
                self.hass.async_add_executor_job(record_matches, record, pin)
                for _, record in records
            )
        )
        return [user_id for (user_id, _), ok in zip(records, results, strict=True) if ok]

    def _raise_if_locked(self, bucket: str) -> None:
        if (until := self.locked_until(bucket)) is not None:
            raise lockout_error(until)

    async def _async_fail(
        self, bucket: str, key: str, context: Context | None
    ) -> ServiceValidationError:
        """Count a failed attempt, log it and return the error to raise."""
        attempt, until = self.book.register_failure(bucket, dt_util.utcnow())
        await self.async_save()
        caller = None if bucket == NO_ACCOUNT else bucket
        entity_id = self._entity_id()
        await events.async_fire(
            self.hass,
            entity_id,
            ACTION_WRONG_CODE,
            context,
            caller_id=caller,
            proby=attempt,
            limit=MAX_FAILURES,
        )
        if until is not None:
            await events.async_fire(
                self.hass,
                entity_id,
                ACTION_LOCKOUT,
                context,
                caller_id=caller,
                do=until.isoformat(),
            )
            return lockout_error(until)
        return alarm_error(key)

    async def async_check_code(
        self, bucket: str, code: str, context: Context | None
    ) -> str:
        """Return the owner of the code or raise; counts wrong codes."""
        async with self._lock:
            self._raise_if_locked(bucket)
            owners = await self._async_owners(code)
            if len(owners) == 1:
                if self.book.reset(bucket):
                    await self.async_save()
                return owners[0]
            raise await self._async_fail(bucket, "wrong_pin", context)

    async def async_set_pin(
        self,
        target_id: str,
        pin: str,
        *,
        admin: bool,
        bucket: str,
        current_pin: str | None,
        context: Context | None,
    ) -> None:
        """Set a PIN after checking rules, the current PIN and uniqueness.

        For a normal user a wrong current PIN and a collision with somebody
        else's PIN both count as a failed attempt, so set_pin cannot be used
        to find out other people's PINs. An administrator's collision is
        refused but not counted.
        """
        async with self._lock:
            if not admin:
                self._raise_if_locked(bucket)
            if (problem := pin_problem(pin)) is not None:
                raise alarm_error(problem)
            check_current = not admin and target_id in self.pins
            if check_current and not current_pin:
                raise alarm_error("current_pin_required")

            jobs = [self._async_owners(pin)]
            if check_current:
                jobs.append(
                    self.hass.async_add_executor_job(
                        record_matches, self.pins[target_id], current_pin
                    )
                )
            results = await asyncio.gather(*jobs)
            owners: list[str] = results[0]

            if check_current and not results[1]:
                raise await self._async_fail(bucket, "wrong_current_pin", context)
            if any(owner != target_id for owner in owners):
                if admin:
                    raise alarm_error("pin_taken")
                raise await self._async_fail(bucket, "pin_taken", context)

            record = await self.hass.async_add_executor_job(
                new_record, pin, dt_util.now()
            )
            self.pins[target_id] = record
            await self.async_save()

    async def async_clear_pin(self, user_id: str) -> bool:
        async with self._lock:
            if self.pins.pop(user_id, None) is None:
                return False
            await self.async_save()
            return True

    async def async_unlock(self, bucket: str) -> bool:
        async with self._lock:
            if not self.book.unlock(bucket):
                return False
            await self.async_save()
            return True
