#!/usr/bin/env python3
"""Stub out the FDE (cryptfs) API that partition.cpp still calls.

TWRP's bootable/recovery/partition.cpp calls set_partition_data(),
cryptfs_check_footer(), cryptfs_get_password_type() and delete_crypto_blk_dev()
whenever TW_INCLUDE_CRYPTO is set. Those came from vold's cryptfs.h, which at
android-14.1 only keeps cryptfs_setup_ext_volume() and cryptfs_get_keygen() --
AOSP removed full-disk encryption years ago and TeamWin's fork followed.

chopin is FBE + metadata encryption (fileencryption=aes-256-xts:...:v2+
inlinecrypt_optimized, keydirectory=/metadata/vold/metadata_encryption), so no
code path here ever wants FDE. Rather than resurrect a whole FDE stack, give the
calls inert stubs: the FBE paths that actually get used are untouched.

Return values are chosen so the dead FDE branches behave like "this device has
no crypto footer" rather than pretending to decrypt something.
"""

import pathlib
import re
import sys

STUB = '''
/* Added by fix_fde.py: vold android-14.1 stopped exporting the FDE/cryptfs API
 * this file still calls. chopin is FBE + metadata-encryption only, so every FDE
 * branch below is dead code here; inert stubs keep it compiling. */
static __attribute__((unused)) int set_partition_data(const char *, const char *) { return -1; }
static __attribute__((unused)) int cryptfs_check_footer(void) { return -1; }
static __attribute__((unused)) int cryptfs_get_password_type(void) { return -1; }
static __attribute__((unused)) int delete_crypto_blk_dev(char *) { return 0; }
'''

RECOVERY = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
target = RECOVERY / "partition.cpp"

text = target.read_text()

if "Added by fix_fde.py" in text:
    print("partition.cpp: already stubbed")
    sys.exit(0)

for symbol in ("set_partition_data", "cryptfs_check_footer",
               "cryptfs_get_password_type", "delete_crypto_blk_dev"):
    if symbol not in text:
        print("ERROR: %s not found in partition.cpp - upstream changed" % symbol,
              file=sys.stderr)
        sys.exit(1)

anchor = re.search(r'^[ \t]*#include "Decrypt\.h"\n#endif\n', text, re.MULTILINE)
if anchor is None:
    print("ERROR: could not find the TW_INCLUDE_CRYPTO include block",
          file=sys.stderr)
    sys.exit(1)

text = text[:anchor.end()] + STUB + text[anchor.end():]
target.write_text(text)

first_use = text.find("set_partition_data(")
if first_use < text.find("Added by fix_fde.py"):
    print("ERROR: stubs landed after first use", file=sys.stderr)
    sys.exit(1)

print("partition.cpp: FDE stubs inserted")
