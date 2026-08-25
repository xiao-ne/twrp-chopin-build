#!/usr/bin/env python3
import os, re

os.chdir(os.environ.get('WORKDIR', os.getcwd()))

# Fix append.c and block.c - remove fscrypt function calls
for fname in ['bootable/recovery/libtar/append.c', 'bootable/recovery/libtar/block.c']:
    if not os.path.exists(fname):
        print(f'Skip {fname}')
        continue
    with open(fname) as f:
        c = f.read()
    # Remove the if blocks containing fscrypt function calls
    # Simple approach: comment out problematic lines
    lines = c.split('\n')
    new = []
    in_skip = False
    brace_count = 0
    for line in lines:
        if not in_skip and any(fn in line for fn in [
            'fscrypt_policy_get_struct', 'fscrypt_policy_size',
            'get_policy_size', 'get_policy_descriptor',
            'lookup_ref_key(t->th_buf.fep'
        ]):
            in_skip = True
            brace_count = line.count('{') - line.count('}')
            continue
        if in_skip:
            brace_count += line.count('{') - line.count('}')
            if brace_count <= 0:
                in_skip = False
            continue
        new.append(line)
    with open(fname, 'w') as f:
        f.write('\n'.join(new))
    print(f'Patched {fname}')

# Fix libtar.h
fname = 'bootable/recovery/libtar/libtar.h'
if os.path.exists(fname):
    with open(fname) as f:
        c = f.read()
    c = c.replace('fscrypt_policy  *fep;', 'struct fscrypt_policy_v1 *fep;')
    with open(fname, 'w') as f:
        f.write(c)
    print(f'Patched {fname}')
