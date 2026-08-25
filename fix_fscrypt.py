#!/usr/bin/env python3
"""Completely disable fscrypt blocks in libtar."""
import os

for fname in ['bootable/recovery/libtar/append.c', 'bootable/recovery/libtar/block.c']:
    if not os.path.exists(fname):
        print(f'Skip {fname}')
        continue
    with open(fname) as f:
        content = f.read()
    
    # Strategy: wrap entire function bodies that contain fscrypt calls
    # Look for patterns like: if (...) { ... fscrypt ... }
    import re
    
    # Replace all fscrypt function calls with no-ops
    replacements = [
        ('fscrypt_policy_get_struct(', '/* DISABLED fscrypt_policy_get_struct('),
        ('get_policy_size(', '/* DISABLED get_policy_size('),
        ('get_policy_descriptor(', '/* DISABLED get_policy_descriptor('),
        ('lookup_ref_key(t->th_buf.fep', '/* DISABLED lookup_ref_key(t->th_buf.fep'),
        ('fscrypt_policy_size(', '/* DISABLED fscrypt_policy_size('),
        ('get_policy_policy(', '/* DISABLED get_policy_policy('),
    ]
    
    for old, new in replacements:
        content = content.replace(old, new)
    
    # Close any open comments
    # Find lines with DISABLED and add closing */
    lines = content.split('\n')
    result = []
    for line in lines:
        if 'DISABLED' in line:
            # Add closing comment at end of line
            stripped = line.rstrip()
            if stripped.endswith(';'):
                line = stripped[:-1] + ' */;\\n'
            elif stripped.endswith(')'):
                line = stripped + ' */\\n'
            else:
                line = stripped + ' */\\n'
        result.append(line)
    
    content = ''.join(result)
    
    with open(fname, 'w') as f:
        f.write(content)
    print(f'Fixed {fname}')

# Fix libtar.h
fname = 'bootable/recovery/libtar/libtar.h'
if os.path.exists(fname):
    with open(fname) as f:
        c = f.read()
    c = c.replace('fscrypt_policy  *fep;', 'struct fscrypt_policy_v1 *fep;')
    with open(fname, 'w') as f:
        f.write(c)
    print(f'Fixed {fname}')
