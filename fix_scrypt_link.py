#!/usr/bin/env python3
"""Link libscrypt_static into the recovery binary.

vold's Decrypt.cpp calls crypto_scrypt() in Decrypt_User_Synth_Pass() and
declares libscrypt_static in its own Android.bp, so the library is in the tree
and built. But `recovery` is a Make module that pulls libvold in through
LOCAL_STATIC_LIBRARIES, and Make does not follow a soong module's transitive
static dependencies -- only libvold.a lands on the link line:

  ld.lld: error: undefined symbol: crypto_scrypt
  >>> referenced by Decrypt.cpp:375 (system/vold/Decrypt.cpp:375)

So the dependency has to be declared again where the link actually happens.
The line it is appended to sits inside the TW_INCLUDE_CRYPTO block of the
recovery module, next to the other vold support libraries.
"""

import pathlib
import re
import sys

RECOVERY = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
target = RECOVERY / "Android.mk"

text = target.read_text()

ANCHOR = "    LOCAL_STATIC_LIBRARIES += libkeymint_support\n"
if "LOCAL_STATIC_LIBRARIES += libscrypt_static" in text:
    print("Android.mk: libscrypt_static already linked")
    sys.exit(0)

count = text.count(ANCHOR)
if count != 1:
    print("ERROR: expected 1 '%s', found %d" % (ANCHOR.strip(), count),
          file=sys.stderr)
    sys.exit(1)

text = text.replace(
    ANCHOR,
    "    LOCAL_STATIC_LIBRARIES += libkeymint_support\n"
    "    # crypto_scrypt() for vold's Decrypt_User_Synth_Pass; Make does not\n"
    "    # follow libvold's soong static deps (see fix_scrypt_link.py).\n"
    "    LOCAL_STATIC_LIBRARIES += libscrypt_static\n",
)

if not re.search(r"LOCAL_MODULE := recovery$", text, re.MULTILINE):
    print("ERROR: recovery module not found", file=sys.stderr)
    sys.exit(1)

target.write_text(text)
print("Android.mk: libscrypt_static linked into recovery")
