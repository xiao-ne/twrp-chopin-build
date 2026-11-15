#!/usr/bin/env python3
"""Neutralise libtar's fscrypt code on TWRP 14.1.

libtar (TeamWin/android_bootable_recovery @ android-14.1) calls
get_policy_descriptor(), get_policy_size(), get_policy(), get_policy_content()
and fscrypt_policy_size(). None of them exist any more: android-14.1 of
TeamWin/android_system_vold only keeps fscrypt_is_native(), bytes_to_hex(),
fscrypt_set_mode() and fscrypt_policy_{get,set}_struct(). The `fscrypt_policy`
typedef is gone as well, so even the struct member stops compiling.

So the tar side of fscrypt cannot be built on this branch at all. Drop the code
instead of inventing a replacement: backups stop storing per-directory fscrypt
policies, everything else (unlock, mount, flash) is unaffected.

Two constraints, both learned the hard way:

  * `#undef USE_FSCRYPT` has to come AFTER internal.h pulls in libtar.h, so
    `struct tar_header` keeps its `fep` member and libtar.so and the recovery
    binary still agree on the layout. Undef'ing at line 1 (the previous hack)
    made the struct 8 bytes shorter inside libtar and shifted every field after
    `fep` -- has_cap_data, cap_data, h, th_pathname -- in those translation
    units, which corrupts memory at runtime instead of failing the build.

  * libtar.h's `fscrypt_policy *fep` needs a type that still exists, because
    recovery's TUs do compile that member (`-DUSE_FSCRYPT` reaches them through
    TW_INCLUDE_CRYPTO in bootable/recovery/Android.mk).
"""

import pathlib
import re
import sys

LIBTAR = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".") / "libtar"

problems = []

header = LIBTAR / "libtar.h"
text = header.read_text()
text, n = re.subn(r"fscrypt_policy\s+\*fep;", "struct fscrypt_policy_v1 *fep;", text)
if n != 1:
    problems.append("libtar.h: expected 1 'fscrypt_policy *fep;', patched %d" % n)
header.write_text(text)

patched = 0
for source in sorted(LIBTAR.glob("*.c")):
    text = source.read_text()
    if "#undef USE_FSCRYPT" in text:
        continue
    if re.search(r"^#include\s+<internal\.h>\n", text, re.MULTILINE) is None:
        continue
    text, n = re.subn(
        r"^(#include\s+<internal\.h>\n)",
        r"\1\n#undef USE_FSCRYPT /* vold dropped the API libtar calls; see fix_fscrypt.py */\n",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n != 1:
        problems.append("%s: anchor matched but substitution failed" % source.name)
        continue
    source.write_text(text)
    patched += 1

print("libtar.h: fep typed")
print("sources patched:", patched)

if patched == 0:
    problems.append("no libtar source needed patching - did upstream change?")

if problems:
    for p in problems:
        print("ERROR:", p, file=sys.stderr)
    sys.exit(1)
