"""Measure the full PIN check of Smart Service Alarm on this machine.

Standalone: needs only Python 3 (no Home Assistant). The integration hashes
the given code for every stored user, each hash in its own executor thread,
so the time of one check is the "parallel" figure below; "sequential" is
shown for comparison (one core).

Usage:
    python3 tools/bench_scrypt.py            # 8 users, 5 rounds
    python3 tools/bench_scrypt.py --users 4 --rounds 10

The parameters must match SCRYPT_* in custom_components/smartservice_alarm/pins.py.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import os
import platform
import secrets
import statistics
import time

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16


def derive(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        pin.encode(),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=128 * SCRYPT_R * (SCRYPT_N + SCRYPT_P + 2) + 2**20,
    )


def make_users(count: int) -> list[tuple[bytes, bytes]]:
    users = []
    for index in range(count):
        salt = secrets.token_bytes(SALT_BYTES)
        users.append((salt, derive(f"{2580 + index * 7:04d}", salt)))
    return users


def check_sequential(users: list[tuple[bytes, bytes]], pin: str) -> int:
    return sum(hmac.compare_digest(derive(pin, salt), digest) for salt, digest in users)


def check_parallel(
    pool: ThreadPoolExecutor, users: list[tuple[bytes, bytes]], pin: str
) -> int:
    futures = [pool.submit(derive, pin, salt) for salt, _ in users]
    return sum(
        hmac.compare_digest(future.result(), digest)
        for future, (_, digest) in zip(futures, users, strict=True)
    )


def measure(function, rounds: int) -> list[float]:
    times = []
    for _ in range(rounds):
        start = time.perf_counter()
        function()
        times.append(time.perf_counter() - start)
    return times


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()

    users = make_users(args.users)
    print(f"Machine: {platform.machine()} {platform.processor() or ''}".rstrip())
    print(f"Python {platform.python_version()}, CPUs: {os.cpu_count()}")
    print(f"scrypt n={SCRYPT_N} r={SCRYPT_R} p={SCRYPT_P}, users: {args.users}")

    sequential = measure(lambda: check_sequential(users, "9999"), args.rounds)
    with ThreadPoolExecutor(max_workers=max(1, args.users)) as pool:
        parallel = measure(lambda: check_parallel(pool, users, "9999"), args.rounds)

    for label, times in (("sequential", sequential), ("parallel", parallel)):
        print(
            f"{label:>10}: median {statistics.median(times):.3f} s, "
            f"max {max(times):.3f} s"
        )
    print(f"Full check (as the integration does it): {statistics.median(parallel):.3f} s")


if __name__ == "__main__":
    main()
