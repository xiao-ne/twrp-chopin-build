#!/usr/bin/env python3
"""Wrap fscrypt blocks with #if 0 instead of deleting lines."""
import os

for fname in ['bootable/recovery/libtar/append.c', 'bootable/recovery/libtar/block.c']:
    if not os.path.exists(fname):
        print(f'Skip {fname}')
        continue
    with open(fname) as f:
        lines = f.readlines()
    
    result = []
    skip_until = 0
    skip_start = -1
    
    for i, line in enumerate(lines):
        if skip_until > 0:
            skip_until += line.count('{') - line.count('}')
            if skip_until <= 0:
                skip_until = 0
                result.append('#endif /* fscrypt disabled */\n')
            continue
        
        # Detect start of fscrypt block
        if any(fn in line for fn in ['fscrypt_policy_get_struct', 'fscrypt_policy_size',
                'get_policy_size', 'get_policy_descriptor',
                'lookup_ref_key(t->th_buf.fep']):
            skip_until = line.count('{') - line.count('}')
            result.append('#if 0 /* fscrypt disabled for compatibility */\n')
            result.append(line)
            if skip_until <= 0:
                skip_until = 0
                result.append('#endif /* fscrypt disabled */\n')
            continue
        
        result.append(line)
    
    with open(fname, 'w') as f:
        f.writelines(result)
    print(f'Fixed {fname}')

# Fix libtar.h struct tag
fname = 'bootable/recovery/libtar/libtar.h'
if os.path.exists(fname):
    with open(fname) as f:
        c = f.read()
    c = c.replace('fscrypt_policy  *fep;', 'struct fscrypt_policy_v1 *fep;')
    with open(fname, 'w') as f:
        f.write(c)
    print(f'Fixed {fname}')
