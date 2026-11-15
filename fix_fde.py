#!/usr/bin/env python3
"""Stub out the FDE (cryptfs) API that TeamWin's recovery still calls.

partition.cpp and partitionmanager.cpp call into the old full-disk-encryption
API -- set_partition_data, cryptfs_check_footer, cryptfs_get_password_type,
cryptfs_check_passwd, delete_crypto_blk_dev. Those came from vold's cryptfs.h,
which at android-14.1 keeps only cryptfs_setup_ext_volume() and
cryptfs_get_keygen(): AOSP deleted full-disk encryption and TeamWin's fork
followed. Both files guard the calls with nothing more than TW_INCLUDE_CRYPTO,
so every FBE build hits them.

chopin is FBE + metadata encryption (fileencryption=aes-256-xts:...:v2+
inlinecrypt_optimized, keydirectory=/metadata/vold/metadata_encryption). The FBE
paths live in the TW_IS_FBE branches and return before any of this runs, so the
FDE code is dead here. Inert stubs keep it compiling; nothing that actually runs
is touched.

The stubs report failure on purpose: "no crypto footer", "unknown password
type", "wrong password". A device with FDE would fail to decrypt instead of
silently pretending it succeeded.

Symbols audited against TeamWin/android_system_vold @ android-14.1 by grepping
the whole bootable/recovery tree -- these five are the complete set. libtar's
fscrypt API is a separate problem, see fix_fscrypt.py.
"""

import pathlib
import re
import sys

RECOVERY = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")

STUBS = {
    "set_partition_data": "int set_partition_data(const char *, const char *) { return -1; }",
    "cryptfs_check_footer": "int cryptfs_check_footer(void) { return -1; }",
    "cryptfs_get_password_type": "int cryptfs_get_password_type(void) { return -1; }",
    "cryptfs_check_passwd": "int cryptfs_check_passwd(char *) { return -1; }",
    "delete_crypto_blk_dev": "int delete_crypto_blk_dev(char *) { return 0; }",
}

TARGETS = {
    "partition.cpp": '\t#include "Decrypt.h"\n#endif\n',
    "partitionmanager.cpp": '#include "adbbu/libtwadbbu.hpp"\n',
}

MARKER = "/* Added by fix_fde.py"

failed = False

for name, anchor in TARGETS.items():
    path = RECOVERY / name
    text = path.read_text()

    if MARKER in text:
        print("%s: already stubbed" % name)
        continue

    needed = [s for s in STUBS if re.search(r"\b%s\s*\(" % s, text)]
    if not needed:
        print("ERROR: %s uses none of the FDE symbols - upstream changed" % name,
              file=sys.stderr)
        failed = True
        continue

    at = text.find(anchor)
    if at < 0:
        print("ERROR: %s: include anchor not found" % name, file=sys.stderr)
        failed = True
        continue
    at += len(anchor)

    block = ["\n" + MARKER + ": vold android-14.1 stopped exporting the FDE/cryptfs",
             " * API these files still call. chopin is FBE + metadata-encryption only,",
             " * so every FDE branch here is dead code; inert stubs keep it compiling. */"]
    for symbol in needed:
        block.append("static __attribute__((unused)) " + STUBS[symbol])
    block = "\n".join(block) + "\n"

    text = text[:at] + block + text[at:]
    path.write_text(text)

    stub_at = text.find(MARKER)
    for symbol in needed:
        use_at = re.search(r"\b%s\s*\(" % symbol, text[stub_at + len(MARKER):])
        if use_at is None:
            print("ERROR: %s: %s stubbed but never used?" % (name, symbol),
                  file=sys.stderr)
            failed = True
    print("%s: stubbed %s" % (name, ", ".join(sorted(needed))))

if failed:
    sys.exit(1)
